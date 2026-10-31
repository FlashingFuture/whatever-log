"""프로세스의 exe에서 아이콘을 뽑아 PNG로 캐싱해 돌려준다.

차트의 프로세스 줄마다 아이콘을 보여주기 위한 모듈이다. Windows 전용 API(user32/
gdi32)를 쓰고, 추가 의존성(Pillow 등) 없이 ctypes + zlib만으로 PNG를 만든다.

캐싱은 세 겹이다 (바깥 → 안쪽):

1. 브라우저: hub가 ETag + Cache-Control을 붙여서 보낸다(__main__). 15초마다 차트가
   다시 그려져도 같은 이미지를 다시 받지 않는다.
2. 메모리(IconStore._memory): 키 → PNG 바이트. 같은 아이콘이 여러 번 요청돼도
   디스크를 다시 읽지 않는다.
3. 디스크(cache_dir/<키>.png): hub를 다시 띄워도 추출을 반복하지 않는다.

키는 `sha256(경로 + 수정시각 + 크기)`다. 앱이 업데이트돼 exe가 바뀌면 키도 바뀌어
자동으로 새 아이콘이 만들어지고, 오래된 파일은 그냥 안 쓰이게 된다(정리는 하지
않는다 — 파일당 몇 KB라 쌓이는 양이 미미하다).

추출에 실패한 경로(아이콘 없음, 접근 불가 등)는 일정 시간 동안 "없음"으로 기억해서
같은 요청마다 Win32 호출을 되풀이하지 않는다.
"""

import ctypes
import hashlib
import struct
import sys
import threading
import time
import zlib
from collections import OrderedDict
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path

ICON_SIZE = 64  # 표시 크기(~20px)의 HiDPI 3배 정도. PNG 한 장이 몇 KB 수준이다.

# 아이콘이 없다고 판단한 결과를 기억하는 시간. 잠깐의 실패(파일 잠금 등)가 영원히
# 남지 않도록 유한하게 둔다.
_NEGATIVE_TTL_SECONDS = 300.0
_MEMORY_ENTRIES = 256


def encode_png(width: int, height: int, rgba: bytes) -> bytes:
    """RGBA 8비트 픽셀(위에서 아래, 행 우선)을 PNG 바이트로 인코딩한다."""
    if len(rgba) != width * height * 4:
        raise ValueError("픽셀 수가 width*height*4와 맞지 않습니다.")
    stride = width * 4
    # 각 행 앞에 필터 타입 0(없음)을 붙인다.
    raw = b"".join(b"\x00" + rgba[y * stride : (y + 1) * stride] for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def extract_icon_png(exe_path: str, size: int = ICON_SIZE) -> bytes | None:
    """exe의 아이콘을 size×size PNG로 뽑는다. 아이콘이 없거나 실패하면 None."""
    if sys.platform != "win32":
        raise NotImplementedError(f"{sys.platform}은 아직 지원하지 않습니다.")
    pixels = _icon_pixels(exe_path, size)
    if pixels is None:
        return None
    return encode_png(size, size, pixels)


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _IconInfo(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


def _icon_pixels(exe_path: str, size: int) -> bytes | None:
    # WinDLL(use_last_error 없이)로 따로 로드해서 argtypes를 이 모듈 안에서만 건다
    # — ctypes.windll은 프로세스 전역이라 recorder 쪽 선언과 섞이지 않게 한다.
    user32 = ctypes.WinDLL("user32")
    gdi32 = ctypes.WinDLL("gdi32")

    # 핸들 타입을 지정하지 않으면 64비트에서 값이 잘린다(window_snapshot.py와 같은 함정).
    user32.PrivateExtractIconsW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(wintypes.HICON),
        ctypes.POINTER(wintypes.UINT),
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.PrivateExtractIconsW.restype = wintypes.UINT
    user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(_IconInfo)]
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC,
        wintypes.HBITMAP,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.UINT,
    ]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]

    icon = wintypes.HICON()
    # 파일 안의 여러 크기 중 size에 가장 가까운 것을 골라 준다.
    extracted = user32.PrivateExtractIconsW(exe_path, 0, size, size, ctypes.byref(icon), None, 1, 0)
    if extracted < 1 or not icon:
        return None

    info = _IconInfo()
    color_bits: bytes | None = None
    mask_bits: bytes | None = None
    mono_bits: bytes | None = None
    try:
        if not user32.GetIconInfo(icon, ctypes.byref(info)):
            return None
        try:
            hdc = user32.GetDC(None)
            try:
                if info.hbmColor:
                    color_bits = _dib_bits(gdi32, hdc, info.hbmColor, size, size)
                    mask_bits = _dib_bits(gdi32, hdc, info.hbmMask, size, size)
                else:
                    # 모노크롬 아이콘은 색 비트맵이 없고, 마스크 하나가 두 배 높이다
                    # (위 절반 = AND 마스크, 아래 절반 = XOR 마스크).
                    mono_bits = _dib_bits(gdi32, hdc, info.hbmMask, size, size * 2)
            finally:
                user32.ReleaseDC(None, hdc)
        finally:
            for bitmap in (info.hbmColor, info.hbmMask):
                if bitmap:
                    gdi32.DeleteObject(bitmap)
    finally:
        user32.DestroyIcon(icon)

    if color_bits is not None:
        return _to_rgba(color_bits, mask_bits)
    if mono_bits is not None:
        return _monochrome_to_rgba(mono_bits, size)
    return None


