"""The worker's private mTLS handoff endpoint, framed by the r7 protocol."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging
import socket
import ssl
import threading
import time

from .codec import encode, validate
from .contracts import (ERROR_STATUS, IngestionError, MAX_CONTEXT, MAX_CONTROL, MAX_RAW)
from .runner_client import unpack_input

LOG = logging.getLogger('kurafolio.ingestion.handoff')
TOTAL_SECONDS = 30
IDLE_SECONDS = 5
MAX_BODY = 4 + MAX_CONTROL + MAX_CONTEXT + MAX_RAW
_REFUSED_HEADERS = ('Transfer-Encoding', 'Content-Encoding', 'Expect')


class HandoffServer:
    """One authenticated route: POST /internal/v1/handoffs."""

    def __init__(self, peer_tls, bind_address, bind_port, handler):
        self._peer_tls = peer_tls
        self._address = bind_address
        self._port = bind_port
        self._handler = handler
        self._httpd = None
        self._thread = None

    def start(self):
        if self._httpd is not None:
            raise RuntimeError('already started')
        server = _Server((self._address, self._port), _Handler)
        server.ssl_context = self._peer_tls.context(server=True)
        server.peer_tls = self._peer_tls
        server.handoff = self._handler
        server.daemon_threads = True
        server.handshake_slots = threading.BoundedSemaphore(16)
        self._httpd = server
        self._thread = threading.Thread(target=server.serve_forever, name='handoff-server', daemon=True)
        self._thread.start()
        return server.server_address

    def stop(self):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._thread.join(timeout=5)
            self._httpd = None
            self._thread = None


class _Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def process_request(self, request, client_address):
        if not self.handshake_slots.acquire(blocking=False):
            try:
                request.close()
            except OSError:
                pass
            return

        def handshake():
            try:
                request.settimeout(5)
                tls = self.ssl_context.wrap_socket(request, server_side=True)
                self.peer_tls.verify_peer(tls)
            except (ssl.SSLError, OSError, ValueError):
                try:
                    request.close()
                except OSError:
                    pass
                return
            try:
                self.finish_request(tls, client_address)
            finally:
                self.shutdown_request(tls)
                self.handshake_slots.release()
        threading.Thread(target=handshake, daemon=True).start()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'kurafolio-ingestion'
    sys_version = ''

    def log_message(self, format, *args):
        LOG.info('handoff method=%s path=%s status=%s', self.command, self.path, getattr(self, '_status', '-'))

    def log_error(self, format, *args):
        LOG.warning('handoff method=%s path=%s status=%s', self.command, self.path, getattr(self, '_status', '-'))

    def do_GET(self):
        self._refuse(404, 'not_found')

    def do_PUT(self):
        self._refuse(405, 'method_not_allowed')

    def do_DELETE(self):
        self._refuse(405, 'method_not_allowed')

    def do_HEAD(self):
        self._refuse(405, 'method_not_allowed')

    def do_POST(self):
        self.close_connection = True
        if self.path != '/internal/v1/handoffs':
            self._refuse(404, 'not_found')
            return
        try:
            body = self._body()
            metadata, context, raw = unpack_input(body, schema='Handoff')
            ack = self.server.handoff(metadata, context, raw)
            ack = validate(ack, 'HandoffAck')
        except IngestionError as error:
            self._refuse(ERROR_STATUS.get(error.code, 422), error.code)
            return
        except Exception as error:
            code = getattr(error, 'code', None)
            if type(code) is str and code in ERROR_STATUS:
                self._refuse(ERROR_STATUS[code], code)
            else:
                self._refuse(500, 'internal_error')
            return
        self._send(202, encode(ack), 'application/json')

    def _body(self):
        for name in _REFUSED_HEADERS:
            if self.headers.get_all(name):
                raise IngestionError('invalid_headers')
        lengths = self.headers.get_all('Content-Length') or []
        if len(lengths) != 1:
            raise IngestionError('length_required' if not lengths else 'invalid_length')
        text = lengths[0].strip()
        if not text.isdigit() or not 0 < int(text) <= MAX_BODY:
            raise IngestionError('import_limit')
        length = int(text)
        deadline = time.monotonic() + TOTAL_SECONDS
        body = bytearray()
        while len(body) < length:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise IngestionError('request_timeout')
            self.connection.settimeout(min(IDLE_SECONDS, remaining))
            try:
                chunk = self.rfile.read(min(65536, length - len(body)))
            except (socket.timeout, TimeoutError):
                raise IngestionError('request_timeout') from None
            if not chunk:
                raise IngestionError('invalid_length')
            body.extend(chunk)
        return bytes(body)

    def _refuse(self, status, code):
        self._send(status, encode({'code': code}), 'application/json')

    def _send(self, status, body, content_type):
        self._status = status
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)
