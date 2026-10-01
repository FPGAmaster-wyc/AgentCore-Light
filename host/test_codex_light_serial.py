import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import codex_light_serial as bridge


class DaemonIdleTests(unittest.TestCase):
    def run_sequence(self, events):
        clock = [0]
        pending = iter(events)
        connections = []
        serial_port = MagicMock()
        server = MagicMock()

        def accept():
            try:
                at, command = next(pending)
            except StopIteration:
                raise KeyboardInterrupt
            clock[0] = at
            if command is None:
                raise TimeoutError
            connection = MagicMock()
            connection.__enter__.return_value = connection
            connection.recv.return_value = (command + "\n").encode()
            connections.append(connection)
            return connection, ("127.0.0.1", 12345)

        server.accept.side_effect = accept
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(bridge, "__file__", str(Path(directory) / "bridge.py")), \
             patch.object(bridge.serial, "Serial") as serial_factory, \
             patch.object(bridge.socket, "socket") as socket_factory, \
             patch.object(bridge.time, "sleep"), \
             patch.object(bridge.time, "monotonic", side_effect=lambda: clock[0]), \
             patch("builtins.print"):
            serial_factory.return_value.__enter__.return_value = serial_port
            socket_factory.return_value.__enter__.return_value = server
            with self.assertRaises(KeyboardInterrupt):
                bridge.run_daemon()
            for connection in connections:
                connection.sendall.assert_called_once_with(b"OK\n")
            return [call.args[0] for call in serial_port.write.call_args_list]

    def test_token_updates_preserve_active_state_and_original_idle_deadline(self):
        for state in ("THINKING", "WRITING", "RUNNING"):
            with self.subTest(state=state):
                writes = self.run_sequence([(1, state), (20, "TOKEN:91"),
                                            (40, "token:90"), (47, None), (90, None)])
                self.assertEqual(writes, [b"IDLE\n", (state + "\n").encode(),
                                          b"TOKEN:91\n", b"TOKEN:90\n", b"IDLE\n"])

    def test_real_activity_still_refreshes_idle_deadline(self):
        writes = self.run_sequence([(1, "THINKING"), (40, "RUNNING"),
                                    (47, None), (50, "TOKEN:90"), (86, None)])
        self.assertEqual(writes, [b"IDLE\n", b"THINKING\n", b"RUNNING\n",
                                  b"TOKEN:90\n", b"IDLE\n"])

    def test_token_updates_do_not_make_other_states_auto_idle(self):
        for state in ("IDLE", "DONE", "ERROR", "NEED_CONFIRM", "OFF"):
            with self.subTest(state=state):
                writes = self.run_sequence([(1, state), (40, "TOKEN:90"), (100, None)])
                self.assertEqual(writes, [b"IDLE\n", (state + "\n").encode(), b"TOKEN:90\n"])


if __name__ == "__main__":
    unittest.main()
