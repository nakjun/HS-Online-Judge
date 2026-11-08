import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import autostart


class AutostartTest(unittest.TestCase):
    def test_no_network_uses_localhost(self):
        with patch.object(autostart, 'capture', return_value=SimpleNamespace(returncode=0, stdout='', stderr='')):
            self.assertEqual(autostart.network_config(), ('127.0.0.1', ''))

    def test_docker_start_is_throttled(self):
        with patch.object(autostart, 'docker_paths', return_value=('docker.exe', 'Docker Desktop.exe')), \
             patch.object(autostart, 'capture', return_value=SimpleNamespace(returncode=1, stdout='')), \
             patch.object(autostart.subprocess, 'Popen') as launch:
            supervisor = autostart.Supervisor()
            supervisor.step()
            supervisor.step()
            launch.assert_called_once()
            self.assertEqual(launch.call_args.args[0], ['Docker Desktop.exe'])

    def test_server_restart_and_port_conflict(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(autostart, 'RUNTIME', Path(directory)), \
             patch.object(autostart, 'docker_paths', return_value=('docker.exe', None)), \
             patch.object(autostart, 'capture', return_value=SimpleNamespace(returncode=0, stdout='linux')), \
             patch.object(autostart, 'network_config', return_value=('0.0.0.0', '192.168.0.0/24')), \
             patch.object(autostart, 'port_in_use', return_value=False) as occupied, \
             patch.object(autostart.subprocess, 'Popen') as launch:
            child = Mock()
            child.poll.return_value = None
            launch.return_value = child
            supervisor = autostart.Supervisor()
            supervisor.step()
            self.assertEqual(launch.call_args.kwargs['env']['JUDGE_PORT'], '18000')
            supervisor.step()
            self.assertEqual(launch.call_count, 1)
            child.poll.return_value = 1
            supervisor.step()
            self.assertEqual(launch.call_count, 2)
            occupied.return_value = True
            supervisor.step()
            self.assertEqual(launch.call_count, 2)
            child.terminate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
