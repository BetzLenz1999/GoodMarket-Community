"""
TurnKey Integration for GoodMarket
Email OTP Login + Wallet Creation + Export
"""

import os
import time
import uuid
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone

import requests
from web3 import Web3

logger = logging.getLogger(__name__)

# TurnKey API Configuration
TURNKEY_API_PUBLIC_KEY = os.getenv("TURNKEY_API_PUBLIC_KEY", "")
TURNKEY_ORGANIZATION_ID = os.getenv("TURNKEY_ORGANIZATION_ID", "")
TURNKEY_API_PRIVATE_KEY = os.getenv("TURNKEY_API_PRIVATE_KEY", "")
TURNKEY_BASE_URL = "https://api.turnkey.com"

# Cache for OTP activities (in-memory for demo, use Redis in production)
_otp_activities: Dict[str, Dict[str, Any]] = {}
_otp_cache_lock = __import__('threading').Lock()


def _get_turnkey_headers() -> Dict[str, str]:
    """Generate headers for TurnKey API requests."""
    return {
        "Content-Type": "application/json",
        "X-API-Key": TURNKEY_API_PUBLIC_KEY,
        "X-Organization-ID": TURNKEY_ORGANIZATION_ID,
    }


def _sign_request(body: Dict[str, Any]) -> Dict[str, str]:
    """
    Create signature headers for TurnKey API requests.
    In production, use the TurnKey SDK for proper signing.
    For this implementation, we'll use the API key directly.
    """
    timestamp = str(int(time.time() * 1000))
    return {
        "Content-Type": "application/json",
        "X-API-Key": TURNKEY_API_PUBLIC_KEY,
        "X-Organization-ID": TURNKEY_ORGANIZATION_ID,
        "X-Timestamp": timestamp,
        "X-Stamp": TURNKEY_API_PRIVATE_KEY,  # In production, sign properly with SDK
    }


def init_otp_auth(email: str, app_name: str = "GoodMarket") -> Dict[str, Any]:
    """
    Initialize OTP authentication - sends OTP code to user's email.
    
    Args:
        email: User's email address
        app_name: Application name for email customization
    
    Returns:
        Dict with activityId and otpEncryptionTargetBundle
    """
    try:
        timestamp_ms = str(int(time.time() * 1000))
        activity_id = str(uuid.uuid4())
        
        payload = {
            "type": "ACTIVITY_TYPE_INIT_OTP_V3",
            "timestampMs": timestamp_ms,
            "organizationId": TURNKEY_ORGANIZATION_ID,
            "parameters": {
                "otpType": "OTP_TYPE_EMAIL",
                "contact": email,
                "userIdentifier": email.lower(),
                "expirationSeconds": 300,  # 5 minutes
                "emailCustomization": {
                    "appName": app_name,
                },
            },
        }
        
        headers = _sign_request(payload)
        
        response = requests.post(
            f"{TURNKEY_BASE_URL}/public/v1/submit/init_otp",
            headers=headers,
            json=payload,
            timeout=30,
        )
        
        if response.status_code != 200:
            logger.error(f"TurnKey init_otp error: {response.status_code} - {response.text}")
            return {"success": False, "error": f"API error: {response.status_code}"}
        
        data = response.json()
        
        # Extract the activity result
        activity_result = data.get("activity", {}).get("result", {})
        init_otp_result = activity_result.get("initOtpV3Result", {})
        
        otp_id = init_otp_result.get("otpId", "")
        otp_bundle = init_otp_result.get("otpEncryptionTargetBundle", "")
        
        # Cache the OTP activity for verification
        with _otp_cache_lock:
            _otp_activities[activity_id] = {
                "otpId": otp_id,
                "otpBundle": otp_bundle,
                "email": email.lower(),
                "created_at": time.time(),
                "expires_at": time.time() + 300,  # 5 minutes
            }
        
        return {
            "success": True,
            "activityId": activity_id,
            "otpId": otp_id,
            "message": "OTP code sent to your email",
        }
        
    except Exception as e:
        logger.error(f"init_otp_auth error: {e}")
        return {"success": False, "error": str(e)}


