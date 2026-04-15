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

# In-memory price cache to avoid rate limiting
_price_cache = {}
_price_cache_time = 0
PRICE_CACHE_SECONDS = 60  # Cache prices for 60 seconds


def fetch_all_prices() -> dict:
    """Fetch all coin prices in a single batched API call with caching."""
    global _price_cache, _price_cache_time

    now = time.time()
    if _price_cache and (now - _price_cache_time) < PRICE_CACHE_SECONDS:
        return _price_cache

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

        if prices:
            _price_cache = prices
            _price_cache_time = now
            logger.info(f"✅ Fetched prices: {prices}")

        return prices

    except Exception as e:
        logger.error(f"❌ Error fetching batch prices: {e}")
        # Return cached prices even if stale, better than nothing
        if _price_cache:
            logger.warning("⚠️ Returning stale cached prices")
            return _price_cache
        return {}


def get_live_price(symbol: str) -> float | None:
    prices = fetch_all_prices()
    return prices.get(symbol.upper())


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

            entry_price = get_live_price(crypto)
            if entry_price is None:
                return {'success': False, 'error': 'Could not fetch live price. Please try again.'}

            now = datetime.utcnow()
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
        try:
            pred_id = prediction['id']
            crypto = prediction['crypto_symbol']
            direction = prediction['direction']
            entry_price = float(prediction['entry_price'])
            wallet_address = prediction['wallet_address']

            result_price = get_live_price(crypto)
            if result_price is None:
                return {'success': False, 'error': 'Could not fetch result price.'}

            if direction == 'UP':
                won = result_price > entry_price
            else:
                won = result_price < entry_price

            timeframe_minutes = prediction.get('timeframe_minutes') or int((prediction.get('timeframe_hours', 24)) * 60)
            status = 'won' if won else 'lost'
            reward = TIMEFRAME_REWARDS.get(timeframe_minutes, 50.0) if won else 0.0

            self.supabase.table('price_predictions').update({
                'result_price': result_price,
                'status': status,
                'reward_paid': won,
                'resolved_at': datetime.utcnow().isoformat()
            }).eq('id', pred_id).execute()

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
                        'updated_at': datetime.utcnow().isoformat()
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
            now = datetime.now(timezone.utc)
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

    def get_all_active_predictions(self) -> dict:
        """Return all pending predictions from all users for the live feed.
        Only returns predictions whose target_time has NOT yet passed."""
        try:
            now = datetime.now(timezone.utc).isoformat()
            res = self.supabase.table('price_predictions') \
                .select('wallet_address, crypto_symbol, direction, timeframe_minutes, entry_price, target_time, created_at') \
                .eq('status', 'pending') \
                .gt('target_time', now) \
                .order('target_time', desc=False) \
                .limit(50) \
                .execute()
            return {'success': True, 'predictions': res.data or []}
        except Exception as e:
            logger.error(f"❌ Error getting all active predictions: {e}")
            return {'success': False, 'predictions': []}

    def get_live_prices(self) -> dict:
        try:
            prices = fetch_all_prices()
            return {'success': True, 'prices': prices}
        except Exception as e:
            logger.error(f"❌ Error getting live prices: {e}")
            return {'success': False, 'prices': {}}


price_prediction_service = PricePredictionService()
