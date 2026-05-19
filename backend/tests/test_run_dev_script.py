from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def load_run_dev() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "run_dev.py"
    spec = importlib.util.spec_from_file_location("run_dev_for_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class InteractiveStdin:
    def isatty(self) -> bool:
        return True


def test_ensure_backend_env_creates_first_run_config(tmp_path, monkeypatch) -> None:
    run_dev = load_run_dev()
    env_path = tmp_path / ".env"
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("PROFITS_CHECK_BOOTSTRAP_PASSWORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(run_dev.sys, "stdin", InteractiveStdin())
    monkeypatch.setattr(run_dev.getpass, "getpass", lambda _: "correct horse battery staple")

    run_dev.ensure_backend_env(env_path)

    content = env_path.read_text()
    assert "APP_ENCRYPTION_KEY=" in content
    assert "PROFITS_CHECK_BOOTSTRAP_PASSWORD=correct horse battery staple" in content
    assert "DATABASE_URL=sqlite:///./data/app.db" in content
    assert "PROFITS_CHECK_ALLOWED_HOSTS=" in content
    assert oct(env_path.stat().st_mode & 0o777) == "0o600"


def test_ensure_backend_env_refuses_noninteractive_missing_password(tmp_path, monkeypatch) -> None:
    run_dev = load_run_dev()
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("PROFITS_CHECK_BOOTSTRAP_PASSWORD", raising=False)

    class NonInteractiveStdin:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr(run_dev.sys, "stdin", NonInteractiveStdin())

    try:
        run_dev.ensure_backend_env(tmp_path / ".env")
    except RuntimeError as exc:
        assert "PROFITS_CHECK_BOOTSTRAP_PASSWORD" in str(exc)
    else:
        raise AssertionError("Expected missing noninteractive password to fail")


def test_ensure_tool_installs_when_missing(monkeypatch) -> None:
    run_dev = load_run_dev()
    calls: list[str] = []
    lookup_results = iter([None, "/tmp/bin/uv"])
    monkeypatch.setattr(run_dev, "which", lambda *_args, **_kwargs: next(lookup_results))
    monkeypatch.setattr(
        run_dev, "install_shell_script", lambda _url, name, _env: calls.append(name)
    )

    run_dev.ensure_tool("uv", "https://example.invalid/uv.sh", {"PATH": "/tmp/bin"})

    assert calls == ["uv"]


def test_sync_dependencies_skips_when_stamp_matches(tmp_path, monkeypatch) -> None:
    run_dev = load_run_dev()
    required_path = tmp_path / ".venv"
    stamp_path = required_path / ".profits-check-sync"
    lock_file = tmp_path / "uv.lock"
    required_path.mkdir()
    lock_file.write_text("locked")
    signature = run_dev.dependency_signature([lock_file])
    stamp_path.write_text(signature)
    calls: list[list[str]] = []
    monkeypatch.setattr(run_dev, "run_command", lambda command, _cwd, _env: calls.append(command))

    run_dev.sync_dependencies(
        label="backend",
        command=["uv", "sync"],
        cwd=tmp_path,
        env={"PATH": ""},
        required_path=required_path,
        stamp_path=stamp_path,
        signature_paths=[lock_file],
    )

    assert calls == []


def test_sync_dependencies_installs_when_lock_changes(tmp_path, monkeypatch) -> None:
    run_dev = load_run_dev()
    required_path = tmp_path / "node_modules"
    stamp_path = required_path / ".profits-check-install"
    lock_file = tmp_path / "bun.lock"
    required_path.mkdir()
    lock_file.write_text("new-lock")
    stamp_path.write_text("old-lock")
    calls: list[list[str]] = []
    monkeypatch.setattr(run_dev, "run_command", lambda command, _cwd, _env: calls.append(command))

    run_dev.sync_dependencies(
        label="frontend",
        command=["bun", "install"],
        cwd=tmp_path,
        env={"PATH": ""},
        required_path=required_path,
        stamp_path=stamp_path,
        signature_paths=[lock_file],
    )

    assert calls == [["bun", "install"]]
    assert stamp_path.read_text() == run_dev.dependency_signature([lock_file])


def test_main_builds_frontend_and_starts_backend_only(monkeypatch) -> None:
    run_dev = load_run_dev()
    commands: list[tuple[list[str], Path]] = []
    started: list[tuple[str, list[str], Path]] = []

    class FinishedProcess:
        def poll(self) -> int:
            return 0

    monkeypatch.setattr(run_dev, "ensure_backend_env", lambda: None)
    monkeypatch.setattr(run_dev, "build_env", lambda: {"PATH": "/tmp/bin"})
    monkeypatch.setattr(run_dev, "ensure_tool", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        run_dev,
        "sync_dependencies",
        lambda **kwargs: commands.append((kwargs["command"], kwargs["cwd"])),
    )
    monkeypatch.setattr(
        run_dev,
        "run_command",
        lambda command, cwd, _env=None: commands.append((command, cwd)),
    )
    monkeypatch.setattr(run_dev.signal, "signal", lambda *_args, **_kwargs: None)

    def fake_start_process(name, command, cwd, _env=None):
        started.append((name, command, cwd))
        return FinishedProcess()

    monkeypatch.setattr(run_dev, "start_process", fake_start_process)

    assert run_dev.main() == 0

    assert (["bun", "run", "build"], run_dev.FRONTEND_DIR) in commands
    assert started == [
        (
            "backend",
            [
                "uv",
                "run",
                "uvicorn",
                "profits_check_backend.main:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                "8200",
            ],
            run_dev.BACKEND_DIR,
        )
    ]
