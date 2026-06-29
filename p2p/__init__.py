from .routes import p2p_bp
from .expiry import init_p2p_expiry_scheduler, get_expiry_scheduler


def init_p2p(app):
    """Initialize the P2P G$ trading module."""
    try:
        app.register_blueprint(p2p_bp)
        import logging
        logging.getLogger(__name__).info("✅ P2P trading module initialized")
        return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"❌ P2P trading initialization failed: {e}")
        return False


__all__ = [
    "p2p_bp",
    "init_p2p",
    "init_p2p_expiry_scheduler",
    "get_expiry_scheduler",
]
