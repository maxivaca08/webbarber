from flask import (Flask, render_template, request, redirect,
                   url_for, jsonify, flash, session, send_from_directory, abort)
from database import init_db, get_db
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import datetime, date, timedelta
from collections import defaultdict
import sqlite3
import os
import uuid
import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
app.secret_key = 'barberapp_secret_2024_#xK9'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB

# ── Configuración de email (ajustar vía variables de entorno) ─────────────────
EMAIL_HOST     = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT     = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USER     = os.getenv('EMAIL_USER', '')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', '')
EMAIL_FROM     = os.getenv('EMAIL_FROM', EMAIL_USER) or 'noreply@barberapp.com'
APP_URL        = os.getenv('APP_URL', 'http://localhost:4321')

# ── Seña obligatoria por transferencia ─────────────────────────────────────
SENA_ALIAS = 'josevilte2001'
SENA_MONTO = 5000

# ── Comprobantes de transferencia ────────────────────────────────────────────
UPLOAD_FOLDER         = os.path.join(os.path.dirname(__file__), 'static', 'comprobantes')
ALLOWED_EXTENSIONS    = {'jpg', 'jpeg', 'png', 'pdf', 'webp'}
MAX_CONTENT_LENGTH    = 5 * 1024 * 1024  # 5 MB
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


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
    return datetime.now() < turno_dt - timedelta(hours=8)


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
        if lunch_s and lunch_e and current < lunch_e and slot_end > lunch_s:
            current = lunch_e
            continue
        slots.append((current.strftime(fmt), slot_end.strftime(fmt)))
        current = slot_end
    return slots

DIAS_ES = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
MESES_ES = ['', 'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
             'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']


@app.template_filter('dia_semana')
def dia_semana_filter(fecha_str):
    d = datetime.strptime(fecha_str, '%Y-%m-%d')
    return DIAS_ES[d.weekday()]

@app.template_filter('fecha_larga')
def fecha_larga_filter(fecha_str):
    d = datetime.strptime(fecha_str, '%Y-%m-%d')
    return f"{DIAS_ES[d.weekday()]} {d.day} de {MESES_ES[d.month]}"

@app.template_filter('fecha_corta')
def fecha_corta_filter(fecha_str):
    d = datetime.strptime(fecha_str, '%Y-%m-%d')
    return f"{d.day:02d}/{d.month:02d}/{d.year}"

# ── Decoradores ──────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('rol') != 'admin':
            flash('Acceso no autorizado.', 'danger')
            return redirect(url_for('cliente_dashboard'))
        return f(*args, **kwargs)
    return decorated

def cliente_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('rol') != 'cliente':
            return redirect(url_for('admin_dashboard'))
        return f(*args, **kwargs)
    return decorated

