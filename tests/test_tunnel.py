import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'box/resi-tunnel.sh'


class TunnelTests(unittest.TestCase):
    def test_supervisor_singleton_refresh_cache_and_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / 'ssh'
            fake.write_text('''#!/usr/bin/env bash
if [[ " $* " == *" -N "* ]]; then
  echo "$*" >> "$TEST_ROOT/connections"
  trap 'exit 0' TERM
  while true; do sleep 0.2; done
else
  [[ -f $TEST_ROOT/fail ]] && exit 1
  cat "$TEST_ROOT/discovery"
fi
''')
            fake.chmod(0o755)
            ports = root / 'discovery'
            ports.write_text('18082\n18090\n')
            env = dict(os.environ, PATH=directory + ':' + os.environ['PATH'], TEST_ROOT=directory,
                       RESI_TUNNEL_STATE=str(root / 'state'), RESI_TUNNEL_INTERVAL='0.2')
            def call(*args):
                return subprocess.run([str(SCRIPT), *args], env=env, capture_output=True, text=True)
            def wait_for(predicate):
                for _ in range(100):
                    if predicate():
                        return
                    time.sleep(0.05)
                self.fail('timed out waiting for supervisor')
            self.assertIn('127.0.0.1:18090:127.0.0.1:18090', call('dry-run').stdout)
            try:
                for _ in range(4):
                    self.assertEqual(call('ensure').returncode, 0)
                connections = root / 'connections'
                wait_for(lambda: connections.exists())
                time.sleep(0.5)
                self.assertEqual(len(connections.read_text().splitlines()), 1)
                ports.write_text('18090\n')
                wait_for(lambda: len(connections.read_text().splitlines()) == 2)
                self.assertNotIn('18082', connections.read_text().splitlines()[-1])
                (root / 'fail').touch()
                time.sleep(0.6)
                self.assertEqual(len(connections.read_text().splitlines()), 2)
                self.assertIn('using cached ports', (root / 'state/log').read_text())
                self.assertEqual(call('status').returncode, 0)
            finally:
                call('stop')
                wait_for(lambda: not (root / 'state/pid').exists())

    def test_explicit_ports_dry_run(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([str(SCRIPT), 'dry-run'], env=dict(os.environ, RESI_TUNNEL_STATE=directory, RESI_TUNNEL_PORTS='18090,18082'), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn('127.0.0.1:18090:127.0.0.1:18090', result.stdout)
            self.assertIn('127.0.0.1:18082:127.0.0.1:18082', result.stdout)

    def test_invalid_port_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([str(SCRIPT), 'dry-run'], env=dict(os.environ, RESI_TUNNEL_STATE=directory, RESI_TUNNEL_PORTS='18090,invalid'), capture_output=True)
            self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
