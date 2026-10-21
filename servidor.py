"""Servicio del tablero de tareas: API JSON sobre SQLite.

Escucha solo en 127.0.0.1; nginx publica /tareas/api/ -> /api/.
Sin dependencias externas (solo la biblioteca estándar).

    python3 servidor.py

Repetición de cada tarea y cuándo cuenta como hecha:
    una      se hace una sola vez; hecha, se ve tachada hasta el fin del día y luego desaparece
    diaria   una vez por día   (periodo = fecha, AAAA-MM-DD)
    semanal  una vez por semana, lunes a domingo (periodo = semana ISO, AAAA-Wss)

Rutas:
    GET    /api/tablero                 personas + tareas visibles hoy, con su estado
    POST   /api/personas                {"nombre"}
    PATCH  /api/personas/<id>           {"nombre"}
    DELETE /api/personas/<id>           sus tareas quedan para "cualquiera"
    POST   /api/tareas                  {"titulo", "persona_id"|null, "repeticion"}
    PATCH  /api/tareas/<id>             {"titulo"?, "persona_id"?, "repeticion"?}
    DELETE /api/tareas/<id>
    POST   /api/tareas/<id>/hecha       {"hecha": true|false}
"""

import json
import os
import re
import sqlite3
import threading
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = '127.0.0.1'
# Se pueden cambiar para pruebas sin tocar los datos reales
PUERTO = int(os.environ.get('TAREAS_PUERTO', 8771))
BD = Path(os.environ.get('TAREAS_BD', Path.home() / '.local/share/casa/tareas.db'))
MAX_CUERPO = 4096
MAX_TITULO, MAX_NOMBRE = 80, 30
REPETICIONES = ('una', 'diaria', 'semanal')
COLORES = ['#e4572e', '#2e86ab', '#7fb069', '#a15dd1', '#f2a541', '#d6457b', '#17a398', '#6c757d']

candado = threading.Lock()   # una escritura a la vez


# ---------- Base de datos ----------

