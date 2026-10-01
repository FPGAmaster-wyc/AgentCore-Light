import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock, patch

from light_daemon import Service


class ChatTitleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / '.codex').mkdir()
        self.index = self.root / '.codex/session_index.jsonl'
        self.service = Service(MagicMock(), self.root / 'settings.json')
        self.service.state.sessions = {'chat': {}}
        home = patch('light_daemon.Path.home', return_value=self.root)
        home.start()
        self.addCleanup(home.stop)
        with closing(sqlite3.connect(self.root / '.codex/state_5.sqlite')) as db, db:
            db.execute('CREATE TABLE threads (id TEXT, title TEXT)')
            db.execute('INSERT INTO threads VALUES (?, ?)', ('chat', '原始提问'))

    def read_title(self, now=100):
        with patch('light_daemon.time.monotonic', return_value=now):
            return self.service.titles([{'id': 'chat'}])[0]['title']

    def test_chat_title_overrides_initial_prompt_and_skips_invalid_lines(self):
        self.index.write_text('\n'.join([
            json.dumps({'id':'chat','thread_name':'旧标题'}),
            'null', '[]', json.dumps({'id': [], 'thread_name':'bad'}),
            json.dumps({'id':'other','thread_name':'其他任务'}),
            json.dumps({'id':'chat','thread_name':'真实中文 Chat Title'}),
            json.dumps({'id':'chat','thread_name':'  '}),
            '{"id":"chat",',
        ]))
        self.assertEqual(self.read_title(), '真实中文 Chat Title')

    def test_rename_refreshes_after_existing_cache_interval(self):
        self.index.write_text(json.dumps({'id':'chat','thread_name':'之前标题'}))
        self.assertEqual(self.read_title(), '之前标题')
        with self.index.open('a') as stream:
            stream.write('\n'+json.dumps({'id':'chat','thread_name':'重命名标题'}))
        self.assertEqual(self.read_title(130), '之前标题')
        self.assertEqual(self.read_title(160), '重命名标题')

    def test_missing_index_falls_back_to_database_then_id(self):
        self.assertEqual(self.read_title(), '原始提问')
        (self.root / '.codex/state_5.sqlite').unlink()
        self.assertEqual(self.read_title(160), 'chat')

    def test_index_works_when_database_is_unavailable(self):
        (self.root / '.codex/state_5.sqlite').unlink()
        self.index.write_text(json.dumps({'id':'chat','thread_name':'Chat 标题'}))
        self.assertEqual(self.read_title(), 'Chat 标题')
