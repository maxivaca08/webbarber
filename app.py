from flask import Flask, request, jsonify, session, send_from_directory, abort

# Carga opcional de variables desde un archivo .env (si python-dotenv está
# instalado). No es obligatorio: si falta, se usan las variables del entorno.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import init_db, get_db, close_db
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, date, timedelta, timezone
import sqlite3
import os
import uuid
import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
# Clave de sesión: obligatoria por variable de entorno en producción.
# El fallback es solo para desarrollo local (invalida sesiones al reiniciar).
app.secret_key = os.environ.get('SECRET_KEY') or 'dev-only-insecure-key-change-me'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB

# Cookie de sesión: HttpOnly siempre; Secure solo en producción (HTTPS).
# Poné COOKIE_SECURE=1 cuando la app corra detrás de HTTPS.
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE']   = os.environ.get('COOKIE_SECURE') == '1'

# Cierre garantizado de la conexión SQLite al terminar cada request,
# incluso si la vista lanza una excepción (evita conexiones colgadas / locks).
app.teardown_appcontext(close_db)

# ── Configuración de email (ajustar vía variables de entorno) ─────────────────
EMAIL_HOST     = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT     = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USER     = os.getenv('EMAIL_USER', '')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', '')
EMAIL_FROM     = os.getenv('EMAIL_FROM', EMAIL_USER) or 'noreply@barberapp.com'
APP_URL        = os.getenv('APP_URL', 'http://localhost:4321')

# ── Seña obligatoria por transferencia ─────────────────────────────────────
SENA_ALIAS = os.getenv('SENA_ALIAS', 'josevilte2001')
SENA_MONTO = int(os.getenv('SENA_MONTO', '8000'))

# ── Comprobantes de transferencia ────────────────────────────────────────────
# DATA_DIR: mismo volumen persistente que usa la base (ver database.py). Los
# comprobantes se guardan ahí para que sobrevivan a los deploys en producción.
DATA_DIR           = os.environ.get('DATA_DIR') or os.path.dirname(__file__)
UPLOAD_FOLDER      = os.path.join(DATA_DIR, 'static', 'comprobantes')
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'pdf', 'webp'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DIAS_ES  = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
MESES_ES = ['', 'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
            'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']

# ── Zona horaria local del negocio ───────────────────────────────────────────
# El servidor (p. ej. Railway) corre en UTC; sin esto la app calcula "ahora" en
# UTC y oculta turnos que todavía no pasaron. Argentina es UTC-3 fijo (no tiene
# horario de verano). Ajustable con TZ_OFFSET si se usa en otra región.
LOCAL_TZ = timezone(timedelta(hours=int(os.getenv('TZ_OFFSET', '-3'))))


def now_local():
    """Ahora en hora local, como datetime naive (para comparar con los horarios
    guardados, que son strings de hora local sin zona)."""
    return datetime.now(LOCAL_TZ).replace(tzinfo=None)


def today_local():
    """Fecha de hoy en hora local."""
    return datetime.now(LOCAL_TZ).date()


def _enviar_email_espera(to_email, nombre, fecha, hora_inicio):
    """Envía notificación por email cuando se libera un turno."""
    try:
        fecha_dt  = datetime.strptime(fecha, '%Y-%m-%d')
        fecha_fmt = (f"{DIAS_ES[fecha_dt.weekday()]} {fecha_dt.day} de "
                     f"{MESES_ES[fecha_dt.month]} {fecha_dt.year}")
    except Exception:
        fecha_fmt = fecha

    cuerpo = (
        f"Hola {nombre},\n\n"
        f"Te avisamos que se liberó un turno para la fecha que solicitaste.\n\n"
        f"📅 Fecha: {fecha_fmt}\n"
        f"🕒 Hora: {hora_inicio}hs\n\n"
        f"Si todavía te interesa reservar este horario, ingresá a la aplicación "
        f"y completá la reserva cuanto antes.\n\n"
        f"Importante: el turno no queda reservado automáticamente y será asignado "
        f"al primer cliente que lo reserve.\n\n"
        f"{APP_URL}/cliente/reservar"
    )

    if not EMAIL_USER or not EMAIL_PASSWORD:
        print(f"[lista-espera] Email no configurado — notificación para "
              f"{to_email}: {fecha} {hora_inicio}")
        return

    try:
        msg              = MIMEMultipart()
        msg['From']      = EMAIL_FROM
        msg['To']        = to_email
        msg['Subject']   = 'Se liberó un turno disponible'
        msg.attach(MIMEText(cuerpo, 'plain', 'utf-8'))
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(EMAIL_USER, EMAIL_PASSWORD)
            smtp.sendmail(EMAIL_FROM, to_email, msg.as_string())
    except Exception as exc:
        print(f"[lista-espera] Error enviando email a {to_email}: {exc}")


def _notificar_lista_espera(fecha, hora_inicio):
    """Busca usuarios en lista de espera para la fecha y les envía email (en hilo aparte)."""
    def _run():
        db       = get_db()
        usuarios = db.execute('''
            SELECT u.nombre, u.email
            FROM lista_espera le
            JOIN usuarios u ON le.usuario_id = u.id
            WHERE le.fecha = ?
        ''', (fecha,)).fetchall()
        db.close()
        for u in usuarios:
            _enviar_email_espera(u['email'], u['nombre'], fecha, hora_inicio)
    threading.Thread(target=_run, daemon=True).start()


