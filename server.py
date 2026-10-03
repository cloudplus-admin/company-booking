# Простой сервер для брони компаний за менеджерами. Без внешних зависимостей.
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get('BOOKING_DB', os.path.join(BASE, 'booking.db'))
PORT = int(os.environ.get('PORT', '48610'))
HOST = os.environ.get('HOST', '127.0.0.1')


def connect(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        'CREATE TABLE IF NOT EXISTS companies ('
        ' id INTEGER PRIMARY KEY AUTOINCREMENT,'
        ' name TEXT NOT NULL,'
        " inn TEXT NOT NULL DEFAULT '',"
        ' booked_by TEXT,'
        ' booked_at TEXT)'
    )
    conn.commit()
    return conn


def list_companies(conn):
    rows = conn.execute('SELECT id, name, inn, booked_by, booked_at FROM companies ORDER BY name').fetchall()
    return [dict(r) for r in rows]


def add_company(conn, name, inn=''):
    name = (name or '').strip()
    if not name:
        raise ValueError('Укажите название компании')
    cur = conn.execute('INSERT INTO companies (name, inn) VALUES (?, ?)', (name, (inn or '').strip()))
    conn.commit()
    return cur.lastrowid


def book(conn, company_id, manager, now):
    manager = (manager or '').strip()
    if not manager:
        raise ValueError('Укажите имя менеджера')
    # Атомарная бронь: занимаем, только если компания свободна.
    cur = conn.execute(
        'UPDATE companies SET booked_by = ?, booked_at = ? WHERE id = ? AND booked_by IS NULL',
        (manager, now, company_id),
    )
    conn.commit()
    if cur.rowcount == 0:
        row = conn.execute('SELECT booked_by FROM companies WHERE id = ?', (company_id,)).fetchone()
        if row is None:
            raise LookupError('Компания не найдена')
        raise PermissionError('Уже в работе у: ' + row['booked_by'])
    return True


def release(conn, company_id, manager):
    manager = (manager or '').strip()
    row = conn.execute('SELECT booked_by FROM companies WHERE id = ?', (company_id,)).fetchone()
    if row is None:
        raise LookupError('Компания не найдена')
    if row['booked_by'] is None:
        return True
    if row['booked_by'] != manager:
        raise PermissionError('Освободить может только ' + row['booked_by'])
    conn.execute('UPDATE companies SET booked_by = NULL, booked_at = NULL WHERE id = ?', (company_id,))
    conn.commit()
    return True


class Handler(BaseHTTPRequestHandler):
    db_path = DB_PATH

    def _send(self, status, payload=None, content_type='application/json; charset=utf-8', raw=None):
        body = raw if raw is not None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get('Content-Length') or 0)
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode('utf-8'))

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            with open(os.path.join(BASE, 'index.html'), 'rb') as f:
                return self._send(200, raw=f.read(), content_type='text/html; charset=utf-8')
        if self.path == '/api/companies':
            conn = connect(self.db_path)
            try:
                return self._send(200, list_companies(conn))
            finally:
                conn.close()
        self._send(404, {'error': 'не найдено'})

    def do_POST(self):
        from datetime import datetime
        conn = connect(self.db_path)
        try:
            data = self._read_json()
            parts = self.path.strip('/').split('/')
            if self.path == '/api/companies':
                new_id = add_company(conn, data.get('name'), data.get('inn'))
                return self._send(201, {'id': new_id})
            if len(parts) == 4 and parts[:2] == ['api', 'companies'] and parts[3] in ('book', 'release'):
                company_id = int(parts[2])
                if parts[3] == 'book':
                    book(conn, company_id, data.get('manager'), datetime.now().strftime('%Y-%m-%d %H:%M'))
                else:
                    release(conn, company_id, data.get('manager'))
                return self._send(200, {'ok': True})
            self._send(404, {'error': 'не найдено'})
        except ValueError as e:
            self._send(400, {'error': str(e)})
        except PermissionError as e:
            self._send(409, {'error': str(e)})
        except LookupError as e:
            self._send(404, {'error': str(e)})
        finally:
            conn.close()


if __name__ == '__main__':
    connect().close()
    print('Слушаю http://%s:%s' % (HOST, PORT), flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
