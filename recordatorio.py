"""
Corre en segundo plano y manda recordatorios por WhatsApp via CallMeBot
a los clientes con turno confirmado al día siguiente.

Uso: python recordatorio.py
"""

import time
import sqlite3
import requests
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / 'peluqueria.db'
CALLMEBOT_URL = 'https://api.callmebot.com/whatsapp.php'
# Cuántas horas antes del día del turno se manda el recordatorio
HORAS_ANTES = 24


def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def mandar_recordatorio(telefono: str, callmebot_key: str, nombre: str,
                        fecha_str: str, hora_inicio: str, hora_fin: str) -> bool:
    """Llama a la API de CallMeBot. Devuelve True si el envío fue exitoso."""
    dias = {
        'Monday': 'lunes', 'Tuesday': 'martes', 'Wednesday': 'miércoles',
        'Thursday': 'jueves', 'Friday': 'viernes', 'Saturday': 'sábado',
        'Sunday': 'domingo',
    }
    from datetime import datetime
    fecha_dt  = datetime.strptime(fecha_str, '%Y-%m-%d')
    dia_nombre = dias.get(fecha_dt.strftime('%A'), fecha_dt.strftime('%A'))
    fecha_fmt  = fecha_dt.strftime(f'{dia_nombre} %d/%m')

    mensaje = (
        f"Hola {nombre}! 💈\n"
        f"Te recordamos que mañana tenés turno:\n"
        f"📅 {fecha_fmt}\n"
        f"🕒 {hora_inicio} – {hora_fin}hs\n\n"
        f"Si necesitás reprogramar, podés hacerlo hasta 8 horas antes desde la app."
    )

    # CallMeBot requiere el número sin + ni espacios, con código de país
    numero = telefono.replace('+', '').replace(' ', '').replace('-', '')
    if not numero.startswith('549') and not numero.startswith('54'):
        numero = '549' + numero

    try:
        resp = requests.get(
            CALLMEBOT_URL,
            params={'phone': numero, 'text': mensaje, 'apikey': callmebot_key},
            timeout=15,
        )
        return resp.status_code == 200
    except requests.RequestException as e:
        print(f'  [ERROR] Falló la llamada a CallMeBot: {e}')
        return False


def procesar():
    manana = (date.today() + timedelta(days=1)).isoformat()
    db = get_db()

    pendientes = db.execute('''
        SELECT t.id,
               u.nombre, u.telefono, u.callmebot_key,
               d.fecha, d.hora_inicio, d.hora_fin
        FROM turnos t
        JOIN usuarios u ON t.cliente_id = u.id
        JOIN disponibilidad d ON t.disponibilidad_id = d.id
        WHERE t.estado = 'confirmado'
          AND t.recordatorio_enviado = 0
          AND d.fecha = ?
          AND u.callmebot_key IS NOT NULL
          AND u.callmebot_key != ''
          AND u.telefono IS NOT NULL
          AND u.telefono != ''
    ''', (manana,)).fetchall()

    if not pendientes:
        print(f'[{date.today()}] Sin recordatorios para mañana.')
        db.close()
        return

    print(f'[{date.today()}] Enviando {len(pendientes)} recordatorio(s)...')

    for t in pendientes:
        print(f'  → {t["nombre"]} ({t["telefono"]}) — {t["fecha"]} {t["hora_inicio"]}')
        ok = mandar_recordatorio(
            telefono=t['telefono'],
            callmebot_key=t['callmebot_key'],
            nombre=t['nombre'],
            fecha_str=t['fecha'],
            hora_inicio=t['hora_inicio'],
            hora_fin=t['hora_fin'],
        )
        if ok:
            db.execute('UPDATE turnos SET recordatorio_enviado = 1 WHERE id = ?', (t['id'],))
            db.commit()
            print(f'    ✅ Enviado')
        else:
            print(f'    ❌ Falló (se reintentará en la próxima pasada)')

    db.close()


def main():
    print('=== Servicio de recordatorios iniciado ===')
    print(f'Revisando cada hora. Manda recordatorios {HORAS_ANTES}hs antes del turno.')
    while True:
        try:
            procesar()
        except Exception as e:
            print(f'[ERROR] {e}')
        time.sleep(3600)  # espera 1 hora


if __name__ == '__main__':
    main()