# ── Auth ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('rol') == 'admin':
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('cliente_dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email    = request.form['email'].strip().lower()
        password = request.form['password']
        db   = get_db()
        user = db.execute('SELECT * FROM usuarios WHERE email=?', (email,)).fetchone()
        db.close()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['rol']     = user['rol']
            session['nombre']  = user['nombre']
            session['email']   = user['email']
            flash(f'Bienvenido, {user["nombre"]}!', 'success')
            return redirect(url_for('admin_dashboard') if user['rol'] == 'admin'
                            else url_for('cliente_dashboard'))

        flash('Email o contraseña incorrectos.', 'danger')

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('index'))

    form_data = {}
    if request.method == 'POST':
        form_data = request.form.to_dict()
        nombre   = request.form['nombre'].strip()
        apellido = request.form['apellido'].strip()
        telefono = request.form['telefono'].strip()
        email    = request.form['email'].strip().lower()
        password = request.form['password']
        confirm  = request.form['confirm_password']

        if password != confirm:
            flash('Las contraseñas no coinciden.', 'danger')
            return render_template('register.html', form=form_data)
        if len(password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres.', 'danger')
            return render_template('register.html', form=form_data)

        db = get_db()
        if db.execute('SELECT id FROM usuarios WHERE email=?', (email,)).fetchone():
            db.close()
            flash('Ya existe una cuenta con ese email.', 'danger')
            return render_template('register.html', form=form_data)

        db.execute(
            'INSERT INTO usuarios (nombre, apellido, telefono, email, password_hash, rol) '
            'VALUES (?,?,?,?,?,?)',
            (nombre, apellido, telefono, email, generate_password_hash(password), 'cliente')
        )
        db.commit()
        db.close()
        flash('¡Cuenta creada! Iniciá sesión para reservar tu turno.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html', form=form_data)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ── Panel Cliente ─────────────────────────────────────────────────────────────

@app.route('/cliente')
@cliente_required
def cliente_dashboard():
    db  = get_db()
    uid = session['user_id']
    hoy = date.today().isoformat()

    proximos = db.execute('''
        SELECT t.id, d.fecha, d.hora_inicio, d.hora_fin, t.estado
        FROM turnos t JOIN disponibilidad d ON t.disponibilidad_id=d.id
        WHERE t.cliente_id=? AND d.fecha >= ?
          AND t.estado NOT IN ('cancelado','completado','rechazado')
        ORDER BY d.fecha, d.hora_inicio
    ''', (uid, hoy)).fetchall()

    historial = db.execute('''
        SELECT t.id, d.fecha, d.hora_inicio, d.hora_fin, t.estado
        FROM turnos t JOIN disponibilidad d ON t.disponibilidad_id=d.id
        WHERE t.cliente_id=? AND (d.fecha < ? OR t.estado IN ('cancelado','completado','rechazado'))
        ORDER BY d.fecha DESC, d.hora_inicio DESC
        LIMIT 10
    ''', (uid, hoy)).fetchall()

    for msg in _verificar_rechazos_pendientes(db, uid):
        flash(msg, 'danger')

    db.close()
    return render_template('cliente/dashboard.html',
                           proximos=proximos, historial=historial)

@app.route('/cliente/reservar', methods=['GET', 'POST'])
@cliente_required
def cliente_reservar():
    db  = get_db()
    uid = session['user_id']
    hoy = date.today().isoformat()

    if request.method == 'POST':
        disp_id = request.form.get('disponibilidad_id', '').strip()
        if not disp_id:
            flash('Seleccioná un horario.', 'danger')
            return redirect(url_for('cliente_reservar'))

        if not request.form.get('confirmo_transferencia'):
            flash('Debés confirmar que realizaste la transferencia de la seña para reservar el turno.', 'danger')
            return redirect(url_for('cliente_reservar'))

        comprobante_path = None
        archivo = request.files.get('comprobante')
        if not archivo or archivo.filename == '':
            flash('Debés adjuntar el comprobante de transferencia.', 'danger')
            return redirect(url_for('cliente_reservar'))
        ext = archivo.filename.rsplit('.', 1)[-1].lower() if '.' in archivo.filename else ''
        if ext not in ALLOWED_EXTENSIONS:
            flash('Formato de comprobante no permitido. Usá JPG, PNG, PDF o WEBP.', 'danger')
            return redirect(url_for('cliente_reservar'))
        filename = f"{uuid.uuid4().hex}.{ext}"
        archivo.save(os.path.join(UPLOAD_FOLDER, filename))
        comprobante_path = f"comprobantes/{filename}"

        try:
            # Integridad: UNIQUE en disponibilidad_id evita doble reserva
            db.execute(
                'INSERT INTO turnos (cliente_id, disponibilidad_id, estado, comprobante_path) VALUES (?,?,?,?)',
                (uid, disp_id, 'pendiente', comprobante_path)
            )
            db.execute('UPDATE disponibilidad SET disponible=0 WHERE id=? AND disponible=1',
                       (disp_id,))
            db.commit()
            db.close()
            flash('¡Solicitud registrada! Tu turno quedará pendiente hasta que el '
                  'administrador verifique la transferencia.', 'success')
            return redirect(url_for('cliente_dashboard'))

        except sqlite3.IntegrityError:
            db.close()
            flash('Este horario acaba de ser tomado por otro usuario. '
                  'Por favor seleccioná otro.', 'danger')
            return redirect(url_for('cliente_reservar'))

    # GET: mostrar slots disponibles agrupados por fecha
    slots = db.execute('''
        SELECT d.id, d.fecha, d.hora_inicio, d.hora_fin
        FROM disponibilidad d
        WHERE d.disponible=1 AND d.fecha >= ?
          AND d.id NOT IN (
              SELECT disponibilidad_id FROM turnos WHERE estado NOT IN ('cancelado')
          )
        ORDER BY d.fecha, d.hora_inicio
    ''', (hoy,)).fetchall()

    by_date = defaultdict(list)
    for s in slots:
        by_date[s['fecha']].append(s)

    # Fechas con slots pero sin disponibilidad (para lista de espera)
    fechas_completas = [dict(r) for r in db.execute('''
        SELECT DISTINCT d.fecha,
               CASE WHEN le.id IS NOT NULL THEN 1 ELSE 0 END AS en_espera
        FROM disponibilidad d
        LEFT JOIN lista_espera le ON le.fecha = d.fecha AND le.usuario_id = ?
        WHERE d.fecha >= ?
          AND d.fecha NOT IN (
              SELECT DISTINCT d2.fecha FROM disponibilidad d2
              WHERE d2.disponible=1 AND d2.fecha >= ?
                AND d2.id NOT IN (
                    SELECT disponibilidad_id FROM turnos WHERE estado NOT IN ('cancelado')
                )
          )
        ORDER BY d.fecha
    ''', (uid, hoy, hoy)).fetchall()]

    db.close()
    return render_template('cliente/reservar.html',
                           by_date=dict(sorted(by_date.items())),
                           fechas_completas=fechas_completas)

@app.route('/cliente/mis-turnos')
@cliente_required
def cliente_mis_turnos():
    db  = get_db()
    hoy = date.today().isoformat()
    rows = db.execute('''
        SELECT t.id, d.fecha, d.hora_inicio, d.hora_fin, t.estado, t.creado_en
        FROM turnos t JOIN disponibilidad d ON t.disponibilidad_id=d.id
        WHERE t.cliente_id=?
        ORDER BY d.fecha DESC, d.hora_inicio DESC
    ''', (session['user_id'],)).fetchall()
    db.close()
    turnos = []
    for r in rows:
        t = dict(r)
        t['puede_reprogramar'] = _puede_reprogramar(r['fecha'], r['hora_inicio'])
        turnos.append(t)
    return render_template('cliente/mis_turnos.html', turnos=turnos, hoy=hoy)

@app.route('/cliente/turnos/<int:id>/cancelar', methods=['POST'])
@cliente_required
def cliente_cancelar(id):
    db    = get_db()
    turno = db.execute(
        'SELECT * FROM turnos WHERE id=? AND cliente_id=?',
        (id, session['user_id'])
    ).fetchone()

    if not turno:
        db.close()
        flash('Turno no encontrado.', 'danger')
        return redirect(url_for('cliente_mis_turnos'))

    if turno['estado'] in ('cancelado', 'completado', 'rechazado'):
        db.close()
        flash('Este turno no puede cancelarse.', 'info')
        return redirect(url_for('cliente_mis_turnos'))

    disp = db.execute('SELECT fecha, hora_inicio FROM disponibilidad WHERE id=?',
                      (turno['disponibilidad_id'],)).fetchone()
    db.execute("UPDATE turnos SET estado='cancelado' WHERE id=?", (id,))
    db.execute('UPDATE disponibilidad SET disponible=1 WHERE id=?',
               (turno['disponibilidad_id'],))
    db.commit()
    db.close()
    if disp:
        _notificar_lista_espera(disp['fecha'], disp['hora_inicio'])
    flash('Turno cancelado. El horario quedó libre nuevamente.', 'info')
    return redirect(url_for('cliente_mis_turnos'))

@app.route('/cliente/lista-espera', methods=['POST'])
@cliente_required
def cliente_lista_espera():
    fecha = request.form.get('fecha', '').strip()
    if not fecha:
        flash('Fecha inválida.', 'danger')
        return redirect(url_for('cliente_reservar'))

    db  = get_db()
    uid = session['user_id']
    try:
        db.execute('INSERT INTO lista_espera (usuario_id, fecha) VALUES (?,?)', (uid, fecha))
        db.commit()
        flash('¡Listo! Te avisaremos por email si se libera un turno para ese día.', 'success')
    except sqlite3.IntegrityError:
        flash('Ya estás anotado en la lista de espera para esa fecha.', 'info')
    finally:
        db.close()
    return redirect(url_for('cliente_reservar'))


@app.route('/cliente/turnos/<int:id>/reprogramar', methods=['GET', 'POST'])
@cliente_required
def cliente_reprogramar(id):
    db    = get_db()
    uid   = session['user_id']
    hoy   = date.today().isoformat()

    turno = db.execute('''
        SELECT t.*, d.fecha, d.hora_inicio, d.hora_fin, d.id AS disp_id
        FROM turnos t JOIN disponibilidad d ON t.disponibilidad_id=d.id
        WHERE t.id=? AND t.cliente_id=?
    ''', (id, uid)).fetchone()

    if not turno or turno['estado'] in ('cancelado', 'completado', 'pendiente', 'rechazado'):
        db.close()
        flash('Turno no disponible para reprogramar.', 'danger')
        return redirect(url_for('cliente_mis_turnos'))

    if not _puede_reprogramar(turno['fecha'], turno['hora_inicio']):
        db.close()
        flash('No es posible reprogramar un turno cuando faltan 8 horas o menos para su inicio.', 'danger')
        return redirect(url_for('cliente_mis_turnos'))

    if request.method == 'POST':
        nueva_disp = request.form.get('disponibilidad_id', '').strip()
        if not nueva_disp:
            flash('Seleccioná un horario.', 'danger')
            return redirect(url_for('cliente_reprogramar', id=id))

        try:
            disp_viejo = db.execute(
                'SELECT fecha, hora_inicio FROM disponibilidad WHERE id=?', (turno['disp_id'],)
            ).fetchone()
            db.execute(
                'UPDATE turnos SET disponibilidad_id=?, estado=? WHERE id=?',
                (nueva_disp, 'reservado', id)
            )
            db.execute('UPDATE disponibilidad SET disponible=1 WHERE id=?',
                       (turno['disp_id'],))
            db.execute('UPDATE disponibilidad SET disponible=0 WHERE id=?',
                       (nueva_disp,))
            db.commit()
            db.close()
            if disp_viejo:
                _notificar_lista_espera(disp_viejo['fecha'], disp_viejo['hora_inicio'])
            flash('Turno reprogramado exitosamente.', 'success')
            return redirect(url_for('cliente_mis_turnos'))

        except sqlite3.IntegrityError:
            db.rollback()
            db.close()
            flash('El horario seleccionado ya fue tomado. Elegí otro.', 'danger')
            return redirect(url_for('cliente_reprogramar', id=id))

    # GET: slots disponibles (excluye el actual)
    slots = db.execute('''
        SELECT d.id, d.fecha, d.hora_inicio, d.hora_fin
        FROM disponibilidad d
        WHERE d.disponible=1 AND d.fecha >= ? AND d.id != ?
          AND d.id NOT IN (
              SELECT disponibilidad_id FROM turnos WHERE estado NOT IN ('cancelado')
          )
        ORDER BY d.fecha, d.hora_inicio
    ''', (hoy, turno['disp_id'])).fetchall()

    by_date = defaultdict(list)
    for s in slots:
        by_date[s['fecha']].append(s)

    db.close()
    return render_template('cliente/reprogramar.html',
                           turno=turno, by_date=dict(sorted(by_date.items())))

# ── Panel Admin ───────────────────────────────────────────────────────────────

@app.route('/admin')
@admin_required
def admin_dashboard():
    db  = get_db()
    hoy = date.today()

    semana_fin = (hoy + timedelta(days=6)).isoformat()
    mes_inicio = hoy.replace(day=1).isoformat()
    prox_mes   = (hoy.replace(day=28) + timedelta(days=4))
    mes_fin    = prox_mes.replace(day=1).isoformat()
    hoy_str    = hoy.isoformat()

    stats = {
        'turnos_hoy': db.execute(
            "SELECT COUNT(*) FROM turnos t JOIN disponibilidad d ON t.disponibilidad_id=d.id "
            "WHERE d.fecha=? AND t.estado NOT IN ('cancelado')", (hoy_str,)
        ).fetchone()[0],
        'turnos_semana': db.execute(
            "SELECT COUNT(*) FROM turnos t JOIN disponibilidad d ON t.disponibilidad_id=d.id "
            "WHERE d.fecha BETWEEN ? AND ? AND t.estado NOT IN ('cancelado')",
            (hoy_str, semana_fin)
        ).fetchone()[0],
        'turnos_mes': db.execute(
            "SELECT COUNT(*) FROM turnos t JOIN disponibilidad d ON t.disponibilidad_id=d.id "
            "WHERE d.fecha BETWEEN ? AND ? AND t.estado NOT IN ('cancelado')",
            (mes_inicio, mes_fin)
        ).fetchone()[0],
        'total_clientes': db.execute(
            "SELECT COUNT(*) FROM usuarios WHERE rol='cliente'"
        ).fetchone()[0],
        'slots_libres': db.execute(
            "SELECT COUNT(*) FROM disponibilidad WHERE disponible=1 AND fecha >= ?", (hoy_str,)
        ).fetchone()[0],
        'turnos_pendientes': db.execute(
            "SELECT COUNT(*) FROM turnos WHERE estado='pendiente'"
        ).fetchone()[0],
    }

    turnos_hoy = db.execute('''
        SELECT t.id, u.nombre||' '||u.apellido AS cliente, u.telefono,
               d.hora_inicio, d.hora_fin, t.estado
        FROM turnos t
        JOIN usuarios u ON t.cliente_id=u.id
        JOIN disponibilidad d ON t.disponibilidad_id=d.id
        WHERE d.fecha=? AND t.estado NOT IN ('cancelado')
        ORDER BY d.hora_inicio
    ''', (hoy_str,)).fetchall()

    proximos = db.execute('''
        SELECT t.id, u.nombre||' '||u.apellido AS cliente,
               d.fecha, d.hora_inicio, d.hora_fin, t.estado
        FROM turnos t
        JOIN usuarios u ON t.cliente_id=u.id
        JOIN disponibilidad d ON t.disponibilidad_id=d.id
        WHERE d.fecha > ? AND t.estado = 'confirmado'
        ORDER BY d.fecha, d.hora_inicio
        LIMIT 8
    ''', (hoy_str,)).fetchall()

    db.close()
    return render_template('admin/dashboard.html',
                           stats=stats, turnos_hoy=turnos_hoy, proximos=proximos)

@app.route('/admin/turnos')
@admin_required
def admin_turnos():
    db     = get_db()
    fecha  = request.args.get('fecha', '')
    estado = request.args.get('estado', '')

    q = '''
        SELECT t.id, u.nombre||' '||u.apellido AS cliente, u.telefono, u.email,
               d.fecha, d.hora_inicio, d.hora_fin, t.estado, t.notas, t.creado_en
        FROM turnos t
        JOIN usuarios u ON t.cliente_id=u.id
        JOIN disponibilidad d ON t.disponibilidad_id=d.id
        WHERE 1=1
    '''
    params = []
    if fecha:
        q += ' AND d.fecha=?';   params.append(fecha)
    if estado:
        q += ' AND t.estado=?';  params.append(estado)
    q += ' ORDER BY d.fecha DESC, d.hora_inicio'

    turnos = db.execute(q, params).fetchall()
    db.close()
    return render_template('admin/turnos.html', turnos=turnos,
                           filtro_fecha=fecha, filtro_estado=estado)

@app.route('/admin/turnos/<int:id>/estado', methods=['POST'])
@admin_required
def admin_cambiar_estado(id):
    estado = request.form['estado']
    db     = get_db()
    turno  = db.execute('SELECT * FROM turnos WHERE id=?', (id,)).fetchone()
    disp_liberado = None
    if turno:
        if estado == 'cancelado':
            disp_liberado = db.execute(
                'SELECT fecha, hora_inicio FROM disponibilidad WHERE id=?',
                (turno['disponibilidad_id'],)
            ).fetchone()
        db.execute('UPDATE turnos SET estado=? WHERE id=?', (estado, id))
        if estado == 'cancelado':
            db.execute('UPDATE disponibilidad SET disponible=1 WHERE id=?',
                       (turno['disponibilidad_id'],))
        db.commit()
    db.close()
    if disp_liberado:
        _notificar_lista_espera(disp_liberado['fecha'], disp_liberado['hora_inicio'])
    flash('Estado actualizado.', 'success')
    return redirect(request.referrer or url_for('admin_turnos'))

@app.route('/admin/turnos-pendientes')
@admin_required
def admin_turnos_pendientes():
    db = get_db()
    pendientes = db.execute('''
        SELECT t.id, u.nombre||' '||u.apellido AS cliente, u.email, u.telefono,
               d.fecha, d.hora_inicio, d.hora_fin, t.estado, t.creado_en, t.comprobante_path
        FROM turnos t
        JOIN usuarios u ON t.cliente_id=u.id
        JOIN disponibilidad d ON t.disponibilidad_id=d.id
        WHERE t.estado='pendiente'
        ORDER BY t.creado_en
    ''').fetchall()
    db.close()
    return render_template('admin/turnos_pendientes.html', pendientes=pendientes,
                           sena_alias=SENA_ALIAS, sena_monto=SENA_MONTO)

@app.route('/admin/turnos-pendientes/<int:id>/aprobar', methods=['POST'])
@admin_required
def admin_aprobar_turno(id):
    db    = get_db()
    turno = db.execute("SELECT * FROM turnos WHERE id=? AND estado='pendiente'", (id,)).fetchone()
    if not turno:
        db.close()
        flash('Solicitud no encontrada o ya procesada.', 'danger')
        return redirect(url_for('admin_turnos_pendientes'))

    db.execute("UPDATE turnos SET estado='confirmado' WHERE id=?", (id,))
    db.commit()
    db.close()
    flash('Turno confirmado. El cliente ya puede ver su turno confirmado.', 'success')
    return redirect(url_for('admin_turnos_pendientes'))

@app.route('/admin/turnos-pendientes/<int:id>/rechazar', methods=['POST'])
@admin_required
def admin_rechazar_turno(id):
    db    = get_db()
    turno = db.execute("SELECT * FROM turnos WHERE id=? AND estado='pendiente'", (id,)).fetchone()
    if not turno:
        db.close()
        flash('Solicitud no encontrada o ya procesada.', 'danger')
        return redirect(url_for('admin_turnos_pendientes'))

    disp = db.execute('SELECT fecha, hora_inicio FROM disponibilidad WHERE id=?',
                      (turno['disponibilidad_id'],)).fetchone()
    db.execute("UPDATE turnos SET estado='rechazado' WHERE id=?", (id,))
    db.execute('UPDATE disponibilidad SET disponible=1 WHERE id=?',
               (turno['disponibilidad_id'],))
    db.commit()
    db.close()
    if disp:
        _notificar_lista_espera(disp['fecha'], disp['hora_inicio'])
    flash('Solicitud rechazada. El horario quedó liberado nuevamente.', 'info')
    return redirect(url_for('admin_turnos_pendientes'))

@app.route('/admin/clientes')
@admin_required
def admin_clientes():
    db = get_db()
    clientes = db.execute('''
        SELECT u.id, u.nombre, u.apellido, u.telefono, u.email, u.creado_en,
               COUNT(CASE WHEN t.estado NOT IN ('cancelado') THEN 1 END) AS turnos_activos,
               COUNT(t.id) AS total_turnos
        FROM usuarios u
        LEFT JOIN turnos t ON u.id=t.cliente_id
        WHERE u.rol='cliente'
        GROUP BY u.id
        ORDER BY u.nombre
    ''').fetchall()
    db.close()
    return render_template('admin/clientes.html', clientes=clientes)

@app.route('/admin/disponibilidad')
@admin_required
def admin_disponibilidad():
    db  = get_db()
    hoy = date.today().isoformat()

    slots = db.execute('''
        SELECT d.*,
               t.id        AS turno_id,
               t.estado    AS turno_estado,
               u.nombre||' '||u.apellido AS cliente_nombre,
               u.telefono  AS cliente_tel
        FROM disponibilidad d
        LEFT JOIN turnos t ON d.id=t.disponibilidad_id AND t.estado NOT IN ('cancelado')
        LEFT JOIN usuarios u ON t.cliente_id=u.id
        WHERE d.fecha >= ?
        ORDER BY d.fecha, d.hora_inicio
    ''', (hoy,)).fetchall()

    by_date = defaultdict(list)
    for s in slots:
        by_date[s['fecha']].append(s)

    db.close()
    return render_template('admin/disponibilidad.html',
                           by_date=dict(sorted(by_date.items())))

@app.route('/admin/disponibilidad/generar', methods=['POST'])
@admin_required
def admin_generar_slots():
    fecha_ini    = request.form['fecha_inicio']
    fecha_fin    = request.form['fecha_fin']
    hora_ini     = request.form['hora_inicio'].strip()
    hora_fin     = request.form['hora_fin'].strip()
    almuerzo_ini = request.form.get('almuerzo_inicio', '').strip() or None
    almuerzo_fin = request.form.get('almuerzo_fin', '').strip() or None
    dias         = [int(d) for d in request.form.getlist('dias')]

    if not dias:
        flash('Seleccioná al menos un día de la semana.', 'danger')
        return redirect(url_for('admin_disponibilidad'))

    try:
        hi = datetime.strptime(hora_ini, '%H:%M')
        hf = datetime.strptime(hora_fin, '%H:%M')
    except ValueError:
        flash('Formato de hora inválido. Usá HH:MM.', 'danger')
        return redirect(url_for('admin_disponibilidad'))

    if hf <= hi:
        flash('El horario de fin debe ser posterior al de inicio.', 'danger')
        return redirect(url_for('admin_disponibilidad'))

    start   = datetime.strptime(fecha_ini, '%Y-%m-%d').date()
    end     = datetime.strptime(fecha_fin, '%Y-%m-%d').date()
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
    flash(f'Se generaron {created} horarios disponibles.', 'success')
    return redirect(url_for('admin_disponibilidad'))

@app.route('/admin/disponibilidad/<int:id>/toggle', methods=['POST'])
@admin_required
def admin_toggle_slot(id):
    db   = get_db()
    slot = db.execute('SELECT * FROM disponibilidad WHERE id=?', (id,)).fetchone()

    if slot:
        tiene_turno = db.execute(
            "SELECT id FROM turnos WHERE disponibilidad_id=? AND estado NOT IN ('cancelado')",
            (id,)
        ).fetchone()

        if tiene_turno and slot['disponible'] == 0:
            db.close()
            flash('No se puede bloquear: hay un turno activo. Cancelá el turno primero.', 'danger')
            return redirect(url_for('admin_disponibilidad'))

        toggling_to_available = (slot['disponible'] == 0)
        db.execute('UPDATE disponibilidad SET disponible=? WHERE id=?',
                   (0 if slot['disponible'] else 1, id))
        db.commit()
        db.close()
        if toggling_to_available:
            _notificar_lista_espera(slot['fecha'], slot['hora_inicio'])
    else:
        db.close()
    return redirect(url_for('admin_disponibilidad'))

@app.route('/admin/disponibilidad/bloquear-dia', methods=['POST'])
@admin_required
def admin_bloquear_dia():
    fecha = request.form['fecha']
    db    = get_db()
    db.execute(
        "UPDATE disponibilidad SET disponible=0 WHERE fecha=? "
        "AND id NOT IN (SELECT disponibilidad_id FROM turnos "
        "               WHERE estado NOT IN ('cancelado'))",
        (fecha,)
    )
    db.commit()
    db.close()
    flash(f'Día {fecha} bloqueado. Los turnos reservados no fueron afectados.', 'info')
    return redirect(url_for('admin_disponibilidad'))

@app.route('/admin/disponibilidad/eliminar-libres', methods=['POST'])
@admin_required
def admin_eliminar_libres():
    fecha = request.form['fecha']
    db    = get_db()
    db.execute(
        "DELETE FROM disponibilidad WHERE fecha=? AND disponible=1",
        (fecha,)
    )
    db.commit()
    db.close()
    flash(f'Horarios libres del {fecha} eliminados.', 'info')
    return redirect(url_for('admin_disponibilidad'))

# ── API calendario ────────────────────────────────────────────────────────────

@app.route('/api/turnos')
@admin_required
def api_turnos():
    db = get_db()
    rows = db.execute('''
        SELECT t.id, u.nombre||' '||u.apellido AS title,
               d.fecha, d.hora_inicio, d.hora_fin, t.estado
        FROM turnos t
        JOIN usuarios u ON t.cliente_id=u.id
        JOIN disponibilidad d ON t.disponibilidad_id=d.id
        WHERE t.estado NOT IN ('cancelado')
    ''').fetchall()
    db.close()

    colors = {
        'reservado':  '#f59e0b',
        'confirmado': '#3b82f6',
        'completado': '#10b981',
        'pendiente':  '#a16207',
    }
    events = []
    for r in rows:
        events.append({
            'id':              r['id'],
            'title':           r['title'],
            'start':           f"{r['fecha']}T{r['hora_inicio']}",
            'end':             f"{r['fecha']}T{r['hora_fin']}",
            'backgroundColor': colors.get(r['estado'], '#6b7280'),
            'borderColor':     colors.get(r['estado'], '#6b7280'),
            'extendedProps':   {'estado': r['estado']},
        })
    return jsonify(events)

# ── JSON API ──────────────────────────────────────────────────────────────────

def json_ok(data: dict, status=200):
    return jsonify({**data, 'success': True}), status

def json_err(msg: str, status=400):
    return jsonify({'success': False, 'error': msg}), status

def api_auth(f):
    """Require login for API routes."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return json_err('No autenticado.', 401)
        return f(*args, **kwargs)
    return decorated

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
    hoy = date.today().isoformat()

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
    db  = get_db()
    hoy = date.today().isoformat()
    uid = session['user_id']

    slots = db.execute('''
        SELECT d.id, d.fecha, d.hora_inicio, d.hora_fin
        FROM disponibilidad d
        WHERE d.disponible=1 AND d.fecha >= ?
          AND d.id NOT IN (SELECT disponibilidad_id FROM turnos WHERE estado NOT IN ('cancelado'))
        ORDER BY d.fecha, d.hora_inicio
    ''', (hoy,)).fetchall()

    fechas_completas = [dict(r) for r in db.execute('''
        SELECT DISTINCT d.fecha,
               CASE WHEN le.id IS NOT NULL THEN 1 ELSE 0 END AS en_espera
        FROM disponibilidad d
        LEFT JOIN lista_espera le ON le.fecha = d.fecha AND le.usuario_id = ?
        WHERE d.fecha >= ?
          AND d.fecha NOT IN (
              SELECT DISTINCT d2.fecha FROM disponibilidad d2
              WHERE d2.disponible=1 AND d2.fecha >= ?
                AND d2.id NOT IN (
                    SELECT disponibilidad_id FROM turnos WHERE estado NOT IN ('cancelado')
                )
          )
        ORDER BY d.fecha
    ''', (uid, hoy, hoy)).fetchall()]

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

    # Procesar comprobante adjunto
    comprobante_path = None
    archivo = request.files.get('comprobante')
    if not archivo or archivo.filename == '':
        return json_err('Debés adjuntar el comprobante de transferencia.')
    ext = archivo.filename.rsplit('.', 1)[-1].lower() if '.' in archivo.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        return json_err('Formato de comprobante no permitido. Usá JPG, PNG, PDF o WEBP.')
    filename = f"{uuid.uuid4().hex}.{ext}"
    archivo.save(os.path.join(UPLOAD_FOLDER, filename))
    comprobante_path = f"comprobantes/{filename}"

    db = get_db()
    try:
        db.execute('INSERT INTO turnos (cliente_id, disponibilidad_id, estado, comprobante_path) VALUES (?,?,?,?)',
                   (session['user_id'], disp_id, 'pendiente', comprobante_path))
        db.execute('UPDATE disponibilidad SET disponible=0 WHERE id=? AND disponible=1', (disp_id,))
        db.commit()
        db.close()
        return json_ok({'message': '¡Solicitud registrada! Tu turno quedará pendiente hasta que '
                                    'el administrador verifique la transferencia.'})
    except sqlite3.IntegrityError:
        db.close()
        return json_err('Este horario acaba de ser tomado. Por favor elegí otro.')

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
    hoy = date.today().isoformat()
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
    db  = get_db()
    hoy = date.today().isoformat()

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
          AND d.id NOT IN (SELECT disponibilidad_id FROM turnos WHERE estado NOT IN ('cancelado'))
        ORDER BY d.fecha, d.hora_inicio
    ''', (hoy, turno['disp_id'])).fetchall()

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

    if not _puede_reprogramar(turno['fecha'], turno['hora_inicio']):
        db.close()
        return json_err('No es posible reprogramar un turno cuando faltan 8 horas o menos para su inicio.', 403)

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
    db  = get_db()
    hoy = date.today()
    hoy_str    = hoy.isoformat()
    semana_fin = (hoy + timedelta(days=6)).isoformat()
    mes_inicio = hoy.replace(day=1).isoformat()
    prox_mes   = (hoy.replace(day=28) + timedelta(days=4))
    mes_fin    = prox_mes.replace(day=1).isoformat()

    stats = {
        'turnos_hoy': db.execute(
            "SELECT COUNT(*) FROM turnos t JOIN disponibilidad d ON t.disponibilidad_id=d.id "
            "WHERE d.fecha=? AND t.estado NOT IN ('cancelado')", (hoy_str,)).fetchone()[0],
        'turnos_semana': db.execute(
            "SELECT COUNT(*) FROM turnos t JOIN disponibilidad d ON t.disponibilidad_id=d.id "
            "WHERE d.fecha BETWEEN ? AND ? AND t.estado NOT IN ('cancelado')",
            (hoy_str, semana_fin)).fetchone()[0],
        'turnos_mes': db.execute(
            "SELECT COUNT(*) FROM turnos t JOIN disponibilidad d ON t.disponibilidad_id=d.id "
            "WHERE d.fecha BETWEEN ? AND ? AND t.estado NOT IN ('cancelado')",
            (mes_inicio, mes_fin)).fetchone()[0],
        'total_clientes': db.execute("SELECT COUNT(*) FROM usuarios WHERE rol='cliente'").fetchone()[0],
        'slots_libres': db.execute(
            "SELECT COUNT(*) FROM disponibilidad WHERE disponible=1 AND fecha >= ?", (hoy_str,)).fetchone()[0],
        'turnos_pendientes': db.execute(
            "SELECT COUNT(*) FROM turnos WHERE estado='pendiente'").fetchone()[0],
    }

    turnos_hoy = [dict(r) for r in db.execute('''
        SELECT t.id, u.nombre||' '||u.apellido AS cliente, u.telefono,
               d.hora_inicio, d.hora_fin, t.estado
        FROM turnos t
        JOIN usuarios u ON t.cliente_id=u.id
        JOIN disponibilidad d ON t.disponibilidad_id=d.id
        WHERE d.fecha=? AND t.estado NOT IN ('cancelado')
        ORDER BY d.hora_inicio
    ''', (hoy_str,)).fetchall()]

    proximos = [dict(r) for r in db.execute('''
        SELECT t.id, u.nombre||' '||u.apellido AS cliente,
               d.fecha, d.hora_inicio, d.hora_fin, t.estado
        FROM turnos t
        JOIN usuarios u ON t.cliente_id=u.id
        JOIN disponibilidad d ON t.disponibilidad_id=d.id
        WHERE d.fecha > ? AND t.estado = 'confirmado'
        ORDER BY d.fecha, d.hora_inicio LIMIT 8
    ''', (hoy_str,)).fetchall()]

    db.close()
    return json_ok({'stats': stats, 'turnos_hoy': turnos_hoy, 'proximos': proximos})

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
    hoy = date.today().isoformat()

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

    start   = datetime.strptime(fecha_ini, '%Y-%m-%d').date()
    end     = datetime.strptime(fecha_fin, '%Y-%m-%d').date()
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
    app.run(debug=True, port=5001)
