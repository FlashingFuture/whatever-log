import json

import pytest

from chromium.profiles import profile_folders, read_profile_names
from chromium.urls import domain_of


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.youtube.com/watch?v=abc#t=1", "youtube.com"),
        ("http://Docs.Example.COM:8080/a/b", "docs.example.com"),
        ("https://127.0.0.1:8787/api", "127.0.0.1"),
        ("chrome://settings", None),
        ("file:///C:/a.txt", None),
        ("https:///nohost", None),
        ("not a url", None),
    ],
)
def test_domain_of_keeps_only_the_host(url: str, expected: str | None) -> None:
    assert domain_of(url) == expected


def _write_local_state(root, names: dict[str, str]) -> None:
    info = {folder: {"name": name} for folder, name in names.items()}
    (root / "Local State").write_text(json.dumps({"profile": {"info_cache": info}}), encoding="utf-8")


def test_reads_profile_names_and_tolerates_a_missing_or_broken_file(tmp_path) -> None:
    assert read_profile_names(tmp_path) == {}
    (tmp_path / "Local State").write_text("not json", encoding="utf-8")
    assert read_profile_names(tmp_path) == {}
    _write_local_state(tmp_path, {"Default": "개인"})
    assert read_profile_names(tmp_path) == {"Default": "개인"}


def test_profile_folders_prefers_local_state_and_falls_back_to_folder_names(tmp_path) -> None:
    for folder in ("Default", "Profile 1", "Crashpad", "Guest Profile"):
        (tmp_path / folder).mkdir()
    (tmp_path / "Local State.bak").write_text("x", encoding="utf-8")

    assert profile_folders(tmp_path) == ["Default", "Profile 1"]

    _write_local_state(tmp_path, {"Profile 1": "업무"})
    assert profile_folders(tmp_path) == ["Profile 1"]
    assert profile_folders(tmp_path / "missing") == []


def test_browser_table_maps_each_process_to_one_browser() -> None:
    from chromium.browsers import BROWSER_BY_PROCESS, BROWSERS

    assert len(BROWSER_BY_PROCESS) == len(BROWSERS)
    assert BROWSER_BY_PROCESS["msedge.exe"].key == "edge"
    assert "Microsoft Edge" in BROWSER_BY_PROCESS["msedge.exe"].title_labels


def test_user_data_dir_is_under_local_app_data(monkeypatch) -> None:
    from chromium.browsers import BROWSER_BY_PROCESS

    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\me\AppData\Local")

    brave = BROWSER_BY_PROCESS["brave.exe"].user_data_dir()
    assert brave.parts[-3:] == ("BraveSoftware", "Brave-Browser", "User Data")
