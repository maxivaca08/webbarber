from flask import Blueprint, request, jsonify
from database import get_db

bp = Blueprint('clientes', __name__, url_prefix='/api/clientes')

@bp.route('', methods=['GET'])
def listar():
    db = get_db()
    rows = db.execute('SELECT * FROM clientes ORDER BY nombre').fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@bp.route('', methods=['POST'])
def crear():
    data = request.get_json()
    db = get_db()
    cur = db.execute(
        'INSERT INTO clientes (nombre, apellido, telefono, email) VALUES (?,?,?,?)',
        (data['nombre'], data['apellido'], data.get('telefono', ''), data.get('email', ''))
    )
    db.commit()
    row = db.execute('SELECT * FROM clientes WHERE id=?', (cur.lastrowid,)).fetchone()
    db.close()
    return jsonify(dict(row)), 201

@bp.route('/<int:id>', methods=['GET'])
def obtener(id):
    db = get_db()
    row = db.execute('SELECT * FROM clientes WHERE id=?', (id,)).fetchone()
    db.close()
    if not row:
        return jsonify({'error': 'Cliente no encontrado'}), 404
    return jsonify(dict(row))

@bp.route('/<int:id>', methods=['PUT'])
def actualizar(id):
    data = request.get_json()
    db = get_db()
    cur = db.execute(
        'UPDATE clientes SET nombre=?,apellido=?,telefono=?,email=? WHERE id=?',
        (data['nombre'], data['apellido'], data.get('telefono', ''), data.get('email', ''), id)
    )
    db.commit()
    if cur.rowcount == 0:
        db.close()
        return jsonify({'error': 'Cliente no encontrado'}), 404
    row = db.execute('SELECT * FROM clientes WHERE id=?', (id,)).fetchone()
    db.close()
    return jsonify(dict(row))

@bp.route('/<int:id>', methods=['DELETE'])
def eliminar(id):
    db = get_db()
    cur = db.execute('DELETE FROM clientes WHERE id=?', (id,))
    db.commit()
    db.close()
    if cur.rowcount == 0:
        return jsonify({'error': 'Cliente no encontrado'}), 404
    return jsonify({'mensaje': 'Cliente eliminado'})
