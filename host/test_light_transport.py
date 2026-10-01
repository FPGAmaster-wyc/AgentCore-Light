"""Exercise the real pyserial transport against a local pseudo-terminal device."""
import os
import pty
import select
import tempfile
import threading
import tty
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from light_daemon import Device, Service


class TransportTests(unittest.TestCase):
    def test_identity_ack_status_and_reconnect_replay(self):
        for version in ('MAC1', 'MAC2'):
            with self.subTest(version=version):
                self.exercise_transport(version)

    def exercise_transport(self, version):
        master, slave = pty.openpty()
        tty.setraw(slave)
        stop = threading.Event()
        hardware = {"state": "IDLE", "token": 100, "brightness": 16}

        frame = ["THREADS:00000000,0,0,0"]

        def firmware():
            buffer = b""
            while not stop.is_set():
                if not select.select([master], [], [], 0.1)[0]:
                    continue
                try:
                    buffer += os.read(master, 4096)
                except OSError:
                    continue
                while b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    command = raw.decode().strip()
                    if command == "PING":
                        reply = "PONG:AGENTCORE-LIGHT-V3"
                    elif command == "STATUS":
                        reply = f"STATUS:{hardware['state']},TOKEN:{hardware['token']},BRIGHTNESS:{hardware['brightness']},FW:{version},{frame[0]}"
                    elif command.startswith("THREADS:"):
                        frame[0] = command
                        reply = command
                    elif command.startswith("TOKEN:"):
                        hardware['token'] = int(command.split(':')[1])
                        reply = f"Token percent: {hardware['token']}"
                    elif command.startswith("BRIGHTNESS:"):
                        hardware['brightness'] = int(command.split(':')[1])
                        reply = command
                    elif command.startswith("STALE:"):
                        reply = command
                    else:
                        hardware['state'] = command
                        reply = 'State changed to: ' + command
                    os.write(master, (reply + '\n').encode())

        thread = threading.Thread(target=firmware, daemon=True)
        thread.start()
        device = Device('test-device')
        port = SimpleNamespace(vid=0x303A, pid=0x1001, serial_number='test-device', device=os.ttyname(slave))
        try:
            with tempfile.TemporaryDirectory() as directory, \
                 patch('light_daemon.list_ports.comports', return_value=[port]):
                service = Service(device, Path(directory) / 'settings.json')
                service.tick()
                self.assertTrue(device.extended)
                service.request('TOKEN:89')
                service.request('BRIGHTNESS:10')
                service.request('THINKING')
                self.assertEqual(device.status(), {'state': 'THINKING', 'token': 89, 'brightness': 10})
                service.request('RECONNECT')
                hardware.update(state='IDLE', token=100, brightness=16)
                service.tick()
                self.assertEqual(device.status(), {'state': 'THINKING', 'token': 89, 'brightness': 10})
                if version == 'MAC2':
                    service.request('{"session_id":"a","state":"THINKING","event":"UserPromptSubmit"}')
                    service.request('{"session_id":"b","state":"NEED_CONFIRM","event":"PermissionRequest"}')
                    service.tick(force=True)
                    device.status()
                    self.assertEqual(device.thread_frame, 'THREADS:16000000,2,1,0')
                    service.request('RECONNECT')
                    frame[0] = 'THREADS:00000000,0,0,0'
                    service.tick()
                    device.status()
                    self.assertEqual(device.thread_frame, 'THREADS:16000000,2,1,0')
                service.request('OFF')
                self.assertEqual(device.status()['state'], 'OFF')
        finally:
            device.close()
            stop.set()
            thread.join(timeout=1)
            os.close(master)
            os.close(slave)


if __name__ == '__main__':
    unittest.main()
