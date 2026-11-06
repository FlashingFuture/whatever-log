/** JSON 응답. 로그인 응답에는 토큰이 들어가므로 어떤 응답도 캐시되지 않게 한다. */
export function jsonResponse(
  body: unknown,
  status = 200,
  headers: HeadersInit = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...headers,
    },
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
