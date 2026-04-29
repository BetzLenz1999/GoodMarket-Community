from .routes import daily_checkin_bp


def init_daily_checkin(app):
    """Initialize Daily Check-in module."""
    try:
        app.register_blueprint(daily_checkin_bp)
        return True
    except Exception as exc:
        print(f"❌ Daily Check-in initialization failed: {exc}")
        return False


__all__ = ["daily_checkin_bp", "init_daily_checkin"]
