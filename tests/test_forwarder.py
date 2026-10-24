import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ForwarderTests(unittest.TestCase):
    def test_real_connect_no_ray_is_sanitized(self):
        with tempfile.TemporaryDirectory() as directory, socket.socket() as upstream:
            upstream.bind(('127.0.0.1', 0))
            upstream.listen(1)
            upstream.settimeout(5)
            upstream_port = upstream.getsockname()[1]
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                local_port = reservation.getsockname()[1]
            def reject():
                client, _ = upstream.accept()
                with client:
                    client.recv(16384)
                    client.sendall(b'HTTP/1.1 400 NO_RAY\r\nContent-Length: 0\r\n\r\n')
            thread = threading.Thread(target=reject, daemon=True)
            thread.start()
            root = Path(directory)
            (root / 'config.json').write_text(json.dumps(dict(port=local_port)))
            sentinel = 'test-secret-sentinel'
            (root / 'upstream.url').write_text(f'http://test:{sentinel}@127.0.0.1:{upstream_port}')
            with (root / 'log').open('w') as log:
                process = subprocess.Popen(['node', '--v8-pool-size=1', str(ROOT / 'lib/forwarder.mjs')], env=dict(os.environ, RESI_INSTANCE_DIR=directory, UV_THREADPOOL_SIZE='1'), stdout=log, stderr=log)
                try:
                    for _ in range(100):
                        try:
                            with socket.create_connection(('127.0.0.1', local_port), timeout=0.1):
                                break
                        except OSError:
                            time.sleep(0.05)
                    result = subprocess.run(['curl', '--silent', '--max-time', '5', '--noproxy', '', '--proxy', f'http://127.0.0.1:{local_port}', 'https://example.invalid'], capture_output=True)
                    self.assertNotEqual(result.returncode, 0)
                    thread.join(5)
                    failure = json.loads((root / 'failure.json').read_text())
                    self.assertIn('NO_RAY', failure['code'])
                finally:
                    process.terminate()
                    process.wait(timeout=5)
            self.assertNotIn(sentinel, (root / 'log').read_text())


if __name__ == '__main__':
    unittest.main()
