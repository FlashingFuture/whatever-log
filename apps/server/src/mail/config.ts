/**
 * 메일 설정과 상수 — 서비스·도메인·발신자·한도를 **한 곳**에서 정한다(docs/mail-design.md).
 *
 * 도메인을 아직 사지 않았어도 같은 코드가 돈다: `MAIL_FROM_DOMAIN`이 비어 있으면 서비스의 시험용 발신 주소(샌드박스)를 쓰고, 도메인을 사서 서비스에서 인증한 뒤
 * `wrangler.toml`의 `MAIL_FROM_DOMAIN`만 채우면 실사용 발신 주소로 바뀐다. 서비스를 바꿀 때는 `MAIL_PROVIDER`(와 새 서비스의 비밀 키)만 바꾼다.
 */

/** 지원하는 메일 서비스. 새 어댑터를 더하면 여기와 `factory.ts`에 이름을 더한다. */
export const MAIL_PROVIDERS = ["resend"] as const;
export type MailProvider = (typeof MAIL_PROVIDERS)[number];

/** 발신자 표시 이름. 받는 사람의 메일함에 보이는 이름이다. */
export const SENDER_NAME = "whatever.log";
/** 도메인을 정했을 때의 발신 주소 앞부분(`reports@<도메인>`). */
export const SENDER_LOCAL_PART = "reports";

/**
 * 도메인이 없을 때 쓰는 서비스별 시험용 발신 주소. Resend의 `onboarding@resend.dev`는 **가입한 계정의 이메일로만** 보낼 수 있다 —
 * 실제 사용자에게 보내려면 도메인을 사서 인증해야 한다.
 */
export const SANDBOX_SENDERS: Record<MailProvider, string> = {
  resend: "onboarding@resend.dev",
};

/**
 * 발송 한도(docs/mail-design.md의 "비용 폭주를 막는 설계"). 무료 한도를 넘기지 않도록 서비스의 한도(Resend Free: 하루 100통, 월 3,000통)보다 낮게 잡는다.
 * 넘으면 보내지 않고 429로 알린다 — 청구가 늘기 전에 코드가 먼저 멈춘다.
 */
export const LIMITS = {
  /** 한 사용자가 하루(UTC)에 요청할 수 있는 시험 메일. */
  testPerUserPerDay: 3,
  /** 서버 전체가 하루(UTC)에 보내는 메일의 상한(시험·보고서 합계). */
  perDayTotal: 80,
} as const;

/** 서버가 설정에서 읽는 값. 비밀 키는 환경 변수 이름만 알고 값은 `wrangler secret`에서 온다. */
export interface MailEnv {
  MAIL_PROVIDER?: string;
  MAIL_FROM_DOMAIN?: string;
  RESEND_API_KEY?: string;
}

export class MailConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MailConfigError";
  }
}

// 도메인 이름: 소문자 라벨을 점으로 이은 것. 앞뒤 공백·스킴·경로가 섞이면(설정 실수) 발신 주소가 깨지므로 엄격하게 받는다.
const DOMAIN =
  /^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;

/** `MAIL_PROVIDER` 값을 지원하는 서비스 이름으로. 비어 있으면 기본(resend), 모르는 값이면 MailConfigError. */
export function resolveProvider(env: MailEnv): MailProvider {
  const name = (env.MAIL_PROVIDER ?? "").trim() || "resend";
  if ((MAIL_PROVIDERS as readonly string[]).includes(name)) {
    return name as MailProvider;
  }
  throw new MailConfigError(
    `MAIL_PROVIDER는 ${MAIL_PROVIDERS.join(", ")} 중 하나여야 합니다.`,
  );
}

export interface Sender {
  /** `이름 <주소>` 형식의 From 값. */
  from: string;
  /** domain: 인증한 내 도메인으로 보낸다 / sandbox: 서비스의 시험용 주소(허용된 수신자에게만 간다). */
  mode: "domain" | "sandbox";
}

/** 발신자를 정한다. 도메인이 설정돼 있으면 도메인 발신, 비어 있으면 샌드박스. 도메인 값이 이상하면 MailConfigError(잘못된 From으로 보내지 않는다). */
export function resolveSender(env: MailEnv): Sender {
  const provider = resolveProvider(env);
  const domain = (env.MAIL_FROM_DOMAIN ?? "").trim().toLowerCase();
  if (domain === "") {
    return {
      from: `${SENDER_NAME} <${SANDBOX_SENDERS[provider]}>`,
      mode: "sandbox",
    };
  }
  if (!DOMAIN.test(domain)) {
    throw new MailConfigError(
      "MAIL_FROM_DOMAIN은 `example.com` 같은 도메인 이름이어야 합니다.",
    );
  }
  return {
    from: `${SENDER_NAME} <${SENDER_LOCAL_PART}@${domain}>`,
    mode: "domain",
  };
}
