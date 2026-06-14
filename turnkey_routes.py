"""
TurnKey Authentication Routes
Email OTP Login + Wallet Creation + Export
"""

from flask import Blueprint, request, jsonify, session
import logging
import os

from turnkey_client import (
    init_otp_auth,
    verify_otp,
    otp_login,
    create_user_suborganization,
    export_wallet,
    get_user_wallets,
    check_turnkey_configured,
    cleanup_expired_otps,
)

logger = logging.getLogger(__name__)

# Create Blueprint
turnkey_routes = Blueprint("turnkey", __name__, url_prefix='/api/turnkey')


def _check_turnkey_enabled():
    """Check if TurnKey is enabled and configured."""
    if not check_turnkey_configured():
        return jsonify({
            "success": False,
            "error": "TurnKey is not configured. Please set TURNKEY_API_PUBLIC_KEY, TURNKEY_ORGANIZATION_ID, and TURNKEY_API_PRIVATE_KEY environment variables."
        }), 503
    return None


@turnkey_routes.route("/status", methods=["GET"])
def turnkey_status():
    """Check if TurnKey integration is configured."""
    enabled = check_turnkey_configured()
    return jsonify({
        "success": True,
        "enabled": enabled,
        "message": "TurnKey is configured and ready" if enabled else "TurnKey not configured"
    })


