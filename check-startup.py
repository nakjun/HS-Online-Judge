"""Run a startup probe with a deadline and without opening another console."""
import os
import subprocess
import sys
import tempfile


def main():
    timeout = float(sys.argv[1])
    command = sys.argv[2:]
    if timeout <= 0 or not command:
        raise ValueError('A positive timeout and command are required.')
    # A file avoids blocking on inherited pipe handles after a probe times out.
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                try:
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if process.poll() is None:
                process.kill()
            process.wait()
            print(f'Command did not respond within {timeout:g} seconds: {command[0]}', flush=True)
            return 124
        output.seek(0)
        text = output.read(65536).decode('utf-8', errors='replace')
        if text:
            print(text.rstrip(), flush=True)
        return process.returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, IndexError) as exc:
        print(f'Startup check failed: {exc}', file=sys.stderr)
        raise SystemExit(1)
