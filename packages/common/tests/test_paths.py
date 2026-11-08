import json

import pytest
from common import paths


@pytest.fixture
def root(tmp_path):
    """저장소(또는 번들) 루트를 흉내 낸 임시 폴더."""
    (tmp_path / "VERSION").write_text("1.0.0-beta.1\n", encoding="utf-8")
    return tmp_path


def _bundle(root, version="1.0.0-beta.1"):
    (root / paths.BUNDLE_MARKER).write_text(json.dumps({"version": version}), encoding="utf-8")


def test_a_development_checkout_has_no_data_dir_so_apps_keep_their_own_folders(root) -> None:
    assert paths.bundle_info(root) is None
    assert paths.data_dir(root, {}) is None


def test_a_release_bundle_keeps_data_in_local_app_data(root, tmp_path) -> None:
    _bundle(root)
    local = tmp_path / "local"

    folder = paths.data_dir(root, {"LOCALAPPDATA": str(local)})

    assert folder == local / "whatever.log" and folder.is_dir()  # 만들어 둔다


def test_the_environment_variable_overrides_both_shapes(root, tmp_path) -> None:
    target = tmp_path / "elsewhere"
    assert paths.data_dir(root, {paths.DATA_DIR_ENV: str(target)}) == target
    _bundle(root)
    assert paths.data_dir(root, {paths.DATA_DIR_ENV: str(target), "LOCALAPPDATA": str(tmp_path)}) == target


def test_a_bundle_without_local_app_data_fails_loudly_instead_of_writing_beside_the_code(root) -> None:
    _bundle(root)

    with pytest.raises(RuntimeError, match="LOCALAPPDATA"):
        paths.data_dir(root, {})


@pytest.mark.parametrize("content", ["not json", "[1, 2]", ""])
def test_a_broken_marker_is_not_a_bundle(root, content) -> None:
    (root / paths.BUNDLE_MARKER).write_text(content, encoding="utf-8")

    assert paths.bundle_info(root) is None


def test_data_path_uses_the_legacy_folder_in_development(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(paths, "data_dir", lambda *a, **k: None)

    assert paths.data_path(tmp_path / "apps" / "hub", "goals.db") == tmp_path / "apps" / "hub" / "goals.db"
    assert paths.data_path(tmp_path / "apps" / "hub", "hub.log", subdir="logs") == tmp_path / "apps" / "hub" / "hub.log"


def test_data_path_puts_logs_in_a_subfolder_and_databases_at_the_top_when_deployed(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(paths, "data_dir", lambda *a, **k: tmp_path / "data")
    (tmp_path / "data").mkdir()

    assert paths.data_path(tmp_path / "legacy", "goals.db") == tmp_path / "data" / "goals.db"
    log = paths.data_path(tmp_path / "legacy", "hub.log", subdir="logs")
    assert log == tmp_path / "data" / "logs" / "hub.log" and log.parent.is_dir()


def test_every_app_resolves_the_shared_files_to_the_same_place(monkeypatch, tmp_path) -> None:
    """hub는 recorder.db와 sync.db를, 동기화 에이전트는 goals.db를 앱 경계를 넘어 연다. 배포 모양에서 어긋나면 서로 다른 DB를 보게 된다."""
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path))
    import importlib

    import hub.__main__ as hub_main
    import recorder.__main__ as recorder_main
    import sync_agent.__main__ as sync_main

    for module in (recorder_main, hub_main, sync_main):
        importlib.reload(module)
    try:
        assert hub_main.DEFAULT_DB_PATH == recorder_main.DEFAULT_DB_PATH == tmp_path / "recorder.db"
        assert hub_main.DEFAULT_GOALS_DB_PATH == sync_main.DEFAULT_GOALS_DB == tmp_path / "goals.db"
        assert hub_main.DEFAULT_SYNC_DB_PATH == sync_main.DEFAULT_STATE_PATH == tmp_path / "sync.db"
        assert hub_main.DEFAULT_LOG_PATH == tmp_path / "logs" / "hub.log"
    finally:
        monkeypatch.undo()
        for module in (recorder_main, hub_main, sync_main):
            importlib.reload(module)


def test_version_comes_from_the_marker_in_a_bundle_and_is_marked_dev_otherwise(root) -> None:
    assert paths.version(root) == "1.0.0-beta.1 (개발)"
    _bundle(root, "2.0.0")
    assert paths.version(root) == "2.0.0"


def test_version_survives_a_missing_file(tmp_path) -> None:
    assert paths.version(tmp_path) == "알 수 없음"
