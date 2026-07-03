"""
Privy Authentication Service for GoodMarket
==========================================
Handles all Privy-related authentication operations including:
- Token verification
- User creation/update
- Wallet address extraction
- Session creation

Author: AI Assistant
Date: 2026-07-03
"""

import os
import logging
import time
from typing import Optional, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger("privy_service")

# Privy Configuration
PRIVY_APP_ID = os.getenv("PRIVY_APP_ID", "")
PRIVY_APP_SECRET = os.getenv("PRIVY_APP_SECRET", "")
PRIVY_API_BASE = "https://api.privy.io/v1"

# Cache for access token
_access_token_cache = {"token": None, "expires_at": 0}
_access_token_lock = __import__("threading").Lock()


def _get_privy_access_token() -> Optional[str]:
    """
    Get a fresh Privy API access token using app credentials.
    Uses caching to avoid excessive token requests.
    """
    global _access_token_cache
    
    # Check cache first
    with _access_token_lock:
        if _access_token_cache["token"] and _access_token_cache["expires_at"] > time.time():
            return _access_token_cache["token"]
    
    if not PRIVY_APP_ID or not PRIVY_APP_SECRET:
        logger.warning("⚠️ Privy credentials not configured")
        return None
    
    try:
        import requests
        
        response = requests.post(
            f"{PRIVY_API_BASE}/app/token",
            json={
                "app_id": PRIVY_APP_ID,
                "app_secret": PRIVY_APP_SECRET,
            },
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        
        if response.status_code == 200:
            data = response.json()
            token = data.get("access_token")
            expires_in = data.get("expires_in", 3600)
            
            with _access_token_lock:
                _access_token_cache["token"] = token
                _access_token_cache["expires_at"] = time.time() + expires_in - 60  # Refresh 1 min early
            
            logger.info("✅ Privy access token obtained")
            return token
        else:
            logger.error(f"❌ Failed to get Privy token: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Error getting Privy access token: {e}")
        return None


def _extract_wallet_from_embedded_wallet(user_data: Dict[str, Any]) -> Optional[str]:
    """Extract wallet address from embedded wallet."""
    embedded_wallet = user_data.get("embedded_wallet", {})
    if embedded_wallet:
        address = embedded_wallet.get("address", "")
        if address:
            return address.lower()
    return None


def _extract_wallet_from_linked_accounts(user_data: Dict[str, Any]) -> Optional[str]:
    """Extract wallet address from linked accounts (external wallets)."""
    linked_accounts = user_data.get("linked_accounts", [])
    
    for account in linked_accounts:
        account_type = account.get("type", "")
        
        if account_type == "wallet":
            # Direct address field
            address = account.get("address", "")
            if address:
                return address.lower()
            
            # Nested wallet object
            wallet_data = account.get("wallet", {})
            address = wallet_data.get("address", "")
            if address:
                return address.lower()
    
    return None


def _determine_auth_method(user_data: Dict[str, Any]) -> str:
    """Determine the primary authentication method used."""
    linked_accounts = user_data.get("linked_accounts", [])
    
    # Check for wallet login first
    for account in linked_accounts:
        if account.get("type") == "wallet":
            return "wallet"
    
    # Check for social logins
    for account in linked_accounts:
        account_type = account.get("type", "")
        if account_type in ("google_oauth", "discord", "twitter", "apple_oauth"):
            return account_type.split("_")[0]
    
    # Check for email
    for account in linked_accounts:
        if account.get("type") == "email":
            return "email"
    
    return "unknown"


def verify_privy_id_token(id_token: str) -> dict:
    """
    Verify a Privy ID token and return user information.
    
    Args:
        id_token: The JWT ID token from Privy login
        
    Returns:
        dict with keys:
            - valid: bool
            - error: str (if invalid)
            - user_id: str
            - wallet_address: str (if wallet login)
            - auth_method: str ('wallet', 'google', 'email', etc.)
            - linked_accounts: list of linked account info
    """
    if not id_token:
        return {"valid": False, "error": "No ID token provided"}
    
    access_token = _get_privy_access_token()
    if not access_token:
        return {"valid": False, "error": "Privy API not configured"}
    
    try:
        import requests
        
        # POST to /auth/verify with the id_token
        response = requests.post(
            f"{PRIVY_API_BASE}/auth/verify",
            json={"id_token": id_token},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Privy-App-ID": PRIVY_APP_ID,
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        
        if response.status_code == 200:
            data = response.json()
            user = data.get("user", {})
            
            # Extract wallet address from embedded wallet first, then linked accounts
            wallet_address = (
                _extract_wallet_from_embedded_wallet(user) or 
                _extract_wallet_from_linked_accounts(user)
            )
            
            auth_method = _determine_auth_method(user)
            
            return {
                "valid": True,
                "user_id": user.get("id"),
                "wallet_address": wallet_address,
                "auth_method": auth_method,
                "linked_accounts": user.get("linked_accounts", []),
                "created_at": user.get("created_at"),
                "has_wallet": wallet_address is not None,
            }
            
        elif response.status_code == 401:
            # Token expired or invalid - clear cache
            with _access_token_lock:
                _access_token_cache["token"] = None
                _access_token_cache["expires_at"] = 0
            return {"valid": False, "error": "Invalid or expired ID token"}
            
        else:
            logger.error(f"❌ Privy verify error: {response.status_code} - {response.text}")
            return {"valid": False, "error": f"Verification failed: {response.status_code}"}
            
    except Exception as e:
        logger.error(f"❌ Error verifying Privy token: {e}")
        return {"valid": False, "error": str(e)}


def process_privy_user_data(user_data: Dict[str, Any]) -> dict:
    """
    Process user data from Privy React SDK and extract authentication info.
    
    This is the main function used for direct session creation from frontend.
    
    Args:
        user_data: User object from Privy SDK (user parameter in usePrivy)
        
    Returns:
        dict with keys:
            - valid: bool
            - error: str (if invalid)
            - user_id: str
            - wallet_address: str (if wallet login)
            - auth_method: str ('wallet', 'google', 'email', etc.)
            - has_wallet: bool
    """
    if not user_data:
        return {"valid": False, "error": "No user data provided"}
    
    try:
        # Get user ID
        user_id = user_data.get("id", "")
        if not user_id:
            # Try different field names
            user_id = user_data.get("sub", "") or user_data.get("userId", "")
        
        if not user_id:
            return {"valid": False, "error": "No user ID in data"}
        
        # Extract wallet address
        wallet_address = None
        
        # Check embedded_wallet
        embedded_wallet = user_data.get("embedded_wallet", {})
        if embedded_wallet:
            wallet_address = embedded_wallet.get("address", "")
        
        # Check wallet property directly (from Privy SDK)
        if not wallet_address:
            wallet_address = user_data.get("wallet", {})
            if isinstance(wallet_address, dict):
                wallet_address = wallet_address.get("address", "")
        
        # Check linked_accounts
        if not wallet_address:
            wallet_address = _extract_wallet_from_linked_accounts(user_data)
        
        # Normalize wallet address
        if wallet_address:
            wallet_address = wallet_address.lower()
        
        # Determine auth method
        auth_method = _determine_auth_method(user_data)
        
        # If no auth method found, check the credential / connector type
        if auth_method == "unknown":
            connector_type = user_data.get("connector_type", "")
            if "wallet" in connector_type.lower():
                auth_method = "wallet"
            elif "google" in connector_type.lower():
                auth_method = "google"
        
        return {
            "valid": True,
            "user_id": user_id,
            "wallet_address": wallet_address,
            "auth_method": auth_method,
            "has_wallet": wallet_address is not None,
        }
        
    except Exception as e:
        logger.error(f"❌ Error processing Privy user data: {e}")
        return {"valid": False, "error": str(e)}


def get_user_from_privy_id(privy_user_id: str) -> Optional[dict]:
    """
    Get user information from Privy by user ID.
    
    Args:
        privy_user_id: The Privy user ID
        
    Returns:
        dict with user info or None if not found
    """
    access_token = _get_privy_access_token()
    if not access_token:
        return None
    
    try:
        import requests
        
        response = requests.get(
            f"{PRIVY_API_BASE}/users/{privy_user_id}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Privy-App-ID": PRIVY_APP_ID,
            },
            timeout=10,
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.warning(f"⚠️ Failed to get Privy user: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Error getting Privy user: {e}")
        return None


def create_session_data(privy_result: dict, wallet_address: str = None) -> dict:
    """
    Create Flask session data from Privy verification result.
    
    Args:
        privy_result: Result from verify_privy_id_token() or process_privy_user_data()
        wallet_address: Override wallet address if needed
        
    Returns:
        dict with session-ready data
    """
    # Use provided wallet or extract from Privy result
    wallet = wallet_address or privy_result.get("wallet_address")
    
    session_data = {
        "wallet": wallet,
        "wallet_address": wallet,
        "verified": True,
        "ubi_verified": True,
        "login_method": "privy",
        "auth_method": privy_result.get("auth_method", "wallet"),
        "privy_user_id": privy_result.get("user_id"),
        "verification_time": datetime.now(timezone.utc).isoformat(),
        "is_new_user": False,  # Will be determined by caller
    }
    
    return session_data


def is_privy_configured() -> bool:
    """Check if Privy is properly configured."""
    return bool(PRIVY_APP_ID and PRIVY_APP_SECRET)


# Export for convenience
__all__ = [
    "verify_privy_id_token",
    "process_privy_user_data",
    "get_user_from_privy_id", 
    "create_session_data",
    "is_privy_configured",
]
