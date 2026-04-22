import logging
import requests
import time
from datetime import datetime, timedelta, timezone
from supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

MAX_ACTIVE_PREDICTIONS = 1

# Timeframe in minutes → reward in G$
TIMEFRAME_REWARDS = {
    1:    2.0,    # 1 minute  → 2 G$
    60:   5.0,    # 1 hour    → 5 G$
    720:  20.0,   # 12 hours  → 20 G$
    1440: 50.0,   # 24 hours  → 50 G$
}

COINGECKO_IDS = {
    'BTC': 'bitcoin',
    'ETH': 'ethereum',
    'CELO': 'celo',
}

COINGECKO_URL = 'https://api.coingecko.com/api/v3/simple/price'
COINGECKO_CHART_URL = 'https://api.coingecko.com/api/v3/coins/{id}/market_chart'

# Display-only price cache (refreshed every 60s). NEVER used for entry or
# resolution prices — those fetch fresh every time to prevent stale-cache
# arbitrage.
_display_price_cache: dict = {}
_display_price_cache_time = 0.0
DISPLAY_PRICE_CACHE_SECONDS = 60

# Sparkline / chart cache (refreshed every 10 minutes per coin).
_sparkline_cache: dict = {}  # symbol -> {'points': [...], 'fetched_at': ts}
SPARKLINE_CACHE_SECONDS = 600
SPARKLINE_HOURS = 24
SPARKLINE_POINTS = 24  # down-sampled points returned to the client


def _fetch_simple_prices() -> dict:
    """Do one live CoinGecko simple/price call for all supported coins."""
    all_ids = ','.join(COINGECKO_IDS.values())
    try:
        resp = requests.get(
            COINGECKO_URL,
            params={'ids': all_ids, 'vs_currencies': 'usd'},
            timeout=10,
            headers={'Accept': 'application/json'}
        )
        resp.raise_for_status()
        data = resp.json()

        prices = {}
        for symbol, coin_id in COINGECKO_IDS.items():
            if coin_id in data and 'usd' in data[coin_id]:
                prices[symbol] = float(data[coin_id]['usd'])
        return prices
    except Exception as e:
        logger.error(f"❌ Error fetching prices from CoinGecko: {e}")
        return {}


def fetch_display_prices() -> dict:
    """Cached prices for UI display. Safe to be slightly stale (60s)."""
    global _display_price_cache, _display_price_cache_time

    now = time.time()
    if _display_price_cache and (now - _display_price_cache_time) < DISPLAY_PRICE_CACHE_SECONDS:
        return _display_price_cache

    prices = _fetch_simple_prices()
    if prices:
        _display_price_cache = prices
        _display_price_cache_time = now
        logger.info(f"✅ Refreshed display prices: {prices}")
        return prices

    if _display_price_cache:
        logger.warning("⚠️ Returning stale cached display prices")
        return _display_price_cache
    return {}


def fetch_fresh_price(symbol: str) -> float | None:
    """Always-fresh price used for prediction entry and resolution.

    Bypasses the display cache so users cannot arbitrage against a stale
    cached price at the moment they submit or resolve a prediction.
    """
    prices = _fetch_simple_prices()
    if prices:
        return prices.get(symbol.upper())

    # Fallback to cached price as a last resort if live call fails, so the
    # game still works during CoinGecko blips.
    if _display_price_cache:
        logger.warning(f"⚠️ fetch_fresh_price falling back to stale cache for {symbol}")
        return _display_price_cache.get(symbol.upper())
    return None


