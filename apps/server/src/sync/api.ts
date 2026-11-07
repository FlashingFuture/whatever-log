import type { Db } from "../db.ts";
import { errorResponse, jsonResponse, readJson } from "../http.ts";
import { deleteAccount, revokeToken } from "./account.ts";
import { authenticate } from "./authenticate.ts";
import { isUuid, parseGoalInput } from "./goalInput.ts";
import { deleteGoal, listGoals, putGoal } from "./goals.ts";
import { deleteDevice, getProgress, putProgress } from "./progress.ts";
import { parsePutProgress, parseRange } from "./progressInput.ts";

export interface ApiDeps {
  db: Db;
  now: () => Date;
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
