import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from opendesk.integrations.local_backends import HTTPBackend


class LocalBackendTests(unittest.TestCase):
    def test_external_urls_rejected(self):
        for url in ['https://api.example.com/v1', 'file:///tmp/x', 'http://127.0.0.1@external.example/v1', 'http://localhost/v1?x=1']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                HTTPBackend('test', url)

    def test_loopback_request_and_redirect_refusal(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                if self.path.startswith('/redirect'):
                    self.send_response(302)
                    self.send_header('Location', 'https://example.com/')
                    self.end_headers()
                    return
                body = json.dumps({'choices': [{'message': {'content': '{"answer":"local"}'}}]}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            messages = [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,eA=='}}]}]
            self.assertIn('local', HTTPBackend('fixture', base, vision=True)(messages))
            self.assertEqual(received[0]['messages'], messages)
            self.assertFalse(received[0]['stream'])
            with self.assertRaises(ValueError):
                HTTPBackend('fixture', base + '/redirect')(messages)
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_hybrid_observes_images_before_text_planning(self):
        from types import ModuleType
        from unittest.mock import Mock, patch
        from opendesk.integrations.local_backends import HybridMLXBackend
        core = ModuleType('mlx.core')
        core.clear_cache = Mock()
        package = ModuleType('mlx')
        package.core = core
        messages = [{'role': 'user', 'content': [
            {'type': 'text', 'text': 'Tool result'},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,eA=='}},
        ]}]
        with patch.dict('sys.modules', {'mlx': package, 'mlx.core': core}):
            with patch('opendesk.integrations.local_backends.MLXVisionBackend') as vision:
                with patch('opendesk.integrations.local_backends.MLXBackend') as text:
                    vision.return_value.return_value = 'Calculator visible'
                    text.return_value.return_value = '{"answer":"Calculator"}'
                    agent = HybridMLXBackend('planner', 'observer')
                    agent.set_response_schema({'type': 'object'})
                    self.assertIn('Calculator', agent(messages))
                    forwarded = text.return_value.call_args.args[0][0]['content']
                    self.assertIsInstance(forwarded, str)
                    self.assertIn('Untrusted local vision observation: Calculator visible', forwarded)
                    self.assertIsInstance(messages[0]['content'], list)
                    text.return_value.set_response_schema.assert_called_once()
                    self.assertEqual(core.clear_cache.call_count, 2)

    def test_inference_bridge_constraints_and_request_isolation(self):
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        from unittest.mock import Mock
        from opendesk.integrations.local_server import make_server
        backend = Mock(return_value='{"answer":"local"}')
        server = make_server(backend, 'fixture')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def send(body, headers=None):
            request = Request(f'http://127.0.0.1:{server.server_port}/v1/chat/completions',
                              data=json.dumps(body).encode(),
                              headers={'Content-Type': 'application/json', **(headers or {})})
            with urlopen(request, timeout=5) as response:
                return json.load(response)
        body = {'model': 'fixture', 'messages': [{'role': 'user', 'content': 'test'}]}
        schema = {'type': 'object'}
        try:
            send({**body, 'response_format': {'type': 'json_schema', 'json_schema': {'schema': schema}}})
            backend.set_response_schema.assert_called_with(schema)
            self.assertEqual(send(body)['choices'][0]['message']['content'], '{"answer":"local"}')
            backend.set_response_schema.assert_called_with(None)
            for invalid, headers, status in [({**body, 'model': 'other'}, {}, 400),
                                              (body, {'Origin': 'http://example.com'}, 403),
                                              ({**body, 'messages': []}, {}, 400)]:
                with self.assertRaises(HTTPError) as error:
                    send(invalid, headers)
                self.assertEqual(error.exception.code, status)
            self.assertEqual(backend.call_count, 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
