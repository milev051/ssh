"""Provera trajnog čuvanja sa privremenim podacima i SSH ključevima."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
from urllib.request import Request, urlopen

spec = importlib.util.spec_from_file_location('ssh_ui', Path(__file__).parents[1] / 'server.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(app, 'APP_DATA_DIR', self.root / 'data'),
                        patch.object(app, 'APP_SERVER_DIR', self.root / 'data' / 'serveri'),
                        patch.object(Path, 'home', return_value=self.root)]
        for p in self.patches:
            p.start()
        self.state = {'hosts': [{'id': 'test', 'host': '203.0.113.10', 'port': '22',
                       'panelUrl': 'panel.example.com/login', 'address': 'example.com',
                       'label': 'produkcija', 'accounts': []}], 'users': [], 'panelUrls': {}}

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def serve(self):
        server = app.ThreadingHTTPServer((app.HOST, 0), app.Handler)
        app.PORT = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server, f'http://{app.HOST}:{app.PORT}'

    def test_restart_on_another_port_and_user_without_key(self):
        first, url = self.serve()
        request = Request(url + '/api/save-state', data=json.dumps(self.state).encode(),
                          headers={'Content-Type': 'application/json', 'Origin': url})
        with urlopen(request) as response:
            self.assertEqual(response.status, 200)
        first.shutdown()
        _, new_url = self.serve()
        self.assertNotEqual(url, new_url)
        with urlopen(new_url + '/api/state') as response:
            loaded = json.load(response)
        self.assertEqual(loaded['hosts'][0]['accounts'], [])
        self.assertEqual(loaded['hosts'][0]['panelUrl'], 'https://panel.example.com/login')
        self.state['hosts'][0]['accounts'] = [{'id': 'account', 'user': 'deploy', 'key': 'none'}]
        app.save_local_state(self.state)
        account = app.load_local_state()['hosts'][0]['accounts'][0]
        self.assertEqual(account['user'], 'deploy')
        self.assertEqual(account['key'], 'none')
        if os.name != 'nt':
            self.assertEqual((app.APP_DATA_DIR / 'podaci.json').stat().st_mode & 0o777, 0o600)

    def test_real_existing_key_is_loaded_without_regeneration(self):
        self.state['hosts'][0]['accounts'] = [{'id': 'account', 'user': 'deploy', 'key': 'active',
                                             'passphrase': 'test-value'}]
        key = app.identity_file_for('', 'deploy', '203.0.113.10', '22', 'local')
        key.parent.mkdir()
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)], check=True)
        original = key.read_bytes()
        app.save_local_state(self.state)
        with patch.object(app.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', '')):
            account = app.load_local_state()['hosts'][0]['accounts'][0]
        self.assertEqual(account['key'], 'inactive')
        self.assertEqual(account['publicKey'], Path(f'{key}.pub').read_text().strip())
        self.assertEqual(key.read_bytes(), original)
        self.assertNotIn('passphrase', (app.APP_DATA_DIR / 'podaci.json').read_text())
        with patch.object(app.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, account['publicKey'], '')):
            self.assertEqual(app.load_local_state()['hosts'][0]['accounts'][0]['key'], 'active')

    def test_failed_save_keeps_previous_data(self):
        app.save_local_state(self.state)
        before = (app.APP_DATA_DIR / 'podaci.json').read_bytes()
        self.state['hosts'][0]['accounts'] = [{'id': 'bad', 'user': '../../bad'}]
        with self.assertRaises(ValueError):
            app.save_local_state(self.state)
        self.assertEqual((app.APP_DATA_DIR / 'podaci.json').read_bytes(), before)
        with patch.object(app.os, 'replace', side_effect=OSError('test')):
            with self.assertRaises(OSError):
                app.save_local_state({'hosts': [], 'users': [], 'panelUrls': {}})
        self.assertEqual((app.APP_DATA_DIR / 'podaci.json').read_bytes(), before)
        self.assertEqual(list(app.APP_DATA_DIR.glob('.podaci-*')), [])

    def test_corrupt_state_is_reported_and_not_replaced(self):
        app.ensure_local_data_dir()
        path = app.APP_DATA_DIR / 'podaci.json'
        path.write_text('{')
        _, url = self.serve()
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError) as error:
            urlopen(url + '/api/state')
        self.assertEqual(error.exception.code, 500)
        error.exception.close()
        self.assertEqual(path.read_text(), '{')


class ShutdownTests(unittest.TestCase):
    def simulate(self, events, expected):
        now = [0]
        app.ACTIVE_TABS.clear()
        server = Mock()

        def tick(seconds):
            now[0] += seconds
            if now[0] > 40:
                self.fail('Server se nije ugasio na vreme.')
            if now[0] in events:
                app.ACTIVE_TABS.clear()
                app.ACTIVE_TABS.update({name: now[0] for name in events[now[0]]})

        with patch.object(app.time, 'monotonic', side_effect=lambda: now[0]), patch.object(app.time, 'sleep', side_effect=tick):
            app.shutdown_when_idle(server)
        server.shutdown.assert_called_once()
        self.assertEqual(now[0], expected)
        app.ACTIVE_TABS.clear()

    def test_last_tab_close_stops_server(self):
        self.simulate({1: ['a'], 2: []}, 7)

    def test_another_app_tab_keeps_server_alive(self):
        self.simulate({1: ['a', 'b'], 2: ['b'], 15: []}, 20)

    def test_refresh_does_not_stop_server(self):
        self.simulate({1: ['a'], 2: [], 4: ['a'], 12: []}, 17)

    def test_first_tab_has_time_to_open(self):
        self.simulate({}, 30)


if __name__ == '__main__':
    unittest.main()
