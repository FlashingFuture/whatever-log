"""`whatever-log update --check` — 지금 버전과 GitHub의 가장 새 버전을 견줘 알린다(받기·설치는 하지 않는다)."""

from common.updates import RELEASES_PAGE, UpdateCheckFailed

from launcher.__main__ import build_parser, check_update


def run(fetch):
    lines: list[str] = []
    ok = check_update(lines.append, fetch=fetch)
    return ok, "\n".join(lines)


def test_a_newer_release_is_announced_with_its_page(monkeypatch) -> None:
    monkeypatch.setattr("common.paths.version", lambda root=None: "1.0.0-beta.2")
    ok, out = run(lambda: [{"tag_name": "v1.0.0", "draft": False, "prerelease": False, "html_url": f"{RELEASES_PAGE}/tag/v1.0.0"}])
    assert ok and "새 버전 1.0.0" in out and f"{RELEASES_PAGE}/tag/v1.0.0" in out


def test_being_up_to_date_and_failing_to_ask(monkeypatch) -> None:
    monkeypatch.setattr("common.paths.version", lambda root=None: "1.0.0")
    assert run(lambda: [])[0] is True
    assert "최신 버전" in run(lambda: [])[1]

    def broken():
        raise UpdateCheckFailed("URLError")

    ok, out = run(broken)
    assert ok is False and "확인하지 못했어요" in out


def test_the_command_needs_the_check_flag() -> None:
    assert build_parser().parse_args(["update", "--check"]).command == "update"
