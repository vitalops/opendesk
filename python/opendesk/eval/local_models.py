"""Reproducible local-model command benchmark. Does NOT execute generated commands.

Run: python -m opendesk.eval.local_models --model MODEL --out results.json
Each case uses real registry schemas and parameter validation; this measures
command selection/arguments, not OS execution or end-to-end task completion.
"""
from __future__ import annotations
import argparse
import json
import time
from pathlib import Path
from opendesk.integrations.local import LocalAgent, parse_command
from opendesk.integrations.local_backends import create_backend

CASES = [
    ('screenshot', 'Take a screenshot.', {}),
    ('mouse', 'Move the mouse to x=120 and y=80.', {'action': 'move', 'x': 120, 'y': 80}),
    ('keyboard', 'Type exactly the text: hello locally', {'action': 'type', 'text': 'hello locally'}),
    ('app', 'Open Calculator.', {'action': 'open', 'name': 'Calculator'}),
    ('ui', 'Inspect the accessibility tree of Calculator.', {'action': 'get_tree', 'app': 'Calculator'}),
    ('clipboard', 'Read the clipboard.', {'action': 'read'}),
    ('ocr', 'Read the text on the screen using OCR.', {}),
    ('learn', 'List learned procedures.', {'action': 'list'}),
    ('schedule', 'List scheduled tasks.', {'action': 'list'}),
    ('audit', 'Show the audit log.', {'action': 'show'}),
    ('memory', 'Search screen memory for invoice today.', {'action': 'search', 'query': 'invoice', 'since': 'today'}),
    ('script', 'Run the shell command pwd.', {'action': 'shell', 'code': 'pwd'}),
    ('browser', 'List browser tabs.', {'action': 'tabs'}),
    ('fleet', 'On the paired peer demo run app list.', {'peers': ['demo'], 'tool': 'app', 'params': {'action': 'list'}}),
    ('memory_manage', 'Pause screen memory for 1h.', {'action': 'pause', 'duration': '1h'}),
]


def benchmark(backend, *, full_catalog=False):
    rows = []
    for name, task, expected in CASES:
        agent = LocalAgent(backend, mode='all', allow_actions=True,
                           tools=None if full_catalog else [name])
        if hasattr(backend, 'set_response_schema'):
            backend.set_response_schema(agent.response_schema(allow_answer=False))
        messages = [{'role': 'system', 'content': agent.instructions()}, {'role': 'user', 'content': task}]
        started = time.perf_counter()
        raw, command, error = '', None, None
        passed = False
        for attempt in range(3):
            try:
                raw = backend(messages)
                command = parse_command(raw)
                if set(command) == {'describe'}:
                    schema = agent.schema(command['describe'])
                    messages += [{'role': 'assistant', 'content': raw},
                                 {'role': 'user', 'content': json.dumps({'schema': schema})}]
                    continue
                assert command.get('tool') == name, f'Expected tool {name}'
                args = command['arguments']
                assert isinstance(args, dict), 'arguments must be an object'
                assert not (set(args) - agent.schema(name)['properties'].keys()), 'Unknown parameters'
                normalized = agent.registry.get(name).parse_params(args).model_dump()
                assert all(normalized.get(k) == v for k, v in expected.items()), f'Expected arguments {expected}'
                passed = True
                break
            except Exception as exc:
                error = str(exc)
                # Correction is protocol-only, never reveals the expected answer.
                messages += [{'role': 'assistant', 'content': raw},
                             {'role': 'user', 'content': 'Return a valid JSON command with all required arguments for the original task.'}]
        row = dict(tool=name, task=task, expected=expected, passed=passed, seconds=round(time.perf_counter()-started, 2),
                   attempts=attempt+1, command=command, error=None if passed else (error or "No command within three turns"), raw=raw)
        rows.append(row)
        print(f"{name}: {'PASS' if passed else 'FAIL'} ({row['seconds']}s)", flush=True)
    return rows


def vision_fixture(backend):
    """A deterministic image tests the actual vision backend, not desktop access."""
    import base64
    import io
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (640, 320), 'white')
    draw = ImageDraw.Draw(image)
    draw.text((30, 70), 'LOCAL 4826', font=ImageFont.load_default(size=60), fill='black')
    draw.rectangle((40, 190, 200, 270), fill='blue')
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    started = time.perf_counter()
    response = backend([{'role': 'user', 'content': [
        {'type': 'text', 'text': 'What four-digit code is shown in the image? Reply with the digits only.'},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()}},
    ]}])
    return {'kind': 'synthetic-vision-fixture', 'answer': response, 'passed': response.strip() == '4826',
            'seconds': round(time.perf_counter() - started, 2)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', required=True)
    p.add_argument('--backend', choices=['mlx', 'http'], default='mlx')
    p.add_argument('--base-url', default='http://127.0.0.1:1234/v1')
    p.add_argument('--full-catalog', action='store_true')
    p.add_argument('--vision', action='store_true', help='Run an image-reading fixture instead of command generation')
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    backend = create_backend(args.backend, args.model, base_url=args.base_url, vision=args.vision)
    if args.vision:
        report = dict(model=args.model, backend=args.backend, **vision_fixture(backend))
    else:
        rows = benchmark(backend, full_catalog=args.full_catalog)
        report = dict(model=args.model, backend=args.backend, full_catalog=args.full_catalog,
                      kind='command-generation-only', cases=rows, passed=sum(r['passed'] for r in rows), total=len(rows))
    import importlib.metadata
    report['versions'] = {name: importlib.metadata.version(name) for name in ['opendesk'] +
                          (['mlx', 'mlx-vlm' if args.vision else 'mlx-lm'] if args.backend == 'mlx' else [])}
    import opendesk
    report['source_version'] = opendesk.__version__
    if args.backend == 'mlx':
        import mlx.core as mx
        report['peak_metal_gib'] = round(mx.get_peak_memory()/1024**3, 2)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2)+'\n')
    print(f"Passed: {report['passed']}; report: {args.out}")


if __name__ == '__main__':
    main()
