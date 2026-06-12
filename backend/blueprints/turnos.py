from flask import Blueprint, request, jsonify
from database import get_db
from datetime import datetime, timedelta

bp = Blueprint('turnos', __name__, url_prefix='/api/turnos')

@bp.route('', methods=['GET'])
def listar():
    db = get_db()
    fecha = request.args.get('fecha', '')
    barbero_id = request.args.get('barbero_id', '')
    estado = request.args.get('estado', '')

    query = '''
        SELECT t.id, c.nombre||' '||c.apellido AS cliente,
               b.nombre||' '||b.apellido AS barbero,
               s.nombre AS servicio, s.precio, s.duracion_minutos,
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
    db.close()
    return jsonify([dict(r) for r in rows])

@bp.route('/calendario', methods=['GET'])
def calendario():
    db = get_db()
    rows = db.execute('''
        SELECT t.id, c.nombre||' '||c.apellido AS title,
               t.fecha_hora AS start, s.duracion_minutos,
               t.estado, b.nombre||' '||b.apellido AS barbero
        FROM turnos t
        JOIN clientes c ON t.cliente_id=c.id
        JOIN barberos b ON t.barbero_id=b.id
        JOIN servicios s ON t.servicio_id=s.id
    ''').fetchall()
    db.close()

    colors = {'pendiente': '#f59e0b', 'confirmado': '#3b82f6',
              'completado': '#10b981', 'cancelado': '#ef4444'}
    events = []
    for r in rows:
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

@bp.route('', methods=['POST'])
def crear():
    data = request.get_json()
    db = get_db()
    cur = db.execute(
        'INSERT INTO turnos (cliente_id, barbero_id, servicio_id, fecha_hora, estado, notas) VALUES (?,?,?,?,?,?)',
        (data['cliente_id'], data['barbero_id'], data['servicio_id'],
         data['fecha_hora'], 'pendiente', data.get('notas', ''))
    )
    db.commit()
    row = db.execute('''
        SELECT t.*, c.nombre||' '||c.apellido AS cliente_nombre,
               b.nombre||' '||b.apellido AS barbero_nombre,
               s.nombre AS servicio_nombre
        FROM turnos t
        JOIN clientes c ON t.cliente_id=c.id
        JOIN barberos b ON t.barbero_id=b.id
        JOIN servicios s ON t.servicio_id=s.id
        WHERE t.id=?
    ''', (cur.lastrowid,)).fetchone()
    db.close()
    return jsonify(dict(row)), 201

@bp.route('/<int:id>', methods=['GET'])
def obtener(id):
    db = get_db()
    row = db.execute('''
        SELECT t.*, c.nombre||' '||c.apellido AS cliente_nombre,
               b.nombre||' '||b.apellido AS barbero_nombre,
               s.nombre AS servicio_nombre, s.duracion_minutos, s.precio
        FROM turnos t
        JOIN clientes c ON t.cliente_id=c.id
        JOIN barberos b ON t.barbero_id=b.id
        JOIN servicios s ON t.servicio_id=s.id
        WHERE t.id=?
    ''', (id,)).fetchone()
    db.close()
    if not row:
        return jsonify({'error': 'Turno no encontrado'}), 404
    return jsonify(dict(row))

@bp.route('/<int:id>', methods=['PUT'])
def actualizar(id):
    data = request.get_json()
    db = get_db()
    cur = db.execute(
        'UPDATE turnos SET cliente_id=?,barbero_id=?,servicio_id=?,fecha_hora=?,estado=?,notas=? WHERE id=?',
        (data['cliente_id'], data['barbero_id'], data['servicio_id'],
         data['fecha_hora'], data.get('estado', 'pendiente'), data.get('notas', ''), id)
    )
    db.commit()
    if cur.rowcount == 0:
        db.close()
        return jsonify({'error': 'Turno no encontrado'}), 404
    row = db.execute('SELECT * FROM turnos WHERE id=?', (id,)).fetchone()
    db.close()
    return jsonify(dict(row))

@bp.route('/<int:id>/estado', methods=['PATCH'])
def cambiar_estado(id):
    data = request.get_json()
    db = get_db()
    cur = db.execute('UPDATE turnos SET estado=? WHERE id=?',
                     (data['estado'], id))
    db.commit()
    if cur.rowcount == 0:
        db.close()
        return jsonify({'error': 'Turno no encontrado'}), 404
    row = db.execute('SELECT * FROM turnos WHERE id=?', (id,)).fetchone()
    db.close()
    return jsonify(dict(row))

@bp.route('/<int:id>', methods=['DELETE'])
def eliminar(id):
    db = get_db()
    cur = db.execute('DELETE FROM turnos WHERE id=?', (id,))
    db.commit()
    db.close()
    if cur.rowcount == 0:
        return jsonify({'error': 'Turno no encontrado'}), 404
    return jsonify({'mensaje': 'Turno eliminado'})
