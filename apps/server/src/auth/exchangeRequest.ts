/** 데스크톱이 보내는 로그인 요청: Google 로그인 뒤 받은 인증 코드와, 코드 교환에 필요한 PKCE·리디렉션 값. */
export interface ExchangeRequest {
  code: string;
  codeVerifier: string;
  redirectUri: string;
}

export type ParseResult =
  | { ok: true; value: ExchangeRequest }
  | { ok: false; message: string };

const FIELDS = new Set(["code", "code_verifier", "redirect_uri"]);
// RFC 7636: code_verifier는 43~128자, [A-Za-z0-9-._~]만 쓴다.
const CODE_VERIFIER = /^[A-Za-z0-9\-._~]{43,128}$/;
// 데스크톱 앱의 루프백 리디렉션(RFC 8252): http, 로컬 주소, 포트 필수. 경로는 있어도 되지만 쿼리·해시는 없다.
const LOOPBACK_REDIRECT =
  /^http:\/\/(127\.0\.0\.1|localhost|\[::1\]):\d{1,5}(\/[A-Za-z0-9\-._~/]*)?$/;
const CODE_MAX_LENGTH = 2048;

/** 로컬 주소 모양이고 포트가 1~65535인지. 범위를 넘는 포트는 URL로 해석되지 않으니 Google에 보내기 전에 거른다. */
function isLoopbackRedirect(value: string): boolean {
  if (!LOOPBACK_REDIRECT.test(value)) return false;
  const port = Number(/^http:\/\/[^/]+:(\d+)/.exec(value)?.[1]);
  return port >= 1 && port <= 65535;
}

/**
 * 요청 본문을 엄격하게 검사한다. 모양이 조금이라도 다르면 거부한다(모르는 칸, 다른 형식, 로컬 주소가 아닌
 * 리디렉션). 리디렉션은 Google이 코드를 발급한 주소와 같아야 교환되므로, 여기서는 "로컬 주소인지"만 본다.
 */
export function parseExchangeRequest(body: unknown): ParseResult {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return { ok: false, message: "본문은 JSON 객체여야 합니다." };
  }
  const record = body as Record<string, unknown>;
  const extra = Object.keys(record).filter((key) => !FIELDS.has(key));
  if (extra.length > 0) {
    return {
      ok: false,
      message: `알 수 없는 칸이 있습니다: ${extra.join(", ")}`,
    };
  }
  const {
    code,
    code_verifier: codeVerifier,
    redirect_uri: redirectUri,
  } = record;
  if (
    typeof code !== "string" ||
    code.length === 0 ||
    code.length > CODE_MAX_LENGTH ||
    /\s/.test(code)
  ) {
    return { ok: false, message: "code가 올바르지 않습니다." };
  }
  if (typeof codeVerifier !== "string" || !CODE_VERIFIER.test(codeVerifier)) {
    return { ok: false, message: "code_verifier가 올바르지 않습니다." };
  }
  if (typeof redirectUri !== "string" || !isLoopbackRedirect(redirectUri)) {
    return {
      ok: false,
      message: "redirect_uri는 로컬 루프백 주소여야 합니다.",
    };
  }
  return { ok: true, value: { code, codeVerifier, redirectUri } };
}
