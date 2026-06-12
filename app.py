from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from database import init_db, get_db
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'peluqueria_secret_key_2024'

@app.before_request
def setup():
    init_db()

# ──────────────────────────────────────────────
# DASHBOARD
# ──────────────────────────────────────────────
@app.route('/')
def index():
    db = get_db()
    stats = {
        'total_clientes': db.execute('SELECT COUNT(*) FROM clientes').fetchone()[0],
        'total_barberos': db.execute('SELECT COUNT(*) FROM barberos WHERE activo=1').fetchone()[0],
        'turnos_hoy': db.execute(
            "SELECT COUNT(*) FROM turnos WHERE DATE(fecha_hora)=DATE('now')"
        ).fetchone()[0],
        'turnos_pendientes': db.execute(
            "SELECT COUNT(*) FROM turnos WHERE estado='pendiente'"
        ).fetchone()[0],
    }
    turnos_hoy = db.execute('''
        SELECT t.id, c.nombre||' '||c.apellido AS cliente,
        b.nombre||' '||b.apellido AS barbero,
        s.nombre AS servicio, t.fecha_hora, t.estado
        FROM turnos t
        JOIN clientes c ON t.cliente_id=c.id
        JOIN barberos b ON t.barbero_id=b.id
        JOIN servicios s ON t.servicio_id=s.id
        WHERE DATE(t.fecha_hora)=DATE('now')
        ORDER BY t.fecha_hora
    ''').fetchall()
    db.close()
    return render_template('index.html', stats=stats, turnos_hoy=turnos_hoy)

# ──────────────────────────────────────────────
# CLIENTES
# ──────────────────────────────────────────────
@app.route('/clientes')
def clientes():
    db = get_db()
    rows = db.execute('SELECT * FROM clientes ORDER BY nombre').fetchall()
    db.close()
    return render_template('clientes.html', clientes=rows)

@app.route('/clientes/nuevo', methods=['GET', 'POST'])
def nuevo_cliente():
    if request.method == 'POST':
        db = get_db()
        db.execute(
            'INSERT INTO clientes (nombre, apellido, telefono, email) VALUES (?,?,?,?)',
            (request.form['nombre'], request.form['apellido'],
             request.form['telefono'], request.form['email'])
        )
        db.commit()
        db.close()
        flash('Cliente creado exitosamente.', 'success')
        return redirect(url_for('clientes'))
    return render_template('cliente_form.html', cliente=None)

@app.route('/clientes/<int:id>/editar', methods=['GET', 'POST'])
def editar_cliente(id):
    db = get_db()
    cliente = db.execute('SELECT * FROM clientes WHERE id=?', (id,)).fetchone()
    if request.method == 'POST':
        db.execute(
            'UPDATE clientes SET nombre=?,apellido=?,telefono=?,email=? WHERE id=?',
            (request.form['nombre'], request.form['apellido'],
             request.form['telefono'], request.form['email'], id)
        )
        db.commit()
        db.close()
        flash('Cliente actualizado.', 'success')
        return redirect(url_for('clientes'))
    db.close()
    return render_template('cliente_form.html', cliente=cliente)

@app.route('/clientes/<int:id>/eliminar', methods=['POST'])
def eliminar_cliente(id):
    db = get_db()
    db.execute('DELETE FROM clientes WHERE id=?', (id,))
    db.commit()
    db.close()
    flash('Cliente eliminado.', 'info')
    return redirect(url_for('clientes'))

# ──────────────────────────────────────────────
# BARBEROS
# ──────────────────────────────────────────────
@app.route('/barberos')
def barberos():
    db = get_db()
    rows = db.execute('SELECT * FROM barberos ORDER BY nombre').fetchall()
    db.close()
    return render_template('barberos.html', barberos=rows)

@app.route('/barberos/nuevo', methods=['GET', 'POST'])
def nuevo_barbero():
    if request.method == 'POST':
        db = get_db()
        db.execute(
            'INSERT INTO barberos (nombre, apellido, especialidad, activo) VALUES (?,?,?,?)',
            (request.form['nombre'], request.form['apellido'],
             request.form['especialidad'], 1)
        )
        db.commit()
        db.close()
        flash('Barbero creado exitosamente.', 'success')
        return redirect(url_for('barberos'))
    return render_template('barbero_form.html', barbero=None)

