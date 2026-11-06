import assert from "node:assert/strict";
import { test } from "node:test";

import {
  exchangeCodeForIdToken,
  GOOGLE_TOKEN_URL,
  GoogleExchangeError,
} from "../src/auth/googleOAuth.ts";
import { jsonResponse } from "./helpers/googleFixtures.ts";

const CONFIG = { clientId: "client-id", clientSecret: "super-secret-value" };
const REQUEST = {
  code: "code-123",
  codeVerifier: "v".repeat(43),
  redirectUri: "http://127.0.0.1:5000/cb",
};

test("코드와 PKCE 값과 비밀을 Google 토큰 주소에 폼으로 보내고 ID 토큰을 돌려준다", async () => {
  let seen: { url: string; init?: RequestInit } | undefined;
  const fetchFn = async (url: string, init?: RequestInit) => {
    seen = { url, init };
    return jsonResponse({ id_token: "the.id.token", access_token: "ignored" });
  };

  assert.equal(
    await exchangeCodeForIdToken(fetchFn, CONFIG, REQUEST),
    "the.id.token",
  );

  assert.equal(seen?.url, GOOGLE_TOKEN_URL);
  assert.equal(seen?.init?.method, "POST");
  const form = seen?.init?.body as URLSearchParams;
  assert.deepEqual(Object.fromEntries(form), {
    client_id: "client-id",
    client_secret: "super-secret-value",
    code: "code-123",
    code_verifier: "v".repeat(43),
    redirect_uri: "http://127.0.0.1:5000/cb",
    grant_type: "authorization_code",
  });
});

async function failure(
  response: Response | Error,
): Promise<GoogleExchangeError> {
  const fetchFn = async () => {
    if (response instanceof Error) {
      throw response;
    }
    return response;
  };
  try {
    await exchangeCodeForIdToken(fetchFn, CONFIG, REQUEST);
  } catch (error) {
    assert.ok(error instanceof GoogleExchangeError, String(error));
    return error;
  }
  assert.fail("거부돼야 한다");
}

test("만료되거나 이미 쓴 코드(invalid_grant)는 사용자 오류로 구분한다", async () => {
  const error = await failure(
    jsonResponse(
      { error: "invalid_grant", error_description: "Bad Request" },
      400,
    ),
  );

  assert.equal(error.kind, "invalid_grant");
});

test("그 밖의 거부와 서버 오류, 네트워크 실패는 upstream이다", async () => {
  for (const response of [
    jsonResponse({ error: "invalid_client" }, 401),
    jsonResponse({ error: "invalid_request" }, 400),
    jsonResponse({}, 500),
    new Response("<html>bad gateway</html>", { status: 502 }),
    jsonResponse({ access_token: "no id token" }, 200),
    jsonResponse({ id_token: "" }, 200),
    new Response("not json", { status: 200 }),
    new Error("network down"),
  ]) {
    assert.equal((await failure(response)).kind, "upstream");
  }
});

test("오류 메시지에 비밀이나 코드를 담지 않는다", async () => {
  const error = await failure(
    jsonResponse(
      {
        error: "invalid_client",
        error_description: "super-secret-value code-123",
      },
      401,
    ),
  );

  assert.doesNotMatch(error.message, /super-secret-value|code-123|v{10}/);
});
