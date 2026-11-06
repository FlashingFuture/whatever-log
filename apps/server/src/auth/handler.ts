import type { Db } from "../db.ts";
import { errorResponse, jsonResponse, readJson } from "../http.ts";
import { loginGoogleUser } from "./accounts.ts";
import { parseExchangeRequest } from "./exchangeRequest.ts";
import {
  exchangeCodeForIdToken,
  type FetchFn,
  GoogleExchangeError,
} from "./googleOAuth.ts";
import { IdTokenError, verifyIdToken } from "./idToken.ts";
import type { KeyProvider } from "./jwks.ts";
import {
  generateToken,
  hashToken,
  TOKEN_LIFETIME_DAYS,
} from "./sessionToken.ts";

/** 로그인 처리가 필요로 하는 것들. 시계·네트워크·DB·난수를 밖에서 넣어 주므로 Workers 밖에서도 테스트할 수 있다. */
export interface LoginDeps {
  clientId: string;
  clientSecret: string;
  db: Db;
  fetch: FetchFn;
  keys: KeyProvider;
  now: () => Date;
  newToken?: () => string;
}

const MAX_BODY_BYTES = 4096;

/**
 * `POST /auth/google`: 데스크톱이 Google 로그인 뒤 받은 인증 코드를 서버 토큰으로 바꿔 준다.
 *
 * 1. 본문을 엄격하게 검사한다. 2. 인증 코드를 Google에서 ID 토큰으로 교환한다(클라이언트 비밀은 서버만 안다).
 * 3. ID 토큰을 검증한다(서명·발급자·대상·만료·이메일 검증 여부). 4. 사용자를 만들거나 찾고 새 토큰의 해시를
 * 저장한다. 5. 토큰 원문은 이 응답에서 단 한 번만 돌려준다. 코드·토큰·비밀은 로그에 남기지 않는다.
 */
export async function handleGoogleLogin(
  request: Request,
  deps: LoginDeps,
): Promise<Response> {
  const read = await readJson(request, MAX_BODY_BYTES);
  if (!read.ok) {
    return read.response;
  }
  const parsed = parseExchangeRequest(read.body);
  if (!parsed.ok) {
    return errorResponse(400, "invalid_request", parsed.message);
  }

  let idToken: string;
  try {
    idToken = await exchangeCodeForIdToken(
      deps.fetch,
      { clientId: deps.clientId, clientSecret: deps.clientSecret },
      parsed.value,
    );
  } catch (error) {
    if (
      error instanceof GoogleExchangeError &&
      error.kind === "invalid_grant"
    ) {
      return errorResponse(400, "invalid_grant", error.message);
    }
    console.error(
      "google exchange failed:",
      error instanceof Error ? error.message : "unknown",
    );
    return errorResponse(
      502,
      "upstream_error",
      "Google 로그인을 처리하지 못했습니다. 잠시 뒤 다시 시도해 주세요.",
    );
  }

  const now = deps.now();
  let claims: Awaited<ReturnType<typeof verifyIdToken>>;
  try {
    claims = await verifyIdToken(idToken, {
      clientId: deps.clientId,
      now,
      keys: deps.keys,
    });
  } catch (error) {
    if (error instanceof IdTokenError && error.kind === "email_not_verified") {
      return errorResponse(403, "email_not_verified", error.message);
    }
    // Google이 직접 준 토큰이 검증에 실패하는 것은 우리 설정(클라이언트 ID)이나 키 조회의 문제다.
    console.error(
      "id token rejected:",
      error instanceof Error ? error.message : "unknown",
    );
    return errorResponse(
      502,
      "upstream_error",
      "Google 로그인을 처리하지 못했습니다. 잠시 뒤 다시 시도해 주세요.",
    );
  }

  const token = (deps.newToken ?? generateToken)();
  const expiresAt = new Date(
    now.getTime() + TOKEN_LIFETIME_DAYS * 24 * 60 * 60 * 1000,
  );
  await loginGoogleUser(deps.db, {
    sub: claims.sub,
    email: claims.email,
    tokenHash: await hashToken(token),
    now,
    expiresAt,
  });
  return jsonResponse({
    token,
    expires_at: expiresAt.toISOString(),
    email: claims.email,
  });
}