@app.route('/barberos/<int:id>/editar', methods=['GET', 'POST'])
def editar_barbero(id):
    db = get_db()
    barbero = db.execute('SELECT * FROM barberos WHERE id=?', (id,)).fetchone()
    if request.method == 'POST':
        db.execute(
            'UPDATE barberos SET nombre=?,apellido=?,especialidad=?,activo=? WHERE id=?',
            (request.form['nombre'], request.form['apellido'],
             request.form['especialidad'], int('activo' in request.form), id)
        )
        db.commit()
        db.close()
        flash('Barbero actualizado.', 'success')
        return redirect(url_for('barberos'))
    db.close()
    return render_template('barbero_form.html', barbero=barbero)

@app.route('/barberos/<int:id>/eliminar', methods=['POST'])
def eliminar_barbero(id):
    db = get_db()
    db.execute('DELETE FROM barberos WHERE id=?', (id,))
    db.commit()
    db.close()
    flash('Barbero eliminado.', 'info')
    return redirect(url_for('barberos'))

# ──────────────────────────────────────────────
# SERVICIOS
# ──────────────────────────────────────────────
@app.route('/servicios')
def servicios():
    db = get_db()
    rows = db.execute('SELECT * FROM servicios ORDER BY nombre').fetchall()
    db.close()
    return render_template('servicios.html', servicios=rows)

@app.route('/servicios/nuevo', methods=['GET', 'POST'])
def nuevo_servicio():
    if request.method == 'POST':
        db = get_db()
        db.execute(
            'INSERT INTO servicios (nombre, descripcion, duracion_minutos, precio) VALUES (?,?,?,?)',
            (request.form['nombre'], request.form['descripcion'],
             request.form['duracion_minutos'], request.form['precio'])
        )
        db.commit()
        db.close()
        flash('Servicio creado exitosamente.', 'success')
        return redirect(url_for('servicios'))
    return render_template('servicio_form.html', servicio=None)

@app.route('/servicios/<int:id>/editar', methods=['GET', 'POST'])
def editar_servicio(id):
    db = get_db()
    servicio = db.execute('SELECT * FROM servicios WHERE id=?', (id,)).fetchone()
    if request.method == 'POST':
        db.execute(
            'UPDATE servicios SET nombre=?,descripcion=?,duracion_minutos=?,precio=? WHERE id=?',
            (request.form['nombre'], request.form['descripcion'],
             request.form['duracion_minutos'], request.form['precio'], id)
        )
        db.commit()
        db.close()
        flash('Servicio actualizado.', 'success')
        return redirect(url_for('servicios'))
    db.close()
    return render_template('servicio_form.html', servicio=servicio)

@app.route('/servicios/<int:id>/eliminar', methods=['POST'])
def eliminar_servicio(id):
    db = get_db()
    db.execute('DELETE FROM servicios WHERE id=?', (id,))
    db.commit()
    db.close()
    flash('Servicio eliminado.', 'info')
    return redirect(url_for('servicios'))

# ──────────────────────────────────────────────
# TURNOS
# ──────────────────────────────────────────────
@app.route('/turnos')
def turnos():
    db = get_db()
    fecha = request.args.get('fecha', '')
    barbero_id = request.args.get('barbero_id', '')
    estado = request.args.get('estado', '')

    query = '''
        SELECT t.id, c.nombre||' '||c.apellido AS cliente,
               b.nombre||' '||b.apellido AS barbero,
               s.nombre AS servicio, s.precio,
               t.fecha_hora, t.estado, t.notas,
               t.cliente_id, t.barbero_id, t.servicio_id
        FROM turnos t
        JOIN clientes c ON t.cliente_id=c.id
        JOIN barberos b ON t.barbero_id=b.id
        JOIN servicios s ON t.servicio_id=s.id
        WHERE 1=1
    '''
    params = []
    if fecha:
        query += ' AND DATE(t.fecha_hora)=?'
        params.append(fecha)
    if barbero_id:
        query += ' AND t.barbero_id=?'
        params.append(barbero_id)
    if estado:
        query += ' AND t.estado=?'
        params.append(estado)
    query += ' ORDER BY t.fecha_hora DESC'

    rows = db.execute(query, params).fetchall()
    barberos = db.execute('SELECT id, nombre||" "||apellido AS nombre FROM barberos WHERE activo=1').fetchall()
    db.close()
    return render_template('turnos.html', turnos=rows, barberos=barberos,
                           filtro_fecha=fecha, filtro_barbero=barbero_id, filtro_estado=estado)

