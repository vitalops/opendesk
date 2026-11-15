"""Loopback inference bridge for OpenDesk's Python/JS agents; never executes tools."""
from __future__ import annotations
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from opendesk.integrations.local_backends import create_backend, DEFAULT_MODEL, DEFAULT_VISION_MODEL

MAX_BODY = 32 * 1024 * 1024


def serve(model=None, *, port=1234, vision=False, planner_model=None):
    model = model or (DEFAULT_VISION_MODEL if vision else DEFAULT_MODEL)
    backend = create_backend('mlx', model, vision=vision, planner_model=planner_model)
    server = make_server(backend, model, port)
    print(f'Local inference ready: http://127.0.0.1:{server.server_port}/v1 — {model}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def make_server(backend, model, port=0):
    """Single request at a time bounds model memory. Bind only literal loopback."""
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def log_message(self, *args):
            pass  # Do not log prompts or model outputs.

        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            if self.path == '/v1/models':
                self.reply(200, {'object': 'list', 'data': [{'id': model, 'object': 'model'}]})
            else:
                self.reply(404, {'error': 'Not found'})

        def do_POST(self):
            if self.path != '/v1/chat/completions':
                self.reply(404, {'error': 'Not found'})
                return
            if self.headers.get('Origin') or self.headers.get_content_type() != 'application/json':
                self.reply(403, {'error': 'Native local JSON clients only; browser origins are disabled'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= MAX_BODY:
                    raise ValueError('Request size must be between 1 byte and 32 MiB')
                body = json.loads(self.rfile.read(length))
                if body.get('model') != model or body.get('stream', False):
                    raise ValueError('Use the configured model with stream=false')
                messages = body.get('messages')
                if not isinstance(messages, list) or not 1 <= len(messages) <= 20:
                    raise ValueError('messages must contain 1–20 entries')
                for message in messages:
                    if (not isinstance(message, dict) or message.get('role') not in {'system', 'user', 'assistant', 'tool'}
                            or not isinstance(message.get('content'), (str, list))):
                        raise ValueError('Invalid message')
                response_format = body.get('response_format') or {}
                schema = None
                if response_format:
                    if response_format.get('type') != 'json_schema':
                        raise ValueError('Only json_schema response_format is supported')
                    schema = response_format.get('json_schema', {}).get('schema')
                    if not isinstance(schema, dict):
                        raise ValueError('A JSON schema object is required')
                # Clear prior request constraints; requests do not share chat history.
                backend.set_response_schema(schema)
                content = backend(messages)
                self.reply(200, {'object': 'chat.completion', 'model': model,
                                 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': content},
                                              'finish_reason': 'stop'}]})
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                self.reply(400, {'error': str(exc)})
            except Exception as exc:
                self.reply(500, {'error': f'Local inference failed: {type(exc).__name__}'})

    return HTTPServer(('127.0.0.1', port), Handler)
