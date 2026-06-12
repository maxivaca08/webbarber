import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, 'peluqueria.db')
SECRET_KEY = os.environ.get('SECRET_KEY', 'peluqueria_secret_key_2024')
DEBUG = os.environ.get('DEBUG', 'true').lower() == 'true'
HOST = os.environ.get('HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT', 5001))
