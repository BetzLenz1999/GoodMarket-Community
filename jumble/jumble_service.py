import logging
import random
import re
import string
from datetime import date, datetime
from supabase_client import get_supabase_client
from .blockchain import jumble_blockchain

logger = logging.getLogger(__name__)

STOP_WORDS = {
    'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can',
    'had', 'her', 'was', 'one', 'our', 'out', 'day', 'get', 'has',
    'him', 'his', 'how', 'man', 'new', 'now', 'old', 'see', 'two',
    'way', 'who', 'boy', 'did', 'its', 'let', 'put', 'say', 'she',
    'too', 'use', 'that', 'with', 'this', 'from', 'they', 'will',
    'been', 'have', 'into', 'more', 'when', 'what', 'your', 'said',
    'each', 'which', 'their', 'time', 'about', 'would', 'there',
    'could', 'other', 'after', 'first', 'very', 'well', 'also',
    'back', 'down', 'just', 'because', 'come', 'some', 'should',
    'than', 'only', 'even', 'these', 'those', 'then', 'both',
    'much', 'such', 'make', 'like', 'into', 'over', 'most', 'here',
    'while', 'where', 'being', 'many', 'long', 'little', 'state',
    'between', 'under', 'never', 'every', 'always', 'often', 'still',
    'before', 'during', 'without', 'within', 'through', 'against'
}

REWARD_PER_WIN = 5.0
MAX_DAILY_WINS = 10
MIN_WITHDRAWAL = 200.0
TIMER_SECONDS = 30


def _jumble_word(word: str) -> str:
    letters = list(word.lower())
    attempts = 0
    while attempts < 20:
        random.shuffle(letters)
        jumbled = ''.join(letters)
        if jumbled != word.lower():
            return jumbled
    return ''.join(reversed(letters)) if ''.join(reversed(letters)) != word.lower() else word[::-1] + word[0]


def _extract_words(content_text: str) -> list:
    words_raw = re.findall(r'[a-zA-Z]+', content_text)
    seen = set()
    extracted = []
    for w in words_raw:
        w_clean = w.lower()
        if (
            len(w_clean) >= 5
            and w_clean not in STOP_WORDS
            and w_clean not in seen
            and w_clean.isalpha()
        ):
            seen.add(w_clean)
            jumbled = _jumble_word(w_clean)
            extracted.append({'word': w_clean, 'jumbled': jumbled})
    return extracted


