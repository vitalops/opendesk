import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from opendesk.integrations.workspace import assist, folder_for, list_folder

class WorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_folder_question_never_loads_model_or_screen_history(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'notes.txt').write_text('private contents')
            (Path(root) / 'project').mkdir()
            factory = Mock(side_effect=AssertionError('must not load inference'))
            result = await assist('What files are in this folder?', folder=root, backend_factory=factory)
            self.assertFalse(result.error)
            self.assertIn('notes.txt', result.output)
            self.assertIn('project/', result.output)
            self.assertNotIn('private contents', result.output)
            factory.assert_not_called()

    def test_github_uses_real_directory(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            expected = home / 'Documents/GitHub'
            expected.mkdir(parents=True)
            self.assertEqual(folder_for('What are the files in my Github folder?', home=home), expected)

    def test_missing_folder_has_actionable_message(self):
        result = list_folder(None)
        self.assertTrue(result.error)
        self.assertIn('Choose folder', result.output)
        self.assertNotIn('daemon', result.output)

    def test_directory_limit_and_hidden_entries(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            (path / '.private').touch()
            for index in range(502):
                (path / f'file{index}').touch()
            result = list_folder(path)
            self.assertIn('500', result.output)
            self.assertNotIn('.private', result.output)

    async def test_screen_uses_guard_then_vision(self):
        from unittest.mock import AsyncMock, patch
        from opendesk.tools.base import Attachment, ToolResult
        planner = Mock(return_value='{"route":"screen"}')
        observer = Mock(return_value='A document is open.')
        factory = Mock(side_effect=[planner, observer])
        screenshot = ToolResult(title='Screen', output='', attachments=[Attachment(filename='screen.png', media_type='image/png', content=b'fixture')])
        with patch('opendesk.safety.guard.run_tool', new_callable=AsyncMock, return_value=screenshot) as dispatch:
            result = await assist('What is on my screen?', backend_factory=factory)
        self.assertEqual(result.output, 'A document is open.')
        dispatch.assert_awaited_once()
        self.assertEqual(factory.call_args.kwargs, {'vision': True})
        self.assertEqual(observer.call_args.args[0][0]['content'][1]['type'], 'image_url')

    async def test_history_empty_is_not_a_terminal_instruction(self):
        from unittest.mock import patch
        planner = Mock(return_value='{"route":"history"}')
        with patch('opendesk.memory.store.MemoryStore') as store:
            store.return_value.__enter__.return_value.timeline.return_value = []
            result = await assist('What was I doing earlier?', backend_factory=Mock(return_value=planner))
        self.assertNotIn('daemon', result.output)
        self.assertNotIn('opendesk memory start', result.output)
        self.assertIn('no saved activity', result.output)

    def test_past_file_question_is_not_current_directory_listing(self):
        from opendesk.integrations.workspace import file_question
        self.assertFalse(file_question('What files did I work on yesterday?'))

    async def test_how_many_files_returns_measured_counts(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'a.txt').touch()
            (Path(root) / 'b.txt').touch()
            (Path(root) / 'subfolder').mkdir()
            result = await assist('How many files are in this folder?', folder=root,
                                  backend_factory=Mock(side_effect=AssertionError('No model needed')))
            self.assertIn('2 files and 1 folders', result.output)

    async def test_app_listing_returns_evidence_not_a_promise(self):
        from unittest.mock import AsyncMock, patch
        from opendesk.tools.base import ToolResult
        planner = Mock(return_value='{"route":"apps"}')
        with patch('opendesk.safety.guard.run_tool', new_callable=AsyncMock,
                   return_value=ToolResult(title='Apps', output='Finder\nCalculator')):
            result = await assist('List running applications.', backend_factory=Mock(return_value=planner))
        self.assertIn('Calculator', result.output)
