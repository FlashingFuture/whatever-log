import type { MailMessage, MailPort, SendResult } from "./port.ts";

const ENDPOINT = "https://api.resend.com/emails";
const TIMEOUT_MS = 10_000;
// 키 자체의 문제를 뜻하는 Resend의 오류 이름(상태 코드가 401이 아니라 403으로 오는 것도 있다).
const KEY_PROBLEMS = new Set([
  "invalid_api_key",
  "missing_api_key",
  "restricted_api_key",
]);

/** Resend의 오류 응답 `{statusCode, name, message}`에서 이름만 꺼낸다(메시지에는 주소가 섞일 수 있어 쓰지 않는다). */
async function errorName(response: Response): Promise<string | undefined> {
  try {
    const body = (await response.json()) as { name?: unknown };
    return typeof body.name === "string" ? body.name.slice(0, 64) : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Resend(https://resend.com)로 보내는 어댑터. 키(`apiKey`)는 호출 헤더에만 쓰고 결과·오류 어디에도 담지 않는다.
 * 응답을 우리 분류로 옮긴다: 401·403 중 키 문제는 unauthorized, 그 밖의 4xx는 rejected(입력·도메인·샌드박스 제한), 429는 rate_limited, 5xx·네트워크·시간 초과는 unavailable.
 */
export function createResendMail(options: {
  apiKey: string;
  fetch: typeof fetch;
}): MailPort {
  return {
    async send(message: MailMessage): Promise<SendResult> {
      const headers: Record<string, string> = {
        Authorization: `Bearer ${options.apiKey}`,
        "Content-Type": "application/json",
      };
      if (message.idempotencyKey) {
        headers["Idempotency-Key"] = message.idempotencyKey;
      }
      let response: Response;
      try {
        response = await options.fetch(ENDPOINT, {
          method: "POST",
          headers,
          body: JSON.stringify({
            from: message.from,
            to: [message.to],
            subject: message.subject,
            text: message.text,
            ...(message.html === undefined ? {} : { html: message.html }),
          }),
          signal: AbortSignal.timeout(TIMEOUT_MS),
        });
      } catch {
        return { ok: false, reason: "unavailable", retryable: true };
      }
      if (response.ok) {
        try {
          const body = (await response.json()) as { id?: unknown };
          if (typeof body.id === "string" && body.id !== "") {
            return { ok: true, id: body.id };
          }
        } catch {
          // 아래에서 처리한다
        }
        // 2xx인데 접수 번호가 없다 — 보냈는지 알 수 없어 성공으로 보지 않는다(다시 보내면 중복일 수 있어 재시도 불가로 표시).
        return {
          ok: false,
          reason: "unavailable",
          retryable: false,
          detail: "no_id",
        };
      }
      const detail = await errorName(response);
      if (response.status === 429) {
        return { ok: false, reason: "rate_limited", retryable: true, detail };
      }
      if (response.status >= 500) {
        return { ok: false, reason: "unavailable", retryable: true, detail };
      }
      if (
        response.status === 401 ||
        (detail !== undefined && KEY_PROBLEMS.has(detail))
      ) {
        return { ok: false, reason: "unauthorized", retryable: false, detail };
      }
      return { ok: false, reason: "rejected", retryable: false, detail };
    },
  };
}
