"""
Webserver for the main app
"""
import os
import sys
from io import BytesIO
from wtforms import StringField, PasswordField, BooleanField
from wtforms.validators import InputRequired, Length
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, after_this_request, request, Response, redirect, url_for, abort
from flask_login import LoginManager, UserMixin, login_required, login_user, logout_user
from flask_bootstrap import Bootstrap
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import sessionmaker
#from sqlalchemy import create_engine
from flask_wtf import FlaskForm
import gzip
import json
import functools
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine


SECRET_LENGTH = 24

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from common import get_config, get_uri


debug = 'DEBUG' in os.environ and os.environ['DEBUG'] == "on"


def gzipped(f):
    @functools.wraps(f)
    def view_func(*args, **kwargs):
        @after_this_request
        def zipper(response):
            accept_encoding = request.headers.get('Accept-Encoding', '')

            if 'gzip' not in accept_encoding.lower():
                return response

            response.direct_passthrough = False

            if response.status_code < 200 or response.status_code >= 300 or 'Content-Encoding' in response.headers:
                return response
            gzip_buffer = BytesIO()
            gzip_file = gzip.GzipFile(mode='wb',
                                      fileobj=gzip_buffer)
            gzip_file.write(response.data)
            gzip_file.close()

            response.data = gzip_buffer.getvalue()
            response.headers['Content-Encoding'] = 'gzip'
            response.headers['Vary'] = 'Accept-Encoding'
            response.headers['Content-Length'] = len(response.data)

            return response

        return f(*args, **kwargs)

    return view_func


app = Flask("Cyborg ear trainer", template_folder=os.path.join(os.path.dirname(__file__), "templates"))


def set_app_db(a):
    settings = get_config()
    a.config["SQLALCHEMY_DATABASE_URI"] = get_uri(settings)
    a.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    return


set_app_db(app)

db = SQLAlchemy(app)


# flask-login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

login_manager.init_app(app)
app.config.setdefault('BOOTSTRAP_SERVE_LOCAL', True)
Bootstrap(app)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), unique=True)
    password = db.Column(db.String(100))

    def __init__(self, username, password):
        self.username = username
        self.password = generate_password_hash(password, method='sha256')

    def __repr__(self):
        return "%d/%s" % (self.id, self.username)


class Sound(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    path = db.Column(db.String(30), unique=True)
    picture = db.Column(db.String(100))

    def __init__(self, id, name, path, picture):
        self.id = id
        self.name = name
        self.path = path
        self.picture = picture

    def __repr__(self):
        return "%s/%s" % (self.id, self.name)
    
    
class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sound_ids = db.Column(db.PickleType())
    difficulty = db.Column(db.Integer())

    def __init__(self, id, name, sound_ids, difficulty):
        self.id = id
        self.name = name
        self.sound_ids = sound_ids
        self.difficulty = difficulty
        
    def __repr__(self):
        return "%s/%s" % (self.id, self.name)
    
    
class Lesion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(30))
    question_ids = db.Column(db.PickleType())
    difficulty = db.Column(db.Integer())

    def __init__(self, id, name, question_ids, difficulty):
        self.id = id
        self.name = name
        self.question_ids = question_ids
        self.difficulty = difficulty
        
    def __repr__(self):
        return "%s/%s" % (self.id, self.name)


Base = declarative_base()


class AppConfig(Base):
    __tablename__ = "app_config"
    id = db.Column(db.Integer, primary_key=True)
    secret = db.Column(db.BINARY(SECRET_LENGTH), unique=True)

    def __init__(self, id , secret):
        self.id = id
        self.secret = secret

    def __repr__(self):
        return "%d/%s/%s" % (self.id, self.name)


def init_db(uri):
    """
    Checks if db is init, if not inits it

    :return:
    """
    engine = create_engine(uri)
    User.metadata.create_all(engine)
    AppConfig.metadata.create_all(engine)

    # Add admin if does not exist

    Session = sessionmaker()
    Session.configure(bind=engine)
    session = Session()

    user = session.query(User).first()
    if user is None:
        settings = get_config()
        entry = User(id=0, username="admin", password=settings["webserver"]["init_password"])
        session.add(entry)
        session.commit()
        print('First run, created database with user admin')

    app_config = session.query(AppConfig).first()
    if app_config is None:
        entry = AppConfig(id=0, secret=os.urandom(SECRET_LENGTH))
        session.add(entry)
        session.commit()
        print('First run, created table with secret key for sessions')

        app_config = session.query(AppConfig).first()

    app.config["SECRET_KEY"] = app_config.secret
    return


class LoginForm(FlaskForm):
    username = StringField('username', validators=[InputRequired(), Length(min=4, max=15)])
    password = PasswordField('password', validators=[InputRequired(), Length(min=4, max=80)])
    remember = BooleanField('remember me')


@app.route("/")
@login_required
def root():
    return render_template("index.jinja2", row=5)


@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()

    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data.strip()).first()
        if user is not None and check_password_hash(user.password, form.password.data):
            login_user(user, remember=form.remember.data)
            return redirect('/')
        else:
            form.password.errors.append('Invalid username or password')

    return render_template('login.jinja2', form=form)


# somewhere to logout
@app.route("/logout")
@login_required
def logout():
    logout_user()
    return Response('<p>Logged out</p>')


# handle login failed
@app.errorhandler(401)
def page_not_found(e):
    return Response('<p>Login failed</p>')


# callback to reload the user object
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def run():
    settings = get_config()
    app.run(debug=debug, host='0.0.0.0', port=int(settings["webserver"]["port"]), threaded=True)
    return


def mysql_init_db(uri, settings):
    #TODO FIX, for now create the database by hand
    mysql_engine = create_engine(uri)
    print(uri)
    mysql_engine.execute("CREATE DATABASE IF NOT EXISTS {0} ".format(settings["db"]["db_name"]))
    return


if __name__ == "__main__":
    settings = get_config()
    mysql_init_db(get_uri(settings), settings)
    init_db(get_uri(settings))
    run()


