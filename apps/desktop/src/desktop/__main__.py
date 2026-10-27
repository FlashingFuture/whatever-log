"""apps/ui(Vite로 빌드한 조회 화면)를 네이티브 창(webview)으로 띄운다.

개발 중엔 Vite dev server를 가리키고(HMR을 그대로 쓸 수 있음), 빌드 후엔
apps/ui/dist/index.html을 file://로 직접 연다 — pywebview가 OS의 네이티브
webview(Windows는 WebView2)를 그대로 쓰기 때문에, Electron처럼 Chromium을
따로 묶어 배포하지 않는다 (docs/2026-10-desktop-ui-framework.md 참고).

사용법:
    uv run python -m desktop            # 빌드된 apps/ui/dist 열기
    uv run python -m desktop --dev      # Vite dev server(기본 http://localhost:5173) 열기
"""

import argparse
from pathlib import Path

import webview

DEV_SERVER_URL = "http://localhost:5173"

_UI_DIST_INDEX = Path(__file__).resolve().parents[3] / "ui" / "dist" / "index.html"


def _resolve_url(use_dev_server: bool) -> str:
    """열 URL을 결정한다 — dev면 Vite dev server, 아니면 빌드된 정적 파일(file://)."""
    if use_dev_server:
        return DEV_SERVER_URL

    if not _UI_DIST_INDEX.exists():
        raise FileNotFoundError(
            f"빌드된 UI를 찾을 수 없습니다: {_UI_DIST_INDEX}\n"
            "apps/ui에서 `pnpm run build`를 먼저 실행하세요."
        )
    return _UI_DIST_INDEX.as_uri()


def main() -> None:
    """CLI 인자(`--dev`)를 파싱해서 webview 창을 띄운다."""
    parser = argparse.ArgumentParser(description="whatever.log 데스크톱 창")
    parser.add_argument(
        "--dev",
        action="store_true",
        help=f"빌드된 파일 대신 Vite dev server({DEV_SERVER_URL})를 연다",
    )
    args = parser.parse_args()

    webview.create_window("whatever.log", _resolve_url(args.dev))
    webview.start()


if __name__ == "__main__":
    main()