def verify_otp(email: str, otp_code: str, public_key: str, activity_id: str = None) -> Dict[str, Any]:
    """
    Verify OTP code and get verification token.
    
    Args:
        email: User's email address
        otp_code: The OTP code from email
        public_key: User's public key for wallet
        activity_id: Optional activity ID from init_otp
    
    Returns:
        Dict with verificationToken
    """
    try:
        timestamp_ms = str(int(time.time() * 1000))
        
        # Find the cached OTP activity
        otp_data = None
        with _otp_cache_lock:
            for oid, data in _otp_activities.items():
                if data["email"] == email.lower() and data["expires_at"] > time.time():
                    otp_data = data
                    break
        
        if not otp_data:
            return {"success": False, "error": "No OTP request found or expired. Please request a new code."}
        
        payload = {
            "type": "ACTIVITY_TYPE_VERIFY_OTP_V2",
            "timestampMs": timestamp_ms,
            "organizationId": TURNKEY_ORGANIZATION_ID,
            "parameters": {
                "otpId": otp_data["otpId"],
                "encryptedOtpBundle": otp_data["otpBundle"],
                "publicKey": public_key,
                "expirationSeconds": 3600,  # 1 hour verification token
            },
        }
        
        headers = _sign_request(payload)
        
        response = requests.post(
            f"{TURNKEY_BASE_URL}/public/v1/submit/verify_otp",
            headers=headers,
            json=payload,
            timeout=30,
        )
        
        if response.status_code != 200:
            logger.error(f"TurnKey verify_otp error: {response.status_code} - {response.text}")
            return {"success": False, "error": f"Invalid OTP code or expired."}
        
        data = response.json()
        activity_result = data.get("activity", {}).get("result", {})
        verify_result = activity_result.get("verifyOtpV2Result", {})
        
        verification_token = verify_result.get("verificationToken", "")
        
        return {
            "success": True,
            "verificationToken": verification_token,
            "message": "OTP verified successfully",
        }
        
    except Exception as e:
        logger.error(f"verify_otp error: {e}")
        return {"success": False, "error": str(e)}


def otp_login(verification_token: str, public_key: str, sub_organization_id: str = None) -> Dict[str, Any]:
    """
    Complete OTP login and create/get user session.
    
    Args:
        verification_token: Token from verify_otp
        public_key: User's public key
        sub_organization_id: Sub-org ID for the user (optional, creates new if not exists)
    
    Returns:
        Dict with user info and wallet addresses
    """
    try:
        timestamp_ms = str(int(time.time() * 1000))
        
        # Use the user's sub-org or create a new one
        if not sub_organization_id:
            # Create a new sub-organization for this user
            sub_org_result = create_user_suborganization(verification_token, public_key)
            if not sub_org_result.get("success"):
                return sub_org_result
            sub_organization_id = sub_org_result.get("subOrganizationId")
        
        payload = {
            "type": "ACTIVITY_TYPE_OTP_LOGIN_V2",
            "timestampMs": timestamp_ms,
            "organizationId": TURNKEY_ORGANIZATION_ID,
            "parameters": {
                "publicKey": public_key,
                "verificationToken": verification_token,
                "expirationSeconds": 86400 * 7,  # 7 days session
                "invalidateExisting": True,
            },
        }
        
        headers = _sign_request(payload)
        
        response = requests.post(
            f"{TURNKEY_BASE_URL}/public/v1/submit/otp_login",
            headers=headers,
            json=payload,
            timeout=30,
        )
        
        if response.status_code != 200:
            logger.error(f"TurnKey otp_login error: {response.status_code} - {response.text}")
            return {"success": False, "error": "Login failed. Please try again."}
        
        data = response.json()
        activity_result = data.get("activity", {}).get("result", {})
        login_result = activity_result.get("otpLoginV2Result", {})
        
        # Extract user info and wallet addresses
        user_id = login_result.get("userId", "")
        wallets = login_result.get("createdWallets", [])
        
        return {
            "success": True,
            "userId": user_id,
            "subOrganizationId": sub_organization_id,
            "walletAddresses": wallets,
            "message": "Login successful",
        }
        
    except Exception as e:
        logger.error(f"otp_login error: {e}")
        return {"success": False, "error": str(e)}


