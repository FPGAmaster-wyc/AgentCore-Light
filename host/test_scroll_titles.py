import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from light_daemon import Device, Service, validate_scroll_bitmap


class ScrollTitleTests(unittest.TestCase):
    def test_validation_and_maximum_width(self):
        value = '2048:' + 'AB' * 3584
        self.assertEqual(validate_scroll_bitmap(value), value)
        for bad in ['91:'+'00'*168, '2049:'+'00'*3584, '92:FF', '92:'+'GG'*168]:
            with self.assertRaises(ValueError):
                validate_scroll_bitmap(bad)

    def test_atomic_chunk_sequence_and_ack_failure(self):
        device = Device('test')
        commands = []
        def exchange(command, accepts):
            self.assertTrue(accepts(command))
            self.assertFalse(accepts('ERR invalid'))
            commands.append(command)
        device.exchange = exchange
        bitmap = 'AB' * 3584
        device.send('SCROLLTITLE:2:2048:' + bitmap)
        self.assertEqual(commands[0], 'TBEGIN:2:2048')
        self.assertEqual(commands[-1], 'TEND:2')
        self.assertTrue(all(len(c) < 383 for c in commands))
        pieces = commands[1:-1]
        self.assertEqual(''.join(c.split(':')[3] for c in pieces), bitmap)
        self.assertEqual([int(c.split(':')[2]) for c in pieces], list(range(0,3584,128)))
        device.exchange = MagicMock(side_effect=[None, TimeoutError('no ack')])
        with self.assertRaises(TimeoutError):
            device.send('SCROLLTITLE:2:2048:' + bitmap)
        self.assertEqual(device.exchange.call_count, 2)

    def test_mac4_and_renderer_mode(self):
        device = Device('test')
        device.exchange = MagicMock(return_value='STATUS:IDLE,TOKEN:80,BRIGHTNESS:16,FW:MAC4,THREADS:00000000,0,0,0')
        device.status()
        self.assertTrue(device.scroll_supported and device.titles_supported and device.extended)
        with tempfile.TemporaryDirectory() as directory:
            service = Service(device, Path(directory)/'settings.json')
            service.titles = lambda rows: [{'title':'完整中文任务名称','slot':1}]
            bitmap = '160:' + 'AB' * 280
            with patch('light_daemon.subprocess.run', return_value=MagicMock(stdout=bitmap)) as render:
                self.assertEqual(service.title_commands(1)['title1'], 'SCROLLTITLE:1:'+bitmap)
                self.assertIn('--render-scroll-title', render.call_args.args[0])
                service.title_commands(2)
                render.assert_called_once()
