/** 기본 헤더에 호출부가 준 헤더를 겹친다. HeadersInit이 배열·Headers 객체여도 같게 동작하도록 Headers로 바꿔 합친다. */
function withDefaults(extra: HeadersInit): Headers {
  const merged = new Headers({
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  });
  for (const [name, value] of new Headers(extra)) merged.set(name, value);
  return merged;
}

/** JSON 응답. 로그인 응답에는 토큰이 들어가므로 어떤 응답도 캐시되지 않게 한다. */
export function jsonResponse(
  body: unknown,
  status = 200,
  headers: HeadersInit = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: withDefaults(headers),
  });
}

/** 오류 응답. 형식은 hub와 같다: `{"error": {"code", "message"}}`. message는 사용자에게 보여 줄 수 있는 문장이다. */
export function errorResponse(
  status: number,
  code: string,
  message: string,
  headers: HeadersInit = {},
): Response {
  return jsonResponse({ error: { code, message } }, status, headers);
}

/** 요청 본문을 JSON으로 읽는다. 형식·크기가 맞지 않으면 그대로 돌려줄 오류 응답을 함께 준다. */
const JSON_CONTENT_TYPE = /^application\/json\s*(;.*)?$/i;

export async function readJson(
  request: Request,
  maxBytes: number,
): Promise<{ ok: true; body: unknown } | { ok: false; response: Response }> {
  if (!JSON_CONTENT_TYPE.test(request.headers.get("Content-Type") ?? "")) {
    return {
      ok: false,
      response: errorResponse(
        415,
        "invalid_request",
        "본문은 application/json이어야 합니다.",
      ),
    };
  }
  const declared = Number(request.headers.get("Content-Length") ?? "0");
  if (declared > maxBytes) {
    return {
      ok: false,
      response: errorResponse(413, "invalid_request", "본문이 너무 큽니다."),
    };
  }
  const raw = await request.arrayBuffer();
  if (raw.byteLength === 0 || raw.byteLength > maxBytes) {
    return {
      ok: false,
      response: errorResponse(
        raw.byteLength === 0 ? 400 : 413,
        "invalid_request",
        raw.byteLength === 0 ? "본문이 비어 있습니다." : "본문이 너무 큽니다.",
      ),
    };
  }
  try {
    return {
      ok: true,
      body: JSON.parse(
        new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(raw),
      ),
    };
  } catch {
    return {
      ok: false,
      response: errorResponse(
        400,
        "invalid_request",
        "본문이 올바른 JSON이 아닙니다.",
      ),
    };
  }
}
