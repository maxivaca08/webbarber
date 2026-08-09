"""Entry point de producción para el backend Flask.

En producción se ejecuta con gunicorn:  gunicorn wsgi:app
A diferencia de `python app.py`, acá no corre el bloque `if __name__ == '__main__'`,
por eso inicializamos la base explícitamente al importar el módulo.
"""
from app import app
from database import init_db

# Crea las tablas y el admin inicial si la base está vacía (idempotente).
init_db()

if __name__ == '__main__':
    app.run()
