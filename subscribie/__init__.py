# -*- coding: utf-8 -*-                                                          
"""                                                                              
    subscribie.app                                                                 
    ~~~~~~~~~                                                                    
    A microframework for buiding subsciption websites.                                                                                 
    This module implements the central subscribie application.              
                                                                                 
    :copyright: (c) 2018 by Karma Computing Ltd
"""
from os import path
import logging
import logging.config
log_file_path = path.join(path.dirname(path.abspath(__file__)), 'logging.conf')
logging.config.fileConfig(log_file_path)
# Create logger
logger = logging.getLogger('subscribie')
import os
from os import environ
import sys
import random
import requests
import time
import gocardless_pro
import sqlite3
import smtplib
from email.mime.text import MIMEText
import jinja2 
import flask
import datetime
from base64 import b64encode, urlsafe_b64encode
import git
import shutil
try:
    import sendgrid
    from sendgrid.helpers.mail import *
except Exception:
    pass
from flask import (Flask, render_template, session, redirect, url_for, escape, 
                   request, current_app, send_from_directory, jsonify, Blueprint)
from oauth2client.client import OAuth2WebServerFlow
import yaml
from .jamla import Jamla
from .forms import (StripWhitespaceForm, LoginForm, CustomerForm, 
                    GocardlessConnectForm, StripeConnectForm, TawkConnectForm,
                    GoogleTagManagerConnectForm, ItemsForm)
from .Template import load_theme
from blinker import signal
from flask_cors import CORS
from flask_uploads import configure_uploads, UploadSet, IMAGES,\
    patch_request_class

def create_app(test_config=None):
    # create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY='dev',
        DATABASE=os.path.join(app.instance_path, 'subscribie.sqlite'),
    )

    @app.before_request
    def start_session():
        try:
            session['sid']
        except KeyError:
            session['sid'] = b64encode(os.urandom(10)).decode('utf-8')
            print("Starting with sid {}".format(session['sid']))

    if test_config is None:
        # load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=False)
    else:
        # load the test config if passed in
        app.config.from_mapping(test_config)
    # ensure the instance folder exists
    try: 
        os.makedirs(app.instance_path)
    except OSError:
        pass

    cors = CORS(app, resources={r"/api/*": {"origins": "*"}})
    jamlaApp = Jamla()
    global jamla
    jamla = jamlaApp.load(src=app.config['JAMLA_PATH'])                          
    images = UploadSet('images', IMAGES)
    patch_request_class(app, 2 * 1024 * 1024)
    configure_uploads(app, images)

    from . import db
    db.init_app(app)
    from . import auth
    from . import views
    app.register_blueprint(auth.bp)
    app.register_blueprint(views.bp)
    from .blueprints.admin import admin_theme
    app.register_blueprint(admin_theme, url_prefix='/admin')
    try:
        front_page = jamla['front_page']
    except:
        front_page = 'choose'
    try:
        app.add_url_rule('/', 'index', views.__getattribute__(front_page))
    except AttributeError:
        app.add_url_rule('/', 'index', views.__getattribute__('choose'))

    """The Subscribie object implements a flask application suited to subscription 
    based web applications and acts as the central object. Once it is created    
    it will act as a central registry for default views, application workflow,   
    the URL rules, and much more. Note most of the application must be defined   
    in Jamla format, a yaml based application markup.                            
                                                                                 
    Usually you create a :class:`Subscribie` instance in your main module or          
    in the :file:`__init__.py` file of your package like this::                  
                                                                                 
        from subscribie import Subscribie 
        app = Subscribie(__name__)                                                 
                                                                                 
    """
    # the signals                                                                    
    from .signals import journey_complete

    alphanum = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRTUVWXYZ0123456789"

    # Set custom modules path
    if type(jamla['modules_path']) is str:
        sys.path.append(jamla['modules_path'])
    elif type(jamla['modules_path']) is list:
        for path in jamla['modules_path']:
            sys.path.append(path)
        
    with app.app_context(): 
        load_theme(app)

    # Register yml pages as routes
    if 'pages' in jamla:
        for i,v in enumerate(jamla['pages']):
            page = jamla['pages'][i].popitem()
            page_path = page[1]['path']
            template_file = page[1]['template_file']
            view_func_name = page[0]
            ##Generate view function
            generate_view_func = """def %s_view_func():
            return render_template('%s', jamla=jamla)""" % (view_func_name, template_file)
            exec(generate_view_func) in globals(), locals()
            method_name = view_func_name + "_view_func"
            possibles = globals().copy()
            possibles.update(locals())
            view_func = possibles.get(method_name)
            app.add_url_rule("/" + page_path, view_func_name + '_view_func', view_func)

    # Handling Errors Gracefully
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('errors/404.html'), 404
    @app.errorhandler(500)
    def page_not_found(e):
        return render_template('errors/500.html'), 500

    # Import any custom modules
    if 'modules' in jamla:
        try:
            for module in jamla['modules']:
                print("Importing module: {}".format(module['name']))
                # Assume standard python module
                try:
                  __import__(module['name'])
                  # Try to fetch the module if 'src' is present
                 
                  # Register module as blueprint (if it is one)
                  try:
                      importedModule = __import__(module['name'])
                      if isinstance(getattr(importedModule, module['name']), Blueprint):
                          # Load any config the Blueprint declares
                          blueprint = getattr(importedModule, module['name'])
                          blueprintConfig = ''.join([blueprint.root_path,'/',
                                                     'config.py'])
                          app.config.from_pyfile(blueprintConfig, silent=True)
                          # Register the Blueprint
                          app.register_blueprint(getattr(importedModule,
                                                         module['name']))
                  except AttributeError:
                      pass
                except ImportError:
                  # Attempt to load module from src
                  #import pdb;pdb.set_trace()
                  dest = os.path.join(os.path.dirname(__file__),'modules/',
                                      module['name'])
                  os.makedirs(dest, exist_ok=True)
                  try: 
                    git.Repo.clone_from(module['src'], dest)
                  except git.exc.GitCommandError:
                    pass
                  # Now re-try import
                  try:
                    __import__(module['name'])
                  except ImportError:
                    exit("Could not import module: {}".format(module['name']))

        except TypeError as e:
            print(e)
    return app
