"""Protocol and dispatch boundaries without downloading models or touching the desktop."""
import json
import unittest
from unittest.mock import AsyncMock, patch

from opendesk.integrations.local import LocalAgent
from opendesk.tools.base import ToolResult


def backend(*responses):
    replies = iter(responses)
    return lambda _: next(replies)


class LocalAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_dispatch_is_bounded_and_text_only(self):
        call = json.dumps({'tool': 'memory', 'arguments': {'action': 'timeline', 'limit': 100}})
        agent = LocalAgent(backend(call, '{"answer":"Found frame #1"}'))
        with patch('opendesk.integrations.local.run_tool', new_callable=AsyncMock) as dispatch:
            dispatch.return_value = ToolResult(title='memory', output='frame #1')
            result = await agent.run('What did I see?')
        self.assertFalse(result.error)
        self.assertEqual(dispatch.call_args.args[2]['limit'], 8)
        self.assertFalse(dispatch.call_args.args[2]['include_image'])

    async def test_actions_blocked_by_default(self):
        call = json.dumps({'tool': 'app', 'arguments': {'action': 'open', 'name': 'TextEdit'}})
        agent = LocalAgent(backend(call), mode='desktop', max_steps=1)
        with patch('opendesk.integrations.local.run_tool', new_callable=AsyncMock) as dispatch:
            result = await agent.run('Open TextEdit')
        self.assertTrue(result.error)
        dispatch.assert_not_called()

    async def test_enabled_actions_use_guard(self):
        call = json.dumps({'tool': 'app', 'arguments': {'action': 'open', 'name': 'TextEdit'}})
        agent = LocalAgent(backend(call, '{"answer":"Opened"}'), mode='desktop', allow_actions=True)
        with patch('opendesk.integrations.local.run_tool', new_callable=AsyncMock) as dispatch:
            dispatch.return_value = ToolResult(title='opened', output='TextEdit opened')
            result = await agent.run('Open TextEdit')
        self.assertFalse(result.error)
        dispatch.assert_awaited_once()

    async def test_invalid_output_never_executes(self):
        for response in ['not json', '[]', '{"tool":"script","arguments":{"action":"shell"}}']:
            with self.subTest(response=response):
                agent = LocalAgent(backend(response), max_steps=1)
                with patch('opendesk.integrations.local.run_tool', new_callable=AsyncMock) as dispatch:
                    self.assertTrue((await agent.run('test')).error)
                dispatch.assert_not_called()

    async def test_tool_errors_are_visible_to_model(self):
        messages = []
        def model(history):
            messages.append(history)
            return ('{"tool":"memory","arguments":{"action":"status"}}'
                    if len(messages) == 1 else '{"answer":"Unable to read memory"}')
        with patch('opendesk.integrations.local.run_tool', new_callable=AsyncMock) as dispatch:
            dispatch.return_value = ToolResult(title='failed', output='Access denied', error=True)
            await LocalAgent(model).run('Check memory')
        self.assertIn('"error": true', messages[1][-1]['content'])
        self.assertIn('Access denied', messages[1][-1]['content'])

    async def test_history_is_bounded(self):
        seen = []
        def model(messages):
            seen.append(messages)
            return '{"tool":"memory","arguments":{"action":"status"}}'
        with patch('opendesk.integrations.local.run_tool', new_callable=AsyncMock) as dispatch:
            dispatch.return_value = ToolResult(title='status', output='x' * 20000)
            result = await LocalAgent(model, max_steps=8).run('test')
        self.assertTrue(result.error)
        self.assertLessEqual(max(map(len, seen)), 6)
        self.assertLess(len(seen[-1][-1]['content']), 6200)

    async def test_answer_without_observation_is_rejected(self):
        result = await LocalAgent(backend('{"answer":"Done"}'), max_steps=1).run('test')
        self.assertTrue(result.error)

    async def test_unadvertised_parameters_are_rejected(self):
        call = '{"tool":"memory","arguments":{"action":"status","peer":"remote"}}'
        with patch('opendesk.integrations.local.run_tool', new_callable=AsyncMock) as dispatch:
            result = await LocalAgent(backend(call), max_steps=1).run('test')
        self.assertTrue(result.error)
        dispatch.assert_not_called()

    async def test_backend_failure_returns_error(self):
        def failing(_):
            raise RuntimeError('Model unavailable')
        result = await LocalAgent(failing).run('test')
        self.assertTrue(result.error)
        self.assertIn('Model unavailable', result.output)

    async def test_tool_subset_changes_prompt_and_dispatch(self):
        agent = LocalAgent(backend('{"tool":"memory","arguments":{"action":"status"}}'),
                           mode='desktop', allow_actions=True, tools=['app'], max_steps=1)
        self.assertIn("open", agent.allowed["app"])
        self.assertNotIn("memory", agent.allowed)
        with patch('opendesk.integrations.local.run_tool', new_callable=AsyncMock) as dispatch:
            self.assertTrue((await agent.run('test')).error)
        dispatch.assert_not_called()

    async def test_every_registered_tool_uses_guard(self):
        from opendesk.eval.local_models import CASES
        from opendesk.registry import create_registry
        self.assertEqual({n for n, _, _ in CASES}, set(create_registry().names()))
        for name, _, params in CASES:
            with self.subTest(tool=name):
                calls = backend(json.dumps({'tool': name, 'arguments': params}), '{"answer":"done"}')
                agent = LocalAgent(calls, mode='all', allow_actions=True, tools=[name])
                with patch('opendesk.integrations.local.run_tool', new_callable=AsyncMock) as dispatch:
                    dispatch.return_value = ToolResult(title='fixture', output='success')
                    outcome = await agent.run('fixture task')
                self.assertFalse(outcome.error)
                dispatch.assert_awaited_once()
                self.assertEqual(dispatch.call_args.args[0].name, name)

    async def test_describe_is_not_an_observation(self):
        agent = LocalAgent(backend('{"describe":"app"}', '{"answer":"done"}'), max_steps=2)
        self.assertTrue((await agent.run('test')).error)

    async def test_images_forwarded_only_to_vision_backend(self):
        from opendesk.tools.base import Attachment
        for vision in [True, False]:
            messages = []
            def model(history):
                messages.append(history)
                return '{"tool":"screenshot","arguments":{}}' if len(messages) == 1 else '{"answer":"seen"}'
            model.vision = vision
            agent = LocalAgent(model, tools=['screenshot'])
            with patch('opendesk.integrations.local.run_tool', new_callable=AsyncMock) as dispatch:
                dispatch.return_value = ToolResult(title='frame', output='frame', attachments=[Attachment('x.png', b'png', 'image/png')])
                self.assertFalse((await agent.run('look')).error)
            content = messages[1][-1]['content']
            self.assertEqual(isinstance(content, list), vision)
            if vision:
                self.assertTrue(content[1]['image_url']['url'].startswith('data:image/png;base64,'))

    async def test_scheduler_local_selection_never_calls_cloud(self):
        from opendesk.automation.runner import _run_natural_language
        from pathlib import Path
        with patch.dict('os.environ', {'OPENDESK_AGENT_BACKEND': 'local-http', 'OPENDESK_MODEL': 'fixture'}):
            with patch('opendesk.integrations.local.run_local_process', new_callable=AsyncMock) as local:
                with patch('opendesk.automation.runner._run_with_claude_code', new_callable=AsyncMock) as cloud:
                    local.return_value = ToolResult(title='local', output='completed')
                    output = await _run_natural_language('test', Path('/tmp'))
                    self.assertIn('ok (local)', output)
                    self.assertEqual(local.call_args.kwargs['backend'], 'http')
                    cloud.assert_not_called()

    async def test_response_schema_covers_registry_without_allowing_final_before_observation(self):
        import jsonschema
        from opendesk.eval.local_models import CASES
        agent = LocalAgent(backend(), mode='all', allow_actions=True)
        schema = agent.response_schema(allow_answer=False)
        validator = jsonschema.Draft202012Validator(schema)
        for name, _, args in CASES:
            validator.validate({'tool': name, 'arguments': args})
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate({'answer': 'done'})
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate({'tool': 'unknown', 'arguments': {}})

    async def test_local_eval_backend_uses_local_subprocess(self):
        from opendesk.eval.backends import get_backend
        from opendesk.eval.task import EvalTask
        for name in ['local-mlx', 'local-http']:
            with patch('opendesk.integrations.local.run_local_process', new_callable=AsyncMock) as local:
                local.return_value = ToolResult(title='local', output='done', metadata={'steps': 2})
                runner = get_backend(name, model='fixture', max_turns=4)
                r = await runner.run(EvalTask(id='fixture', instruction='test'), 'test', workdir='/tmp', timeout=10)
                self.assertIsNone(r.error)
                self.assertEqual(r.turns, 2)
                self.assertEqual(local.call_args.kwargs['backend'], name.removeprefix('local-'))

    async def test_local_subprocess_killed_on_timeout(self):
        import asyncio
        from opendesk.integrations.local import run_local_process
        from unittest.mock import Mock
        process = Mock(returncode=None)
        async def slow():
            await asyncio.sleep(60)
        process.communicate = slow
        process.wait = AsyncMock()
        with patch('asyncio.create_subprocess_exec', new_callable=AsyncMock, return_value=process):
            with self.assertRaises(asyncio.TimeoutError):
                await run_local_process('test', timeout=0.01)
        process.kill.assert_called_once()
        process.wait.assert_awaited_once()

    async def test_local_subprocess_rejects_malformed_success_output(self):
        from unittest.mock import Mock
        from opendesk.integrations.local import run_local_process
        process = Mock(returncode=0)
        process.communicate = AsyncMock(return_value=(b'not a tool result', b''))
        with patch('asyncio.create_subprocess_exec', new_callable=AsyncMock, return_value=process) as spawn:
            result = await run_local_process('test', structured=True)
        self.assertTrue(result.error)
        self.assertIn('--structured', spawn.call_args.args)