def conectar():
    con = sqlite3.connect(BD, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    return con


def preparar_bd():
    BD.parent.mkdir(parents=True, exist_ok=True)
    with conectar() as con:
        con.executescript('''
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS personas (
                id     INTEGER PRIMARY KEY,
                nombre TEXT NOT NULL,
                color  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tareas (
                id         INTEGER PRIMARY KEY,
                titulo     TEXT NOT NULL,
                persona_id INTEGER REFERENCES personas(id) ON DELETE SET NULL,
                repeticion TEXT NOT NULL,
                creada     TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS hechas (
                tarea_id INTEGER NOT NULL REFERENCES tareas(id) ON DELETE CASCADE,
                periodo  TEXT NOT NULL,
                hecha_en TEXT NOT NULL,
                PRIMARY KEY (tarea_id, periodo)
            );
            CREATE TABLE IF NOT EXISTS meta (
                clave TEXT PRIMARY KEY,
                valor INTEGER NOT NULL
            );
            INSERT OR IGNORE INTO meta (clave, valor) VALUES ('version', 0);
        ''')


def ahora():
    return datetime.now().isoformat(timespec='seconds')


def periodos(hoy=None):
    hoy = hoy or date.today()
    anio, semana, _ = hoy.isocalendar()
    return {'una': 'una', 'diaria': hoy.isoformat(), 'semanal': f'{anio}-W{semana:02d}'}


def subir_version(con):
    con.execute("UPDATE meta SET valor = valor + 1 WHERE clave = 'version'")


def leer_tablero(con):
    hoy = date.today()
    p = periodos(hoy)
    version = con.execute("SELECT valor FROM meta WHERE clave = 'version'").fetchone()[0]
    personas = [dict(f) for f in con.execute('SELECT id, nombre, color FROM personas ORDER BY id')]
    filas = con.execute('''
        SELECT t.id, t.titulo, t.persona_id, t.repeticion, h.hecha_en
        FROM tareas t
        LEFT JOIN hechas h ON h.tarea_id = t.id AND h.periodo = CASE t.repeticion
            WHEN 'una' THEN :una WHEN 'diaria' THEN :diaria ELSE :semanal END
        ORDER BY t.id
    ''', p).fetchall()

    tareas = []
    for f in filas:
        t = dict(f, hecha=f['hecha_en'] is not None)
        # Las de una vez ya hechas en días anteriores no se muestran más
        if t['repeticion'] == 'una' and t['hecha'] and not t['hecha_en'].startswith(p['diaria']):
            continue
        tareas.append(t)
    return {'version': version, 'hoy': p['diaria'], 'semana': p['semanal'],
            'personas': personas, 'tareas': tareas}


def limpiar_texto(valor, maximo):
    if not isinstance(valor, str):
        return ''
    return re.sub(r'\s+', ' ', valor).strip()[:maximo]


def validar_persona(con, persona_id):
    if persona_id is None:
        return None
    if not isinstance(persona_id, int) or isinstance(persona_id, bool):
        raise ValueError('Persona inválida')
    if not con.execute('SELECT 1 FROM personas WHERE id = ?', (persona_id,)).fetchone():
        raise ValueError('Esa persona ya no existe')
    return persona_id


# ---------- Operaciones ----------

def crear_persona(datos):
    nombre = limpiar_texto(datos.get('nombre'), MAX_NOMBRE)
    if not nombre:
        raise ValueError('Falta el nombre')
    with candado, conectar() as con:
        usados = {f['color'] for f in con.execute('SELECT color FROM personas')}
        libres = [c for c in COLORES if c not in usados]
        cuantas = con.execute('SELECT count(*) FROM personas').fetchone()[0]
        color = libres[0] if libres else COLORES[cuantas % len(COLORES)]
        con.execute('INSERT INTO personas (nombre, color) VALUES (?, ?)', (nombre, color))
        subir_version(con)
        return leer_tablero(con)


def cambiar_persona(persona_id, datos):
    nombre = limpiar_texto(datos.get('nombre'), MAX_NOMBRE)
    if not nombre:
        raise ValueError('Falta el nombre')
    with candado, conectar() as con:
        if con.execute('UPDATE personas SET nombre = ? WHERE id = ?', (nombre, persona_id)).rowcount:
            subir_version(con)
        return leer_tablero(con)


def borrar_persona(persona_id):
    with candado, conectar() as con:
        if con.execute('DELETE FROM personas WHERE id = ?', (persona_id,)).rowcount:
            subir_version(con)
        return leer_tablero(con)


def crear_tarea(datos):
    titulo = limpiar_texto(datos.get('titulo'), MAX_TITULO)
    repeticion = datos.get('repeticion', 'una')
    if not titulo:
        raise ValueError('Falta el nombre de la tarea')
    if repeticion not in REPETICIONES:
        raise ValueError('Repetición inválida')
    with candado, conectar() as con:
        persona_id = validar_persona(con, datos.get('persona_id'))
        con.execute('INSERT INTO tareas (titulo, persona_id, repeticion, creada) VALUES (?, ?, ?, ?)',
                    (titulo, persona_id, repeticion, ahora()))
        subir_version(con)
        return leer_tablero(con)


def cambiar_tarea(tarea_id, datos):
    with candado, conectar() as con:
        cambios, valores = [], []
        if 'titulo' in datos:
            titulo = limpiar_texto(datos['titulo'], MAX_TITULO)
            if not titulo:
                raise ValueError('El nombre no puede quedar vacío')
            cambios.append('titulo = ?')
            valores.append(titulo)
        if 'persona_id' in datos:
            cambios.append('persona_id = ?')
            valores.append(validar_persona(con, datos['persona_id']))
        if 'repeticion' in datos:
            if datos['repeticion'] not in REPETICIONES:
                raise ValueError('Repetición inválida')
            cambios.append('repeticion = ?')
            valores.append(datos['repeticion'])
        if not cambios:
            raise ValueError('Nada que cambiar')
        if con.execute(f'UPDATE tareas SET {", ".join(cambios)} WHERE id = ?', (*valores, tarea_id)).rowcount:
            subir_version(con)
        return leer_tablero(con)


def borrar_tarea(tarea_id):
    with candado, conectar() as con:
        if con.execute('DELETE FROM tareas WHERE id = ?', (tarea_id,)).rowcount:
            subir_version(con)
        return leer_tablero(con)


def marcar(tarea_id, datos):
    hecha = bool(datos.get('hecha'))
    with candado, conectar() as con:
        fila = con.execute('SELECT repeticion FROM tareas WHERE id = ?', (tarea_id,)).fetchone()
        if not fila:
            raise ValueError('Esa tarea ya no existe')
        periodo = periodos()[fila['repeticion']]
        if hecha:
            con.execute('INSERT OR IGNORE INTO hechas (tarea_id, periodo, hecha_en) VALUES (?, ?, ?)',
                        (tarea_id, periodo, ahora()))
        else:
            con.execute('DELETE FROM hechas WHERE tarea_id = ? AND periodo = ?', (tarea_id, periodo))
        subir_version(con)
        return leer_tablero(con)


# ---------- HTTP ----------

RUTAS = [
    ('GET',    r'/api/tablero',              lambda m, d: leer_tablero(conectar())),
    ('POST',   r'/api/personas',             lambda m, d: crear_persona(d)),
    ('PATCH',  r'/api/personas/(\d+)',       lambda m, d: cambiar_persona(int(m[1]), d)),
    ('DELETE', r'/api/personas/(\d+)',       lambda m, d: borrar_persona(int(m[1]))),
    ('POST',   r'/api/tareas',               lambda m, d: crear_tarea(d)),
    ('PATCH',  r'/api/tareas/(\d+)',         lambda m, d: cambiar_tarea(int(m[1]), d)),
    ('DELETE', r'/api/tareas/(\d+)',         lambda m, d: borrar_tarea(int(m[1]))),
    ('POST',   r'/api/tareas/(\d+)/hecha',   lambda m, d: marcar(int(m[1]), d)),
]


class Manejador(BaseHTTPRequestHandler):
    server_version = 'Tareas'

    def log_message(self, formato, *args):
        pass  # sin ruido en el journal por cada consulta

    def responder(self, codigo, datos):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode('utf-8')
        self.send_response(codigo)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def leer_json(self):
        largo = int(self.headers.get('Content-Length') or 0)
        if largo > MAX_CUERPO:
            raise ValueError('Pedido demasiado grande')
        if not largo:
            return {}
        try:
            datos = json.loads(self.rfile.read(largo))
        except json.JSONDecodeError:
            raise ValueError('JSON inválido') from None
        if not isinstance(datos, dict):
            raise ValueError('Se esperaba un objeto JSON')
        return datos

    def atender(self):
        ruta = self.path.split('?')[0]
        for metodo, patron, accion in RUTAS:
            m = re.fullmatch(patron, ruta)
            if metodo == self.command and m:
                break
        else:
            self.responder(404, {'error': 'No existe'})
            return
        try:
            datos = self.leer_json() if self.command in ('POST', 'PATCH') else {}
            self.responder(200, accion(m, datos))
        except ValueError as e:
            self.responder(400, {'error': str(e)})
        except Exception as e:  # noqa: BLE001 - que el servicio no se caiga por un pedido
            print('Error:', repr(e), flush=True)
            self.responder(500, {'error': 'Error interno'})

    do_GET = do_POST = do_PATCH = do_DELETE = atender


def main():
    preparar_bd()
    servidor = ThreadingHTTPServer((HOST, PUERTO), Manejador)
    print(f'Tareas en http://{HOST}:{PUERTO} (BD: {BD})', flush=True)
    servidor.serve_forever()


if __name__ == '__main__':
    main()
