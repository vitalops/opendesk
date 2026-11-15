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
        self.assertIn('"action":"open"', agent.instructions())
        self.assertNotIn('"tool":"memory"', agent.instructions())
        with patch('opendesk.integrations.local.run_tool', new_callable=AsyncMock) as dispatch:
            self.assertTrue((await agent.run('test')).error)
        dispatch.assert_not_called()
