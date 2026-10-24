import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

loader = importlib.machinery.SourceFileLoader('proxy', str(Path(__file__).resolve().parents[1] / 'bin/proxy'))
spec = importlib.util.spec_from_loader(loader.name, loader)
proxy = importlib.util.module_from_spec(spec)
loader.exec_module(proxy)


class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name)
        self.patch = patch.object(proxy, 'CONFIG', self.config)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.c = dict(name='cn', port=18090, country='cn', state=None, city=None, sticky=True, ttl=120)

    def test_credentials_encoded_and_private_atomic_rotation(self):
        with patch.object(proxy, 'credentials', return_value=('test:user', 'pass@word;', 'http://example.invalid:823')):
            proxy.rotate(self.c)
            path = self.config / 'cn/upstream.url'
            first = path.read_text()
            proxy.rotate(self.c)
            self.assertNotEqual(first, path.read_text())
            url = urlsplit(first)
            self.assertIn('test:user__cr.cn;sessid.', unquote(url.username))
            self.assertEqual(unquote(url.password), 'pass@word;')
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_mainland_cn_excludes_hk(self):
        response = subprocess.CompletedProcess([], 0, json.dumps(dict(ip='192.0.2.1', country='HK', region='Hong Kong', city='Hong Kong')) + '\n200', '')
        with patch.object(proxy.subprocess, 'run', return_value=response):
            self.assertEqual(proxy.probe(self.c)['result'], 'MISMATCH')

    def test_no_ray_surfaces_without_raw_upstream_error(self):
        directory = self.config / 'cn'
        directory.mkdir()
        (directory / 'failure.json').write_text(json.dumps(dict(time=proxy.time.time(), code='NO_RAY: no IP available for requested geo')))
        with patch.object(proxy.subprocess, 'run', return_value=subprocess.CompletedProcess([], 56, '', 'secret error')):
            result = proxy.probe(self.c)
            self.assertEqual(result['result'], 'ERROR')
            self.assertIn('NO_RAY', result['error'])
            self.assertNotIn('secret', str(result))

    def test_down_stops_units_and_retains_config(self):
        path = self.config / 'cn/config.json'
        path.parent.mkdir()
        path.write_text(json.dumps(self.c))
        with patch.object(proxy, 'systemctl') as systemctl, patch('sys.argv', ['proxy', 'down', 'cn']):
            self.assertEqual(proxy.main(), 0)
            self.assertTrue(path.exists())
            self.assertEqual(systemctl.call_args_list[0].args, ('disable', '--now', 'resi-proxy-watchdog@cn.timer'))
            self.assertEqual(systemctl.call_args_list[-1].args, ('disable', '--now', 'resi-proxy@cn.service'))

    def test_watchdog_bounded_retries(self):
        with patch.object(proxy, 'active', return_value=True), patch.object(proxy, 'probe', return_value=dict(result='MISMATCH', country='HK')), patch.object(proxy, 'rotate') as rotate, patch.object(proxy.time, 'sleep'):
            self.assertEqual(proxy.watchdog(self.c, attempts=3), 1)
            self.assertEqual(rotate.call_count, 2)

    def test_list_ports_only_active_and_targeting_cost(self):
        configs = [self.c, dict(self.c, name='jp', country='jp', port=18082, city='tokyo')]
        with patch.object(proxy, 'instances', return_value=configs), patch.object(proxy, 'active', side_effect=lambda name: name == 'cn'), patch('sys.argv', ['proxy', 'list', '--ports']), patch('builtins.print') as out:
            self.assertEqual(proxy.main(), 0)
            out.assert_called_once_with(18090)
        with patch.object(proxy, 'instances', return_value=configs), patch.object(proxy, 'active', return_value=False), patch('sys.argv', ['proxy', 'list', '--json']), patch('builtins.print') as out:
            proxy.main()
            self.assertEqual(json.loads(out.call_args.args[0])[1]['targeting_cost'], '2x')


if __name__ == '__main__':
    unittest.main()
