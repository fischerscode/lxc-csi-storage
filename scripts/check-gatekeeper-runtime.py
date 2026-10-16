#!/usr/bin/env python3
"""Exercise a real gatekeeper process with ephemeral mTLS and a fake CSI backend.

Run inside the isolated build rootfs; requires build-only py3-h2 and openssl.
No storage, consumer configuration or persistent credentials are used.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time

from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.events import DataReceived, RequestReceived, ResponseReceived, StreamEnded, TrailersReceived


def framed(data):
    return b'\0' + len(data).to_bytes(4, 'big') + data


class Backend:
    def __init__(self, path):
        self.calls = []
        self.lock = threading.Lock()
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.bind(str(path))
        self.socket.listen()
        threading.Thread(target=self.accept, daemon=True).start()

    def accept(self):
        while True:
            try:
                connection, _ = self.socket.accept()
            except OSError:
                return
            threading.Thread(target=self.serve, args=(connection,), daemon=True).start()

    def serve(self, connection):
        requests = {}
        protocol = H2Connection(H2Configuration(client_side=False, header_encoding='utf-8'))
        protocol.initiate_connection()
        with connection:
            connection.sendall(protocol.data_to_send())
            while data := connection.recv(65536):
                for event in protocol.receive_data(data):
                    if isinstance(event, RequestReceived):
                        requests[event.stream_id] = [dict(event.headers), bytearray()]
                    elif isinstance(event, DataReceived):
                        requests[event.stream_id][1].extend(event.data)
                        protocol.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                    elif isinstance(event, StreamEnded):
                        headers, request = requests.pop(event.stream_id)
                        with self.lock:
                            self.calls.append(headers)
                        assert 'x-runtime-secret' not in headers
                        method = headers[':path'].rsplit('/', 1)[-1]
                        response = b''
                        if method == 'GetPluginInfo':
                            name = b'org.democratic-csi'
                            response = b'\x0a' + bytes([len(name)]) + name
                        status = '14' if b'pvc-error' in request else '0'
                        protocol.send_headers(event.stream_id, [(':status', '200'),
                                              ('content-type', 'application/grpc')])
                        if status == '0':
                            protocol.send_data(event.stream_id, framed(response))
                        protocol.send_headers(event.stream_id, [('grpc-status', status),
                                              ('grpc-message', 'SECRET_BACKEND' if status != '0' else '')],
                                              end_stream=True)
                connection.sendall(protocol.data_to_send())


class Client:
    def __init__(self, directory, port, identity='allowed', hostname='localhost', ca='ca'):
        context = ssl.create_default_context(cafile=str(directory / f'{ca}.pem'))
        context.set_alpn_protocols(['h2'])
        if identity:
            context.load_cert_chain(directory / f'{identity}.pem', directory / f'{identity}.key')
        self.socket = context.wrap_socket(socket.create_connection(('127.0.0.1', port), timeout=5),
                                          server_hostname=hostname)
        assert self.socket.selected_alpn_protocol() == 'h2'
        self.protocol = H2Connection(H2Configuration(header_encoding='utf-8'))
        self.protocol.initiate_connection()
        self.socket.sendall(self.protocol.data_to_send())

    def close(self):
        self.socket.close()

    def call(self, method='Probe', request=b'', service='Identity'):
        stream = self.protocol.get_next_available_stream_id()
        self.protocol.send_headers(stream, [(':method', 'POST'), (':scheme', 'https'),
            (':authority', 'localhost'), (':path', f'/csi.v1.{service}/{method}'),
            ('content-type', 'application/grpc'), ('te', 'trailers'),
            ('x-runtime-secret', 'do-not-forward')])
        self.protocol.send_data(stream, framed(request), end_stream=True)
        self.socket.sendall(self.protocol.data_to_send())
        response = bytearray()
        trailers = {}
        while data := self.socket.recv(65536):
            ended = False
            for event in self.protocol.receive_data(data):
                if getattr(event, 'stream_id', 0):
                    assert event.stream_id == stream
                if isinstance(event, DataReceived):
                    response.extend(event.data)
                    self.protocol.acknowledge_received_data(event.flow_controlled_length, stream)
                elif isinstance(event, (TrailersReceived, ResponseReceived)):
                    trailers.update(event.headers)
                elif isinstance(event, StreamEnded):
                    ended = True
            self.socket.sendall(self.protocol.data_to_send())
            if ended:
                return int(trailers['grpc-status']), bytes(response), trailers
        raise ConnectionError('TLS/gRPC connection closed before response')


def certificates(directory):
    def openssl(*args):
        subprocess.run(['openssl', *args], cwd=directory, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'ca.key',
            '-out', 'ca.pem', '-days', '1', '-subj', '/CN=Ephemeral runtime test CA',
            '-addext', 'basicConstraints=critical,CA:TRUE',
            '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
    for name in ('server', 'allowed', 'denied'):
        openssl('req', '-newkey', 'rsa:2048', '-nodes', '-keyout', f'{name}.key',
                '-out', f'{name}.csr', '-subj', f'/CN={name}')
        (directory / f'{name}.ext').write_text('subjectAltName=DNS:localhost\n'
            'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n'
            'extendedKeyUsage=' + ('serverAuth' if name == 'server' else 'clientAuth') + '\n')
        openssl('x509', '-req', '-in', f'{name}.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key',
                '-CAcreateserial', '-out', f'{name}.pem', '-days', '1', '-extfile', f'{name}.ext')
    openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'untrusted.key',
            '-out', 'untrusted.pem', '-days', '1', '-subj', '/CN=Untrusted runtime test')


def check(binary, profile):
    result = subprocess.run([binary], capture_output=True, timeout=10)
    assert result.returncode == 64 and b'Usage: csi-gatekeeper' in result.stderr
    with tempfile.TemporaryDirectory(prefix='gatekeeper-runtime-') as temporary:
        directory = Path(temporary)
        certificates(directory)
        backend = Backend(directory / 'backend.sock')
        with socket.socket() as port_reservation:
            port_reservation.bind(('127.0.0.1', 0))
            port = port_reservation.getsockname()[1]
        config = {
            'listenAddress': '127.0.0.1', 'port': port,
            'backendSocket': str(directory / 'backend.sock'),
            'certificate': str(directory / 'server.pem'), 'privateKey': str(directory / 'server.key'),
            'clientCa': str(directory / 'ca.pem'),
            'clientSha256': hashlib.sha256(ssl.PEM_cert_to_DER_cert(
                (directory / 'allowed.pem').read_text())).hexdigest(),
            'profile': 'democratic-csi-1.9.3-' + profile, 'volumeParent': 'test/volumes',
            'snapshotParent': 'test/snapshots', 'maxBytes': 1073741824,
            'methods': ['GetPluginInfo', 'Probe', 'DeleteVolume'], 'parameters': {},
            'context': {'node_attach_driver': 'nfs', 'server': '192.0.2.1',
                        'share': '/test/{id}', 'provisioner_driver': 'zfs-generic-nfs'},
        }
        if profile == 'iscsi':
            config['context'] = {'node_attach_driver': 'iscsi', 'portal': '192.0.2.1:3260',
                'portals': '', 'interface': '', 'iqn': 'iqn.2026-01.example:runtime:{id}',
                'lun': '0', 'provisioner_driver': 'zfs-generic-iscsi'}
        path = directory / 'config.json'
        path.write_text(json.dumps(config))
        for stop_signal in (signal.SIGTERM, signal.SIGINT):
            with (directory / 'process.log').open('w+') as log:
                process = subprocess.Popen([binary, str(path)], stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 10
                    while 'CSI gateway listening' not in (directory / 'process.log').read_text():
                        assert process.poll() is None, (directory / 'process.log').read_text()
                        assert time.monotonic() < deadline, 'startup timed out'
                        time.sleep(0.02)
                    client = Client(directory, port)
                    try:
                        status, response, _ = client.call('GetPluginInfo')
                        assert status == 0 and b'csi-gatekeeper-0.1.1' in response
                        for _ in range(1000):
                            assert client.call()[0] == 0
                        assert client.call('DeleteVolume', b'\x0a\x08pvc-test', 'Controller')[0] == 0
                        before = len(backend.calls)
                        assert client.call('DeleteVolume', b'\x0a\x03../', 'Controller')[0] != 0
                        assert client.call('GetCapacity', service='Controller')[0] == 12
                        assert len(backend.calls) == before
                        status, _, trailers = client.call('DeleteVolume', b'\x0a\x09pvc-error', 'Controller')
                        assert status == 14 and 'SECRET_BACKEND' not in str(trailers)
                    finally:
                        client.close()
                    before = len(backend.calls)
                    denied = Client(directory, port, 'denied')
                    try:
                        assert denied.call()[0] == 16
                    finally:
                        denied.close()
                    for kwargs in ({'identity': None}, {'identity': 'untrusted'},
                                   {'hostname': 'wrong.example'}, {'ca': 'untrusted'}):
                        failed = None
                        try:
                            failed = Client(directory, port, **kwargs)
                            failed.call()
                        except (ssl.SSLError, ConnectionError, OSError):
                            pass
                        else:
                            raise AssertionError('Invalid TLS peer accepted: ' + str(kwargs))
                        finally:
                            if failed:
                                failed.close()
                    assert len(backend.calls) == before

                    def parallel(_):
                        client = Client(directory, port)
                        try:
                            for _ in range(50):
                                assert client.call()[0] == 0
                        finally:
                            client.close()
                    with ThreadPoolExecutor(max_workers=8) as executor:
                        list(executor.map(parallel, range(8)))
                    process.send_signal(stop_signal)
                    assert process.wait(timeout=10) == 0
                    assert 'SECRET_BACKEND' not in (directory / 'process.log').read_text()
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
        backend.socket.close()
        bad = directory / 'bad.json'
        bad.write_text('{}')
        assert subprocess.run([binary, str(bad)], capture_output=True, timeout=10).returncode == 1
    print('Gatekeeper runtime passed (' + profile + '): mTLS, pinning, gRPC/Unix proxy, policy, errors, '
          '2800 repeated/concurrent probes, restart, SIGTERM/SIGINT, invalid config')


if __name__ == '__main__':
    for profile in ('nfs', 'iscsi'):
        check(sys.argv[1], profile)
