from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from desktop_app.utils.docker_manager import DockerManager


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_docker_manager_resolves_app_image_from_process_env(monkeypatch):
    monkeypatch.setenv("APP_IMAGE", "ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab")
    manager = DockerManager(PROJECT_ROOT)

    assert manager._resolve_app_image() == "ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab"


def test_docker_manager_resolves_app_image_from_windows_user_env(monkeypatch):
    monkeypatch.delenv("APP_IMAGE", raising=False)
    manager = DockerManager(PROJECT_ROOT)

    with patch.object(manager, "_read_windows_user_env", return_value="ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab"):
        assert manager._resolve_app_image() == "ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab"


def test_run_compose_command_uses_env_file_and_cleans_up(monkeypatch, tmp_path):
    manager = DockerManager(tmp_path)
    monkeypatch.setenv("APP_IMAGE", "ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab")

    captured = {}

    def fake_run(cmd, cwd, capture_output, text, timeout):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["timeout"] = timeout
        env_file = Path(cmd[3])
        captured["env_file_exists_during_run"] = env_file.exists()
        captured["env_file_contents"] = env_file.read_text(encoding="utf-8")
        return CompletedProcess(cmd, 0, stdout="ok", stderr="")

    with patch("desktop_app.utils.docker_manager.subprocess.run", side_effect=fake_run):
        result = manager._run_compose_command(["pull"], timeout=300)

    assert result.returncode == 0
    assert captured["cmd"][:3] == ["docker", "compose", "--env-file"]
    assert captured["cmd"][4:] == ["pull"]
    assert captured["cwd"] == str(tmp_path)
    assert captured["timeout"] == 300
    assert captured["env_file_exists_during_run"] is True
    assert captured["env_file_contents"] == "APP_IMAGE=ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab\n"
    assert not Path(captured["cmd"][3]).exists()


def test_pull_images_uses_compose_env_file(monkeypatch, tmp_path):
    manager = DockerManager(tmp_path)
    monkeypatch.setenv("APP_IMAGE", "ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab")

    with patch.object(manager, "_run_compose_command", return_value=CompletedProcess(["docker"], 0, stdout="", stderr="")) as mock_run:
        success, message = manager.pull_images()

    assert success is True
    assert "updated successfully" in message
    mock_run.assert_called_once_with(["pull"], timeout=300)


def test_start_containers_force_pull_uses_compose_env_file(monkeypatch, tmp_path):
    manager = DockerManager(tmp_path)
    monkeypatch.setenv("APP_IMAGE", "ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab")

    statuses = [(False, False), (True, True), (True, True), (True, True), (True, True)]

    with patch.object(manager, "check_daemon_connection", return_value=(True, "")), \
         patch.object(manager, "pull_images", return_value=(True, "ok")) as mock_pull, \
         patch.object(manager, "get_container_status", side_effect=statuses), \
         patch.object(manager, "_run_compose_command", return_value=CompletedProcess(["docker"], 0, stdout="", stderr="")) as mock_run, \
         patch("desktop_app.utils.docker_manager.time.sleep", return_value=None):
        success, message = manager.start_containers(force_pull=True)

    assert success is True
    assert "Containers started successfully" in message
    mock_pull.assert_called_once_with()
    mock_run.assert_called_once_with(["up", "-d", "--force-recreate"], timeout=120)


def test_stop_containers_uses_compose_env_file(monkeypatch, tmp_path):
    manager = DockerManager(tmp_path)
    monkeypatch.setenv("APP_IMAGE", "ghcr.io/valginer0/pgvectorragindexer:debug-windows-license-org-tab")

    with patch.object(manager, "_run_compose_command", return_value=CompletedProcess(["docker"], 0, stdout="", stderr="")) as mock_run:
        success, message = manager.stop_containers()

    assert success is True
    assert message == "Containers stopped successfully"
    mock_run.assert_called_once_with(["down"], timeout=60)
