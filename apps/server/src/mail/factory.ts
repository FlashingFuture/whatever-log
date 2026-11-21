import { MailConfigError, type MailEnv, resolveProvider } from "./config.ts";
import type { MailPort } from "./port.ts";
import { createResendMail } from "./resend.ts";

/**
 * 설정(`MAIL_PROVIDER`)에 맞는 메일 어댑터를 만든다. 서비스별로 다른 것(필요한 비밀 키, 어댑터)이 여기에만 있다.
 * 키가 없으면 MailConfigError — 호출부는 "메일이 아직 설정되지 않았다"고 알리면 된다.
 */
export function createMail(env: MailEnv, fetchFn: typeof fetch): MailPort {
  switch (resolveProvider(env)) {
    case "resend": {
      const apiKey = (env.RESEND_API_KEY ?? "").trim();
      if (apiKey === "") {
        throw new MailConfigError("RESEND_API_KEY가 설정되지 않았습니다.");
      }
      return createResendMail({ apiKey, fetch: fetchFn });
    }
  }
}
