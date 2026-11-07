"""서버(`apps/server/src/sync/goalInput.ts`의 `nameKey`)와 이 패키지의 `name_key`가 모든 유니코드 글자에서 같은 묶음을 만드는지 확인한다.

두 키가 어긋나면 한쪽에서는 같은 이름이 다른 쪽에서는 다른 이름이 되어, 로컬에서 만든 두 목표 중 하나가 서버에서 거부되거나(서버가 더 합칠 때),
서버에서 둘로 올라간 목표를 내려받은 PC가 하나를 저장하지 못한다(덜 합칠 때). 서버 코드를 실제로 실행해 비교하므로 `node`(22.6 이상, TypeScript
직접 실행)가 있어야 하고, 없으면 건너뛴다.

파이썬과 Workers 런타임의 유니코드 버전이 다르면 새 버전에서 추가된 글자는 파이썬에서 아직 정의되지 않아(`Cn`) 비교할 수 없다 — 그런 글자는 뺀다.
"""

import json
import shutil
import subprocess
import unicodedata
from pathlib import Path

import pytest

from goals.validation import name_key

ROOT = Path(__file__).resolve().parents[3]
SERVER_KEY = ROOT / "apps" / "server" / "src" / "sync" / "goalInput.ts"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not SERVER_KEY.exists(), reason="node와 서버 소스가 있어야 한다"
)

_SCRIPT = f"""
import {{ nameKey }} from {json.dumps(SERVER_KEY.as_uri())};
const out = [];
for (let cp = 0; cp <= 0x10ffff; cp += 1) {{
  if (cp >= 0xd800 && cp <= 0xdfff) continue;
  out.push([cp, nameKey(String.fromCodePoint(cp))]);
}}
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def server_keys() -> dict[int, str]:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", _SCRIPT], capture_output=True, text=True, encoding="utf-8", timeout=120
    )
    if result.returncode != 0:
        pytest.skip(f"node가 서버 코드를 실행하지 못했다: {result.stderr[:200]}")
    return {cp: key for cp, key in json.loads(result.stdout)}


def _assigned(cp: int) -> bool:
    return unicodedata.category(chr(cp)) != "Cn"


def test_the_server_merges_exactly_the_characters_the_local_key_merges(server_keys) -> None:
    groups: dict[str, list[int]] = {}
    for cp in server_keys:
        if _assigned(cp):
            groups.setdefault(name_key(chr(cp)), []).append(cp)

    split = [  # 로컬은 같은 이름으로 보는데 서버는 다르게 보는 글자들
        [(hex(cp), server_keys[cp]) for cp in cps] for cps in groups.values() if len({server_keys[cp] for cp in cps}) > 1
    ]
    assert split == []

    by_server: dict[str, set[str]] = {}
    for cp, key in server_keys.items():
        if _assigned(cp):
            by_server.setdefault(key, set()).add(name_key(chr(cp)))
    merged = [(key, sorted(locals_)) for key, locals_ in by_server.items() if len(locals_) > 1]  # 서버가 더 합치는 글자들
    assert merged == []


@pytest.mark.parametrize(
    "name",
    ["Straße", "STRASSE", "ẞ", "ß", "ss", "ı", "i", "I", "İ", "ΟΔΟΣ", "οδοσ", "ς", "σ", "ﬁle", "file", "ǅ", "ǆ", "ſ", "s", "공부", "Ａ", "ａ"],
)
def test_sample_names_group_the_same_way(server_keys, name) -> None:
    # 여러 글자 이름도 같은 묶음인지(글자 단위 비교로는 못 보는 어말 시그마 등)
    others = ["Straße", "STRASSE", "ẞ", "ß", "ss", "ı", "i", "I", "İ", "ΟΔΟΣ", "οδοσ", "ς", "σ", "ﬁle", "file", "ǅ", "ǆ", "ſ", "s", "공부", "Ａ", "ａ"]
    script = (
        f"import {{ nameKey }} from {json.dumps(SERVER_KEY.as_uri())};"
        f"const names = {json.dumps(others, ensure_ascii=False)};"
        "process.stdout.write(JSON.stringify(names.map((n) => nameKey(n))));"
    )
    keys = json.loads(
        subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60).stdout
    )
    server = dict(zip(others, keys, strict=True))
    for other in others:
        assert (name_key(name) == name_key(other)) == (server[name] == server[other]), (name, other)
