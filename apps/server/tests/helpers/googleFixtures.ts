export const CLIENT_ID = "test-client.apps.googleusercontent.com";
export const NOW = new Date("2026-11-06T03:00:00.000Z");

function base64Url(bytes: Uint8Array | string): string {
  const raw =
    typeof bytes === "string" ? new TextEncoder().encode(bytes) : bytes;
  return btoa(String.fromCharCode(...raw))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");
}

/** Google처럼 RS256으로 ID 토큰을 서명하는 테스트용 발급자. 공개키(JWKS 한 줄)와 토큰 발급 함수를 준다. */
export async function createIssuer(kid = "key-1") {
  const pair = await crypto.subtle.generateKey(
    {
      name: "RSASSA-PKCS1-v1_5",
      modulusLength: 2048,
      publicExponent: new Uint8Array([1, 0, 1]),
      hash: "SHA-256",
    },
    true,
    ["sign", "verify"],
  );
  const publicJwk = {
    ...(await crypto.subtle.exportKey("jwk", pair.publicKey)),
    kid,
    alg: "RS256",
    use: "sig",
  };

  async function sign(
    claims: Record<string, unknown>,
    header: Record<string, unknown> = { alg: "RS256", kid, typ: "JWT" },
  ): Promise<string> {
    const input = `${base64Url(JSON.stringify(header))}.${base64Url(JSON.stringify(claims))}`;
    const signature = await crypto.subtle.sign(
      "RSASSA-PKCS1-v1_5",
      pair.privateKey,
      new TextEncoder().encode(input),
    );
    return `${input}.${base64Url(new Uint8Array(signature))}`;
  }

  /** 기본값이 모두 올바른 클레임에 덮어쓸 값을 얹어 서명한다. */
  function idToken(overrides: Record<string, unknown> = {}): Promise<string> {
    return sign({
      iss: "https://accounts.google.com",
      aud: CLIENT_ID,
      sub: "google-user-1",
      email: "person@example.com",
      email_verified: true,
      iat: Math.floor(NOW.getTime() / 1000) - 10,
      exp: Math.floor(NOW.getTime() / 1000) + 3600,
      ...overrides,
    });
  }

  return {
    publicJwk,
    sign,
    idToken,
    keys: { get: async (id: string) => (id === kid ? publicJwk : undefined) },
  };
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export const VERIFIER = "a".repeat(43);
export const VALID_BODY = {
  code: "4/0AabcdEFGH",
  code_verifier: VERIFIER,
  redirect_uri: "http://127.0.0.1:53412/callback",
};
