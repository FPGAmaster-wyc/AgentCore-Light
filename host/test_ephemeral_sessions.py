"""Only persisted chats should appear as active tasks on the lamp."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import MagicMock, patch

from codex_light_serial import send_event
from light_daemon import Service
from thread_reconcile import ThreadReconciler


class EphemeralSessionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.db = root / 'state.sqlite'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('CREATE TABLE threads (id TEXT, rollout_path TEXT)')
        self.device = MagicMock()
        self.device.threads_supported = True
        self.device.titles_supported = False
        self.device.extended = False
        self.device.status.return_value = {'state':'IDLE','token':100,'brightness':16}
        self.service = Service(self.device, root / 'settings.json')
        self.service.reconciler = ThreadReconciler(self.db)

    def event(self, name='UserPromptSubmit', state='THINKING', **kwargs):
        return {'session_id':'hidden','turn_id':'turn','event':name,'state':state,
                'transcript_path':None, **kwargs}

    def register(self, key):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('INSERT INTO threads VALUES (?,?)', (key,None))

    def test_hidden_session_never_lights_ring_and_stop_does_not_show_done(self):
        for name,state in [('SessionStart','IDLE'),('UserPromptSubmit','THINKING'),
                           ('PreToolUse','RUNNING'),('PermissionRequest','NEED_CONFIRM'),
                           ('PostToolUse','THINKING'),('Stop','DONE')]:
            self.assertEqual(self.service.request(json.dumps(self.event(name,state))), 'QUEUED')
            self.assertEqual(self.service.state.sessions,{})
        self.assertEqual(self.service.pending_events,{})
        self.service.tick(force=True)
        sent=[call.args[0] for call in self.device.send.call_args_list]
        self.assertIn('THREADS:00000000,0,0,0',sent)
        self.assertIn('IDLE',sent)
        self.assertNotIn('DONE',sent)

    def test_new_chat_is_promoted_after_delayed_registration(self):
        event=self.event()
        self.service.accept_event(event,10)
        self.service.promote_pending_events(11)
        self.assertEqual(self.service.state.sessions,{})
        self.register('hidden')
        self.service.promote_pending_events(12)
        self.assertEqual(self.service.state.sessions['hidden']['state'],'THINKING')
        self.assertEqual(self.service.pending_events,{})

    def test_completed_pending_chat_is_not_promoted_later(self):
        self.service.accept_event(self.event(),1)
        self.service.accept_event(self.event('Stop','DONE'),2)
        self.register('hidden')
        self.service.promote_pending_events(3)
        self.assertEqual(self.service.state.sessions,{})

    def test_persisted_chat_without_transcript_and_legacy_events_still_work(self):
        self.register('hidden')
        self.service.accept_event(self.event(),1)
        self.assertIn('hidden',self.service.state.sessions)
        self.service.accept_event({'session_id':'legacy','state':'RUNNING'},2)
        self.assertIn('legacy',self.service.state.sessions)
        self.service.accept_event(self.event(session_id='new',transcript_path='/new/rollout.jsonl'),3)
        self.assertIn('new',self.service.state.sessions)

    def test_unavailable_database_retains_existing_and_promotes_pending_after_recovery(self):
        self.service.accept_event(self.event(session_id='known',transcript_path='/chat.jsonl'),1)
        with patch.object(self.service.reconciler,'is_registered',return_value=None):
            self.service.accept_event(self.event(session_id='known'),2)
            self.service.accept_event(self.event(),3)
            self.service.promote_pending_events(4)
        self.assertIn('known',self.service.state.sessions)
        self.assertNotIn('hidden',self.service.state.sessions)
        self.register('hidden')
        self.service.promote_pending_events(5)
        self.assertIn('hidden',self.service.state.sessions)

    def test_pending_expiry_and_interrupt(self):
        self.service.accept_event(self.event(),1)
        self.service.promote_pending_events(301)
        self.assertEqual(self.service.pending_events,{})
        self.service.accept_event(self.event(),302)
        self.service.accept_event(self.event('Interrupt','IDLE'),303)
        self.assertEqual(self.service.pending_events,{})

    def test_transport_preserves_explicit_null_and_omits_unknown_metadata(self):
        with patch('codex_light_serial.request_daemon',return_value='QUEUED') as request:
            send_event({'session_id':'a','transcript_path':None},'THINKING')
            value=json.loads(request.call_args.args[0])
            self.assertIn('transcript_path',value)
            self.assertIsNone(value['transcript_path'])
            send_event({'session_id':'a'},'THINKING')
            self.assertNotIn('transcript_path',json.loads(request.call_args.args[0]))
