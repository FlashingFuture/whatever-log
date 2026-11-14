import type { Db } from "../db.ts";
import { errorResponse, jsonResponse, readJson } from "../http.ts";
import { MailConfigError } from "../mail/config.ts";
import { type MailDeps, sendTestMail } from "../mail/testMail.ts";
import { deleteAccount, revokeToken } from "./account.ts";
import { authenticate } from "./authenticate.ts";
import { isUuid, parseGoalInput } from "./goalInput.ts";
import { deleteGoal, listGoals, putGoal } from "./goals.ts";
import {
  deleteDevice,
  getProgress,
  listDevices,
  putProgress,
} from "./progress.ts";
import { parsePutProgress, parseRange } from "./progressInput.ts";

export interface ApiDeps {
  db: Db;
  now: () => Date;
  /**
   * 메일 발송 준비(어댑터와 발신자). 설정이 없거나 틀리면 MailConfigError를 던지고, 주지 않으면(메일을 쓰지 않는 호출) 메일 주소는 "설정되지 않음"으로 답한다.
   * 요청마다 부르므로 가벼워야 한다 — 어댑터는 호출 사이에 상태를 갖지 않는다.
   */
  mail?: () => MailDeps;
}

const GOAL_BODY_BYTES = 1024;
const PROGRESS_BODY_BYTES = 16 * 1024;
const noContent = () =>
  new Response(null, { status: 204, headers: { "Cache-Control": "no-store" } });

interface Route {
  methods: string[];
  handle(
    request: Request,
    url: URL,
    params: string[],
    caller: { userId: number; tokenHash: string },
    deps: ApiDeps,
  ): Promise<Response>;
}

const notFound = () => errorResponse(404, "not_found", "없는 주소입니다.");

/** 주소의 {id} 자리가 UUID가 아니면 DB까지 가지 않고 404로 돌려보낸다. */
const withUuid = (
  handler: (
    request: Request,
    id: string,
    caller: { userId: number; tokenHash: string },
    deps: ApiDeps,
  ) => Promise<Response>,
): Route["handle"] => {
  return (request, _url, params, caller, deps) =>
    isUuid(params[0])
      ? handler(request, params[0], caller, deps)
      : Promise.resolve(notFound());
};

