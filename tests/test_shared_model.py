"""Two independently authenticated clients use the server credential, never receive it."""
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as s


class SharedModelTests(unittest.TestCase):
    def test_two_clients_share_config_without_exposing_or_replacing_key(self):
        key = 'fictional-server-credential-for-test'
        password = 'fictional-access-password'
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=2) as executor:
            data = Path(folder)
            with patch.object(s, 'DB', data / 'test.sqlite3'), patch.object(s, 'DATA', data), \
                 patch.object(s, 'ORIGIN', 'https://workspace.example'), patch.object(s, 'PASSWORD', password), \
                 patch.object(s, 'EXECUTOR', executor), patch.dict(s.CONFIG, api_key=key, model='test-deepseek'):
                s.initialize()
                http = s.ThreadingHTTPServer(('127.0.0.1', 0), s.Handler)
                thread = threading.Thread(target=http.serve_forever, daemon=True)
                thread.start()
                url = 'http://127.0.0.1:' + str(http.server_port)
                clients = [urllib.request.build_opener(urllib.request.ProxyHandler({})) for _ in range(2)]

                def request(client, path, payload=None, cookie=None):
                    headers = {'Host': 'workspace.example', 'Origin': 'https://workspace.example',
                               'X-Workspace-Request': '1', 'Content-Type': 'application/json'}
                    if cookie:
                        headers['Cookie'] = cookie
                    req = urllib.request.Request(url + path, headers=headers,
                        data=None if payload is None else json.dumps(payload).encode())
                    with client.open(req, timeout=4) as response:
                        body = response.read().decode()
                        self.assertNotIn(key, body)
                        return json.loads(body), response.headers.get('Set-Cookie')

                try:
                    with self.assertRaises(urllib.error.HTTPError) as denied:
                        request(clients[0], '/api/status')
                    self.assertEqual(denied.exception.code, 401)
                    cookies = [request(client, '/api/login', {'password': password})[1].split(';')[0]
                               for client in clients]
                    self.assertNotEqual(cookies[0], cookies[1])
                    for client, cookie in zip(clients, cookies):
                        status, _ = request(client, '/api/status', cookie=cookie)
                        self.assertTrue(status['ready'])
                        self.assertFalse(status['local_config'])
                        self.assertEqual(status['connection_scope'], 'server')
                        with self.assertRaises(urllib.error.HTTPError) as denied:
                            request(client, '/api/config', {'api_key': 'replacement', 'model': 'other'}, cookie)
                        self.assertEqual(denied.exception.code, 403)
                    with patch.object(s.ai_gateway, 'generate', return_value={'answer': '服务器模型测试回复', 'proposal': None}) as model:
                        for index, (client, cookie) in enumerate(zip(clients, cookies)):
                            project, _ = request(client, '/api/projects', {'name': f'独立客户端 {index}', 'mode': 'live'}, cookie)
                            request(client, f"/api/projects/{project['id']}/jobs/chat",
                                    {'revision': project['revision'], 'message': '请分析业务', 'document': 'material'}, cookie)
                            deadline = time.monotonic() + 5
                            while True:
                                jobs, _ = request(client, f"/api/projects/{project['id']}/jobs", cookie=cookie)
                                if jobs[0]['status'] not in ('queued', 'running'):
                                    self.assertEqual(jobs[0]['status'], 'done', jobs[0])
                                    break
                                if time.monotonic() > deadline:
                                    self.fail('Shared model job did not finish')
                                time.sleep(.05)
                        self.assertEqual(model.call_count, 2)
                        for call in model.call_args_list:
                            self.assertEqual(call.args[0], 'chat')
                            self.assertEqual(call.args[2]['api_key'], key)
                            self.assertEqual(call.args[2]['model'], 'test-deepseek')
                        self.assertEqual(s.CONFIG['api_key'], key)
                finally:
                    http.shutdown()
                    http.server_close()
                    thread.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