def create_user_suborganization(verification_token: str, public_key: str) -> Dict[str, Any]:
    """
    Create a sub-organization for a new user.
    
    Args:
        verification_token: Token from verify_otp
        public_key: User's public key for the wallet
    
    Returns:
        Dict with subOrganizationId and wallet addresses
    """
    try:
        timestamp_ms = str(int(time.time() * 1000))
        
        # Generate a unique sub-org name
        sub_org_name = f"GoodMarket_User_{int(time.time())}"
        
        payload = {
            "type": "ACTIVITY_TYPE_CREATE_SUBORGANIZATION_V7",
            "timestampMs": timestamp_ms,
            "organizationId": TURNKEY_ORGANIZATION_ID,
            "parameters": {
                "subOrganizationName": sub_org_name,
                "rootUsers": [
                    {
                        "userName": f"User_{int(time.time())}",
                        "userEmail": "user@turnkey.placeholder",  # Required but not used for OTP users
                        "authenticators": [
                            {
                                "authenticatorName": "OTP Auth",
                                "publicKey": public_key,
                            }
                        ],
                    }
                ],
                "wallet:wallet:default": {
                    "accounts": [
                        {
                            "curve": "CURVE_SECP256K1",
                            "pathFormat": "PATH_FORMAT_BIP32",
                            "path": "m/44'/60'/0'/0/0",  # Ethereum compatible
                            "addressFormat": "ADDRESS_FORMAT_ETHEREUM",
                        },
                        {
                            "curve": "CURVE_SECP256K1",
                            "pathFormat": "PATH_FORMAT_BIP32",
                            "path": "m/44'/144'/0'/0/0",  # XDC compatible (same as XDC uses secp256k1)
                            "addressFormat": "ADDRESS_FORMAT_XRP",
                        },
                    ],
                },
                "signingKey": {
                    "publicKey": public_key,
                },
            },
        }
        
        headers = _sign_request(payload)
        
        response = requests.post(
            f"{TURNKEY_BASE_URL}/public/v1/submit/create_suborganization",
            headers=headers,
            json=payload,
            timeout=60,
        )
        
        if response.status_code != 200:
            logger.error(f"TurnKey create_suborganization error: {response.status_code} - {response.text}")
            return {"success": False, "error": f"Failed to create wallet: {response.status_code}"}
        
        data = response.json()
        activity_result = data.get("activity", {}).get("result", {})
        sub_org_result = activity_result.get("createSuborganizationResult", {})
        
        sub_org_id = sub_org_result.get("subOrganizationId", "")
        wallets = sub_org_result.get("createdWallets", [])
        
        # Extract addresses from wallets
        wallet_addresses = []
        for wallet in wallets:
            addresses = wallet.get("addresses", [])
            wallet_addresses.extend(addresses)
        
        return {
            "success": True,
            "subOrganizationId": sub_org_id,
            "walletAddresses": wallet_addresses,
            "subOrganizationName": sub_org_name,
        }
        
    except Exception as e:
        logger.error(f"create_user_suborganization error: {e}")
        return {"success": False, "error": str(e)}


def export_wallet(wallet_id: str, public_key: str) -> Dict[str, Any]:
    """
    Initialize wallet export - generates encrypted bundle.
    
    Args:
        wallet_id: The TurnKey wallet ID
        public_key: User's public key for encryption
    
    Returns:
        Dict with export bundle
    """
    try:
        timestamp_ms = str(int(time.time() * 1000))
        
        payload = {
            "type": "ACTIVITY_TYPE_EXPORT_WALLET",
            "timestampMs": timestamp_ms,
            "organizationId": TURNKEY_ORGANIZATION_ID,
            "parameters": {
                "walletId": wallet_id,
                "targetPublicKey": public_key,
            },
        }
        
        headers = _sign_request(payload)
        
        response = requests.post(
            f"{TURNKEY_BASE_URL}/public/v1/submit/export_wallet",
            headers=headers,
            json=payload,
            timeout=30,
        )
        
        if response.status_code != 200:
            logger.error(f"TurnKey export_wallet error: {response.status_code} - {response.text}")
            return {"success": False, "error": "Failed to initialize export"}
        
        data = response.json()
        activity_result = data.get("activity", {}).get("result", {})
        export_result = activity_result.get("exportWalletResult", {})
        
        encrypted_bundle = export_result.get("encryptedWallet", "")
        
        return {
            "success": True,
            "encryptedBundle": encrypted_bundle,
            "message": "Export initialized. Complete in browser.",
        }
        
    except Exception as e:
        logger.error(f"export_wallet error: {e}")
        return {"success": False, "error": str(e)}


def get_user_wallets(sub_organization_id: str) -> Dict[str, Any]:
    """
    Get all wallets for a user/sub-organization.
    
    Args:
        sub_organization_id: The sub-organization ID
    
    Returns:
        Dict with wallet list
    """
    try:
        headers = _sign_request({})
        
        response = requests.get(
            f"{TURNKEY_BASE_URL}/public/v1/query/get_wallets",
            headers=headers,
            params={"organizationId": sub_organization_id},
            timeout=30,
        )
        
        if response.status_code != 200:
            logger.error(f"TurnKey get_wallets error: {response.status_code} - {response.text}")
            return {"success": False, "error": "Failed to get wallets"}
        
        data = response.json()
        wallets = data.get("wallets", [])
        
        return {
            "success": True,
            "wallets": wallets,
        }
        
    except Exception as e:
        logger.error(f"get_user_wallets error: {e}")
        return {"success": False, "error": str(e)}


def check_turnkey_configured() -> bool:
    """Check if TurnKey is properly configured with API keys."""
    return bool(
        TURNKEY_API_PUBLIC_KEY and 
        TURNKEY_ORGANIZATION_ID and 
        TURNKEY_API_PRIVATE_KEY
    )


# Clean up expired OTP activities periodically
def cleanup_expired_otps():
    """Remove expired OTP activities from cache."""
    with _otp_cache_lock:
        current_time = time.time()
        expired_keys = [
            oid for oid, data in _otp_activities.items()
            if data["expires_at"] < current_time
        ]
        for key in expired_keys:
            del _otp_activities[key]