import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'peluqueria.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn

def init_db():
    db = get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS clientes (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre    TEXT NOT NULL,
            apellido  TEXT NOT NULL,
            telefono  TEXT,
            email     TEXT,
            creado_en DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS barberos (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre       TEXT NOT NULL,
            apellido     TEXT NOT NULL,
            especialidad TEXT,
            activo       INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS servicios (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre            TEXT NOT NULL,
            descripcion       TEXT,
            duracion_minutos  INTEGER NOT NULL DEFAULT 30,
            precio            REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS turnos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id  INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
            barbero_id  INTEGER NOT NULL REFERENCES barberos(id) ON DELETE CASCADE,
            servicio_id INTEGER NOT NULL REFERENCES servicios(id) ON DELETE CASCADE,
            fecha_hora  DATETIME NOT NULL,
            estado      TEXT NOT NULL DEFAULT 'pendiente'
                        CHECK(estado IN ('pendiente','confirmado','completado','cancelado')),
            notas       TEXT,
            creado_en   DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_turnos_fecha ON turnos(fecha_hora);
        CREATE INDEX IF NOT EXISTS idx_turnos_barbero ON turnos(barbero_id);
        CREATE INDEX IF NOT EXISTS idx_turnos_cliente ON turnos(cliente_id);
    ''')

    # Datos de ejemplo si la DB está vacía
    if db.execute('SELECT COUNT(*) FROM barberos').fetchone()[0] == 0:
        db.executescript("""
            INSERT INTO barberos (nombre, apellido, especialidad) VALUES
                ('Carlos','Pérez','Corte clásico'),
                ('María','López','Coloración y tinte'),
                ('Juan','García','Barba y bigote');

            INSERT INTO servicios (nombre, descripcion, duracion_minutos, precio) VALUES
                ('Corte de pelo','Corte con tijera o máquina',30,1500),
                ('Coloración','Tintura completa del cabello',90,4500),
                ('Barba','Afeitado y perfilado de barba',20,800),
                ('Brushing','Lavado y secado con cepillo',40,1200),
                ('Mechas','Mechas parciales o completas',120,6000);
        """)

    db.commit()
    db.close()