@turnkey_routes.route("/auth/init-otp", methods=["POST"])
def turnkey_init_otp():
    """
    Initialize OTP authentication - sends OTP code to user's email.
    
    Request body:
    {
        "email": "user@example.com"
    }
    """
    # Check if TurnKey is enabled
    error_resp = _check_turnkey_enabled()
    if error_resp:
        return error_resp
    
    try:
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        
        if not email or "@" not in email:
            return jsonify({"success": False, "error": "Valid email address is required"}), 400
        
        # Clean up expired OTPs
        cleanup_expired_otps()
        
        # Initialize OTP auth
        result = init_otp_auth(email, app_name="GoodMarket")
        
        if result.get("success"):
            return jsonify({
                "success": True,
                "activityId": result.get("activityId"),
                "message": result.get("message", "OTP code sent to your email"),
            })
        else:
            return jsonify({
                "success": False,
                "error": result.get("error", "Failed to send OTP")
            }), 400
            
    except Exception as e:
        logger.error(f"turnkey_init_otp error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@turnkey_routes.route("/auth/verify-otp", methods=["POST"])
def turnkey_verify_otp():
    """
    Verify OTP code and get verification token.
    
    Request body:
    {
        "email": "user@example.com",
        "otpCode": "123456",
        "publicKey": "0x..."
    }
    """
    error_resp = _check_turnkey_enabled()
    if error_resp:
        return error_resp
    
    try:
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        otp_code = (data.get("otpCode") or "").strip()
        public_key = (data.get("publicKey") or "").strip()
        
        if not email or "@" not in email:
            return jsonify({"success": False, "error": "Valid email is required"}), 400
        
        if not otp_code or len(otp_code) < 6:
            return jsonify({"success": False, "error": "Valid OTP code is required"}), 400
        
        if not public_key:
            return jsonify({"success": False, "error": "Public key is required for wallet creation"}), 400
        
        # Verify OTP
        result = verify_otp(email, otp_code, public_key)
        
        if result.get("success"):
            return jsonify({
                "success": True,
                "verificationToken": result.get("verificationToken"),
                "message": "OTP verified successfully",
            })
        else:
            return jsonify({
                "success": False,
                "error": result.get("error", "Invalid OTP code")
            }), 400
            
    except Exception as e:
        logger.error(f"turnkey_verify_otp error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@turnkey_routes.route("/auth/login", methods=["POST"])
def turnkey_login():
    """
    Complete OTP login - creates wallet and session.
    
    Request body:
    {
        "verificationToken": "...",
        "publicKey": "0x...",
        "email": "user@example.com"
    }
    """
    error_resp = _check_turnkey_enabled()
    if error_resp:
        return error_resp
    
    try:
        data = request.get_json(silent=True) or {}
        verification_token = (data.get("verificationToken") or "").strip()
        public_key = (data.get("publicKey") or "").strip()
        email = (data.get("email") or "").strip().lower()
        
        if not verification_token:
            return jsonify({"success": False, "error": "Verification token is required"}), 400
        
        if not public_key:
            return jsonify({"success": False, "error": "Public key is required"}), 400
        
        # Create sub-organization (wallet) for user
        sub_org_result = create_user_suborganization(verification_token, public_key)
        
        if not sub_org_result.get("success"):
            return jsonify({
                "success": False,
                "error": sub_org_result.get("error", "Failed to create wallet")
            }), 400
        
        # Complete login
        login_result = otp_login(verification_token, public_key)
        
        if login_result.get("success"):
            # Store user info in session
            session["wallet"] = sub_org_result.get("walletAddresses", [None])[0] if sub_org_result.get("walletAddresses") else None
            session["verified"] = True
            session["email"] = email
            session["login_method"] = "turnkey"
            session["turnkey_user_id"] = login_result.get("userId")
            session["turnkey_sub_org_id"] = sub_org_result.get("subOrganizationId")
            
            # Get Ethereum address (first wallet)
            eth_address = None
            for addr in sub_org_result.get("walletAddresses", []):
                if addr.startswith("0x"):
                    eth_address = addr
                    break
            
            return jsonify({
                "success": True,
                "message": "Login successful",
                "wallet": eth_address,
                "walletAddresses": sub_org_result.get("walletAddresses", []),
                "subOrganizationId": sub_org_result.get("subOrganizationId"),
            })
        else:
            return jsonify({
                "success": False,
                "error": login_result.get("error", "Login failed")
            }), 400
            
    except Exception as e:
        logger.error(f"turnkey_login error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@turnkey_routes.route("/wallet/export/init", methods=["POST"])
def turnkey_export_init():
    """
    Initialize wallet export - returns encrypted bundle for client-side decryption.
    
    Request body:
    {
        "walletId": "..."
    }
    """
    error_resp = _check_turnkey_enabled()
    if error_resp:
        return error_resp
    
    try:
        # Check if user is logged in with TurnKey
        if session.get("login_method") != "turnkey":
            return jsonify({"success": False, "error": "Please login with email to access this feature"}), 401
        
        data = request.get_json(silent=True) or {}
        wallet_id = (data.get("walletId") or "").strip()
        
        if not wallet_id:
            return jsonify({"success": False, "error": "Wallet ID is required"}), 400
        
        # For security, verify wallet belongs to user
        sub_org_id = session.get("turnkey_sub_org_id")
        
        # Get user's public key from session (stored during login)
        public_key = session.get("turnkey_public_key", "")
        
        result = export_wallet(wallet_id, public_key)
        
        if result.get("success"):
            return jsonify({
                "success": True,
                "encryptedBundle": result.get("encryptedBundle"),
                "message": "Export initialized",
            })
        else:
            return jsonify({
                "success": False,
                "error": result.get("error", "Failed to initialize export")
            }), 400
            
    except Exception as e:
        logger.error(f"turnkey_export_init error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@turnkey_routes.route("/wallet/list", methods=["GET"])
def turnkey_list_wallets():
    """Get all wallets for the logged-in TurnKey user."""
    error_resp = _check_turnkey_enabled()
    if error_resp:
        return error_resp
    
    try:
        if session.get("login_method") != "turnkey":
            return jsonify({"success": False, "error": "Please login with email"}), 401
        
        sub_org_id = session.get("turnkey_sub_org_id")
        
        if not sub_org_id:
            return jsonify({"success": False, "error": "No wallet found"}), 400
        
        result = get_user_wallets(sub_org_id)
        
        if result.get("success"):
            return jsonify({
                "success": True,
                "wallets": result.get("wallets", []),
            })
        else:
            return jsonify({
                "success": False,
                "error": result.get("error", "Failed to get wallets")
            }), 400
            
    except Exception as e:
        logger.error(f"turnkey_list_wallets error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@turnkey_routes.route("/auth/logout", methods=["POST"])
def turnkey_logout():
    """Logout TurnKey user and clear session."""
    try:
        # Clear TurnKey-related session data
        session.pop("turnkey_user_id", None)
        session.pop("turnkey_sub_org_id", None)
        session.pop("turnkey_public_key", None)
        
        # Note: We don't clear wallet, verified, email as they might be used by other login methods
        # Only clear TurnKey-specific data
        
        return jsonify({
            "success": True,
            "message": "Logged out from TurnKey"
        })
    except Exception as e:
        logger.error(f"turnkey_logout error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500