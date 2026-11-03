"""URL에서 사이트(도메인)만 뽑는 규칙."""

from urllib.parse import urlsplit


def domain_of(url: str) -> str | None:
    """URL에서 도메인(호스트)만 남긴다. http(s)가 아니거나 호스트가 없으면 None.

    앞의 "www."는 같은 사이트로 묶기 위해 뗀다. 경로·쿼리·해시는 버린다.
    """
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host:
        return None
    return host.removeprefix("www.")