class JumbleService:
    def __init__(self):
        self.supabase = get_supabase_client()

    def add_content(self, content_text: str, added_by: str = 'admin') -> dict:
        try:
            words = _extract_words(content_text)
            if not words:
                return {'success': False, 'error': 'No suitable words found in content (need words with 5+ letters).'}

            content_res = self.supabase.table('jumble_contents').insert({
                'content_text': content_text,
                'added_by': added_by,
                'word_count': len(words)
            }).execute()

            if not content_res.data:
                return {'success': False, 'error': 'Failed to save content.'}

            content_id = content_res.data[0]['id']

            rows = [{'content_id': content_id, 'word': w['word'], 'jumbled': w['jumbled']} for w in words]
            self.supabase.table('jumble_words').insert(rows).execute()

            return {
                'success': True,
                'content_id': content_id,
                'words_generated': len(words),
                'sample_words': words[:5]
            }
        except Exception as e:
            logger.error(f"❌ Error adding jumble content: {e}")
            return {'success': False, 'error': str(e)}

    def delete_content(self, content_id: int) -> dict:
        try:
            self.supabase.table('jumble_words').delete().eq('content_id', content_id).execute()
            self.supabase.table('jumble_contents').delete().eq('id', content_id).execute()
            return {'success': True}
        except Exception as e:
            logger.error(f"❌ Error deleting jumble content: {e}")
            return {'success': False, 'error': str(e)}

    def get_all_contents(self) -> dict:
        try:
            res = self.supabase.table('jumble_contents')\
                .select('*')\
                .order('created_at', desc=True)\
                .execute()
            return {'success': True, 'contents': res.data or []}
        except Exception as e:
            logger.error(f"❌ Error fetching jumble contents: {e}")
            return {'success': False, 'error': str(e)}

    def get_daily_wins(self, wallet_address: str) -> int:
        try:
            today = date.today().isoformat()
            res = self.supabase.table('daily_game_limits')\
                .select('plays_today')\
                .eq('wallet_address', wallet_address)\
                .eq('game_date', today)\
                .eq('game_type', 'jumble_words')\
                .execute()
            if res.data:
                return res.data[0].get('plays_today', 0)
            return 0
        except Exception as e:
            logger.error(f"❌ Error getting daily wins: {e}")
            return 0

    def get_random_word(self, wallet_address: str) -> dict:
        try:
            daily_wins = self.get_daily_wins(wallet_address)
            if daily_wins >= MAX_DAILY_WINS:
                return {
                    'success': False,
                    'limit_reached': True,
                    'message': f'You have reached your daily limit of {MAX_DAILY_WINS} wins. Come back tomorrow!'
                }

            all_words_res = self.supabase.table('jumble_words')\
                .select('id, word, jumbled')\
                .execute()

            if not all_words_res.data:
                return {'success': False, 'error': 'No jumble words available yet. Ask the admin to add content.'}

            word = random.choice(all_words_res.data)
            return {
                'success': True,
                'word_id': word['id'],
                'jumbled': word['jumbled'],
                'length': len(word['word']),
                'daily_wins': daily_wins,
                'max_wins': MAX_DAILY_WINS,
                'reward': REWARD_PER_WIN,
                'timer': TIMER_SECONDS
            }
        except Exception as e:
            logger.error(f"❌ Error getting random word: {e}")
            return {'success': False, 'error': str(e)}

    def submit_answer(self, wallet_address: str, word_id: int, answer: str) -> dict:
        try:
            daily_wins = self.get_daily_wins(wallet_address)
            if daily_wins >= MAX_DAILY_WINS:
                return {
                    'success': False,
                    'limit_reached': True,
                    'message': f'Daily limit of {MAX_DAILY_WINS} wins reached. Come back tomorrow!'
                }

            word_res = self.supabase.table('jumble_words')\
                .select('word')\
                .eq('id', word_id)\
                .execute()

            if not word_res.data:
                return {'success': False, 'error': 'Word not found.'}

            correct_word = word_res.data[0]['word'].lower()
            user_answer = answer.strip().lower()

            if user_answer != correct_word:
                return {
                    'success': True,
                    'correct': False,
                    'message': f'Wrong! The correct answer was "{correct_word}".',
                    'correct_word': correct_word
                }

            today = date.today().isoformat()
            self.supabase.table('daily_game_limits').upsert({
                'wallet_address': wallet_address,
                'game_date': today,
                'game_type': 'jumble_words',
                'plays_today': daily_wins + 1,
                'earned_today': (daily_wins + 1) * REWARD_PER_WIN
            }, on_conflict='wallet_address,game_date,game_type').execute()

            balance_res = self.supabase.table('minigame_balances')\
                .select('available_balance')\
                .eq('wallet_address', wallet_address)\
                .execute()

            if balance_res.data:
                current_balance = float(balance_res.data[0]['available_balance'])
                new_balance = current_balance + REWARD_PER_WIN
                self.supabase.table('minigame_balances')\
                    .update({'available_balance': new_balance, 'updated_at': datetime.utcnow().isoformat()})\
                    .eq('wallet_address', wallet_address)\
                    .execute()
            else:
                self.supabase.table('minigame_balances').insert({
                    'wallet_address': wallet_address,
                    'available_balance': REWARD_PER_WIN
                }).execute()
                new_balance = REWARD_PER_WIN

            new_wins = daily_wins + 1
            return {
                'success': True,
                'correct': True,
                'message': f'Correct! You earned {REWARD_PER_WIN} G$!',
                'reward': REWARD_PER_WIN,
                'new_balance': new_balance,
                'daily_wins': new_wins,
                'max_wins': MAX_DAILY_WINS,
                'limit_reached': new_wins >= MAX_DAILY_WINS
            }
        except Exception as e:
            logger.error(f"❌ Error submitting jumble answer: {e}")
            return {'success': False, 'error': str(e)}

    def get_leaderboard(self) -> dict:
        try:
            today = date.today().isoformat()
            res = self.supabase.table('daily_game_limits')\
                .select('wallet_address, plays_today, earned_today')\
                .eq('game_date', today)\
                .eq('game_type', 'jumble_words')\
                .order('plays_today', desc=True)\
                .limit(10)\
                .execute()
            return {'success': True, 'leaderboard': res.data or []}
        except Exception as e:
            logger.error(f"❌ Error getting leaderboard: {e}")
            return {'success': False, 'leaderboard': []}


jumble_service = JumbleService()
