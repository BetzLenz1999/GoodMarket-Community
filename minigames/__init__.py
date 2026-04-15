
from .minigames_manager import minigames_manager
from .routes import minigames_bp
from .blockchain import minigames_blockchain

def init_minigames(app):
    """Initialize minigames system"""
    try:
        app.register_blueprint(minigames_bp)
        return True
    except Exception as e:
        print(f"❌ Minigames initialization failed: {e}")
        return False

__all__ = ['minigames_manager', 'minigames_bp', 'minigames_blockchain', 'init_minigames']
