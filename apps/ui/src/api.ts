export interface ProcessUsage {
  process: string;
  active_seconds: number;
  idle_seconds: number;
  background_seconds: number;
  total_seconds: number;
}

export interface RangeUsage {
  start: string;
  end: string;
  by_process: ProcessUsage[];
}

/** 한 프로세스의 칸 하나(시간 하나, 날짜 하나)의 사용 시간. */
export interface BucketUsage {
  start: string;
  end: string;
  active_seconds: number;
  idle_seconds: number;
  background_seconds: number;
  total_seconds: number;
}

export interface ProcessSeries {
  process: string;
  buckets: BucketUsage[];
}

/**
 * hub의 에러 응답 `{"error": {"code", "message"}}`에서 온 오류. 형식의 원본은
 * packages/common의 api_error.py다(언어가 달라 같은 모양을 여기 따로 선언한다
 * — 바꾸면 양쪽을 같이 고친다).
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | undefined;

  constructor(status: number, code: string | undefined, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as {
      error?: { code?: string; message?: string };
    };
    if (body.error?.message) {
      return new ApiError(response.status, body.error.code, body.error.message);
    }
  } catch {
    // 본문이 JSON이 아니면(프록시 오류 페이지 등) 상태 코드만 알린다.
  }
  return new ApiError(response.status, undefined, `HTTP ${response.status}`);
}

// apps/hub가 고정 포트로 뜬다(apps/desktop이 자식 프로세스로 띄움).
const HUB_URL = "http://127.0.0.1:8787";

// hub가 연결만 열어 두고 응답을 끝내지 않아도 요청이 영원히 매달려 있지 않게 한다 —
// PeriodView의 15초 갱신은 최신 요청이 끝나야 다시 시작되므로, 안 끝나는 요청 하나가
// 화면 갱신을 멈춰 세운다. 정상 응답(월 단위 집계 포함)보다 충분히 긴 값.
const REQUEST_TIMEOUT_MS = 10_000;

/**
 * 프로세스 아이콘 URL. 이름만 넘기고 경로는 hub가 DB에서 찾는다. 브라우저가
 * hub의 Cache-Control/ETag로 캐싱하므로 같은 URL은 다시 받지 않는다.
 */
export function iconUrl(processName: string): string {
  return `${HUB_URL}/api/icons/${encodeURIComponent(processName)}`;
}

async function getJson<T>(path: string): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${HUB_URL}${path}`, {
      signal: controller.signal,
    });
    // fetch()는 HTTP 상태와 무관하게 resolve된다 — hub가 DB를 못 읽어 503을
    // 주면 { "error": ... } 모양이라, 체크 없이 바로 결과로 취급하면 렌더링이
    // undefined 필드에서 깨진다. 서버가 준 사유는 화면에 보이게 싣는다.
    if (!response.ok) {
      throw await toApiError(response);
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

export function fetchUsage(start: Date, end: Date): Promise<RangeUsage> {
  // toISOString()은 항상 UTC("...Z")라 오프셋의 "+"가 쿼리 문자열에서 공백으로
  // 깨질 일이 없다. URLSearchParams가 나머지 인코딩을 맡는다.
  const query = new URLSearchParams({
    start: start.toISOString(),
    end: end.toISOString(),
  });
  return getJson(`/api/usage?${query}`);
}

/**
 * 한 프로세스의 사용 시간을 칸별로 받는다. 칸 경계는 로컬 타임존으로 계산한
 * 것을 넘긴다(hub는 달력을 모른다) — 맨 앞 칸의 시작부터 맨 뒤 칸의 끝까지
 * 이어진 경계 목록이다.
 */
export function fetchProcessUsage(
  process: string,
  buckets: { start: Date; end: Date }[],
): Promise<ProcessSeries> {
  const edges = [
    ...buckets.map((b) => b.start),
    buckets[buckets.length - 1].end,
  ];
  const query = new URLSearchParams({
    edges: edges.map((edge) => edge.toISOString()).join(","),
  });
  return getJson(
    `/api/processes/${encodeURIComponent(process)}/usage?${query}`,
  );
}
