from __future__ import annotations

import base64
import getpass
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from shutil import which


ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
BACKEND_ENV_FILE = BACKEND_DIR / ".env"
COMMON_BIN_DIRS = [
    Path.home() / ".local" / "bin",
    Path.home() / ".bun" / "bin",
    Path.home() / ".cargo" / "bin",
]


def read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", maxsplit=1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def generate_fernet_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def ensure_backend_env(path: Path = BACKEND_ENV_FILE) -> None:
    values = read_dotenv(path)
    missing_key = not (os.getenv("APP_ENCRYPTION_KEY") or values.get("APP_ENCRYPTION_KEY"))
    missing_password = not (
        os.getenv("PROFITS_CHECK_BOOTSTRAP_PASSWORD")
        or values.get("PROFITS_CHECK_BOOTSTRAP_PASSWORD")
    )

    if not missing_key and not missing_password:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    additions: list[str] = []
    if missing_key:
        additions.append(f"APP_ENCRYPTION_KEY={generate_fernet_key()}")
    if missing_password:
        if not sys.stdin.isatty():
            raise RuntimeError(
                "PROFITS_CHECK_BOOTSTRAP_PASSWORD is missing. Run interactively once "
                "or add it to backend/.env."
            )
        password = getpass.getpass("Set initial login password: ")
        if len(password) < 12:
            raise RuntimeError("Initial login password must be at least 12 characters.")
        additions.append(f"PROFITS_CHECK_BOOTSTRAP_PASSWORD={password}")
    if "DATABASE_URL" not in values and not os.getenv("DATABASE_URL"):
        additions.append("DATABASE_URL=sqlite:///./data/app.db")
    if "PROFITS_CHECK_COOKIE_SECURE" not in values and not os.getenv("PROFITS_CHECK_COOKIE_SECURE"):
        additions.append("PROFITS_CHECK_COOKIE_SECURE=false")

    existing = path.read_text() if path.exists() else ""
    separator = "\n" if existing and not existing.endswith("\n") else ""
    rendered_additions = "\n".join(additions)
    path.write_text(f"{existing}{separator}{rendered_additions}\n")
    path.chmod(0o600)
    try:
        display_path = path.relative_to(ROOT)
    except ValueError:
        display_path = path
    print(f"Created {display_path}")


def build_env() -> dict[str, str]:
    env = read_dotenv(BACKEND_ENV_FILE)
    env.update(os.environ)
    path_entries = [str(path) for path in COMMON_BIN_DIRS]
    env["PATH"] = os.pathsep.join([*path_entries, env.get("PATH", "")])
    return env


def install_shell_script(url: str, name: str, env: dict[str, str]) -> None:
    print(f"Installing {name}...")
    with urllib.request.urlopen(url, timeout=30) as response:
        script = response.read()
    subprocess.run(["sh"], input=script, env=env, check=True)


def ensure_tool(name: str, install_url: str, env: dict[str, str]) -> None:
    if which(name, path=env["PATH"]):
        return
    install_shell_script(install_url, name, env)
    if not which(name, path=env["PATH"]):
        raise RuntimeError(f"{name} was installed but is still not available on PATH.")


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
    ensure_backend_env()
    env = build_env()
    ensure_tool("uv", "https://astral.sh/uv/install.sh", env)
    ensure_tool("bun", "https://bun.sh/install", env)

    backend_host = env.get("PROFITS_CHECK_BACKEND_HOST", "127.0.0.1")
    frontend_host = env.get("PROFITS_CHECK_FRONTEND_HOST", "127.0.0.1")
    backend_url = f"http://{backend_host}:8200"
    frontend_url = f"http://{frontend_host}:8300"

    print("Installing Python 3.12 if needed...")
    run_command(["uv", "python", "install", "3.12"], ROOT, env)

    print("Installing backend dependencies...")
    run_command(["uv", "sync"], BACKEND_DIR, env)

    print("Installing frontend dependencies...")
    run_command(["bun", "install"], FRONTEND_DIR, env)

    print(f"Starting backend on {backend_url}")
    backend = start_process(
        "backend",
        [
            "uv",
            "run",
            "uvicorn",
            "profits_check_backend.main:create_app",
            "--factory",
            "--host",
            backend_host,
            "--port",
            "8200",
        ],
        BACKEND_DIR,
        env,
    )

    print(f"Starting frontend on {frontend_url}")
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

    print(f"Frontend: {frontend_url}")
    print(f"Backend:  {backend_url}")
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
