import type { ExchangeRequest } from "./exchangeRequest.ts";

export const GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token";
const TIMEOUT_MS = 10_000;

export type FetchFn = (input: string, init?: RequestInit) => Promise<Response>;

/**
 * 코드 교환이 실패한 이유. invalid_grant는 코드가 만료됐거나 이미 쓰인 것(사용자가 다시 로그인하면 된다)이고,
 * upstream은 Google 쪽이나 우리 설정의 문제다.
 */
export class GoogleExchangeError extends Error {
  kind: "invalid_grant" | "upstream";

  constructor(kind: "invalid_grant" | "upstream", message: string) {
    super(message);
    this.name = "GoogleExchangeError";
    this.kind = kind;
  }
}

/**
 * 인증 코드를 Google에 보내 ID 토큰으로 바꾼다. 클라이언트 비밀은 서버만 알고(데스크톱 앱에는 넣지 않는다),
 * 요청의 `code_verifier`(PKCE)는 Google이 코드를 발급받은 쪽과 같은 쪽인지 확인하는 데 쓴다.
 * 응답 본문과 코드는 오류 메시지·로그에 남기지 않는다.
 */
export async function exchangeCodeForIdToken(
  fetchFn: FetchFn,
  config: { clientId: string; clientSecret: string },
  request: ExchangeRequest,
): Promise<string> {
  let response: Response;
  try {
    response = await fetchFn(GOOGLE_TOKEN_URL, {
      method: "POST",
      body: new URLSearchParams({
        client_id: config.clientId,
        client_secret: config.clientSecret,
        code: request.code,
        code_verifier: request.codeVerifier,
        redirect_uri: request.redirectUri,
        grant_type: "authorization_code",
      }),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch {
    throw new GoogleExchangeError("upstream", "Google에 연결하지 못했습니다.");
  }

  const body = (await response.json().catch(() => null)) as Record<
    string,
    unknown
  > | null;
  if (response.ok) {
    if (typeof body?.id_token === "string" && body.id_token.length > 0) {
      return body.id_token;
    }
    throw new GoogleExchangeError(
      "upstream",
      "Google 응답에 id_token이 없습니다.",
    );
  }
  if (response.status === 400 && body?.error === "invalid_grant") {
    throw new GoogleExchangeError(
      "invalid_grant",
      "인증 코드가 만료됐거나 이미 사용됐습니다.",
    );
  }
  // invalid_client(우리 설정 오류), 5xx 등. 어떤 오류인지만 남기고 값은 남기지 않는다.
  const reason =
    typeof body?.error === "string" ? body.error : `http_${response.status}`;
  throw new GoogleExchangeError(
    "upstream",
    `Google 코드 교환이 거부됐습니다(${reason}).`,
  );
}
