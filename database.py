import sqlite3
import os
import secrets
from werkzeug.security import generate_password_hash

# DATA_DIR: carpeta donde vive la base. En local es el directorio del proyecto;
# en producción se apunta al volumen persistente (p. ej. /data en Railway) para
# que la base NO se borre en cada deploy.
DATA_DIR = os.environ.get('DATA_DIR') or os.path.dirname(__file__)
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, 'peluqueria.db')

def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA journal_mode = WAL')
    return conn

def get_db():
    """Devuelve una conexión SQLite.

    Dentro de un request Flask la conexión se cachea en `g` y su cierre queda
    garantizado por `close_db` (registrado como teardown), incluso si la vista
    lanza una excepción antes del `db.close()` explícito. Fuera de contexto de
    aplicación (p. ej. hilos de fondo de la lista de espera) devuelve una
    conexión suelta que el llamador debe cerrar."""
    try:
        from flask import g, has_app_context
    except ImportError:
        return _connect()
    if not has_app_context():
        return _connect()
    if 'db' not in g:
        g.db = _connect()
    return g.db

def close_db(e=None):
    """Cierra la conexión cacheada en `g` al final del request (teardown)."""
    from flask import g
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()

    # Migración: si existe esquema viejo, eliminarlo
    tables = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    if 'clientes' in tables or 'barberos' in tables:
        db.executescript('''
            DROP TABLE IF EXISTS turnos;
            DROP TABLE IF EXISTS clientes;
            DROP TABLE IF EXISTS barberos;
            DROP TABLE IF EXISTS servicios;
            DROP TABLE IF EXISTS disponibilidad;
            DROP TABLE IF EXISTS usuarios;
        ''')

    # Migración: ampliar CHECK(estado) de turnos para soportar 'pendiente' y 'rechazado'
    # (seña obligatoria por transferencia). SQLite no permite ALTER de un CHECK,
    # así que se recrea la tabla preservando los datos existentes.
    if 'turnos' in tables:
        turnos_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='turnos'"
        ).fetchone()[0]
        if 'pendiente' not in turnos_sql:
            db.executescript('''
                ALTER TABLE turnos RENAME TO turnos_old;
                CREATE TABLE turnos (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    cliente_id          INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                    disponibilidad_id   INTEGER NOT NULL UNIQUE REFERENCES disponibilidad(id),
                    estado              TEXT NOT NULL DEFAULT 'reservado'
                                        CHECK(estado IN ('reservado','confirmado','completado',
                                                          'cancelado','pendiente','rechazado')),
                    notas               TEXT,
                    notificado_rechazo  INTEGER NOT NULL DEFAULT 0,
                    creado_en           DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO turnos (id, cliente_id, disponibilidad_id, estado, notas, creado_en)
                    SELECT id, cliente_id, disponibilidad_id, estado, notas, creado_en FROM turnos_old;
                DROP TABLE turnos_old;
            ''')
            db.commit()

    # Migración: agregar notificado_rechazo si la tabla ya existía sin esa columna
    if 'turnos' in tables:
        cols = {r[1] for r in db.execute("PRAGMA table_info(turnos)").fetchall()}
        if 'notificado_rechazo' not in cols:
            db.execute('ALTER TABLE turnos ADD COLUMN notificado_rechazo INTEGER NOT NULL DEFAULT 0')
            db.commit()

    # Migración: agregar comprobante_path para adjuntar comprobante de transferencia
    if 'turnos' in tables:
        cols = {r[1] for r in db.execute("PRAGMA table_info(turnos)").fetchall()}
        if 'comprobante_path' not in cols:
            db.execute('ALTER TABLE turnos ADD COLUMN comprobante_path TEXT')
            db.commit()

    # Migración: notificación al admin cuando un cliente reprograma
    if 'turnos' in tables:
        cols = {r[1] for r in db.execute("PRAGMA table_info(turnos)").fetchall()}
        if 'reprogramado_sin_ver' not in cols:
            db.execute('ALTER TABLE turnos ADD COLUMN reprogramado_sin_ver INTEGER NOT NULL DEFAULT 0')
            db.commit()

    db.executescript('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre        TEXT NOT NULL,
            apellido      TEXT NOT NULL,
            telefono      TEXT,
            email         TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            rol           TEXT NOT NULL DEFAULT 'cliente'
                          CHECK(rol IN ('admin','cliente')),
            creado_en     DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS disponibilidad (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha       DATE NOT NULL,
            hora_inicio TEXT NOT NULL,
            hora_fin    TEXT NOT NULL,
            disponible  INTEGER NOT NULL DEFAULT 1,
            UNIQUE(fecha, hora_inicio)
        );

        CREATE TABLE IF NOT EXISTS turnos (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id          INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
            disponibilidad_id   INTEGER NOT NULL UNIQUE REFERENCES disponibilidad(id),
            estado              TEXT NOT NULL DEFAULT 'reservado'
                                CHECK(estado IN ('reservado','confirmado','completado',
                                                  'cancelado','pendiente','rechazado')),
            notas               TEXT,
            notificado_rechazo  INTEGER NOT NULL DEFAULT 0,
            creado_en           DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS lista_espera (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
            fecha      DATE NOT NULL,
            creado_en  DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(usuario_id, fecha)
        );

        CREATE INDEX IF NOT EXISTS idx_disp_fecha    ON disponibilidad(fecha);
        CREATE INDEX IF NOT EXISTS idx_turnos_cliente ON turnos(cliente_id);
        CREATE INDEX IF NOT EXISTS idx_turnos_disp    ON turnos(disponibilidad_id);
        CREATE INDEX IF NOT EXISTS idx_espera_fecha   ON lista_espera(fecha);
    ''')

    # Seed: admin por defecto. Credenciales por variable de entorno;
    # si no hay ADMIN_PASSWORD se genera una temporal y se muestra una sola vez.
    if db.execute("SELECT COUNT(*) FROM usuarios WHERE rol='admin'").fetchone()[0] == 0:
        admin_email  = os.getenv('ADMIN_EMAIL', 'admin@barberapp.com')
        admin_nombre = os.getenv('ADMIN_NOMBRE', 'Admin')
        admin_pass   = os.getenv('ADMIN_PASSWORD')
        if not admin_pass:
            admin_pass = secrets.token_urlsafe(12)
            print('=' * 60)
            print('[init] Admin creado con contraseña temporal.')
            print(f'[init]   Email:      {admin_email}')
            print(f'[init]   Contraseña: {admin_pass}')
            print('[init] Cambiala e idealmente definí ADMIN_PASSWORD por entorno.')
            print('=' * 60)
        db.execute(
            "INSERT INTO usuarios (nombre, apellido, email, password_hash, rol) "
            "VALUES (?,?,?,?,?)",
            (admin_nombre, '', admin_email, generate_password_hash(admin_pass), 'admin')
        )
        db.commit()

    db.close()
