from .routes import savings_bp


def init_savings(app):
    """Initialize G$ Savings module"""
    try:
        app.register_blueprint(savings_bp)
        import logging
        logging.getLogger(__name__).info("✅ G$ Savings module initialized")
        return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"❌ G$ Savings initialization failed: {e}")
        return False


__all__ = ["savings_bp", "init_savings"]
