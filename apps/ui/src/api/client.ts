// hub와 통신하는 공통 부분: 주소, 오류 형식, 제한 시간, JSON 요청. 무엇을 요청하는지(usage.ts, goals.ts 등)는 모른다.

import type { FieldError } from "./types";

/**
 * hub의 에러 응답 `{"error": {"code", "message"}}`에서 온 오류. 형식의 원본은
 * packages/common의 api_error.py다(언어가 달라 같은 모양을 여기 따로 선언한다
 * — 바꾸면 양쪽을 같이 고친다).
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | undefined;
  /** 입력 오류일 때 칸별 오류(없으면 빈 목록). */
  readonly fields: readonly FieldError[];

  constructor(
    status: number,
    code: string | undefined,
    message: string,
    fields: readonly FieldError[] = [],
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

function toFieldErrors(value: unknown): FieldError[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (item): item is FieldError =>
      typeof item?.field === "string" &&
      typeof item?.code === "string" &&
      typeof item?.message === "string",
  );
}

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as {
      error?: { code?: string; message?: string; fields?: unknown };
    };
    if (body.error?.message) {
      return new ApiError(
        response.status,
        body.error.code,
        body.error.message,
        toFieldErrors(body.error.fields),
      );
    }
  } catch {
    // 본문이 JSON이 아니면(프록시 오류 페이지 등) 상태 코드만 알린다.
  }
  return new ApiError(response.status, undefined, `HTTP ${response.status}`);
}

// apps/hub가 고정 포트로 뜬다(apps/desktop이 자식 프로세스로 띄움).
export const HUB_URL = "http://127.0.0.1:8787";

// hub가 연결만 열어 두고 응답을 끝내지 않아도 요청이 영원히 매달려 있지 않게 한다 —
// PeriodView의 15초 갱신은 최신 요청이 끝나야 다시 시작되므로, 안 끝나는 요청 하나가
// 화면 갱신을 멈춰 세운다. 정상 응답(월 단위 집계 포함)보다 충분히 긴 값.
export const SHORT_REQUEST_TIMEOUT_MS = 10_000;
// 월 단위 조회는 틱을 한 달치 훑는다 — 기본 15초 간격이면 몇 초지만, recorder를 1초
// 간격으로 돌리면 틱이 270만 개라 1분 가까이 걸릴 수 있다(틱당 약 20µs). 그때도 시간
// 초과 오류가 반복되지 않게 긴 조회에는 더 길게 준다.
const LONG_REQUEST_TIMEOUT_MS = 60_000;
const LONG_SPAN_MS = 8 * 24 * 60 * 60 * 1000;

/** 조회 구간이 길수록 hub가 더 오래 걸리므로 제한 시간도 길게 준다. */
export function requestTimeoutMs(spanMs: number): number {
  return spanMs > LONG_SPAN_MS
    ? LONG_REQUEST_TIMEOUT_MS
    : SHORT_REQUEST_TIMEOUT_MS;
}

export type HttpMethod = "GET" | "POST" | "PUT" | "DELETE";

/**
 * hub에 JSON 요청을 보내고 JSON 응답을 돌려준다(본문 없는 응답, 예: 204는 undefined). 쓰기 요청(POST·
 * PUT·DELETE)은 브라우저가 알아서 Origin을 붙이고, 본문이 있으면 `Content-Type: application/json`을
 * 단다 — hub는 이 둘이 맞는 요청만 받는다(허용된 UI에서 온 JSON 요청만).
 */
async function requestJson<T>(
  method: HttpMethod,
  path: string,
  body: unknown,
  timeoutMs: number,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${HUB_URL}${path}`, {
      method,
      signal: controller.signal,
      ...(body === undefined
        ? {}
        : {
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }),
    });
    // fetch()는 HTTP 상태와 무관하게 resolve된다 — hub가 DB를 못 읽어 503을
    // 주면 { "error": ... } 모양이라, 체크 없이 바로 결과로 취급하면 렌더링이
    // undefined 필드에서 깨진다. 서버가 준 사유는 화면에 보이게 싣는다.
    if (!response.ok) {
      throw await toApiError(response);
    }
    if (response.status === 204) {
      return undefined as T;
    }
    // 본문을 읽는 동안에도 제한 시간이 적용되도록 같은 try 안에서 읽는다.
    return (await response.json()) as T;
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error("hub 응답 시간이 초과되었습니다.");
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

/** GET 요청. */
export function getJson<T>(path: string, timeoutMs: number): Promise<T> {
  return requestJson("GET", path, undefined, timeoutMs);
}

/** 쓰기 요청(POST·PUT·DELETE). body가 없으면 본문 없이 보낸다(DELETE). */
export function sendJson<T>(
  method: Exclude<HttpMethod, "GET">,
  path: string,
  body: unknown,
  timeoutMs: number,
): Promise<T> {
  return requestJson(method, path, body, timeoutMs);
}
