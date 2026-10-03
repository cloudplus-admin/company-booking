import os
import tempfile
import threading
import unittest
import json
import urllib.request
from http.server import ThreadingHTTPServer

import server


class BookingLogicTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        self.conn = server.connect(self.path)

    def tearDown(self):
        self.conn.close()
        os.remove(self.path)

    def test_add_and_list(self):
        server.add_company(self.conn, 'Ромашка', '1234')
        rows = server.list_companies(self.conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'Ромашка')
        self.assertIsNone(rows[0]['booked_by'])

    def test_empty_name_rejected(self):
        with self.assertRaises(ValueError):
            server.add_company(self.conn, '   ')

    def test_book_then_second_manager_blocked(self):
        cid = server.add_company(self.conn, 'Альфа')
        server.book(self.conn, cid, 'Анна', '2026-10-03 10:00')
        with self.assertRaises(PermissionError):
            server.book(self.conn, cid, 'Борис', '2026-10-03 10:01')
        self.assertEqual(server.list_companies(self.conn)[0]['booked_by'], 'Анна')

    def test_only_owner_can_release(self):
        cid = server.add_company(self.conn, 'Бета')
        server.book(self.conn, cid, 'Анна', '2026-10-03 10:00')
        with self.assertRaises(PermissionError):
            server.release(self.conn, cid, 'Борис')
        server.release(self.conn, cid, 'Анна')
        self.assertIsNone(server.list_companies(self.conn)[0]['booked_by'])

    def test_book_unknown_company(self):
        with self.assertRaises(LookupError):
            server.book(self.conn, 999, 'Анна', '2026-10-03 10:00')

    def test_book_requires_manager(self):
        cid = server.add_company(self.conn, 'Гамма')
        with self.assertRaises(ValueError):
            server.book(self.conn, cid, '  ', '2026-10-03 10:00')


class HttpApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls.path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        server.Handler.db_path = cls.path
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        os.remove(cls.path)

    def call(self, method, url, body=None):
        data = json.dumps(body).encode('utf-8') if body is not None else None
        req = urllib.request.Request('http://127.0.0.1:%s%s' % (self.port, url), data=data, method=method,
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, json.loads(res.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode('utf-8'))

    def test_full_flow(self):
        status, body = self.call('POST', '/api/companies', {'name': 'Дельта', 'inn': '777'})
        self.assertEqual(status, 201)
        cid = body['id']
        status, _ = self.call('POST', '/api/companies/%d/book' % cid, {'manager': 'Анна'})
        self.assertEqual(status, 200)
        status, body = self.call('POST', '/api/companies/%d/book' % cid, {'manager': 'Борис'})
        self.assertEqual(status, 409)
        self.assertIn('Анна', body['error'])
        status, body = self.call('GET', '/api/companies')
        self.assertEqual(body[0]['booked_by'], 'Анна')
        status, _ = self.call('POST', '/api/companies/%d/release' % cid, {'manager': 'Анна'})
        self.assertEqual(status, 200)
        status, body = self.call('GET', '/api/companies')
        self.assertIsNone(body[0]['booked_by'])

    def test_unknown_route(self):
        status, _ = self.call('GET', '/nope')
        self.assertEqual(status, 404)


if __name__ == '__main__':
    unittest.main()
