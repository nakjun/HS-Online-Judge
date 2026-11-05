import os
import subprocess
import sys
import time
import unittest
from pathlib import Path


class StartupProbeTest(unittest.TestCase):
    def probe(self, timeout, *command):
        environment = dict(os.environ, PYTHONIOENCODING='utf-8')
        return subprocess.run([sys.executable, str(Path(__file__).with_name('check-startup.py')),
                               str(timeout), *command], capture_output=True, text=True,
                              encoding='utf-8', env=environment, timeout=10)

    def test_command_output_and_arguments_with_spaces(self):
        result = self.probe(3, sys.executable, '-c', 'import sys; print(sys.argv[1])',
                            'quoted "value" with spaces 한글')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), 'quoted "value" with spaces 한글')

    def test_nonzero_exit_and_missing_executable(self):
        failed = self.probe(3, sys.executable, '-c', 'print("probe error"); raise SystemExit(7)')
        self.assertEqual(failed.returncode, 7)
        self.assertIn('probe error', failed.stdout)
        missing = self.probe(3, str(Path(__file__).with_name('missing-docker-binary.exe')))
        self.assertEqual(missing.returncode, 1)
        self.assertIn('Startup check failed', missing.stderr)

    def test_hung_command_has_a_deadline(self):
        started = time.monotonic()
        result = self.probe(0.3, sys.executable, '-c', 'import time; time.sleep(60)')
        self.assertEqual(result.returncode, 124)
        self.assertIn('did not respond within 0.3 seconds', result.stdout)
        self.assertLess(time.monotonic() - started, 6)


if __name__ == '__main__':
    unittest.main()