def _verificar_rechazos_pendientes(db, uid):
    """Devuelve mensajes de turnos rechazados aún no notificados y los marca como vistos."""
    rows = db.execute('''
        SELECT t.id, d.fecha, d.hora_inicio
        FROM turnos t JOIN disponibilidad d ON t.disponibilidad_id=d.id
        WHERE t.cliente_id=? AND t.estado='rechazado' AND t.notificado_rechazo=0
    ''', (uid,)).fetchall()
    mensajes = []
    for r in rows:
        mensajes.append(
            f"Tu solicitud de turno para el {r['fecha']} a las {r['hora_inicio']}hs fue "
            f"rechazada por el administrador (seña no verificada). El horario quedó liberado."
        )
        db.execute('UPDATE turnos SET notificado_rechazo=1 WHERE id=?', (r['id'],))
    if mensajes:
        db.commit()
    return mensajes


def _puede_reprogramar(fecha_str, hora_inicio_str):
    """True si faltan más de 8 horas para el inicio del turno."""
    turno_dt = datetime.strptime(f"{fecha_str} {hora_inicio_str}", '%Y-%m-%d %H:%M')
    return now_local() < turno_dt - timedelta(hours=8)


def _slot_pasado(fecha_str, hora_inicio_str):
    """True si el horario ya empezó o pasó (no se puede reservar más)."""
    try:
        inicio = datetime.strptime(f"{fecha_str} {hora_inicio_str}", '%Y-%m-%d %H:%M')
    except (ValueError, TypeError):
        return False
    return inicio <= now_local()


def _generar_slots_del_dia(hora_ini_str, hora_fin_str,
                           almuerzo_ini_str=None, almuerzo_fin_str=None):
    """Devuelve lista de tuplas (inicio, fin) de 1 hora para un día.
    Salta slots que se superponen con el horario de almuerzo (opcional)."""
    fmt = '%H:%M'
    current  = datetime.strptime(hora_ini_str, fmt)
    end_dt   = datetime.strptime(hora_fin_str, fmt)
    lunch_s  = datetime.strptime(almuerzo_ini_str, fmt) if almuerzo_ini_str else None
    lunch_e  = datetime.strptime(almuerzo_fin_str, fmt) if almuerzo_fin_str else None

    slots = []
    while True:
        slot_end = current + timedelta(hours=1)
        if slot_end > end_dt:
            break
        # Se saltea el slot si se superpone con el almuerzo, pero SIN mover la
        # grilla: los horarios siguen alineados a la hora de inicio. Así, con un
        # almuerzo no alineado a la hora (p. ej. 13:30-14:30), la tarde arranca
        # limpia (15:00, 16:00…) en vez de quedar corrida (13:45-14:45…).
        superpone_almuerzo = (lunch_s and lunch_e
                              and current < lunch_e and slot_end > lunch_s)
        if not superpone_almuerzo:
            slots.append((current.strftime(fmt), slot_end.strftime(fmt)))
        current = slot_end
    return slots


# ── JSON API helpers ────────────────────────────────────────────────────────

def json_ok(data: dict, status=200):
    return jsonify({**data, 'success': True}), status


def json_err(msg: str, status=400):
    return jsonify({'success': False, 'error': msg}), status


def api_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return json_err('No autenticado.', 401)
        if session.get('rol') != 'admin':
            return json_err('Acceso denegado.', 403)
        return f(*args, **kwargs)
    return decorated


