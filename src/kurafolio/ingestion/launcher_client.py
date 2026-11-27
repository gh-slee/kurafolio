"""The worker's authenticated client for the trusted launcher."""
from __future__ import annotations

import http.client
import json
import ssl

from .codec import decode, encode, validate
from .contracts import IngestionError
from .runner_client import PeerTLS, pack_input


class HttpLauncherClient:
    """One mTLS peer; raw and result bytes stay in memory."""

    def __init__(self, config, *, timeout=30):
        self._tls = config.launcher_tls
        self._host = config.launcher_host
        self._port = config.launcher_port
        self._timeout = timeout

    def start(self, metadata, context, raw):
        body = pack_input(metadata, context, raw, schema='LaunchStart')
        status = self._post('/internal/v1/jobs', body, 'application/octet-stream')
        return validate(status, 'LaunchStatus')

    def control(self, request):
        body = encode(validate(request, 'LaunchControl'))
        status = self._post('/internal/v1/control', body, 'application/json', frame=True)
        if type(status) is tuple:
            return status
        return status, None

    def _post(self, path, body, content_type, frame=False):
        connection = None
        try:
            context = self._tls.context()
            connection = http.client.HTTPSConnection(self._host, self._port, timeout=self._timeout,
                                                     context=context)
            connection.connect()
            self._tls.verify_peer(connection.sock)
            connection.request('POST', path, body=body,
                               headers={'Content-Type': content_type,
                                        'Content-Length': str(len(body)),
                                        'Connection': 'close'})
            response = connection.getresponse()
            payload = response.read(4 + 16 * 1024 * 1024 + 4 * 1024 * 1024 + 1)
            kind = response.getheader('Content-Type', '')
            if response.status != 200:
                if 200 < response.status < 300:
                    raise IngestionError('import_runner_unavailable')
                try:
                    code = json.loads(payload).get('code')
                except (ValueError, UnicodeError, AttributeError):
                    code = None
                if type(code) is not str:
                    code = 'import_runner_unavailable'
                raise IngestionError(code)
            if frame and kind.startswith('application/octet-stream'):
                return None, payload
            return decode(payload, 'LaunchStatus')
        except IngestionError:
            raise
        except (OSError, http.client.HTTPException, ssl.SSLError, ValueError):
            raise IngestionError('import_runner_unavailable') from None
        finally:
            if connection is not None:
                connection.close()
