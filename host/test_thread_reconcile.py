import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from codex_light_serial import send_event
from light_state import LightState
from thread_reconcile import ThreadReconciler


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.db = self.path / 'state.sqlite'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('create table threads(id text, rollout_path text)')
        self.reconcile = ThreadReconciler(self.db)

    def item(self):
        return {'state': 'THINKING', 'at': 0, 'wall': 1, 'turn': 'new'}

    def test_unknown_requires_grace_and_repeated_successful_checks(self):
        sessions = {'ghost': self.item()}
        self.assertEqual(self.reconcile.reconcile(sessions, 299), [])
        self.assertEqual(len(self.reconcile.reconcile(sessions, 330)), 1)
        self.assertEqual(sessions, {})

    def test_recent_activity_and_database_failure_do_not_remove(self):
        sessions = {'unknown': self.item()}
        self.reconcile.reconcile(sessions, 301)
        sessions['unknown']['at'] = 305
        self.assertEqual(self.reconcile.reconcile(sessions, 340), [])
        self.db.unlink()
        self.assertEqual(self.reconcile.reconcile(sessions, 1000), [])
        self.assertIn('unknown', sessions)

    def test_registered_long_thinking_is_retained(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('insert into threads values (?,?)', ('known', None))
        sessions = {'known': self.item()}
        self.reconcile.reconcile(sessions, 400)
        self.reconcile.reconcile(sessions, 500)
        self.assertIn('known', sessions)

    def test_completion_must_match_turn_and_follow_last_hook(self):
        transcript = self.path / 'rollout.jsonl'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('insert into threads values (?,?)', ('known', str(transcript)))
        sessions = {'known': self.item()}
        def event(kind, turn):
            return json.dumps({'type':'event_msg', 'timestamp':'1970-01-01T00:00:02Z',
                               'payload':{'type':kind,'turn_id':turn}})+'\n'
        transcript.write_text(event('task_complete','old'))
        self.assertEqual(self.reconcile.reconcile(sessions, 400), [])
        transcript.write_text(event('task_complete','new')+event('task_started','later'))
        self.assertEqual(self.reconcile.reconcile(sessions, 440), [])
        transcript.write_text(event('task_complete','new'))
        self.assertEqual(len(self.reconcile.reconcile(sessions, 480)), 1)

    def test_ids_merge_without_changing_slot_and_session_only_events_follow_alias(self):
        state = LightState()
        state.event({'session_id':'alias','state':'RUNNING'}, 1)
        slot = state.sessions['alias']['slot']
        state.event({'session_id':'thread','source_session_id':'alias','state':'THINKING'}, 2)
        state.event({'session_id':'alias','state':'DONE'}, 3)
        self.assertEqual(list(state.sessions), ['thread'])
        self.assertEqual(state.sessions['thread']['slot'], slot)
        self.assertEqual(state.sessions['thread']['state'], 'DONE')

    def test_sender_prefers_thread_id_with_session_fallback(self):
        with patch('codex_light_serial.request_daemon',return_value='QUEUED') as request:
            send_event({'thread_id':'real','session_id':'alias'},'RUNNING')
            self.assertEqual(json.loads(request.call_args.args[0])['session_id'],'real')
            send_event({'thread_id':'','session_id':'alias'},'RUNNING')
            self.assertEqual(json.loads(request.call_args.args[0])['session_id'],'alias')
