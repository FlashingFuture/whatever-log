/**
 * 메일 발송의 경계. 서버의 나머지 코드는 이 인터페이스만 알고, 어떤 서비스(Resend, Cloudflare Email Service, SES …)로 보내는지는
 * `factory.ts`와 어댑터(`resend.ts` 등)에만 있다 — 서비스를 바꿀 때 이 폴더 밖은 건드리지 않는다(docs/mail-design.md).
 */

/** 보낼 메일 한 통. 수신자는 호출부가 **서버가 아는 주소**(로그인한 계정의 이메일)로 정한다 — 요청에서 받은 주소를 그대로 넘기지 않는다. */
export interface MailMessage {
  /** 발신자(`이름 <주소>` 형식). `config.resolveSender`가 만든 값을 쓴다. */
  from: string;
  to: string;
  subject: string;
  /** 일반 텍스트 본문(항상 있다 — HTML을 못 보는 곳을 위해). */
  text: string;
  html?: string;
  /** 같은 요청을 다시 보내도 한 번만 발송되게 하는 키(서비스가 지원할 때). */
  idempotencyKey?: string;
}

export type SendResult =
  | { ok: true; id: string }
  | {
      ok: false;
      /** 기계가 보는 분류. 사용자에게 어떻게 알릴지·다시 시도해도 되는지는 이 값으로 정한다. */
      reason: SendFailure;
      /** 다시 시도하면 될 수도 있는가(일시적 실패). 설정·입력 문제면 false. */
      retryable: boolean;
      /** 서비스가 알려 준 오류 이름(로그·진단용). 비밀·주소가 섞이지 않은 짧은 값만 담는다. */
      detail?: string;
    };

/**
 * 실패의 분류:
 * - `unauthorized`: 서비스 키가 잘못됐거나 권한이 없다(우리 설정 문제).
 * - `rejected`: 서비스가 이 메일을 받지 않았다(발신 도메인 미인증, 샌드박스 수신자 제한, 잘못된 주소 등).
 * - `rate_limited`: 서비스의 한도에 닿았다(잠시 뒤 다시).
 * - `unavailable`: 서비스가 응답하지 못했다(5xx, 네트워크 오류, 시간 초과).
 */
export type SendFailure =
  | "unauthorized"
  | "rejected"
  | "rate_limited"
  | "unavailable";

export interface MailPort {
  /** 메일 한 통을 보낸다. 실패해도 예외를 내지 않고 SendResult로 알린다(호출부가 사용자 응답으로 바꾸기 쉽게). */
  send(message: MailMessage): Promise<SendResult>;
}
