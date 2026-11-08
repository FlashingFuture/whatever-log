"""assets/icon.svg·icon-mark.svg에서 윈도우용 icon.ico(여러 크기)를 만든다.

아이콘을 바꿀 때만 개발자가 한 번 돌리는 도구다(결과물 icon.ico는 저장소에 들어 있어서 사용자는 이걸 돌릴 필요가 없다).
SVG를 그리는 데는 윈도우에 기본으로 있는 Edge(headless)를 쓰고, ICO로 묶는 데는 Pillow를 쓴다:

    uv run --with pillow python apps/desktop/tools/build_icon.py
    uv run --with pillow python apps/desktop/tools/build_icon.py --edge "<msedge.exe 경로>"   # Edge가 다른 곳에 있을 때
    (환경변수 EDGE_PATH로도 줄 수 있다)

작은 크기(16~32px)에서는 세부가 뭉개지므로 굵게 그린 mark를, 48px 이상에서는 전체 아이콘을 쓴다(둘 다 책으로 만든 w + 세워 둔 책 한 권).
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parent.parent / "src" / "desktop" / "assets"
_EDGE_DEFAULT_LOCATIONS = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)
RENDER_SIZE = 512
FULL_SIZES = (256, 128, 64, 48)
MARK_SIZES = (32, 24, 16)


def find_edge(explicit: str | None = None) -> Path:
    """SVG를 그리는 데 쓸 Edge 실행 파일을 찾는다: 인자(--edge) → 환경변수 EDGE_PATH → 기본 설치 위치 → PATH 순서.

    못 찾으면 해결 방법을 담은 SystemExit(스택 트레이스 없이 안내만 보인다).
    """
    if explicit and not Path(explicit).is_file():
        # 직접 지정한 경로가 틀렸는데 조용히 다른 Edge로 넘어가면, 의도와 다른 것으로 그렸는지 알 수 없다
        raise SystemExit(f"--edge로 지정한 경로에 파일이 없어요: {explicit}")
    candidates = [Path(explicit)] if explicit else []
    from_env = os.environ.get("EDGE_PATH")
    if from_env and not explicit:
        if not Path(from_env).is_file():
            raise SystemExit(f"환경변수 EDGE_PATH가 가리키는 파일이 없어요: {from_env}")
        candidates.append(Path(from_env))
    candidates.extend(_EDGE_DEFAULT_LOCATIONS)
    on_path = shutil.which("msedge")
    if on_path:
        candidates.append(Path(on_path))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit(
        "Edge(msedge.exe)를 찾지 못했어요. 설치 위치를 알려 주세요:\n"
        '  uv run --with pillow python apps/desktop/tools/build_icon.py --edge "<msedge.exe 경로>"\n'
        "또는 환경변수 EDGE_PATH에 그 경로를 넣어 주세요."
    )


def render(edge: Path, svg: Path, out: Path) -> Image.Image:
    """SVG를 투명 배경의 큰 PNG로 그린다(작은 크기는 여기서 줄여 만든다)."""
    subprocess.run(
        [
            str(edge),
            "--headless",
            "--disable-gpu",
            "--default-background-color=00000000",
            f"--screenshot={out}",
            f"--window-size={RENDER_SIZE},{RENDER_SIZE}",
            svg.as_uri(),
        ],
        check=True,
        capture_output=True,
    )
    return Image.open(out).convert("RGBA")


def main() -> None:
    """두 SVG를 그려서 크기별 이미지를 한 icon.ico에 담고, 창 아이콘용 PNG도 함께 만든다."""
    parser = argparse.ArgumentParser(description="icon.svg·icon-mark.svg에서 icon.ico를 만든다")
    parser.add_argument("--edge", help="msedge.exe 경로(기본: 설치 위치를 찾아 본다)")
    edge = find_edge(parser.parse_args().edge)
    with tempfile.TemporaryDirectory() as tmp:
        full = render(edge, ASSETS / "icon.svg", Path(tmp) / "full.png")
        mark = render(edge, ASSETS / "icon-mark.svg", Path(tmp) / "mark.png")
    images = [full.resize((s, s), Image.LANCZOS) for s in FULL_SIZES]
    images += [mark.resize((s, s), Image.LANCZOS) for s in MARK_SIZES]
    images[0].save(
        ASSETS / "icon.ico",
        format="ICO",
        sizes=[(i.width, i.height) for i in images],
        append_images=images[1:],
    )
    full.resize((256, 256), Image.LANCZOS).save(ASSETS / "icon.png")
    sys.stdout.reconfigure(encoding="utf-8")
    print("만들었습니다:", ASSETS / "icon.ico")


if __name__ == "__main__":
    main()
