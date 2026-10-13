"""Run untrusted submissions only inside a constrained Docker container."""
import os
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

IMAGE = os.environ.get("JUDGE_IMAGE", "python:3.13-alpine")
TIMEOUT = 6
OUTPUT_LIMIT = 64 * 1024


def run_code(code: str, stdin: str) -> dict:
    name = "python-judge-" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="python-judge-") as directory:
        source = Path(directory) / "main.py"
        source.write_text(code, encoding="utf-8")
        command = [
            "docker", "run", "--rm", "--name", name, "--interactive",
            "--network", "none", "--memory", "128m", "--memory-swap", "128m",
            "--cpus", "0.5", "--pids-limit", "32", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
            "--mount", f"type=bind,source={source.resolve()},target=/app/main.py,readonly",
            "--workdir", "/app", IMAGE, "python", "-B", "-I", "/app/main.py",
        ]
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except FileNotFoundError:
            return {"status": "SYSTEM_ERROR", "stdout": "", "stderr": "Docker 명령을 찾을 수 없습니다."}

        chunks = {"stdout": bytearray(), "stderr": bytearray()}
        too_large = threading.Event()

        def collect(stream, key):
            while block := stream.read(4096):
                if len(chunks[key]) + len(block) > OUTPUT_LIMIT:
                    too_large.set()
                    chunks[key].extend(block[:max(0, OUTPUT_LIMIT - len(chunks[key]))])
                    break
                chunks[key].extend(block)

        readers = [threading.Thread(target=collect, args=(process.stdout, "stdout")),
                   threading.Thread(target=collect, args=(process.stderr, "stderr"))]
        for reader in readers:
            reader.start()

        def feed():
            try:
                process.stdin.write(stdin.encode("utf-8"))
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        writer = threading.Thread(target=feed, daemon=True)
        writer.start()
        timed_out = False
        try:
            process.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            timed_out = True
        if timed_out or too_large.is_set():
            subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=5, check=False)
            process.kill()
        process.wait()
        for reader in readers:
            reader.join(timeout=1)
        stdout = chunks["stdout"].decode("utf-8", errors="replace")
        stderr = chunks["stderr"].decode("utf-8", errors="replace")
        if too_large.is_set():
            status = "OUTPUT_LIMIT"
        elif timed_out:
            status = "TIME_LIMIT"
        elif process.returncode == 0:
            status = "OK"
        elif "Cannot connect to the Docker daemon" in stderr or "docker API" in stderr:
            status = "SYSTEM_ERROR"
        else:
            status = "RUNTIME_ERROR"
        return {"status": status, "stdout": stdout, "stderr": stderr}
