

"""
Application Configuration
"""
import os

# Production domain configuration
PRODUCTION_DOMAIN = os.getenv('PRODUCTION_DOMAIN', 'https://goodmarket.live')

# ============================
# Blockchain Contract Addresses
# ============================
# Public on-chain addresses — safe to hardcode (visible on Celoscan anyway)
ESCROW_MARKETPLACE_ADDRESS = os.getenv(
    'ESCROW_MARKETPLACE_ADDRESS',
    '0x3512475f78847F6B467054395da0D77437EeC6B5'
)
GOODDOLLAR_CONTRACT_ADDRESS = os.getenv(
    'GOODDOLLAR_CONTRACT_ADDRESS',
    '0x62B8B11039FcfE5aB0C56E502b1C372A3d2a9c7A'
)
ACHIEVEMENT_NFT_CONTRACT_ADDRESS = os.getenv(
    'ACHIEVEMENT_NFT_CONTRACT_ADDRESS',
    '0x8798dc478eCc00aba0Bda196580b24f3A928F161'
)
LEARN_EARN_CONTRACT_ADDRESS = os.getenv(
    'LEARN_EARN_CONTRACT_ADDRESS',
    '0x52347653a24A9A1e432aEC6CD91a271158205963'
)
DAILY_TASK_CONTRACT_ADDRESS = os.getenv(
    'DAILY_TASK_CONTRACT_ADDRESS',
    '0x3cC19de5b06Ce73C35Cf1D5ab3c6Cc3583dFe11f'
)

# Use production domain for external links (referrals, shares, etc.)
# Use local domain for internal API calls
def get_share_url_base():
    """Get base URL for shareable links (referrals, invites, etc.)"""
    return PRODUCTION_DOMAIN

def get_api_url_base():
    """Get base URL for API calls (always use current origin)"""
    return ''  # Empty string uses relative URLs

# ============================
# Community Stories Settings
# ============================
COMMUNITY_STORIES_CONFIG = {
    # Reward amounts (in G$)
    'LOW_REWARD': 2000.0,  # Text post
    'HIGH_REWARD': 5000.0,  # Video post (min. 30 seconds)

    # Requirements
    'REQUIRED_MENTIONS': '@gooddollarorg @GoodDollarTeam',
    'MIN_VIDEO_DURATION': 30,  # seconds

    # Participation window
    'WINDOW_START_DAY': 26,  # Day of month (1-31)
    'WINDOW_END_DAY': 30,    # Day of month (1-31)
    'WINDOW_START_HOUR': 0,  # UTC hour (0-23)
    'WINDOW_START_MINUTE': 0,
    'WINDOW_END_HOUR': 23,
    'WINDOW_END_MINUTE': 59,

    # Rules
    'DESCRIPTION': {
        'earn_title': '💰 Earn G$ by sharing our story:',
        'requirements_title': '📋 Requirements:',
        'schedule_title': '📅 Participation Schedule:',
        'requirements': [
            'Must use hashtags: @gooddollarorg @GoodDollarTeam',
            'Post must be public',
            'Original content only'
        ],
        'schedule_notes': [
            'Opens: 26th of each month at 12:00 AM UTC',
            'Closes: 30th of each month at 11:59 PM UTC',
            'Duration: 5 days only each month',
            'After reward: Blocked until next 26th'
        ],
        'warning': '⚠️ Late submissions after 30th are NOT accepted!'
    }
}
