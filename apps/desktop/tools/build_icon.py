"""assets/icon.svg·icon-mark.svg에서 윈도우용 icon.ico(여러 크기)를 만든다.

아이콘을 바꿀 때만 개발자가 한 번 돌리는 도구다(결과물 icon.ico는 저장소에 들어 있어서 사용자는 이걸 돌릴 필요가 없다).
SVG를 그리는 데는 윈도우에 기본으로 있는 Edge(headless)를 쓰고, ICO로 묶는 데는 Pillow를 쓴다:

    uv run --with pillow python apps/desktop/tools/build_icon.py

작은 크기(16~32px)에서는 책 쌓기가 뭉개지므로 책으로 만든 w만 굵게 그린 mark를, 48px 이상에서는 전체 아이콘(w + 쌓은 책)을 쓴다.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parent.parent / "src" / "desktop" / "assets"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
RENDER_SIZE = 512
FULL_SIZES = (256, 128, 64, 48)
MARK_SIZES = (32, 24, 16)


def render(svg: Path, out: Path) -> Image.Image:
    """SVG를 투명 배경의 큰 PNG로 그린다(작은 크기는 여기서 줄여 만든다)."""
    subprocess.run(
        [
            str(EDGE),
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
    with tempfile.TemporaryDirectory() as tmp:
        full = render(ASSETS / "icon.svg", Path(tmp) / "full.png")
        mark = render(ASSETS / "icon-mark.svg", Path(tmp) / "mark.png")
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
