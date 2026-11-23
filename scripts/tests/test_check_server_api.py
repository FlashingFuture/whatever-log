import importlib.util
import re
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "check_server_api", Path(__file__).resolve().parents[1] / "check_server_api.py"
)
check_server_api = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_server_api)

ROOT = Path(__file__).resolve().parents[2]


def _serving(payload):
    return lambda url: payload


def test_a_server_at_or_above_the_required_contract_passes() -> None:
    ok, message = check_server_api.check("https://s", 2, _serving({"api": 2, "commit": "abc"}))
    assert ok and "abc" in message
    assert check_server_api.check("https://s", 2, _serving({"api": 3, "commit": None}))[0]


def test_a_server_behind_the_app_stops_the_release() -> None:
    ok, message = check_server_api.check("https://s", 2, _serving({"api": 1, "commit": "old"}))
    assert not ok and "서버를 먼저 배포" in message


@pytest.mark.parametrize("payload", [{"ok": True}, {"api": "2"}, {"api": True}, [], None])
def test_a_server_without_a_usable_version_stops_the_release(payload) -> None:
    assert check_server_api.check("https://s", 2, _serving(payload))[0] is False


def test_an_unreachable_server_stops_the_release() -> None:
    def broken(url):
        raise OSError("down")

    ok, message = check_server_api.check("https://s", 2, broken)
    assert not ok and "읽지 못했습니다" in message


def test_the_app_and_the_server_agree_on_the_current_contract() -> None:
    """같은 저장소의 앱과 서버는 같은 계약 번호여야 한다(서버를 올리고 앱의 요구를 안 올리거나, 그 반대를 막는다)."""
    from cloud.compat import REQUIRED_SERVER_API

    server = (ROOT / "apps" / "server" / "src" / "version.ts").read_text(encoding="utf-8")
    assert f"export const API_VERSION = {REQUIRED_SERVER_API};" in server


DEPLOY = ROOT / ".github" / "workflows" / "deploy-server.yml"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"


def test_the_deploy_waits_for_approval_and_migrates_before_deploying() -> None:
    workflow = DEPLOY.read_text(encoding="utf-8")

    assert "name: production" in workflow  # 승인자가 있는 환경 — 배포 기록이 남는다
    assert workflow.index("pnpm test") < workflow.index("migrations apply DB --remote") < workflow.index("wrangler deploy")
    assert 'COMMIT_SHA:${GITHUB_SHA}' in workflow and "/version" in workflow
    assert "cancel-in-progress: false" in workflow  # 마이그레이션 도중에 끊지 않는다
    assert workflow.count("actions/checkout@") == workflow.count("persist-credentials: false") == 1


def test_the_release_checks_the_server_before_building() -> None:
    workflow = RELEASE.read_text(encoding="utf-8")

    check = workflow.index("scripts/check_server_api.py")
    assert check < workflow.index("scripts/build_release.py")
    step = workflow[workflow.rindex("- name:", 0, check) : check]
    assert "continue-on-error: ${{ github.ref_type != 'tag' }}" in step  # 태그(출시)에서는 멈춘다


def test_the_cloudflare_token_is_only_given_to_the_steps_that_deploy() -> None:
    """토큰은 마이그레이션·배포 단계에만 — 의존성 설치 스크립트나 테스트 코드가 읽지 못하게."""
    workflow = DEPLOY.read_text(encoding="utf-8")
    first_use = workflow.index("secrets.CLOUDFLARE_API_TOKEN")

    assert workflow.index("pnpm test") < first_use  # 그 전의 단계(설치·검사)에는 없다
    assert workflow.count("secrets.CLOUDFLARE_API_TOKEN") == 2
    assert "--filter server..." in workflow


def test_the_deploy_refuses_to_go_back_to_an_older_contract_before_migrating() -> None:
    workflow = DEPLOY.read_text(encoding="utf-8")

    guard = workflow.index("운영보다 뒤로 가지 않는지 확인")
    assert guard < workflow.index("migrations apply DB --remote")
    assert "allow_downgrade" in workflow and "jq -e --arg c" in workflow


def test_actions_that_see_the_deploy_token_are_pinned_to_a_commit() -> None:
    workflow = DEPLOY.read_text(encoding="utf-8")
    uses = re.findall(r"uses: (\S+)", workflow)

    assert uses and all(re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", use) for use in uses)


def test_the_release_checkout_does_not_keep_the_write_token() -> None:
    workflow = RELEASE.read_text(encoding="utf-8")

    assert workflow.count("actions/checkout@") == workflow.count("persist-credentials: false") == 1


def test_the_server_has_no_local_deploy_script() -> None:
    """로컬에서 운영에 배포하지 않는다(docs/deploy.md 규칙 4)."""
    package = (ROOT / "apps" / "server" / "package.json").read_text(encoding="utf-8")

    assert '"deploy"' not in package
