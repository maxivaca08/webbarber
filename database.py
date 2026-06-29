import sqlite3
import os
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), 'peluqueria.db')

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA journal_mode = WAL')
    return conn

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

    # Migración: agregar recordatorio_enviado para no mandar dos veces
    if 'turnos' in tables:
        cols = {r[1] for r in db.execute("PRAGMA table_info(turnos)").fetchall()}
        if 'recordatorio_enviado' not in cols:
            db.execute('ALTER TABLE turnos ADD COLUMN recordatorio_enviado INTEGER NOT NULL DEFAULT 0')
            db.commit()

    # Migración: notificación al admin cuando un cliente reprograma
    if 'turnos' in tables:
        cols = {r[1] for r in db.execute("PRAGMA table_info(turnos)").fetchall()}
        if 'reprogramado_sin_ver' not in cols:
            db.execute('ALTER TABLE turnos ADD COLUMN reprogramado_sin_ver INTEGER NOT NULL DEFAULT 0')
            db.commit()

    # Migración: agregar callmebot_key y telegram_user en usuarios
    if 'usuarios' in tables:
        cols = {r[1] for r in db.execute("PRAGMA table_info(usuarios)").fetchall()}
        if 'callmebot_key' not in cols:
            db.execute('ALTER TABLE usuarios ADD COLUMN callmebot_key TEXT')
            db.commit()
        if 'telegram_user' not in cols:
            db.execute('ALTER TABLE usuarios ADD COLUMN telegram_user TEXT')
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

    # Seed: admin y cliente por defecto
    if db.execute("SELECT COUNT(*) FROM usuarios WHERE rol='admin'").fetchone()[0] == 0:
        db.execute(
            "INSERT INTO usuarios (nombre, apellido, email, password_hash, rol) "
            "VALUES (?,?,?,?,?)",
            ('Maximiliano', 'Vaca', 'maxivaca2304@gmail.com',
             generate_password_hash('ferre0811'), 'admin')
        )
        db.commit()

    db.close()