const ROUTES: { pattern: RegExp; route: Route }[] = [
  {
    pattern: /^\/goals$/,
    route: {
      methods: ["GET"],
      async handle(_request, _url, _params, caller, deps) {
        return jsonResponse({
          goals: await listGoals(deps.db, caller.userId, deps.now()),
        });
      },
    },
  },
  {
    pattern: /^\/goals\/([^/]+)$/,
    route: {
      methods: ["PUT", "DELETE"],
      handle: withUuid(async (request, id, caller, deps) => {
        if (request.method === "DELETE") {
          const found = await deleteGoal(
            deps.db,
            caller.userId,
            id,
            deps.now(),
          );
          return found ? noContent() : notFound();
        }
        const read = await readJson(request, GOAL_BODY_BYTES);
        if (!read.ok) return read.response;
        const parsed = parseGoalInput(read.body);
        if (!parsed.ok) {
          return errorResponse(400, "invalid_request", parsed.message);
        }
        const result = await putGoal(
          deps.db,
          caller.userId,
          id,
          parsed.value,
          deps.now(),
        );
        if (result.ok) return jsonResponse(result.goal, result.status);
        if (result.status === 404) {
          return errorResponse(404, result.code, result.message);
        }
        return jsonResponse(
          {
            error: { code: result.code, message: result.message },
            current: result.current ?? null,
          },
          409,
        );
      }),
    },
  },
  {
    pattern: /^\/progress$/,
    route: {
      methods: ["GET", "PUT"],
      async handle(request, url, _params, caller, deps) {
        if (request.method === "GET") {
          const range = parseRange(url.searchParams);
          if (!range.ok) {
            return errorResponse(400, "invalid_request", range.message);
          }
          return jsonResponse({
            days: await getProgress(
              deps.db,
              caller.userId,
              range.from,
              range.to,
            ),
          });
        }
        const read = await readJson(request, PROGRESS_BODY_BYTES);
        if (!read.ok) return read.response;
        const now = deps.now();
        const parsed = parsePutProgress(read.body, now);
        if (!parsed.ok) {
          return errorResponse(400, "invalid_request", parsed.message);
        }
        const result = await putProgress(
          deps.db,
          caller.userId,
          parsed.deviceId,
          parsed.entries,
          now,
        );
        if (!result.ok) {
          return errorResponse(409, result.code, result.message);
        }
        return jsonResponse({
          accepted: result.accepted,
          ignored_goal_ids: result.ignoredGoalIds,
        });
      },
    },
  },
  {
    pattern: /^\/devices$/,
    route: {
      methods: ["GET"],
      async handle(_request, _url, _params, caller, deps) {
        return jsonResponse({
          devices: await listDevices(deps.db, caller.userId),
        });
      },
    },
  },
  {
    pattern: /^\/devices\/([^/]+)$/,
    route: {
      methods: ["DELETE"],
      handle: withUuid(async (_request, id, caller, deps) => {
        await deleteDevice(deps.db, caller.userId, id);
        return noContent();
      }),
    },
  },
  {
    pattern: /^\/mail\/test$/,
    route: {
      methods: ["POST"],
      async handle(_request, _url, _params, caller, deps) {
        let mail: MailDeps;
        try {
          if (!deps.mail) {
            throw new MailConfigError("메일이 설정되지 않았습니다.");
          }
          mail = deps.mail();
        } catch (error) {
          if (!(error instanceof MailConfigError)) throw error;
          // 사용자에게는 "설정되지 않음"만 알리고, 무엇이 빠졌는지는 서버 로그에 남긴다(메시지에는 값이 아니라 이름만 있다 — 비밀이 섞이지 않는다).
          console.warn(`mail config: ${error.message}`);
          return errorResponse(
            503,
            "mail_not_configured",
            "메일 발송이 아직 설정되지 않았어요.",
          );
        }
        const result = await sendTestMail(
          deps.db,
          caller.userId,
          mail,
          deps.now(),
        );
        return result.ok
          ? jsonResponse({ sent: true, to: result.to, mode: result.mode })
          : errorResponse(result.status, result.code, result.message);
      },
    },
  },
  {
    pattern: /^\/auth\/logout$/,
    route: {
      methods: ["POST"],
      async handle(_request, _url, _params, caller, deps) {
        await revokeToken(deps.db, caller.tokenHash);
        return noContent();
      },
    },
  },
  {
    pattern: /^\/account$/,
    route: {
      methods: ["DELETE"],
      async handle(_request, _url, _params, caller, deps) {
        await deleteAccount(deps.db, caller.userId);
        return noContent();
      },
    },
  },
];

/**
 * 로그인한 사용자의 API(목표·달성도·기기·로그아웃·계정 삭제)를 처리한다. 이 모듈의 주소가 아니면 null을 돌려줘
 * 호출부가 다른 처리를 하게 한다. 순서: 주소 → 메서드(405) → 토큰(401) → 처리. 토큰 없이는 어떤 데이터도 읽지 않는다.
 */
export async function handleApi(
  request: Request,
  url: URL,
  deps: ApiDeps,
): Promise<Response | null> {
  for (const { pattern, route } of ROUTES) {
    const match = pattern.exec(url.pathname);
    if (!match) continue;
    if (!route.methods.includes(request.method)) {
      return errorResponse(
        405,
        "method_not_allowed",
        "허용되지 않는 방법입니다.",
        {
          Allow: route.methods.join(", "),
        },
      );
    }
    const caller = await authenticate(request, deps.db, deps.now());
    if (caller instanceof Response) return caller;
    return route.handle(request, url, match.slice(1), caller, deps);
  }
  return null;
}