def _dib_bits(gdi32, hdc, bitmap, width: int, height: int) -> bytes | None:
    """비트맵을 위에서 아래 순서의 32비트 BGRA 픽셀로 읽는다."""
    if not bitmap:
        return None
    header = _BitmapInfoHeader()
    header.biSize = ctypes.sizeof(_BitmapInfoHeader)
    header.biWidth = width
    header.biHeight = -height  # 음수 = 위에서 아래
    header.biPlanes = 1
    header.biBitCount = 32
    buffer = ctypes.create_string_buffer(width * height * 4)
    # 비트맵 크기가 요청과 다르면 이 아이콘은 포기한다(GetDIBits가 0을 돌려준다).
    if gdi32.GetDIBits(hdc, bitmap, 0, height, buffer, ctypes.byref(header), 0) == 0:
        return None
    return buffer.raw


def _to_rgba(color_bgra: bytes, mask_bgra: bytes | None) -> bytes:
    """BGRA → RGBA. 알파 채널이 없는 옛 아이콘은 마스크(검정=불투명)로 알파를 만든다."""
    pixels = bytearray(color_bgra)
    if not any(pixels[3::4]):
        for i in range(0, len(pixels), 4):
            opaque = mask_bgra is None or mask_bgra[i] == 0
            pixels[i + 3] = 255 if opaque else 0
    # B와 R을 맞바꾼다.
    pixels[0::4], pixels[2::4] = pixels[2::4], pixels[0::4]
    return bytes(pixels)


def _monochrome_to_rgba(mask_bgra: bytes, size: int) -> bytes:
    """모노크롬 아이콘(두 배 높이 마스크: 위 AND, 아래 XOR)을 RGBA로 바꾼다.

    AND=0,XOR=0 → 검정, AND=0,XOR=1 → 흰색, AND=1,XOR=0 → 투명. AND=1,XOR=1은 배경을
    뒤집는 "반전"이라 화면 위가 아니면 뜻이 없어서 투명으로 둔다.
    """
    pixels = bytearray(size * size * 4)
    xor_offset = size * size * 4
    for i in range(0, size * size * 4, 4):
        and_bit = mask_bgra[i] != 0
        xor_bit = mask_bgra[xor_offset + i] != 0
        if and_bit:
            continue  # 투명(0,0,0,0)
        value = 255 if xor_bit else 0
        pixels[i : i + 4] = bytes((value, value, value, 255))
    return bytes(pixels)


class IconStore:
    """exe 경로 → PNG. 위 모듈 설명의 메모리·디스크 캐시와 실패 기억을 맡는다."""

    def __init__(
        self,
        cache_dir: Path,
        extract: Callable[[str], bytes | None] = extract_icon_png,
    ) -> None:
        self._cache_dir = cache_dir
        self._extract = extract
        self._memory: OrderedDict[str, bytes] = OrderedDict()
        self._missing_until: dict[str, float] = {}
        # 같은 아이콘을 여러 요청이 동시에 달라고 해도 추출은 한 번만 하도록 키별로
        # 잠근다(차트가 한꺼번에 이미지를 요청하므로 흔한 상황이다).
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, exe_path: str) -> tuple[str, bytes] | None:
        """(키, PNG 바이트)를 돌려준다. 키는 ETag로 쓸 수 있다. 없으면 None."""
        key = self.key_for(exe_path)
        if key is None:
            return None

        png = self._from_memory(key)
        if png is not None:
            return key, png
        if self._is_known_missing(key):
            return None

        with self._lock_for(key):
            png = self._from_memory(key)
            if png is not None:
                return key, png

            disk_path = self._cache_dir / f"{key}.png"
            try:
                png = disk_path.read_bytes()
            except OSError:
                png = None

            if png is None:
                png = self._safe_extract(exe_path)
                if png is not None:
                    self._write_disk(disk_path, png)

            if png is None:
                with self._guard:
                    self._missing_until[key] = time.monotonic() + _NEGATIVE_TTL_SECONDS
                return None
            self._remember(key, png)
            return key, png

    @staticmethod
    def key_for(exe_path: str) -> str | None:
        """경로 + 수정시각 + 크기로 만든 키. 파일이 없으면 None."""
        try:
            stat = Path(exe_path).stat()
        except OSError:
            return None
        material = f"{exe_path}|{stat.st_mtime_ns}|{stat.st_size}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

    def _safe_extract(self, exe_path: str) -> bytes | None:
        try:
            return self._extract(exe_path)
        except Exception:
            # 아이콘은 장식이라 추출 실패가 API 전체 오류가 되면 안 된다.
            return None

    def _write_disk(self, path: Path, png: bytes) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            # 쓰다 만 파일이 깨진 이미지로 읽히지 않게 임시 파일에 쓰고 바꿔치기한다.
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(png)
            tmp.replace(path)
        except OSError:
            pass  # 디스크 캐시는 최적화일 뿐이다 — 메모리에는 남는다.

    def _from_memory(self, key: str) -> bytes | None:
        with self._guard:
            png = self._memory.get(key)
            if png is not None:
                self._memory.move_to_end(key)
            return png

    def _remember(self, key: str, png: bytes) -> None:
        with self._guard:
            self._memory[key] = png
            self._memory.move_to_end(key)
            while len(self._memory) > _MEMORY_ENTRIES:
                self._memory.popitem(last=False)

    def _is_known_missing(self, key: str) -> bool:
        with self._guard:
            until = self._missing_until.get(key)
            if until is None:
                return False
            if time.monotonic() >= until:
                del self._missing_until[key]
                return False
            return True

    def _lock_for(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())
