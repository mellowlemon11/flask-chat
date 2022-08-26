from socket import SocketIO, socket
from flask import Flask, render_template
from flask_bootstrap import Bootstrap
from flask_mail import Mail
from flask_moment import Moment
from flask_sqlalchemy import SQLAlchemy
from config import config
from flask_login import LoginManager
from flask_socketio import SocketIO
from flask_session import Session
import secrets




login_manager = LoginManager()
login_manager.login_view = "auth.login"

bootstrap = Bootstrap()
mail = Mail()
moment = Moment()
db = SQLAlchemy()
socketio = SocketIO()

ROOMS = ['lounge', 'news', 'games', 'coding']


def create_app(config_name):
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    secret = secrets.token_urlsafe(32)
    app.secret_key = secret
    config[config_name].init_app(app)

    bootstrap.init_app(app)
    mail.init_app(app)
    moment.init_app(app)
    db.init_app(app)
    socketio.init_app(app)

    from .main import main as main_blueprint

    app.register_blueprint(main_blueprint)

    # attach routes and custom error pages here
    from .auth import auth as auth_blueprint

    app.register_blueprint(auth_blueprint, url_prefix="/auth")
    login_manager.init_app(app)
    return app
