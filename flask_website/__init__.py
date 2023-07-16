from flask import Flask

app = Flask(__name__)

from flask_website.views import views

app.config.from_pyfile('config.py')

