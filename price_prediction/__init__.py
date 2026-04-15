from .routes import price_prediction_bp
from .price_prediction_service import price_prediction_service

def init_price_prediction(app):
    app.register_blueprint(price_prediction_bp)
