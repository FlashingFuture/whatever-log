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

export function fetchUsage(start: Date, end: Date): Promise<RangeUsage> {
  // toISOString()은 항상 UTC("...Z")라 오프셋의 "+"가 쿼리 문자열에서 공백으로
  // 깨질 일이 없다. URLSearchParams가 나머지 인코딩을 맡는다.
  const query = new URLSearchParams({
    start: start.toISOString(),
    end: end.toISOString(),
  });
  return fetch(`${HUB_URL}/api/usage?${query}`).then(async (response) => {
    // fetch()는 HTTP 상태와 무관하게 resolve된다 — hub가 DB를 못 읽어 503을
    // 주면 { "error": ... } 모양이라, 체크 없이 바로 RangeUsage로 취급하면
    // 렌더링이 undefined 필드에서 깨진다. 서버가 준 사유는 화면에 보이게 싣는다.
    if (!response.ok) {
      throw await toApiError(response);
    }
    return response.json() as Promise<RangeUsage>;
  });
}