def api_cliente(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return json_err('No autenticado.', 401)
        if session.get('rol') != 'cliente':
            return json_err('Acceso denegado.', 403)
        return f(*args, **kwargs)
    return decorated

# ── Auth API ──────────────────────────────────────────────────────────────────

@app.route('/api/auth/me')
def api_me():
    if 'user_id' not in session:
        return json_err('No autenticado.', 401)
    return json_ok({'id': session['user_id'], 'rol': session['rol'],
                    'nombre': session['nombre'], 'email': session['email']})

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data     = request.get_json(force=True) or {}
    email    = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    db       = get_db()
    user     = db.execute('SELECT * FROM usuarios WHERE email=?', (email,)).fetchone()
    db.close()

    if not user or not check_password_hash(user['password_hash'], password):
        return json_err('Email o contraseña incorrectos.')

    session['user_id'] = user['id']
    session['rol']     = user['rol']
    session['nombre']  = user['nombre']
    session['email']   = user['email']

    redirect_url = '/admin' if user['rol'] == 'admin' else '/cliente'
    return json_ok({'redirect': redirect_url})

@app.route('/api/auth/register', methods=['POST'])
def api_register():
    data     = request.get_json(force=True) or {}
    nombre   = (data.get('nombre') or '').strip()
    apellido = (data.get('apellido') or '').strip()
    telefono = (data.get('telefono') or '').strip()
    email    = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    confirm  = data.get('confirm_password') or ''

    if not nombre or not apellido or not telefono or not email or not password:
        return json_err('Completá todos los campos obligatorios.')
    if password != confirm:
        return json_err('Las contraseñas no coinciden.')
    if len(password) < 6:
        return json_err('La contraseña debe tener al menos 6 caracteres.')

    db = get_db()
    if db.execute('SELECT id FROM usuarios WHERE email=?', (email,)).fetchone():
        db.close()
        return json_err('Ya existe una cuenta con ese email.')

    db.execute(
        'INSERT INTO usuarios (nombre, apellido, telefono, email, password_hash, rol) '
        'VALUES (?,?,?,?,?,?)',
        (nombre, apellido, telefono, email, generate_password_hash(password), 'cliente')
    )
    db.commit()
    db.close()
    return json_ok({'message': '¡Cuenta creada exitosamente!'})

@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    session.clear()
    return json_ok({'message': 'Sesión cerrada.'})

# ── Cliente API ────────────────────────────────────────────────────────────────

@app.route('/api/cliente/dashboard')
@api_cliente
def api_cliente_dashboard():
    db  = get_db()
    uid = session['user_id']
    hoy = today_local().isoformat()

    proximos = [dict(r) for r in db.execute('''
        SELECT t.id, d.fecha, d.hora_inicio, d.hora_fin, t.estado
        FROM turnos t JOIN disponibilidad d ON t.disponibilidad_id=d.id
        WHERE t.cliente_id=? AND d.fecha >= ?
          AND t.estado NOT IN ('cancelado','completado','rechazado')
        ORDER BY d.fecha, d.hora_inicio
    ''', (uid, hoy)).fetchall()]

    historial = [dict(r) for r in db.execute('''
        SELECT t.id, d.fecha, d.hora_inicio, d.hora_fin, t.estado
        FROM turnos t JOIN disponibilidad d ON t.disponibilidad_id=d.id
        WHERE t.cliente_id=? AND (d.fecha < ? OR t.estado IN ('cancelado','completado','rechazado'))
        ORDER BY d.fecha DESC, d.hora_inicio DESC LIMIT 10
    ''', (uid, hoy)).fetchall()]

    alertas_rechazo = _verificar_rechazos_pendientes(db, uid)

    db.close()
    return json_ok({'proximos': proximos, 'historial': historial, 'alertas_rechazo': alertas_rechazo})

@app.route('/api/cliente/slots')
@api_cliente
def api_cliente_slots():
    db    = get_db()
    hoy   = today_local().isoformat()
    ahora = now_local().strftime('%H:%M')
    uid   = session['user_id']

    # (d.fecha > hoy OR d.hora_inicio > ahora): excluye horarios de hoy que ya pasaron.
    slots = db.execute('''
        SELECT d.id, d.fecha, d.hora_inicio, d.hora_fin
        FROM disponibilidad d
        WHERE d.disponible=1 AND d.fecha >= ?
          AND (d.fecha > ? OR d.hora_inicio > ?)
          AND d.id NOT IN (SELECT disponibilidad_id FROM turnos WHERE estado NOT IN ('cancelado'))
        ORDER BY d.fecha, d.hora_inicio
    ''', (hoy, hoy, ahora)).fetchall()

    fechas_completas = [dict(r) for r in db.execute('''
        SELECT DISTINCT d.fecha,
               CASE WHEN le.id IS NOT NULL THEN 1 ELSE 0 END AS en_espera
        FROM disponibilidad d
        LEFT JOIN lista_espera le ON le.fecha = d.fecha AND le.usuario_id = ?
        WHERE d.fecha >= ?
          -- Solo fechas que todavía tienen algún horario futuro (si no, el día ya pasó)
          AND EXISTS (
              SELECT 1 FROM disponibilidad d3
              WHERE d3.fecha = d.fecha AND (d3.fecha > ? OR d3.hora_inicio > ?)
          )
          AND d.fecha NOT IN (
              SELECT DISTINCT d2.fecha FROM disponibilidad d2
              WHERE d2.disponible=1 AND d2.fecha >= ?
                AND (d2.fecha > ? OR d2.hora_inicio > ?)
                AND d2.id NOT IN (
                    SELECT disponibilidad_id FROM turnos WHERE estado NOT IN ('cancelado')
                )
          )
        ORDER BY d.fecha
    ''', (uid, hoy, hoy, ahora, hoy, hoy, ahora)).fetchall()]

    by_date: dict = {}
    for s in slots:
        f = s['fecha']
        if f not in by_date:
            by_date[f] = []
        by_date[f].append(dict(s))

    db.close()
    return json_ok({'by_date': by_date, 'fechas_completas': fechas_completas})

@app.route('/api/cliente/reservar', methods=['POST'])
@api_cliente
def api_cliente_reservar():
    # Acepta multipart/form-data (con comprobante) o JSON (legacy)
    if request.content_type and 'multipart/form-data' in request.content_type:
        disp_id  = str(request.form.get('disponibilidad_id') or '').strip()
        confirmo = request.form.get('confirmo_transferencia') in ('1', 'true', True)
    else:
        data     = request.get_json(force=True) or {}
        disp_id  = str(data.get('disponibilidad_id') or '').strip()
        confirmo = data.get('confirmo_transferencia')

    if not disp_id:
        return json_err('Seleccioná un horario.')
    if not confirmo:
        return json_err('Debés confirmar que realizaste la transferencia de la seña para reservar el turno.')

    # Validar comprobante ANTES de tocar la base, pero persistirlo en disco
    # solo si la reserva se registra con éxito (evita archivos huérfanos).
    archivo = request.files.get('comprobante')
    if not archivo or archivo.filename == '':
        return json_err('Debés adjuntar el comprobante de transferencia.')
    ext = archivo.filename.rsplit('.', 1)[-1].lower() if '.' in archivo.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        return json_err('Formato de comprobante no permitido. Usá JPG, PNG, PDF o WEBP.')
    filename = f"{uuid.uuid4().hex}.{ext}"
    comprobante_path = f"comprobantes/{filename}"

    db = get_db()
    slot = db.execute('SELECT fecha, hora_inicio FROM disponibilidad WHERE id=?', (disp_id,)).fetchone()
    if not slot:
        db.close()
        return json_err('El horario seleccionado no existe.')
    if _slot_pasado(slot['fecha'], slot['hora_inicio']):
        db.close()
        return json_err('Ese horario ya pasó. Elegí otro.')
    try:
        db.execute('INSERT INTO turnos (cliente_id, disponibilidad_id, estado, comprobante_path) VALUES (?,?,?,?)',
                   (session['user_id'], disp_id, 'pendiente', comprobante_path))
        db.execute('UPDATE disponibilidad SET disponible=0 WHERE id=? AND disponible=1', (disp_id,))
        db.commit()
    except sqlite3.IntegrityError:
        db.close()
        return json_err('Este horario acaba de ser tomado. Por favor elegí otro.')
    db.close()

    # Reserva confirmada → recién ahora guardamos el archivo en disco.
    archivo.save(os.path.join(UPLOAD_FOLDER, filename))
    return json_ok({'message': '¡Solicitud registrada! Tu turno quedará pendiente hasta que '
                                'el administrador verifique la transferencia.'})

@app.route('/api/cliente/lista-espera', methods=['POST'])
@api_cliente
def api_cliente_lista_espera():
    data  = request.get_json(force=True) or {}
    fecha = str(data.get('fecha') or '').strip()
    if not fecha:
        return json_err('Fecha requerida.')
    db  = get_db()
    uid = session['user_id']
    try:
        db.execute('INSERT INTO lista_espera (usuario_id, fecha) VALUES (?,?)', (uid, fecha))
        db.commit()
        db.close()
        return json_ok({'message': '¡Listo! Te avisaremos por email si se libera un turno para ese día.'})
    except sqlite3.IntegrityError:
        db.close()
        return json_err('Ya estás anotado en la lista de espera para esa fecha.', 409)


@app.route('/api/cliente/mis-turnos')
@api_cliente
def api_cliente_mis_turnos():
    db  = get_db()
    hoy = today_local().isoformat()
    rows = db.execute('''
        SELECT t.id, d.fecha, d.hora_inicio, d.hora_fin, t.estado, t.creado_en
        FROM turnos t JOIN disponibilidad d ON t.disponibilidad_id=d.id
        WHERE t.cliente_id=? ORDER BY d.fecha DESC, d.hora_inicio DESC
    ''', (session['user_id'],)).fetchall()
    db.close()
    turnos = []
    for r in rows:
        t = dict(r)
        t['puede_reprogramar'] = _puede_reprogramar(r['fecha'], r['hora_inicio'])
        turnos.append(t)
    return json_ok({'turnos': turnos, 'hoy': hoy})

@app.route('/api/cliente/turnos/<int:id>/cancelar', methods=['POST'])
@api_cliente
def api_cliente_cancelar(id):
    db    = get_db()
    turno = db.execute('SELECT * FROM turnos WHERE id=? AND cliente_id=?',
                       (id, session['user_id'])).fetchone()
    if not turno:
        db.close()
        return json_err('Turno no encontrado.', 404)
    if turno['estado'] in ('cancelado', 'completado', 'rechazado'):
        db.close()
        return json_err('Este turno no puede cancelarse.')

    disp = db.execute('SELECT fecha, hora_inicio FROM disponibilidad WHERE id=?',
                      (turno['disponibilidad_id'],)).fetchone()
    db.execute("UPDATE turnos SET estado='cancelado' WHERE id=?", (id,))
    db.execute('UPDATE disponibilidad SET disponible=1 WHERE id=?', (turno['disponibilidad_id'],))
    db.commit()
    db.close()
    if disp:
        _notificar_lista_espera(disp['fecha'], disp['hora_inicio'])
    return json_ok({'message': 'Turno cancelado. El horario quedó libre nuevamente.'})

@app.route('/api/cliente/turnos/<int:id>/slots')
@api_cliente
def api_cliente_reprogramar_slots(id):
    db    = get_db()
    hoy   = today_local().isoformat()
    ahora = now_local().strftime('%H:%M')

    turno = db.execute('''
        SELECT t.*, d.fecha, d.hora_inicio, d.hora_fin, d.id AS disp_id
        FROM turnos t JOIN disponibilidad d ON t.disponibilidad_id=d.id
        WHERE t.id=? AND t.cliente_id=?
    ''', (id, session['user_id'])).fetchone()

    if not turno or turno['estado'] in ('cancelado', 'completado', 'pendiente', 'rechazado'):
        db.close()
        return json_err('Turno no disponible para reprogramar.', 404)

    if not _puede_reprogramar(turno['fecha'], turno['hora_inicio']):
        db.close()
        return json_err('No es posible reprogramar un turno cuando faltan 8 horas o menos para su inicio.', 403)

    slots = db.execute('''
        SELECT d.id, d.fecha, d.hora_inicio, d.hora_fin
        FROM disponibilidad d
        WHERE d.disponible=1 AND d.fecha >= ? AND d.id != ?
          AND (d.fecha > ? OR d.hora_inicio > ?)
          AND d.id NOT IN (SELECT disponibilidad_id FROM turnos WHERE estado NOT IN ('cancelado'))
        ORDER BY d.fecha, d.hora_inicio
    ''', (hoy, turno['disp_id'], hoy, ahora)).fetchall()

    by_date: dict = {}
    for s in slots:
        f = s['fecha']
        if f not in by_date:
            by_date[f] = []
        by_date[f].append(dict(s))

    db.close()
    return json_ok({'turno': dict(turno), 'by_date': by_date})

@app.route('/api/cliente/turnos/<int:id>/reprogramar', methods=['POST'])
@api_cliente
def api_cliente_reprogramar(id):
    data       = request.get_json(force=True) or {}
    nueva_disp = str(data.get('disponibilidad_id') or '').strip()
    if not nueva_disp:
        return json_err('Seleccioná un horario.')

    db    = get_db()
    turno = db.execute(
        'SELECT * FROM turnos t JOIN disponibilidad d ON t.disponibilidad_id=d.id '
        'WHERE t.id=? AND t.cliente_id=?', (id, session['user_id'])
    ).fetchone()

    if not turno:
        db.close()
        return json_err('Turno no encontrado.', 404)

    if turno['estado'] in ('cancelado', 'completado', 'pendiente', 'rechazado'):
        db.close()
        return json_err('Turno no disponible para reprogramar.', 403)

    if not _puede_reprogramar(turno['fecha'], turno['hora_inicio']):
        db.close()
        return json_err('No es posible reprogramar un turno cuando faltan 8 horas o menos para su inicio.', 403)

    nuevo_slot = db.execute('SELECT fecha, hora_inicio FROM disponibilidad WHERE id=?', (nueva_disp,)).fetchone()
    if not nuevo_slot:
        db.close()
        return json_err('El horario seleccionado no existe.')
    if _slot_pasado(nuevo_slot['fecha'], nuevo_slot['hora_inicio']):
        db.close()
        return json_err('Ese horario ya pasó. Elegí otro.')

    try:
        disp_viejo = db.execute(
            'SELECT fecha, hora_inicio FROM disponibilidad WHERE id=?', (turno['disponibilidad_id'],)
        ).fetchone()
        db.execute('UPDATE turnos SET disponibilidad_id=?, estado=?, reprogramado_sin_ver=1 WHERE id=?',
                   (nueva_disp, 'reservado', id))
        db.execute('UPDATE disponibilidad SET disponible=1 WHERE id=?', (turno['disponibilidad_id'],))
        db.execute('UPDATE disponibilidad SET disponible=0 WHERE id=?', (nueva_disp,))
        db.commit()
        db.close()
        if disp_viejo:
            _notificar_lista_espera(disp_viejo['fecha'], disp_viejo['hora_inicio'])
        return json_ok({'message': 'Turno reprogramado exitosamente.'})
    except sqlite3.IntegrityError:
        db.rollback()
        db.close()
        return json_err('El horario seleccionado ya fue tomado. Elegí otro.')

# ── Admin API ──────────────────────────────────────────────────────────────────

@app.route('/api/admin/notificaciones')
@api_admin
def api_admin_notificaciones():
    db = get_db()
    reprogramados = db.execute(
        'SELECT COUNT(*) FROM turnos WHERE reprogramado_sin_ver=1'
    ).fetchone()[0]
    db.close()
    return json_ok({'reprogramados': reprogramados})

@app.route('/api/admin/notificaciones/marcar-visto', methods=['POST'])
@api_admin
def api_admin_marcar_visto():
    db = get_db()
    db.execute('UPDATE turnos SET reprogramado_sin_ver=0 WHERE reprogramado_sin_ver=1')
    db.commit()
    db.close()
    return json_ok({'message': 'OK'})

@app.route('/api/admin/dashboard')
@api_admin
def api_admin_dashboard():
    from datetime import datetime as dt
    db      = get_db()
    hoy     = today_local()
    hoy_str = hoy.isoformat()
    ahora   = now_local().strftime('%H:%M')

    # Permitir consultar otra fecha via ?fecha=YYYY-MM-DD
    fecha_param = request.args.get('fecha', '')
    try:
        fecha_obj = date.fromisoformat(fecha_param) if fecha_param else hoy
    except ValueError:
        fecha_obj = hoy
    fecha_str = fecha_obj.isoformat()
    es_hoy = (fecha_obj == hoy)

    stats = {
        'confirmados_hoy': db.execute(
            "SELECT COUNT(*) FROM turnos t JOIN disponibilidad d ON t.disponibilidad_id=d.id "
            "WHERE d.fecha=? AND t.estado='confirmado'", (fecha_str,)).fetchone()[0],
        'pendientes_hoy': db.execute(
            "SELECT COUNT(*) FROM turnos t JOIN disponibilidad d ON t.disponibilidad_id=d.id "
            "WHERE d.fecha=? AND t.estado IN ('reservado','pendiente')", (fecha_str,)).fetchone()[0],
        'libres_hoy': db.execute(
            "SELECT COUNT(*) FROM disponibilidad WHERE fecha=? AND disponible=1", (fecha_str,)).fetchone()[0],
        'por_validar': db.execute(
            "SELECT COUNT(*) FROM turnos WHERE estado='pendiente'").fetchone()[0],
    }

    # Agenda completa del día: todos los slots con turno activo si existe
    agenda = [dict(r) for r in db.execute('''
        SELECT d.id AS disp_id, d.hora_inicio, d.hora_fin, d.disponible,
               t.id AS turno_id, t.estado, t.comprobante_path,
               u.nombre||' '||u.apellido AS cliente,
               u.telefono, u.email
        FROM disponibilidad d
        LEFT JOIN turnos t ON t.disponibilidad_id=d.id
                           AND t.estado NOT IN ('cancelado')
        LEFT JOIN usuarios u ON t.cliente_id=u.id
        WHERE d.fecha=?
        ORDER BY d.hora_inicio
    ''', (fecha_str,)).fetchall()]

    # Próximo turno confirmado (solo si es hoy)
    proximo = None
    if es_hoy:
        prox_row = db.execute('''
            SELECT t.id, u.nombre||' '||u.apellido AS cliente,
                   d.hora_inicio, d.hora_fin, u.telefono
            FROM turnos t
            JOIN usuarios u ON t.cliente_id=u.id
            JOIN disponibilidad d ON t.disponibilidad_id=d.id
            WHERE d.fecha=? AND t.estado='confirmado' AND d.hora_inicio > ?
            ORDER BY d.hora_inicio LIMIT 1
        ''', (hoy_str, ahora)).fetchone()
        if prox_row:
            proximo = dict(prox_row)
            turno_dt = dt.strptime(f"{hoy_str} {proximo['hora_inicio']}", '%Y-%m-%d %H:%M')
            proximo['minutos_restantes'] = max(0, int((turno_dt - now_local()).total_seconds() / 60))

    # Próximos turnos confirmados (días posteriores a la fecha consultada)
    proximos = [dict(r) for r in db.execute('''
        SELECT t.id, u.nombre||' '||u.apellido AS cliente,
               d.fecha, d.hora_inicio, d.hora_fin, t.estado
        FROM turnos t
        JOIN usuarios u ON t.cliente_id=u.id
        JOIN disponibilidad d ON t.disponibilidad_id=d.id
        WHERE d.fecha > ? AND t.estado='confirmado'
        ORDER BY d.fecha, d.hora_inicio LIMIT 6
    ''', (fecha_str,)).fetchall()]

    db.close()
    return json_ok({
        'stats': stats, 'agenda': agenda, 'proximo': proximo, 'proximos': proximos,
        'fecha': fecha_str, 'es_hoy': es_hoy,
    })

@app.route('/api/admin/turnos')
@api_admin
def api_admin_turnos():
    db     = get_db()
    fecha  = request.args.get('fecha', '')
    estado = request.args.get('estado', '')

    q = '''SELECT t.id, u.nombre||' '||u.apellido AS cliente, u.telefono, u.email,
                  d.fecha, d.hora_inicio, d.hora_fin, t.estado, t.notas, t.creado_en,
                  t.reprogramado_sin_ver
           FROM turnos t
           JOIN usuarios u ON t.cliente_id=u.id
           JOIN disponibilidad d ON t.disponibilidad_id=d.id WHERE 1=1'''
    params = []
    if fecha:  q += ' AND d.fecha=?';  params.append(fecha)
    if estado: q += ' AND t.estado=?'; params.append(estado)
    q += ' ORDER BY d.fecha DESC, d.hora_inicio'

    turnos = [dict(r) for r in db.execute(q, params).fetchall()]
    db.close()
    return json_ok({'turnos': turnos})

@app.route('/api/admin/turnos/<int:id>/estado', methods=['POST'])
@api_admin
def api_admin_cambiar_estado(id):
    data   = request.get_json(force=True) or {}
    estado = data.get('estado')
    db     = get_db()
    turno  = db.execute('SELECT * FROM turnos WHERE id=?', (id,)).fetchone()
    if not turno:
        db.close()
        return json_err('Turno no encontrado.', 404)

    disp_liberado = None
    if estado == 'cancelado':
        disp_liberado = db.execute(
            'SELECT fecha, hora_inicio FROM disponibilidad WHERE id=?',
            (turno['disponibilidad_id'],)
        ).fetchone()
    db.execute('UPDATE turnos SET estado=? WHERE id=?', (estado, id))
    if estado == 'cancelado':
        db.execute('UPDATE disponibilidad SET disponible=1 WHERE id=?', (turno['disponibilidad_id'],))
    db.commit()
    db.close()
    if disp_liberado:
        _notificar_lista_espera(disp_liberado['fecha'], disp_liberado['hora_inicio'])
    return json_ok({'message': 'Estado actualizado.'})

@app.route('/api/admin/clientes')
@api_admin
def api_admin_clientes():
    db = get_db()
    clientes = [dict(r) for r in db.execute('''
        SELECT u.id, u.nombre, u.apellido, u.telefono, u.email, u.creado_en,
               COUNT(CASE WHEN t.estado NOT IN ('cancelado') THEN 1 END) AS turnos_activos,
               COUNT(t.id) AS total_turnos
        FROM usuarios u
        LEFT JOIN turnos t ON u.id=t.cliente_id
        WHERE u.rol='cliente'
        GROUP BY u.id ORDER BY u.nombre
    ''').fetchall()]
    db.close()
    return json_ok({'clientes': clientes})

@app.route('/api/admin/clientes/<int:id>/resetear-password', methods=['POST'])
@api_admin
def api_admin_resetear_password(id):
    data  = request.get_json(force=True) or {}
    nueva = (data.get('nueva_password') or '').strip()
    if len(nueva) < 6:
        return json_err('La contraseña debe tener al menos 6 caracteres.')
    db = get_db()
    usuario = db.execute("SELECT id FROM usuarios WHERE id=? AND rol='cliente'", (id,)).fetchone()
    if not usuario:
        db.close()
        return json_err('Cliente no encontrado.')
    db.execute('UPDATE usuarios SET password_hash=? WHERE id=?',
               (generate_password_hash(nueva), id))
    db.commit()
    db.close()
    return json_ok({'message': 'Contraseña reseteada correctamente.'})

@app.route('/api/admin/disponibilidad')
@api_admin
def api_admin_disponibilidad():
    db  = get_db()
    hoy = today_local().isoformat()

    slots = db.execute('''
        SELECT d.*,
               t.id        AS turno_id,
               t.estado    AS turno_estado,
               u.nombre||' '||u.apellido AS cliente_nombre,
               u.telefono  AS cliente_tel
        FROM disponibilidad d
        LEFT JOIN turnos t ON d.id=t.disponibilidad_id AND t.estado NOT IN ('cancelado')
        LEFT JOIN usuarios u ON t.cliente_id=u.id
        WHERE d.fecha >= ? ORDER BY d.fecha, d.hora_inicio
    ''', (hoy,)).fetchall()

    by_date: dict = {}
    for s in slots:
        f = s['fecha']
        if f not in by_date:
            by_date[f] = []
        by_date[f].append(dict(s))

    db.close()
    return json_ok({'by_date': by_date})

@app.route('/api/admin/disponibilidad/generar', methods=['POST'])
@api_admin
def api_admin_generar_slots():
    data         = request.get_json(force=True) or {}
    fecha_ini    = data.get('fecha_inicio', '')
    fecha_fin    = data.get('fecha_fin', '')
    hora_ini     = str(data.get('hora_inicio', '09:00')).strip()
    hora_fin     = str(data.get('hora_fin', '18:00')).strip()
    almuerzo_ini = str(data.get('almuerzo_inicio') or '').strip() or None
    almuerzo_fin = str(data.get('almuerzo_fin') or '').strip() or None
    dias         = [int(d) for d in (data.get('dias') or [])]

    if not dias:
        return json_err('Seleccioná al menos un día de la semana.')

    try:
        hi = datetime.strptime(hora_ini, '%H:%M')
        hf = datetime.strptime(hora_fin, '%H:%M')
    except ValueError:
        return json_err('Formato de hora inválido. Usá HH:MM.')

    if hf <= hi:
        return json_err('El horario de fin debe ser posterior al de inicio.')

    try:
        start = datetime.strptime(fecha_ini, '%Y-%m-%d').date()
        end   = datetime.strptime(fecha_fin, '%Y-%m-%d').date()
    except ValueError:
        return json_err('Rango de fechas inválido. Usá YYYY-MM-DD.')
    if end < start:
        return json_err('La fecha de fin debe ser posterior o igual a la de inicio.')

    db      = get_db()
    created = 0
    current = start
    while current <= end:
        if current.weekday() in dias:
            for (h_ini, h_fin) in _generar_slots_del_dia(hora_ini, hora_fin, almuerzo_ini, almuerzo_fin):
                try:
                    db.execute(
                        'INSERT INTO disponibilidad (fecha, hora_inicio, hora_fin) VALUES (?,?,?)',
                        (current.isoformat(), h_ini, h_fin)
                    )
                    created += 1
                except sqlite3.IntegrityError:
                    pass
        current += timedelta(days=1)

    db.commit()
    db.close()
    return json_ok({'message': f'Se generaron {created} horarios disponibles.'})

@app.route('/api/admin/disponibilidad/<int:id>/toggle', methods=['POST'])
@api_admin
def api_admin_toggle_slot(id):
    db   = get_db()
    slot = db.execute('SELECT * FROM disponibilidad WHERE id=?', (id,)).fetchone()
    if not slot:
        db.close()
        return json_err('Slot no encontrado.', 404)

    tiene_turno = db.execute(
        "SELECT id FROM turnos WHERE disponibilidad_id=? AND estado NOT IN ('cancelado')", (id,)
    ).fetchone()

    if tiene_turno and slot['disponible'] == 0:
        db.close()
        return json_err('No se puede bloquear: hay un turno activo.')

    toggling_to_available = (slot['disponible'] == 0)
    db.execute('UPDATE disponibilidad SET disponible=? WHERE id=?',
               (0 if slot['disponible'] else 1, id))
    db.commit()
    db.close()
    if toggling_to_available:
        _notificar_lista_espera(slot['fecha'], slot['hora_inicio'])
    return json_ok({'message': 'Slot actualizado.'})

@app.route('/api/admin/disponibilidad/<int:id>/eliminar', methods=['POST'])
@api_admin
def api_admin_eliminar_slot(id):
    db   = get_db()
    slot = db.execute('SELECT * FROM disponibilidad WHERE id=?', (id,)).fetchone()
    if not slot:
        db.close()
        return json_err('Slot no encontrado.', 404)
    tiene_turno = db.execute(
        "SELECT id FROM turnos WHERE disponibilidad_id=? AND estado NOT IN ('cancelado')", (id,)
    ).fetchone()
    if tiene_turno:
        db.close()
        return json_err('No se puede eliminar: hay un turno reservado en ese horario.')
    db.execute('DELETE FROM disponibilidad WHERE id=?', (id,))
    db.commit()
    db.close()
    return json_ok({'message': f'Horario {slot["hora_inicio"]} eliminado correctamente.'})

@app.route('/api/admin/disponibilidad/bloquear-dia', methods=['POST'])
@api_admin
def api_admin_bloquear_dia():
    data  = request.get_json(force=True) or {}
    fecha = data.get('fecha', '')
    db    = get_db()
    db.execute(
        "UPDATE disponibilidad SET disponible=0 WHERE fecha=? "
        "AND id NOT IN (SELECT disponibilidad_id FROM turnos WHERE estado NOT IN ('cancelado'))",
        (fecha,)
    )
    db.commit()
    db.close()
    return json_ok({'message': f'Día {fecha} bloqueado.'})

@app.route('/api/admin/disponibilidad/eliminar-libres', methods=['POST'])
@api_admin
def api_admin_eliminar_libres():
    data  = request.get_json(force=True) or {}
    fecha = data.get('fecha', '')
    db    = get_db()
    db.execute("DELETE FROM disponibilidad WHERE fecha=? AND disponible=1", (fecha,))
    db.commit()
    db.close()
    return json_ok({'message': f'Horarios libres del {fecha} eliminados.'})

@app.route('/api/admin/turnos-pendientes')
@api_admin
def api_admin_turnos_pendientes():
    db = get_db()
    pendientes = [dict(r) for r in db.execute('''
        SELECT t.id, u.nombre||' '||u.apellido AS cliente, u.email, u.telefono,
               d.fecha, d.hora_inicio, d.hora_fin, t.estado, t.creado_en, t.comprobante_path
        FROM turnos t
        JOIN usuarios u ON t.cliente_id=u.id
        JOIN disponibilidad d ON t.disponibilidad_id=d.id
        WHERE t.estado='pendiente'
        ORDER BY t.creado_en
    ''').fetchall()]
    db.close()
    return json_ok({'pendientes': pendientes, 'sena_alias': SENA_ALIAS, 'sena_monto': SENA_MONTO})

@app.route('/api/admin/comprobante/<path:filename>')
@api_admin
def api_admin_comprobante(filename):
    safe = os.path.basename(filename)
    filepath = os.path.join(UPLOAD_FOLDER, safe)
    if not os.path.isfile(filepath):
        abort(404)
    return send_from_directory(UPLOAD_FOLDER, safe)

@app.route('/api/admin/turnos-pendientes/<int:id>/aprobar', methods=['POST'])
@api_admin
def api_admin_aprobar_turno(id):
    db    = get_db()
    turno = db.execute("SELECT * FROM turnos WHERE id=? AND estado='pendiente'", (id,)).fetchone()
    if not turno:
        db.close()
        return json_err('Solicitud no encontrada o ya procesada.', 404)
    db.execute("UPDATE turnos SET estado='confirmado' WHERE id=?", (id,))
    db.commit()
    db.close()
    return json_ok({'message': 'Turno confirmado. El cliente ya puede ver su turno confirmado.'})

@app.route('/api/admin/turnos-pendientes/<int:id>/rechazar', methods=['POST'])
@api_admin
def api_admin_rechazar_turno(id):
    db    = get_db()
    turno = db.execute("SELECT * FROM turnos WHERE id=? AND estado='pendiente'", (id,)).fetchone()
    if not turno:
        db.close()
        return json_err('Solicitud no encontrada o ya procesada.', 404)
    disp = db.execute('SELECT fecha, hora_inicio FROM disponibilidad WHERE id=?',
                      (turno['disponibilidad_id'],)).fetchone()
    db.execute("UPDATE turnos SET estado='rechazado' WHERE id=?", (id,))
    db.execute('UPDATE disponibilidad SET disponible=1 WHERE id=?', (turno['disponibilidad_id'],))
    db.commit()
    db.close()
    if disp:
        _notificar_lista_espera(disp['fecha'], disp['hora_inicio'])
    return json_ok({'message': 'Solicitud rechazada. El horario quedó liberado.'})


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    # debug se activa solo con FLASK_DEBUG=1; por defecto queda apagado.
    debug = os.getenv('FLASK_DEBUG') == '1'
    app.run(debug=debug, port=int(os.getenv('PORT', '5001')))
