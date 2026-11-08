"""Keep Docker Desktop and the judge running after Windows sign-in."""
import ipaddress
import json
import logging
from logging.handlers import RotatingFileHandler
import msvcrt
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
PORT = 18000
HIDDEN = subprocess.CREATE_NO_WINDOW


def capture(command, timeout=20):
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout,
                          creationflags=HIDDEN)


def docker_paths():
    roots = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/DockerDesktop",
             Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Docker/Docker"]
    cli = next((str(root / "resources/bin/docker.exe") for root in roots
                if (root / "resources/bin/docker.exe").exists()), shutil.which("docker"))
    desktop = next((str(root / "Docker Desktop.exe") for root in roots
                    if (root / "Docker Desktop.exe").exists()), None)
    return cli, desktop


def network_config():
    command = "Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address } | ForEach-Object { $_.IPv4Address } | Select-Object IPAddress,PrefixLength | ConvertTo-Json -Compress"
    result = capture(["powershell.exe", "-NoProfile", "-Command", command])
    if result.returncode:
        raise RuntimeError(result.stderr)
    addresses = json.loads(result.stdout.strip() or "[]")
    if isinstance(addresses, dict):
        addresses = [addresses]
    subnets = set()
    for address in addresses:
        interface = ipaddress.ip_interface(f"{address['IPAddress']}/{address['PrefixLength']}")
        if not interface.ip.is_link_local and not interface.ip.is_loopback:
            subnets.add(str(interface.network))
    return ("0.0.0.0", ",".join(sorted(subnets))) if subnets else ("127.0.0.1", "")


def port_in_use():
    with socket.socket() as client:
        client.settimeout(1)
        return client.connect_ex(("127.0.0.1", PORT)) == 0


class Supervisor:
    def __init__(self):
        self.server = None
        self.network = None
        self.last_desktop_start = -float("inf")

    def step(self):
        cli, desktop = docker_paths()
        if not cli:
            raise RuntimeError("Docker CLI is missing. Run install.cmd again.")
        docker_directory = str(Path(cli).parent)
        if docker_directory not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = docker_directory + os.pathsep + os.environ.get("PATH", "")
        result = capture([cli, "info", "--format", "{{.OSType}}"])
        if result.returncode or result.stdout.strip() != "linux":
            if desktop and time.monotonic() - self.last_desktop_start >= 180:
                startup = subprocess.STARTUPINFO()
                startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startup.wShowWindow = 0
                subprocess.Popen([desktop], startupinfo=startup, creationflags=HIDDEN)
                self.last_desktop_start = time.monotonic()
                logging.info("Starting Docker Desktop; waiting for Linux engine")
            return
        network = network_config()
        if self.server and self.server.poll() is None and network != self.network:
            logging.info("Network changed; restarting owned server")
            # Windows venv executables can spawn a Python child process.
            # Stop only the process tree owned by this supervisor.
            capture(["taskkill.exe", "/PID", str(self.server.pid), "/T", "/F"])
            self.server.wait(timeout=10)
        if self.server and self.server.poll() is None:
            return
        if port_in_use():
            # Never stop a process that this supervisor did not start.
            logging.warning("Port 18000 is occupied; waiting without launching a duplicate")
            return
        env = dict(os.environ, JUDGE_PORT=str(PORT), JUDGE_HOST=network[0],
                   JUDGE_ALLOWED_SUBNETS=network[1], PYTHONUNBUFFERED="1")
        with (RUNTIME / "server.out.log").open("ab") as output, (RUNTIME / "server.err.log").open("ab") as error:
            self.server = subprocess.Popen([sys.executable, str(ROOT / "server.py")],
                                           cwd=ROOT, env=env, stdout=output, stderr=error,
                                           creationflags=HIDDEN)
        self.network = network
        logging.info("Started server pid=%s at %s:18000 subnets=%s", self.server.pid, *network)


def main():
    RUNTIME.mkdir(exist_ok=True)
    # The open file lock is released automatically even if Windows kills us.
    with (RUNTIME / "autostart.lock").open("a+b") as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return
        handler = RotatingFileHandler(RUNTIME / "autostart.log", maxBytes=1_000_000,
                                      backupCount=2, encoding="utf-8")
        logging.basicConfig(level=logging.INFO, handlers=[handler],
                            format="%(asctime)s %(levelname)s %(message)s")
        supervisor = Supervisor()
        logging.info("Supervisor started pid=%s", os.getpid())
        while True:
            try:
                supervisor.step()
            except Exception:
                logging.exception("Startup check failed; retrying in 15 seconds")
            time.sleep(15)


if __name__ == "__main__":
    main()
