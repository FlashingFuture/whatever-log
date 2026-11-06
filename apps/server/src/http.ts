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
