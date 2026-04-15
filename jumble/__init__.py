from .blockchain import jumble_blockchain
from .jumble_service import jumble_service
from .routes import jumble_bp


def init_jumble(app):
    try:
        app.register_blueprint(jumble_bp)
        return True
    except Exception as e:
        print(f"❌ Jumble initialization failed: {e}")
        return False


__all__ = ['jumble_blockchain', 'jumble_service', 'jumble_bp', 'init_jumble']
