import { handleGoogleLogin } from "./auth/handler.ts";
import { createGoogleKeyProvider } from "./auth/jwks.ts";
import type { Db } from "./db.ts";
import { errorResponse, jsonResponse } from "./http.ts";

/** Worker가 받는 환경: wrangler.toml의 [vars]·바인딩과 비밀 값(.dev.vars / wrangler secret). */
export interface Env {
  GOOGLE_CLIENT_ID: string;
  GOOGLE_CLIENT_SECRET: string;
  DB: Db;
}

// Worker 인스턴스가 살아 있는 동안 재사용되도록 모듈 수준에서 한 번만 만든다(Google 공개키를 1시간 캐시).
// `fetch`를 변수로 넘기면 Workers에서 "Illegal invocation"이 나므로 화살표로 감싼다.
const keys = createGoogleKeyProvider(
  (input, init) => fetch(input, init),
  () => Date.now(),
);

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const { pathname } = new URL(request.url);
    try {
      if (pathname === "/health") {
        return jsonResponse({ ok: true });
      }
      if (pathname === "/auth/google") {
        if (request.method !== "POST") {
          return errorResponse(405, "method_not_allowed", "POST만 받습니다.", {
            Allow: "POST",
          });
        }
        return await handleGoogleLogin(request, {
          clientId: env.GOOGLE_CLIENT_ID,
          clientSecret: env.GOOGLE_CLIENT_SECRET,
          db: env.DB,
          fetch: (input, init) => fetch(input, init),
          keys,
          now: () => new Date(),
        });
      }
      return errorResponse(404, "not_found", "없는 주소입니다.");
    } catch (error) {
      // 예상하지 못한 오류. 내용(토큰·코드가 섞일 수 있다)은 응답에 내지 않고 오류 이름만 남긴다.
      console.error(
        "unhandled error:",
        error instanceof Error ? error.name : "unknown",
      );
      return errorResponse(500, "internal_error", "서버에서 오류가 났습니다.");
    }
  },
} satisfies ExportedHandler<Env>;
