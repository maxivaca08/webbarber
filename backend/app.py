from flask import Flask, jsonify
from flask_cors import CORS
from database import init_db, get_db
from blueprints.clientes import bp as clientes_bp
from blueprints.barberos import bp as barberos_bp
from blueprints.servicios import bp as servicios_bp
from blueprints.turnos import bp as turnos_bp
from config import SECRET_KEY, DEBUG, HOST, PORT

app = Flask(__name__)
app.secret_key = SECRET_KEY
CORS(app)

@app.before_request
def setup():
    init_db()

# Dashboard stats
@app.route('/api/stats')
def stats():
    db = get_db()
    stats_data = {
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
    return jsonify({'stats': stats_data, 'turnos_hoy': [dict(r) for r in turnos_hoy]})

app.register_blueprint(clientes_bp)
app.register_blueprint(barberos_bp)
app.register_blueprint(servicios_bp)
app.register_blueprint(turnos_bp)

if __name__ == '__main__':
    app.run(debug=DEBUG, host=HOST, port=PORT)
