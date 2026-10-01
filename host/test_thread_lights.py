import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from light_daemon import Device, Service
from light_state import LightState


class ThreadLightTests(unittest.TestCase):
    def event(self, state, key, value, at):
        state.event({'session_id': key, 'state': value, 'event': 'PostToolUse'}, at)

    def test_slots_survive_updates_and_overflow_fills_only_released_slot(self):
        state = LightState()
        for i in range(10):
            self.event(state, str(i), 'RUNNING', 1)
        initial = state.layout(2)
        self.assertEqual([r['slot'] for r in initial], list(range(1, 9)) + [None, None])
        self.event(state, '0', 'DONE', 3)
        self.event(state, '1', 'NEED_CONFIRM', 4)
        self.assertEqual(state.frame(5), 'THREADS:46333333,9,1,2')
        rows = {r['id']: r for r in state.layout(13)}
        self.assertEqual(rows['8']['slot'], 1)
        self.assertEqual(rows['1']['slot'], 2)
        self.assertEqual(rows['9']['slot'], None)
        self.assertEqual(rows['1']['color'], initial[1]['color'])

    def test_off_cleanup_and_error_recovery_keep_colors(self):
        state = LightState()
        self.event(state, 'a', 'ERROR', 1)
        before = state.layout(2)[0]
        state.command('OFF', 2)
        self.assertEqual(state.desired(12), 'OFF')
        after = state.layout(12)[0]
        self.assertEqual(after['state'], 'THINKING')
        self.assertEqual(after['color'], before['color'])
        self.assertEqual(state.layout(1801), [])

    def test_frame_has_bounded_counts_and_fits_firmware_buffer(self):
        state = LightState()
        state.sessions = {str(i): {'state': 'NEED_CONFIRM', 'at': 1, 'turn': None, 'slot': None}
                          for i in range(1100)}
        frame = state.frame(2)
        self.assertEqual(frame, 'THREADS:66666666,999,999,999')
        self.assertLessEqual(len(frame), 31)

    def test_firmware_capability_and_reported_frame(self):
        device = Device('test')
        device.exchange = MagicMock(return_value='STATUS:RUNNING,TOKEN:89,BRIGHTNESS:16,FW:MAC2,THREADS:13000000,2,0,0')
        self.assertEqual(device.status()['state'], 'RUNNING')
        self.assertTrue(device.threads_supported)
        self.assertEqual(device.thread_frame, 'THREADS:13000000,2,0,0')
        device.exchange.return_value = 'STATUS:IDLE,TOKEN:89,BRIGHTNESS:16,FW:MAC1'
        device.status()
        self.assertFalse(device.threads_supported)
        self.assertTrue(device.extended)

    def test_missing_title_database_does_not_break_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            device = MagicMock()
            device.threads_supported = True
            service = Service(device, Path(directory) / 'settings.json')
            self.event(service.state, 'test-session', 'RUNNING', time.monotonic())
            with patch('light_daemon.Path.home', return_value=Path(directory)):
                self.assertEqual(service.snapshot()['threads'][0]['title'], 'test-session')
            self.assertFalse((Path(directory) / '.codex').exists())

    def test_device_reset_replays_thread_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            device = MagicMock()
            device.threads_supported = True
            device.thread_frame = 'THREADS:00000000,0,0,0'
            device.status.return_value = {'state': 'RUNNING', 'token': 100, 'brightness': 16}
            service = Service(device, Path(directory) / 'settings.json')
            self.event(service.state, 'a', 'RUNNING', time.monotonic())
            service.tick(force=True)
            service.tick()
            frames = [c.args[0] for c in device.send.call_args_list if c.args[0].startswith('THREADS:')]
            self.assertEqual(frames, ['THREADS:30000000,1,0,0'] * 2)


class TitleTests(unittest.TestCase):
    def test_mac3_capability(self):
        device = Device('test')
        device.exchange = MagicMock(return_value='STATUS:RUNNING,TOKEN:80,BRIGHTNESS:16,FW:MAC3,THREADS:30000000,1,0,0')
        device.status()
        self.assertTrue(device.titles_supported)
        self.assertTrue(device.threads_supported)
        self.assertTrue(device.extended)

    def test_title_bitmap_cache_and_changed_title(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Service(MagicMock(), Path(directory) / 'settings.json')
            service.titles = lambda rows: [{'title': '中文任务', 'slot': 2}]
            result = MagicMock(stdout='AA' * 168)
            with patch('light_daemon.subprocess.run', return_value=result) as render:
                self.assertEqual(service.title_commands(1), {'title2': 'TITLE:2:' + 'AA' * 168})
                service.title_commands(2)
                render.assert_called_once()
                service.titles = lambda rows: [{'title': '新标题', 'slot': 2}]
                service.title_commands(3)
                self.assertEqual(render.call_count, 2)

    def test_renderer_failure_sends_blank_for_firmware_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Service(MagicMock(), Path(directory) / 'settings.json')
            service.titles = lambda rows: [{'title': '任务', 'slot': 1}]
            with patch('light_daemon.subprocess.run', side_effect=OSError('unavailable')):
                command = service.title_commands(1)['title1']
                self.assertEqual(command, 'TITLE:1:' + '0' * 336)
                self.assertLess(len(command), 383)
