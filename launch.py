"""Start the installed Windows judge without PowerShell or WMI queries."""
import argparse
import ctypes
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / 'runtime'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def log(message):
    print(message, flush=True)
    with (RUNTIME / 'startup.log').open('a', encoding='utf-8') as output:
        output.write(message + '\n')


def probe(command, seconds=8):
    with tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run([sys.executable, str(ROOT / 'check-startup.py'), str(seconds), *command],
                                    stdout=output, stderr=subprocess.STDOUT, timeout=seconds + 8,
                                    creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            return False, f'Startup check did not finish: {command[0]}'
        output.seek(0)
        return result.returncode == 0, output.read(65536).decode('utf-8', errors='replace').strip()


def judge_running(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=1) as response:
            return response.status == 200 and b'<title>Python Judge</title>' in response.read(100000)
    except (OSError, urllib.error.URLError):
        return False


def port_busy(port):
    with socket.socket() as connection:
        connection.settimeout(0.5)
        return connection.connect_ex(('127.0.0.1', port)) == 0


def process_identity(pid):
    """Match Windows process creation time so a reused PID cannot be stopped."""
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
            return None
        return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
    finally:
        kernel.CloseHandle(handle)


def stop_owned_server(port):
    try:
        state = json.loads((RUNTIME / f'server-{port}.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        state = {}
    pid = state.get('pid')
    if (type(pid) is not int or state.get('project') != str(ROOT) or not state.get('identity')
            or process_identity(pid) != state['identity']):
        raise RuntimeError('The old server was not started with this project path. Stop the old server manually, then run run.cmd again.')
    log(f'Stopping this project server (PID {pid})...')
    subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8, creationflags=NO_WINDOW)
    deadline = time.monotonic() + 5
    while port_busy(port) and time.monotonic() < deadline:
        time.sleep(0.1)
    if port_busy(port):
        raise RuntimeError(f'Port {port} did not close after stopping the server.')


def find_docker():
    found = shutil.which('docker')
    if found:
        return found
    for path in (Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/DockerDesktop/resources/bin/docker.exe',
                 Path(os.environ.get('ProgramFiles', '')) / 'Docker/Docker/resources/bin/docker.exe'):
        if path.is_file():
            return str(path)
    raise RuntimeError('Docker is missing. Run install.cmd first.')


def ensure_docker(docker):
    def ready():
        return probe([docker, 'info', '--format', '{{.OSType}}'])
    succeeded, detail = ready()
    if not succeeded:
        log('Docker connection check: ' + detail)
        desktop = next((path for path in (
            Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/DockerDesktop/Docker Desktop.exe',
            Path(os.environ.get('ProgramFiles', '')) / 'Docker/Docker/Docker Desktop.exe') if path.is_file()), None)
        if not desktop:
            raise RuntimeError('Open Docker Desktop and try again. ' + detail)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        subprocess.Popen([str(desktop)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=NO_WINDOW, startupinfo=startup)
        log('Starting Docker Desktop. Complete any initial setup in Docker Desktop.')
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            log(f'Waiting for Docker Desktop... {max(0, 120 - int(deadline - time.monotonic()))}/120 seconds')
            time.sleep(2)
            succeeded, detail = ready()
            if succeeded:
                break
        if not succeeded:
            raise RuntimeError('Docker did not become ready. ' + detail)
    if detail.strip().lower() != 'linux':
        raise RuntimeError('Linux containers are required. Docker reported: ' + detail)
    log('Docker Linux engine connected.')


def lan_configuration():
    # UDP connect selects a route without sending application data.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        connection.connect(('192.0.2.1', 80))
        address = connection.getsockname()[0]
    result = subprocess.run(['ipconfig', '/all'], capture_output=True, timeout=8, creationflags=NO_WINDOW)
    if result.returncode:
        raise RuntimeError('Could not read network configuration. Try run.cmd -LocalOnly.')
    found_address = False
    for line in result.stdout.decode(errors='replace').splitlines():
        addresses = re.findall(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])', line)
        if address in addresses:
            found_address = True
            continue
        if found_address:
            for candidate in addresses:
                try:
                    network = ipaddress.IPv4Network(f'{address}/{candidate}', strict=False)
                except ValueError:
                    continue
                if candidate.startswith('255.'):
                    return address, str(network)
    raise RuntimeError('LAN subnet unavailable. Try run.cmd -LocalOnly to start on this PC.')


def start(args):
    url = f'http://127.0.0.1:{args.Port}/'
    log('[1/5] Checking existing server...')
    log(f'Project: {ROOT}')
    log(f'Local URL: {url}')
    running = judge_running(url)
    if port_busy(args.Port) and not running:
        raise RuntimeError(f'Port {args.Port} is used by another application.')
    if running and args.Restart:
        stop_owned_server(args.Port)
        running = False
    if running:
        log('Using the existing server. After git pull, use run.cmd -Restart to reload server code.')
    else:
        log('[2/5] Checking Python and dependencies...')
        succeeded, detail = probe([sys.executable, '-c', 'import sys, openpyxl; raise SystemExit(sys.version_info < (3, 10))'])
        if not succeeded:
            raise RuntimeError('Python dependencies unavailable. Run install.cmd first. ' + detail)
        log('[3/5] Checking Docker (up to 8 seconds per check)...')
        docker = find_docker()
        environment = dict(os.environ)
        environment['PATH'] = str(Path(docker).parent) + os.pathsep + environment.get('PATH', '')
        ensure_docker(docker)
        image = environment.get('JUDGE_IMAGE', 'python:3.13-alpine')
        succeeded, detail = probe([docker, 'image', 'inspect', image])
        if not succeeded:
            raise RuntimeError(f'Grading image missing: {image}. Run install.cmd first. ' + detail)
        log('[4/5] Checking network configuration...')
        environment.update(JUDGE_PORT=str(args.Port), JUDGE_HOST='127.0.0.1', JUDGE_ALLOWED_SUBNETS='')
        if not args.LocalOnly:
            address, subnet = lan_configuration()
            environment.update(JUDGE_HOST='0.0.0.0', JUDGE_ALLOWED_SUBNETS=subnet)
            log(f'Student LAN URL: http://{address}:{args.Port}/')
        log('[5/5] Starting Python Judge server...')
        with (RUNTIME / 'server.out.log').open('w', encoding='utf-8') as out, (RUNTIME / 'server.err.log').open('w', encoding='utf-8') as err:
            process = subprocess.Popen([sys.executable, '-u', str(ROOT / 'server.py')], cwd=ROOT,
                                       env=environment, stdout=out, stderr=err, creationflags=NO_WINDOW)
        (RUNTIME / f'server-{args.Port}.json').write_text(json.dumps(
            {'pid': process.pid, 'identity': process_identity(process.pid), 'project': str(ROOT)}), encoding='utf-8')
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if judge_running(url):
                break
            if process.poll() is not None:
                raise RuntimeError(f'Server exited. Check {RUNTIME / "server.err.log"}')
            time.sleep(0.3)
        else:
            raise RuntimeError(f'Server startup timed out. Check {RUNTIME / "server.err.log"}')
    log('Python Judge: ' + url)
    if not args.NoBrowser:
        log('Opening browser: ' + url)
        if not webbrowser.open(url):
            log('Open the URL above in your browser.')
    log('Startup complete.')


def main():
    parser = argparse.ArgumentParser()
    for flag in ('NoBrowser', 'Restart', 'LocalOnly'):
        parser.add_argument('-' + flag, action='store_true')
    parser.add_argument('-Port', type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.Port <= 65535:
        parser.error('Port must be between 1 and 65535.')
    RUNTIME.mkdir(exist_ok=True)
    (RUNTIME / 'startup.log').write_text('', encoding='utf-8')
    try:
        start(args)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        log('ERROR: ' + str(exc))
        log('Startup log: ' + str(RUNTIME / 'startup.log'))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
