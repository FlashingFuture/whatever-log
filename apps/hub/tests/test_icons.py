import struct
import sys
import zlib
from pathlib import Path

import pytest

from hub.icons import IconStore, encode_png, extract_icon_png


def _decode_png(png: bytes) -> tuple[int, int, bytes]:
    """encode_png 결과를 다시 풀어 (너비, 높이, RGBA)로 돌려준다(필터 0 전제)."""
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, size = 8, b"", (0, 0)
    while pos < len(png):
        length, kind = struct.unpack(">I4s", png[pos : pos + 8])
        data = png[pos + 8 : pos + 8 + length]
        (crc,) = struct.unpack(">I", png[pos + 8 + length : pos + 12 + length])
        assert crc == zlib.crc32(kind + data)
        if kind == b"IHDR":
            size = struct.unpack(">II", data[:8])
        elif kind == b"IDAT":
            idat += data
        pos += 12 + length
    raw = zlib.decompress(idat)
    width, height = size
    stride = width * 4
    rows = [raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)] for y in range(height)]
    assert all(raw[y * (stride + 1)] == 0 for y in range(height))
    return width, height, b"".join(rows)


def test_encode_png_roundtrips_pixels() -> None:
    pixels = bytes([255, 0, 0, 255, 0, 255, 0, 128, 0, 0, 255, 0, 1, 2, 3, 4])

    assert _decode_png(encode_png(2, 2, pixels)) == (2, 2, pixels)


def test_encode_png_rejects_wrong_pixel_count() -> None:
    with pytest.raises(ValueError):
        encode_png(2, 2, b"\x00" * 3)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 전용 API")
def test_extracts_a_real_icon_from_an_exe() -> None:
    """실제 exe(이 테스트를 돌리는 python)에서 투명하지 않은 픽셀이 있는 아이콘이 나와야 한다."""
    png = extract_icon_png(sys.executable, size=32)

    assert png is not None
    width, height, pixels = _decode_png(png)
    assert (width, height) == (32, 32)
    assert any(pixels[3::4])  # 전부 투명이면 변환이 틀린 것


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 전용 API")
def test_returns_none_for_a_file_without_an_icon(tmp_path) -> None:
    plain = tmp_path / "plain.exe"
    plain.write_bytes(b"not an executable")

    assert extract_icon_png(str(plain)) is None


def _exe(tmp_path: Path, content: bytes = b"v1") -> str:
    path = tmp_path / "app.exe"
    path.write_bytes(content)
    return str(path)


def test_store_extracts_once_then_serves_from_memory_and_disk(tmp_path) -> None:
    calls = []

    def extract(path: str) -> bytes:
        calls.append(path)
        return b"PNG-BYTES"

    exe = _exe(tmp_path)
    store = IconStore(tmp_path / "cache", extract)

    first = store.get(exe)
    second = store.get(exe)
    assert first == second and first is not None and first[1] == b"PNG-BYTES"
    assert len(calls) == 1

    # 새 IconStore(= hub 재시작)는 디스크 캐시에서 읽고 다시 추출하지 않는다.
    restarted = IconStore(tmp_path / "cache", extract)
    assert restarted.get(exe) == first
    assert len(calls) == 1


def test_store_key_changes_when_the_exe_changes(tmp_path) -> None:
    """앱이 업데이트돼 exe가 바뀌면 캐시된 옛 아이콘을 쓰면 안 된다."""
    exe = _exe(tmp_path, b"v1")
    store = IconStore(tmp_path / "cache", lambda path: Path(path).read_bytes())
    old = store.get(exe)

    Path(exe).write_bytes(b"version-2-longer")
    new = store.get(exe)

    assert old is not None and new is not None
    assert old[0] != new[0]
    assert new[1] == b"version-2-longer"


def test_store_remembers_failures_and_returns_none_for_missing_files(tmp_path) -> None:
    calls = []

    def extract(path: str) -> None:
        calls.append(path)

    exe = _exe(tmp_path)
    store = IconStore(tmp_path / "cache", extract)

    assert store.get(exe) is None
    assert store.get(exe) is None
    assert len(calls) == 1  # 두 번째는 실패 기억으로 건너뜀
    assert store.get(str(tmp_path / "gone.exe")) is None


def test_store_treats_extractor_exceptions_as_missing(tmp_path) -> None:
    def extract(path: str) -> bytes:
        raise OSError("boom")

    assert IconStore(tmp_path / "cache", extract).get(_exe(tmp_path)) is None
