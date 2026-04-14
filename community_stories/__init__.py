
from flask import Flask
from .routes import community_stories_bp
from .community_stories_service import community_stories_service
import logging

logger = logging.getLogger(__name__)

def init_community_stories(app: Flask):
    """Initialize Community Stories module"""
    try:
        # Register blueprint
        app.register_blueprint(community_stories_bp, url_prefix='/community-stories')
        
        logger.info("✅ Community Stories module initialized")
        return True
    except Exception as e:
        logger.error(f"❌ Community Stories initialization failed: {e}")
        return False
