from __future__ import annotations

import base64
import getpass
import hashlib
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from shutil import rmtree, which

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
BACKEND_ENV_FILE = BACKEND_DIR / ".env"
COMMON_BIN_DIRS = [
    Path.home() / ".local" / "bin",
    Path.home() / ".bun" / "bin",
    Path.home() / ".cargo" / "bin",
]
BACKEND_STAMP = BACKEND_DIR / ".venv" / ".profits-check-sync"
FRONTEND_STAMP = FRONTEND_DIR / "node_modules" / ".profits-check-install"
FRONTEND_BUILD_STAMP = FRONTEND_DIR / "dist" / ".profits-check-build"
FRONTEND_BUILD_FILES = [
    "package.json",
    "bun.lock",
    "index.html",
    "vite.config.ts",
    "tsconfig.json",
    "tsconfig.app.json",
    "tsconfig.node.json",
]
FRONTEND_BUILD_DIRS = ["src", "public"]


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
    if "PROFITS_CHECK_ALLOWED_HOSTS" not in values and not os.getenv("PROFITS_CHECK_ALLOWED_HOSTS"):
        additions.append("PROFITS_CHECK_ALLOWED_HOSTS=")

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


def file_digest(path: Path) -> str:
    if not path.exists():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dependency_signature(paths: list[Path]) -> str:
    return "\n".join(f"{path.name}:{file_digest(path)}" for path in paths)


def frontend_build_inputs(frontend_dir: Path) -> list[Path]:
    inputs: list[Path] = []
    for file_name in FRONTEND_BUILD_FILES:
        path = frontend_dir / file_name
        if path.exists():
            inputs.append(path)

    for dir_name in FRONTEND_BUILD_DIRS:
        root = frontend_dir / dir_name
        if not root.exists():
            continue
        inputs.extend(path for path in root.rglob("*") if path.is_file())

    return sorted(inputs, key=lambda path: path.relative_to(frontend_dir).as_posix())


def frontend_build_signature(frontend_dir: Path = FRONTEND_DIR) -> str:
    return "\n".join(
        f"{path.relative_to(frontend_dir).as_posix()}:{file_digest(path)}"
        for path in frontend_build_inputs(frontend_dir)
    )


def dependencies_are_current(required_path: Path, stamp_path: Path, signature: str) -> bool:
    return required_path.exists() and stamp_path.exists() and stamp_path.read_text() == signature


def write_dependency_stamp(stamp_path: Path, signature: str) -> None:
    stamp_path.parent.mkdir(parents=True, exist_ok=True)
    stamp_path.write_text(signature)


def sync_dependencies(
    *,
    label: str,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    required_path: Path,
    stamp_path: Path,
    signature_paths: list[Path],
) -> None:
    signature = dependency_signature(signature_paths)
    if dependencies_are_current(required_path, stamp_path, signature):
        print(f"{label} dependencies are already installed.")
        return

    print(f"Installing {label} dependencies...")
    run_command(command, cwd, env)
    write_dependency_stamp(stamp_path, signature)


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


def clean_frontend_dist(dist_dir: Path) -> None:
    if not dist_dir.exists():
        return

    generated_paths = [
        dist_dir / "assets",
        dist_dir / "index.html",
        dist_dir / "vite.svg",
    ]
    for path in generated_paths:
        if path.is_dir():
            rmtree(path)
        elif path.exists():
            path.unlink()


def build_frontend_static_files(
    frontend_dir: Path = FRONTEND_DIR,
    stamp_path: Path = FRONTEND_BUILD_STAMP,
    env: dict[str, str] | None = None,
) -> None:
    dist_dir = frontend_dir / "dist"
    signature = frontend_build_signature(frontend_dir)
    if dependencies_are_current(dist_dir / "index.html", stamp_path, signature):
        print("Frontend static files are already built.")
        return

    print("Building frontend static files...")
    clean_frontend_dist(dist_dir)
    run_command(["bun", "run", "build"], frontend_dir, env)
    write_dependency_stamp(stamp_path, signature)


def start_process(
    name: str, command: list[str], cwd: Path, env: dict[str, str] | None = None
) -> subprocess.Popen[str]:
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
    backend_url = f"http://{backend_host}:8200"

    print("Installing Python 3.12 if needed...")
    run_command(["uv", "python", "install", "3.12"], ROOT, env)

    sync_dependencies(
        label="backend",
        command=["uv", "sync"],
        cwd=BACKEND_DIR,
        env=env,
        required_path=BACKEND_DIR / ".venv",
        stamp_path=BACKEND_STAMP,
        signature_paths=[BACKEND_DIR / "pyproject.toml", BACKEND_DIR / "uv.lock"],
    )
    sync_dependencies(
        label="frontend",
        command=["bun", "install"],
        cwd=FRONTEND_DIR,
        env=env,
        required_path=FRONTEND_DIR / "node_modules",
        stamp_path=FRONTEND_STAMP,
        signature_paths=[FRONTEND_DIR / "package.json", FRONTEND_DIR / "bun.lock"],
    )

    build_frontend_static_files(FRONTEND_DIR, FRONTEND_BUILD_STAMP, env)

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
            "--log-level",
            "error",
            "--no-access-log",
        ],
        BACKEND_DIR,
        env,
    )

    processes = [backend]

    def shutdown(*_: object) -> None:
        for process in processes:
            terminate_process(process)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"Frontend build: {FRONTEND_DIR / 'dist'}")
    print(f"Backend:  {backend_url}")
    print("Press Ctrl+C to stop the backend.")

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
