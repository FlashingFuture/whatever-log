import { handleGoogleLogin } from "./auth/handler.ts";
import { createGoogleKeyProvider } from "./auth/jwks.ts";
import type { Db } from "./db.ts";
import { errorResponse, jsonResponse } from "./http.ts";
import { MailConfigError, type MailEnv, resolveSender } from "./mail/config.ts";
import { dispatchReports } from "./mail/dispatch.ts";
import { createMail } from "./mail/factory.ts";
import type { LinkConfig } from "./mail/links.ts";
import { handleUnsubscribe } from "./mail/unsubscribe.ts";
import { handleResendWebhook } from "./mail/webhook.ts";
import { handleApi } from "./sync/api.ts";
import { API_VERSION } from "./version.ts";

/** Worker가 받는 환경: wrangler.toml의 [vars]·바인딩과 비밀 값(.dev.vars / wrangler secret). */
export interface Env extends MailEnv {
  GOOGLE_CLIENT_ID: string;
  GOOGLE_CLIENT_SECRET: string;
  DB: Db;
  /** 배포한 커밋(배포 워크플로가 `wrangler deploy --var COMMIT_SHA:…`로 넣는다). 로컬·직접 배포에서는 없다. */
  COMMIT_SHA?: string;
  /** 메일의 링크가 가리킬 이 서버의 공개 주소(wrangler.toml의 [vars]). */
  SERVER_PUBLIC_URL?: string;
  /** 수신 거부 링크의 서명 비밀(`wrangler secret put MAIL_LINK_SECRET`). 없으면 확인 메일을 보내지 않고 링크도 처리하지 않는다. */
  MAIL_LINK_SECRET?: string;
  /** Resend 웹훅의 서명 비밀(`whsec_…`, `wrangler secret put RESEND_WEBHOOK_SECRET`). */
  RESEND_WEBHOOK_SECRET?: string;
}

/** 수신 거부 링크 설정. 비밀이나 공개 주소가 없으면 undefined(링크가 든 메일을 보내지 않는다). */
export function linkConfig(env: Env): LinkConfig | undefined {
  const secret = env.MAIL_LINK_SECRET?.trim();
  const baseUrl = env.SERVER_PUBLIC_URL?.trim().replace(/\/+$/, "");
  return secret && baseUrl ? { secret, baseUrl } : undefined;
}

// Worker 인스턴스가 살아 있는 동안 재사용되도록 모듈 수준에서 한 번만 만든다(Google 공개키를 1시간 캐시).
// `fetch`를 변수로 넘기면 Workers에서 "Illegal invocation"이 나므로 화살표로 감싼다.
const keys = createGoogleKeyProvider(
  (input, init) => fetch(input, init),
  () => Date.now(),
);

/**
 * 요청 한 줄 로그: 메서드, 경로, 상태 코드, 걸린 시간(ms)만 남긴다. 쿼리·본문·헤더(토큰)·이메일은 남기지 않는다.
 * `wrangler dev`/`docker compose logs server`에서 보이고, 배포한 Worker에서는 `wrangler tail`·대시보드 로그에서 본다.
 */
export function logRequest(
  method: string,
  pathname: string,
  status: number,
  startedAt: number,
  now: () => number = () => Date.now(),
): void {
  console.log(`${method} ${pathname} ${status} ${now() - startedAt}ms`);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const startedAt = Date.now();
    const response = await route(request, env);
    const { pathname } = new URL(request.url);
    if (pathname !== "/health") {
      logRequest(request.method, pathname, response.status, startedAt);
    }
    return response;
  },

  /** Cron(wrangler.toml의 [triggers])이 10분마다 부른다: 지금 보낼 보고서를 보낸다(docs/mail-design.md "보고서 발송"). */
  async scheduled(
    _controller: ScheduledController,
    env: Env,
    ctx: ExecutionContext,
  ): Promise<void> {
    ctx.waitUntil(runReports(env));
  },
} satisfies ExportedHandler<Env>;

/** 보고서 발송 한 번. 메일 설정이 없거나 틀리면 보내지 않고 이유만 로그에 남긴다(값은 남기지 않는다). 결과는 개수만 남긴다. */
export async function runReports(
  env: Env,
  now: Date = new Date(),
): Promise<void> {
  let mail: Parameters<typeof dispatchReports>[1] = null;
  try {
    mail = {
      port: createMail(env, (input, init) => fetch(input, init)),
      sender: resolveSender(env),
      links: linkConfig(env),
    };
  } catch (error) {
    if (!(error instanceof MailConfigError)) throw error;
    console.warn(`mail config: ${error.message}`);
  }
  const summary = await dispatchReports(env.DB, mail, now);
  if (summary.due > 0 || summary.notConfigured) {
    console.log(`reports: ${JSON.stringify(summary)}`);
  }
}

async function route(request: Request, env: Env): Promise<Response> {
  const { pathname } = new URL(request.url);
  try {
    if (pathname === "/health") {
      return jsonResponse({ ok: true });
    }
    if (pathname === "/version") {
      if (request.method !== "GET") {
        return errorResponse(405, "method_not_allowed", "GET만 받습니다.", {
          Allow: "GET",
        });
      }
      // 공개 정보다: API 계약 번호와 배포한 커밋(저장소가 공개라 커밋은 비밀이 아니다). 운영 서버가 어느 코드인지 바로 확인하려는 것.
      return jsonResponse({ api: API_VERSION, commit: env.COMMIT_SHA ?? null });
    }
    if (pathname === "/mail/unsubscribe") {
      return await handleUnsubscribe(request, new URL(request.url), {
        db: env.DB,
        secret: env.MAIL_LINK_SECRET?.trim() || undefined,
        now: () => new Date(),
      });
    }
    if (pathname === "/mail/webhooks/resend") {
      return await handleResendWebhook(request, {
        db: env.DB,
        secret: env.RESEND_WEBHOOK_SECRET?.trim() || undefined,
        now: () => new Date(),
      });
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
    const handled = await handleApi(request, new URL(request.url), {
      db: env.DB,
      now: () => new Date(),
      // 설정이 틀리면 MailConfigError가 나서 메일 주소만 "설정되지 않음"이 된다(다른 기능은 영향이 없다).
      mail: () => ({
        port: createMail(env, (input, init) => fetch(input, init)),
        sender: resolveSender(env),
        links: linkConfig(env),
      }),
    });
    return handled ?? errorResponse(404, "not_found", "없는 주소입니다.");
  } catch (error) {
    // 예상하지 못한 오류. 내용(토큰·코드가 섞일 수 있다)은 응답에 내지 않고 오류 이름만 남긴다.
    console.error(
      "unhandled error:",
      error instanceof Error ? error.name : "unknown",
    );
    return errorResponse(500, "internal_error", "서버에서 오류가 났습니다.");
  }
}
