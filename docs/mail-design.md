# 메일 발송 (apps/server)

보고서 메일(`docs/goal-management.md` §3)을 보내기 위한 서버 쪽 기반이다. 지금 만든 것은 **발송 경계·Resend 연결·시험 메일**이고, 보고서 일정을 서버에 저장해 정해진 시각에 보내는 것은 다음 작업이다.

## 구조

```
PC(앱) ──▶ 서버(Workers) ──▶ 메일 서비스(Resend) ──▶ 사용자
          POST /mail/test      (키는 서버만 안다)
```

| 파일 | 책임 |
| --- | --- |
| `src/mail/port.ts` | `MailPort`(보낼 메일 → 결과) — 서버의 나머지는 이것만 안다. 실패는 예외가 아니라 `unauthorized / rejected / rate_limited / unavailable` 분류로 돌려준다. |
| `src/mail/config.ts` | 서비스 이름·발신자·한도 **상수**를 한 곳에서 정한다. 도메인이 비어 있으면 샌드박스 발신, 채우면 도메인 발신. |
| `src/mail/resend.ts` | Resend 어댑터. 키는 `Authorization` 헤더에만 쓰고 결과·오류에 담지 않는다. |
| `src/mail/factory.ts` | `MAIL_PROVIDER`에 맞는 어댑터를 만든다(서비스별로 다른 것은 여기와 어댑터뿐). |
| `src/mail/testMail.ts` | 시험 메일: 한도 확인 → 발송 → 기록. |

### 서비스·도메인을 바꾸는 방법 (갈아끼우기)

바꿀 때 만지는 곳은 설정뿐이다.

| 바꾸려는 것 | 어디를 | 비고 |
| --- | --- | --- |
| 발신 도메인(도메인을 산 뒤) | `wrangler.toml`의 `MAIL_FROM_DOMAIN = "내도메인.com"` | 발신 주소는 `reports@내도메인.com`. 비어 있으면 샌드박스. 값이 도메인 모양이 아니면 보내지 않고 설정 오류(503)로 알린다. |
| 메일 서비스 | `MAIL_PROVIDER`와 그 서비스의 비밀 키 | 새 서비스는 `resend.ts`처럼 `MailPort`를 구현한 어댑터 파일 하나와 `factory.ts`·`config.ts`의 이름 한 줄이면 된다. |
| 발신 표시 이름·앞부분 | `config.ts`의 `SENDER_NAME`, `SENDER_LOCAL_PART` | |
| 발송 한도 | `config.ts`의 `LIMITS` | |

비밀 키는 코드·`wrangler.toml`에 쓰지 않는다: 로컬은 `apps/server/.dev.vars`(gitignore), 운영은 `wrangler secret put RESEND_API_KEY`.

## 시험 메일 `POST /mail/test`

- **로그인한 사용자 본인의 이메일로만** 간다. 요청 본문의 주소는 읽지 않는다 — 읽으면 우리 도메인으로 아무에게나 보내는 **스팸 중계**가 된다.
- 응답에는 전체 주소가 아니라 가린 주소(`p***@example.com`)만 담긴다.
- 한도: 사용자당 하루 3통, 서버 전체 하루 80통(UTC 날짜 기준, `LIMITS`). Resend 무료 한도(하루 100통, 월 3,000통)보다 낮게 잡아, 청구가 늘기 전에 코드가 먼저 멈춘다.
  확인과 자리 잡기를 한 SQL 문으로 해서(`mail_sends`) 동시에 요청이 몰려도 넘지 않는다. 발송에 실패하면 잡은 자리를 돌려준다(실패가 한도를 깎지 않는다).
- 기록(`mail_sends`)에는 사용자·종류·날짜·접수 번호만 있고 **주소·제목·본문은 없다**(테스트가 칸을 고정한다). 계정을 지우면 같이 지워진다.
- 실패 응답: `mail_not_configured`(503/502 — 키·설정), `mail_rejected`(502 — 서비스가 거절), `provider_rate_limited`(429), `mail_unavailable`(503), `daily_limit`·`service_daily_limit`(429).

## 처음 시험해 보는 순서 (도메인 없이 $0)

1. [Resend](https://resend.com)에 가입하고 API 키를 만든다(발송 권한만 있는 키).
2. `apps/server/.dev.vars`에 `RESEND_API_KEY=<키>`를 한 줄 추가한다(이 파일은 커밋되지 않는다).
3. 로컬 DB 준비와 서버 실행:
   ```
   cd apps/server
   pnpm exec wrangler d1 migrations apply DB --local
   TOKEN=$(node scripts/dev-token.mjs <Resend에 가입한 이메일>)   # 시험용 사용자와 토큰을 로컬 DB에 만든다
   pnpm exec wrangler dev
   ```
4. 다른 터미널에서: `curl -X POST http://127.0.0.1:8787/mail/test -H "Authorization: Bearer $TOKEN"`
5. 도메인이 없는 동안은 샌드박스 발신(`onboarding@resend.dev`)이라 **Resend에 가입한 계정의 이메일로만** 갈 수 있다. 3번의 이메일을 그 주소로 해야 한다 — 다른 주소면 `mail_rejected`(도메인 설정 필요)가 온다.

## 도메인을 산 뒤

1. Cloudflare Registrar에서 도메인을 산다(원가 판매, 연 $10 안팎).
2. Resend에서 그 도메인을 추가하고, 알려 주는 **SPF·DKIM(·DMARC) DNS 레코드**를 Cloudflare DNS에 넣어 인증을 마친다. 발신 주소의 도메인이 서명 도메인과 같아야(정렬) 스팸함으로 가지 않는다.
3. `wrangler.toml`의 `MAIL_FROM_DOMAIN`을 채우고 배포한다. 운영 키는 `wrangler secret put RESEND_API_KEY`, DB는 `wrangler d1 migrations apply DB --remote`.
4. 시험 메일을 다시 보내 메일 헤더의 `spf=pass dkim=pass dmarc=pass`를 확인한다.

## 비용 가드

- 무료 구성(Workers Free + D1 Free + Resend Free)은 한도에 닿으면 **청구가 아니라 멈춤**이다. Paid로 올리기 전에 `LIMITS`를 먼저 점검한다.
- 수신자 고정 + 사용자별·서버 전체 한도 + 실패 시 자리 반환이 폭주를 막는다.
- 보고서 메일을 붙일 때는 한 사용자의 여러 목표를 **한 통으로 묶고**(다이제스트), 보낼 시각을 분산한다(하루 100통 한도).

## 아직 없는 것 (다음 작업)

- 보고서 일정의 서버 저장과 Cron 발송, 메일 본문(집계값만 — `docs/data-handling.md`), 수신 거부(서명 토큰·`List-Unsubscribe`), 반송·신고 웹훅과 발송 정지 목록.
- 이 PC의 앱에서 시험 메일을 요청하는 화면. 지금은 서버 API만 있다.
