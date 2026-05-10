from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
BACKEND_HOST = "0.0.0.0"
FRONTEND_HOST = "0.0.0.0"
BACKEND_URL = f"http://{BACKEND_HOST}:8200"
FRONTEND_URL = f"http://{FRONTEND_HOST}:8300"


def stream_output(name: str, process: subprocess.Popen[str]) -> None:
    assert process.stdout is not None
    for line in process.stdout:
        print(f"[{name}] {line}", end="")


def terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def run_command(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def start_process(name: str, command: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    threading.Thread(target=stream_output, args=(name, process), daemon=True).start()
    return process


def main() -> int:
    print("Installing backend dependencies...")
    run_command(["uv", "sync"], BACKEND_DIR)

    print("Installing frontend dependencies...")
    run_command(["bun", "install"], FRONTEND_DIR)

    env = os.environ.copy()
    env.setdefault("DATABASE_URL", "sqlite:///./data/app.db")

    print(f"Starting backend on {BACKEND_URL}")
    backend = start_process(
        "backend",
        [
            "uv",
            "run",
            "uvicorn",
            "profits_check_backend.main:create_app",
            "--factory",
            "--host",
            BACKEND_HOST,
            "--port",
            "8200",
        ],
        BACKEND_DIR,
        env,
    )

    print(f"Starting frontend on {FRONTEND_URL}")
    frontend = start_process(
        "frontend",
        ["bun", "run", "dev"],
        FRONTEND_DIR,
        env,
    )

    processes = [backend, frontend]

    def shutdown(*_: object) -> None:
        for process in processes:
            terminate_process(process)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"Frontend: {FRONTEND_URL}")
    print(f"Backend:  {BACKEND_URL}")
    print("Press Ctrl+C to stop both services.")

    try:
        while True:
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    shutdown()
                    return return_code
            time.sleep(0.5)
    except KeyboardInterrupt:
        shutdown()
        return 0


if __name__ == "__main__":
    sys.exit(main())
