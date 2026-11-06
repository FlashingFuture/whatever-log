/** 로그인 토큰의 유효 기간. 만료되면 다시 로그인한다(갱신 토큰은 아직 없다). */
export const TOKEN_LIFETIME_DAYS = 30;
/** 사용자당 동시에 유효한 토큰 수. 넘으면 가장 오래된 것부터 지운다(기기를 여러 개 써도 되지만 무한히 쌓이지 않게). */
export const MAX_TOKENS_PER_USER = 5;

/** 새 로그인 토큰. 예측할 수 없는 무작위 32바이트이고 서명 키가 필요 없다(서버는 해시로만 확인한다). */
export function generateToken(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");
}

/**
 * 토큰의 SHA-256 해시(16진수). DB에는 이것만 저장해, DB가 새도 토큰을 쓸 수 없게 한다. 토큰이 충분히 긴
 * 무작위 값이라 salt나 느린 해시는 필요 없다.
 */
export async function hashToken(token: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(token),
  );
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}