def fetch_sparkline(symbol: str) -> list:
    """Return a down-sampled 24h price series for a coin, as [timestamp_ms, price] pairs."""
    symbol = symbol.upper()
    coin_id = COINGECKO_IDS.get(symbol)
    if not coin_id:
        return []

    entry = _sparkline_cache.get(symbol)
    now = time.time()
    if entry and (now - entry['fetched_at']) < SPARKLINE_CACHE_SECONDS:
        return entry['points']

    try:
        resp = requests.get(
            COINGECKO_CHART_URL.format(id=coin_id),
            params={'vs_currency': 'usd', 'days': '1'},
            timeout=10,
            headers={'Accept': 'application/json'}
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data.get('prices') or []
        if not raw:
            return entry['points'] if entry else []

        # Down-sample evenly to SPARKLINE_POINTS points.
        if len(raw) <= SPARKLINE_POINTS:
            points = raw
        else:
            step = len(raw) / SPARKLINE_POINTS
            points = [raw[min(len(raw) - 1, int(i * step))] for i in range(SPARKLINE_POINTS)]
            if points[-1] != raw[-1]:
                points[-1] = raw[-1]

        _sparkline_cache[symbol] = {'points': points, 'fetched_at': now}
        return points
    except Exception as e:
        logger.error(f"❌ Error fetching sparkline for {symbol}: {e}")
        return entry['points'] if entry else []


def fetch_all_sparklines() -> dict:
    return {sym: fetch_sparkline(sym) for sym in COINGECKO_IDS.keys()}


def _short_wallet(wallet: str | None) -> str:
    if not wallet:
        return '???'
    if len(wallet) <= 10:
        return wallet
    return f"{wallet[:6]}...{wallet[-4:]}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PricePredictionService:
    def __init__(self):
        self.supabase = get_supabase_client()

    def get_active_prediction(self, wallet_address: str) -> dict:
        try:
            res = self.supabase.table('price_predictions') \
                .select('*') \
                .eq('wallet_address', wallet_address) \
                .eq('status', 'pending') \
                .order('created_at', desc=True) \
                .limit(1) \
                .execute()
            if res.data:
                return {'success': True, 'prediction': res.data[0]}
            return {'success': True, 'prediction': None}
        except Exception as e:
            logger.error(f"❌ Error getting active prediction: {e}")
            return {'success': False, 'error': str(e)}

    def submit_prediction(self, wallet_address: str, crypto: str, direction: str, timeframe_minutes: int) -> dict:
        try:
            crypto = crypto.upper()
            direction = direction.upper()

            if crypto not in COINGECKO_IDS:
                return {'success': False, 'error': 'Invalid crypto symbol. Use BTC, ETH, or CELO.'}

            if direction not in ('UP', 'DOWN'):
                return {'success': False, 'error': 'Direction must be UP or DOWN.'}

            if timeframe_minutes not in TIMEFRAME_REWARDS:
                return {'success': False, 'error': 'Invalid timeframe selected.'}

            active = self.get_active_prediction(wallet_address)
            if active.get('prediction'):
                return {
                    'success': False,
                    'error': 'You already have an active prediction. Wait for it to resolve first.'
                }

            entry_price = fetch_fresh_price(crypto)
            if entry_price is None:
                return {'success': False, 'error': 'Could not fetch live price. Please try again.'}

            now = _utcnow()
            target_time = now + timedelta(minutes=timeframe_minutes)
            reward = TIMEFRAME_REWARDS[timeframe_minutes]

            res = self.supabase.table('price_predictions').insert({
                'wallet_address': wallet_address,
                'crypto_symbol': crypto,
                'direction': direction,
                'timeframe_minutes': timeframe_minutes,
                'entry_price': entry_price,
                'target_time': target_time.isoformat(),
                'status': 'pending',
                'reward_paid': False,
                'created_at': now.isoformat()
            }).execute()

            if not res.data:
                return {'success': False, 'error': 'Failed to save prediction.'}

            logger.info(f"📈 New prediction: {wallet_address[:8]}... {crypto} {direction} {timeframe_minutes}min @ ${entry_price} (reward: {reward} G$)")
            return {
                'success': True,
                'prediction': res.data[0],
                'entry_price': entry_price,
                'target_time': target_time.isoformat(),
                'reward': reward
            }
        except Exception as e:
            logger.error(f"❌ Error submitting prediction: {e}")
            return {'success': False, 'error': str(e)}

    def resolve_prediction(self, prediction: dict) -> dict:
        """Resolve a single prediction atomically.

        Uses a conditional update on status='pending' to claim the prediction,
        so concurrent resolvers (multiple tabs, overlapping polls) can never
        double-credit the reward.
        """
        try:
            pred_id = prediction['id']
            crypto = prediction['crypto_symbol']
            direction = prediction['direction']
            entry_price = float(prediction['entry_price'])
            wallet_address = prediction['wallet_address']
            timeframe_minutes = prediction.get('timeframe_minutes') or int((prediction.get('timeframe_hours', 24)) * 60)

            result_price = fetch_fresh_price(crypto)
            if result_price is None:
                return {'success': False, 'error': 'Could not fetch result price.'}

            # Treat an exact-flat result as a win in the user's favor (extremely
            # rare; avoids a silent loss on a dead-flat tick).
            if direction == 'UP':
                won = result_price >= entry_price
            else:
                won = result_price <= entry_price

            status = 'won' if won else 'lost'
            reward = TIMEFRAME_REWARDS.get(timeframe_minutes, 50.0) if won else 0.0

            # Atomic claim: only the first caller whose WHERE clause matches
            # (status='pending' AND reward_paid=False) gets rows back.
            claim = self.supabase.table('price_predictions') \
                .update({
                    'result_price': result_price,
                    'status': status,
                    'reward_paid': won,
                    'resolved_at': _utcnow().isoformat()
                }) \
                .eq('id', pred_id) \
                .eq('status', 'pending') \
                .eq('reward_paid', False) \
                .execute()

            if not claim.data:
                # Someone else already resolved this prediction — skip reward.
                logger.info(f"ℹ️ Skipping already-resolved prediction {pred_id}")
                return {'success': False, 'error': 'already_resolved'}

            if won:
                balance_res = self.supabase.table('minigame_balances') \
                    .select('available_balance') \
                    .eq('wallet_address', wallet_address) \
                    .execute()

                if balance_res.data:
                    current = float(balance_res.data[0]['available_balance'])
                    new_balance = current + reward
                    self.supabase.table('minigame_balances').update({
                        'available_balance': new_balance,
                        'updated_at': _utcnow().isoformat()
                    }).eq('wallet_address', wallet_address).execute()
                else:
                    new_balance = reward
                    self.supabase.table('minigame_balances').insert({
                        'wallet_address': wallet_address,
                        'available_balance': new_balance
                    }).execute()

                logger.info(f"🏆 Prediction WON: {wallet_address[:8]}... earned {reward} G$ ({crypto} {direction} {timeframe_minutes}min)")
            else:
                logger.info(f"❌ Prediction LOST: {wallet_address[:8]}... ({crypto} {direction})")

            return {
                'success': True,
                'status': status,
                'won': won,
                'entry_price': entry_price,
                'result_price': result_price,
                'reward': reward,
                'direction': direction,
                'crypto': crypto,
                'timeframe_minutes': timeframe_minutes
            }
        except Exception as e:
            logger.error(f"❌ Error resolving prediction: {e}")
            return {'success': False, 'error': str(e)}

    def check_and_resolve(self, wallet_address: str) -> dict:
        try:
            now = _utcnow()
            res = self.supabase.table('price_predictions') \
                .select('*') \
                .eq('wallet_address', wallet_address) \
                .eq('status', 'pending') \
                .execute()

            resolved = []
            for pred in (res.data or []):
                raw = pred['target_time']
                # Handle both 'Z' and '+00:00' timezone formats from Supabase
                if raw.endswith('Z'):
                    target_time = datetime.fromisoformat(raw.replace('Z', '+00:00'))
                else:
                    target_time = datetime.fromisoformat(raw)
                if now >= target_time:
                    result = self.resolve_prediction(pred)
                    if result.get('success'):
                        resolved.append(result)

            return {'success': True, 'resolved': resolved}
        except Exception as e:
            logger.error(f"❌ Error in check_and_resolve: {e}")
            return {'success': False, 'error': str(e)}

    def get_prediction_history(self, wallet_address: str) -> dict:
        try:
            res = self.supabase.table('price_predictions') \
                .select('*') \
                .eq('wallet_address', wallet_address) \
                .order('created_at', desc=True) \
                .limit(20) \
                .execute()
            return {'success': True, 'predictions': res.data or []}
        except Exception as e:
            logger.error(f"❌ Error getting prediction history: {e}")
            return {'success': False, 'predictions': []}

    def get_all_active_predictions(self, current_wallet: str | None = None) -> dict:
        """Return all pending predictions for the live feed.

        Wallet addresses are truncated server-side to avoid exposing full
        addresses to other users. An ``is_me`` flag is added so the client
        can still highlight the current user's own rows.
        """
        try:
            now = _utcnow().isoformat()
            res = self.supabase.table('price_predictions') \
                .select('wallet_address, crypto_symbol, direction, timeframe_minutes, entry_price, target_time, created_at') \
                .eq('status', 'pending') \
                .gt('target_time', now) \
                .order('target_time', desc=False) \
                .limit(50) \
                .execute()

            rows = res.data or []
            my_wallet = (current_wallet or '').lower()
            sanitized = []
            for row in rows:
                full = row.get('wallet_address') or ''
                is_me = bool(my_wallet) and full.lower() == my_wallet
                sanitized.append({
                    'wallet_short': _short_wallet(full),
                    'is_me': is_me,
                    'crypto_symbol': row.get('crypto_symbol'),
                    'direction': row.get('direction'),
                    'timeframe_minutes': row.get('timeframe_minutes'),
                    'entry_price': row.get('entry_price'),
                    'target_time': row.get('target_time'),
                    'created_at': row.get('created_at'),
                })

            return {'success': True, 'predictions': sanitized}
        except Exception as e:
            logger.error(f"❌ Error getting all active predictions: {e}")
            return {'success': False, 'predictions': []}

    def get_live_prices(self) -> dict:
        try:
            prices = fetch_display_prices()
            return {'success': True, 'prices': prices}
        except Exception as e:
            logger.error(f"❌ Error getting live prices: {e}")
            return {'success': False, 'prices': {}}

    def get_sparklines(self) -> dict:
        try:
            return {'success': True, 'sparklines': fetch_all_sparklines()}
        except Exception as e:
            logger.error(f"❌ Error getting sparklines: {e}")
            return {'success': False, 'sparklines': {}}


price_prediction_service = PricePredictionService()
