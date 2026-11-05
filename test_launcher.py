import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import launch


class LauncherTest(unittest.TestCase):
    def test_running_linux_engine_is_accepted_without_desktop_start(self):
        with patch.object(launch, 'probe', return_value=(True, 'linux')) as probe, \
                patch.object(launch.subprocess, 'Popen') as start, patch.object(launch, 'log'):
            launch.ensure_docker('docker.exe')
            probe.assert_called_once_with(['docker.exe', 'info', '--format', '{{.OSType}}'])
            start.assert_not_called()

    def test_windows_engine_is_reported(self):
        with patch.object(launch, 'probe', return_value=(True, 'windows')):
            with self.assertRaisesRegex(RuntimeError, 'Linux containers are required'):
                launch.ensure_docker('docker.exe')

    def test_lan_subnet_from_ipconfig_without_powershell(self):
        sample = '''Adapter one:
 IPv4 Address: 172.30.10.1
 Subnet Mask: 255.255.0.0
Adapter two:
 IPv4 주소: 192.168.0.50(Preferred)
 서브넷 마스크: 255.255.255.0
 Default Gateway: 192.168.0.1
'''.encode('utf-8')
        with patch.object(launch.socket, 'socket') as socket, \
                patch.object(launch.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, sample)) as run:
            socket.return_value.__enter__.return_value.getsockname.return_value = ('192.168.0.50', 123)
            self.assertEqual(launch.lan_configuration(), ('192.168.0.50', '192.168.0.0/24'))
            self.assertEqual(run.call_args.args[0], ['ipconfig', '/all'])
            self.assertEqual(run.call_args.kwargs['timeout'], 8)

    def test_restart_refuses_reused_pid(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(launch, 'RUNTIME', Path(directory)), \
                patch.object(launch, 'process_identity', return_value='different-creation-time'), \
                patch.object(launch.subprocess, 'run') as stop:
            (Path(directory) / 'server-8000.json').write_text(json.dumps(
                {'pid': 123, 'project': str(launch.ROOT), 'identity': 'old-creation-time'}), encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'old server was not started'):
                launch.stop_owned_server(8000)
            stop.assert_not_called()


if __name__ == '__main__':
    unittest.main()
