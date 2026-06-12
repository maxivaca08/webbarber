from flask import Blueprint, request, jsonify
from database import get_db

bp = Blueprint('servicios', __name__, url_prefix='/api/servicios')

@bp.route('', methods=['GET'])
def listar():
    db = get_db()
    rows = db.execute('SELECT * FROM servicios ORDER BY nombre').fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@bp.route('', methods=['POST'])
def crear():
    data = request.get_json()
    db = get_db()
    cur = db.execute(
        'INSERT INTO servicios (nombre, descripcion, duracion_minutos, precio) VALUES (?,?,?,?)',
        (data['nombre'], data.get('descripcion', ''),
         data['duracion_minutos'], data['precio'])
    )
    db.commit()
    row = db.execute('SELECT * FROM servicios WHERE id=?', (cur.lastrowid,)).fetchone()
    db.close()
    return jsonify(dict(row)), 201

@bp.route('/<int:id>', methods=['GET'])
def obtener(id):
    db = get_db()
    row = db.execute('SELECT * FROM servicios WHERE id=?', (id,)).fetchone()
    db.close()
    if not row:
        return jsonify({'error': 'Servicio no encontrado'}), 404
    return jsonify(dict(row))

@bp.route('/<int:id>', methods=['PUT'])
def actualizar(id):
    data = request.get_json()
    db = get_db()
    cur = db.execute(
        'UPDATE servicios SET nombre=?,descripcion=?,duracion_minutos=?,precio=? WHERE id=?',
        (data['nombre'], data.get('descripcion', ''),
         data['duracion_minutos'], data['precio'], id)
    )
    db.commit()
    if cur.rowcount == 0:
        db.close()
        return jsonify({'error': 'Servicio no encontrado'}), 404
    row = db.execute('SELECT * FROM servicios WHERE id=?', (id,)).fetchone()
    db.close()
    return jsonify(dict(row))

@bp.route('/<int:id>', methods=['DELETE'])
def eliminar(id):
    db = get_db()
    cur = db.execute('DELETE FROM servicios WHERE id=?', (id,))
    db.commit()
    db.close()
    if cur.rowcount == 0:
        return jsonify({'error': 'Servicio no encontrado'}), 404
    return jsonify({'mensaje': 'Servicio eliminado'})