@app.route('/turnos/nuevo', methods=['GET', 'POST'])
def nuevo_turno():
    db = get_db()
    if request.method == 'POST':
        db.execute(
            'INSERT INTO turnos (cliente_id, barbero_id, servicio_id, fecha_hora, estado, notas) VALUES (?,?,?,?,?,?)',
            (request.form['cliente_id'], request.form['barbero_id'],
             request.form['servicio_id'], request.form['fecha_hora'],
             'pendiente', request.form.get('notas', ''))
        )
        db.commit()
        db.close()
        flash('Turno reservado exitosamente.', 'success')
        return redirect(url_for('turnos'))
    clientes = db.execute('SELECT id, nombre||" "||apellido AS nombre FROM clientes ORDER BY nombre').fetchall()
    barberos = db.execute('SELECT id, nombre||" "||apellido AS nombre FROM barberos WHERE activo=1 ORDER BY nombre').fetchall()
    servicios = db.execute('SELECT id, nombre, duracion_minutos, precio FROM servicios ORDER BY nombre').fetchall()
    db.close()
    return render_template('turno_form.html', turno=None,
                           clientes=clientes, barberos=barberos, servicios=servicios)

@app.route('/turnos/<int:id>/editar', methods=['GET', 'POST'])
def editar_turno(id):
    db = get_db()
    turno = db.execute('SELECT * FROM turnos WHERE id=?', (id,)).fetchone()
    if request.method == 'POST':
        db.execute(
            'UPDATE turnos SET cliente_id=?,barbero_id=?,servicio_id=?,fecha_hora=?,estado=?,notas=? WHERE id=?',
            (request.form['cliente_id'], request.form['barbero_id'],
             request.form['servicio_id'], request.form['fecha_hora'],
             request.form['estado'], request.form.get('notas', ''), id)
        )
        db.commit()
        db.close()
        flash('Turno actualizado.', 'success')
        return redirect(url_for('turnos'))
    clientes = db.execute('SELECT id, nombre||" "||apellido AS nombre FROM clientes ORDER BY nombre').fetchall()
    barberos = db.execute('SELECT id, nombre||" "||apellido AS nombre FROM barberos WHERE activo=1 ORDER BY nombre').fetchall()
    servicios = db.execute('SELECT id, nombre, duracion_minutos, precio FROM servicios ORDER BY nombre').fetchall()
    db.close()
    return render_template('turno_form.html', turno=turno,
                           clientes=clientes, barberos=barberos, servicios=servicios)

@app.route('/turnos/<int:id>/estado', methods=['POST'])
def cambiar_estado_turno(id):
    estado = request.form['estado']
    db = get_db()
    db.execute('UPDATE turnos SET estado=? WHERE id=?', (estado, id))
    db.commit()
    db.close()
    flash(f'Estado actualizado a "{estado}".', 'success')
    return redirect(request.referrer or url_for('turnos'))

@app.route('/turnos/<int:id>/eliminar', methods=['POST'])
def eliminar_turno(id):
    db = get_db()
    db.execute('DELETE FROM turnos WHERE id=?', (id,))
    db.commit()
    db.close()
    flash('Turno eliminado.', 'info')
    return redirect(url_for('turnos'))

# ──────────────────────────────────────────────
# API JSON para calendario
# ──────────────────────────────────────────────
@app.route('/api/turnos')
def api_turnos():
    db = get_db()
    rows = db.execute('''
        SELECT t.id, c.nombre||' '||c.apellido AS title,
               t.fecha_hora AS start, s.duracion_minutos,
               t.estado,
               b.nombre||' '||b.apellido AS barbero
        FROM turnos t
        JOIN clientes c ON t.cliente_id=c.id
        JOIN barberos b ON t.barbero_id=b.id
        JOIN servicios s ON t.servicio_id=s.id
    ''').fetchall()
    db.close()
    colors = {'pendiente': '#f59e0b', 'confirmado': '#3b82f6', 'completado': '#10b981', 'cancelado': '#ef4444'}
    events = []
    for r in rows:
        from datetime import datetime, timedelta
        start = datetime.fromisoformat(r['start'])
        end = start + timedelta(minutes=r['duracion_minutos'])
        events.append({
            'id': r['id'],
            'title': f"{r['title']} ({r['barbero']})",
            'start': start.isoformat(),
            'end': end.isoformat(),
            'backgroundColor': colors.get(r['estado'], '#6b7280'),
            'borderColor': colors.get(r['estado'], '#6b7280'),
        })
    return jsonify(events)

if __name__ == '__main__':
    app.run(debug=True, port=5001)
