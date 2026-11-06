import re

from cloud import pkce


def test_the_challenge_matches_the_rfc_7636_example() -> None:
    # RFC 7636 부록 B의 예시 값
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"

    assert pkce.code_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_the_verifier_fits_what_the_server_accepts() -> None:
    # 서버(apps/server의 exchangeRequest)는 43~128자의 [A-Za-z0-9-._~]만 받는다.
    for _ in range(50):
        assert re.fullmatch(r"[A-Za-z0-9\-._~]{43,128}", pkce.new_code_verifier())


def test_verifier_and_state_are_unpredictable() -> None:
    assert len({pkce.new_code_verifier() for _ in range(50)}) == 50
    assert len({pkce.new_state() for _ in range(50)}) == 50


def test_the_challenge_has_no_padding_and_hides_the_verifier() -> None:
    verifier = pkce.new_code_verifier()
    challenge = pkce.code_challenge(verifier)

    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge)
    assert verifier not in challenge
