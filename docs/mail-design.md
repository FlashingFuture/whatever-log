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
  확인과 자리 잡기를 한 SQL 문으로 해서(`mail_sends`) 동시에 요청이 몰려도 넘지 않는다. 
  **자리를 돌려주는 경우는 서비스가 접수하지 않았음이 확실한 실패(키 오류·거절·한도)뿐이다.** 응답을 확인하지 못한 실패(5xx·네트워크·시간 초과·접수 번호 없음)는 서비스가 이미 접수했을 수 있어 자리를 **유지**한다 — 돌려주면 재시도가 새 멱등 키로 같은 메일을 한 번 더 보내 실제 발송이 한도를 넘을 수 있다. 그래서 일시 장애도 사용자의 하루 한도에 들어가고, 안내는 "메일이 이미 갔을 수 있으니 받은편지함을 확인하라"고 한다.
- 기록(`mail_sends`)에는 사용자 키·종류·날짜·접수 번호만 있고 **주소·제목·본문은 없다**(테스트가 칸을 고정한다).
  사용자 키는 계정(`users.id`)이 아니라 **Google 계정 고유 값(sub)의 SHA-256**이다. 이 기록은 계정 행을 참조하지 않아 **계정을 지워도 남는다** — 지우면 "발송 → 계정 삭제 → 재로그인"으로 하루 한도를 되돌릴 수 있기 때문이다(같은 Google 계정은 재로그인해도 같은 키).
  쌓이지 않게 이틀(`RETENTION_DAYS`)이 지난 행은 다음 발송 때 지운다.
- 실패 응답: `mail_not_configured`(503/502 — 키·설정), `mail_rejected`(502 — 서비스가 거절), `provider_rate_limited`(429), `mail_unavailable`(503), `daily_limit`·`service_daily_limit`(429).

## 처음 시험해 보는 순서 (도메인 없이 $0)

1. [Resend](https://resend.com)에 가입하고 API 키를 만든다(발송 권한만 있는 키).
2. `apps/server/.dev.vars`에 `RESEND_API_KEY=<키>`를 한 줄 추가한다(이 파일은 커밋되지 않는다).
3. 로컬 DB를 준비한다(한 번만. 이미 적용돼 있으면 "No migrations to apply"가 나오는 것이 정상이다):
   ```
   cd apps/server
   pnpm exec wrangler d1 migrations apply DB --local
   ```
4. **터미널 두 개**를 쓴다 — `wrangler dev`가 터미널 하나를 계속 차지하기 때문이다. 포트는 hub(8787)와 겹치지 않게 지정한다.
   - 터미널 1(서버): `pnpm exec wrangler dev --port 8798` — `Ready on http://127.0.0.1:8798`이 보일 때까지 둔다.
   - 터미널 2(요청):
     ```
     cd apps/server
     TOKEN=$(command node scripts/dev-token.mjs <Resend에 가입한 이메일>)   # 닫는 괄호까지 한 줄로. 시험용 사용자와 토큰을 로컬 DB에 만든다
     curl -X POST http://127.0.0.1:8798/mail/test -H "Authorization: Bearer $TOKEN"
     ```
     성공하면 `{"sent":true,"to":"x***@...","mode":"sandbox"}`가 오고, 잠시 뒤 그 주소의 받은편지함(또는 스팸함)에 "[whatever.log] 시험 메일"이 온다.
5. 도메인이 없는 동안은 샌드박스 발신(`onboarding@resend.dev`)이라 **Resend에 가입한 계정의 이메일로만** 갈 수 있다. 4번의 이메일을 그 주소로 해야 한다 — 다른 주소면 `mail_rejected`(도메인 설정 필요)가 온다.
   > Git Bash(mintty)는 `node`를 `winpty node.exe`로 바꾸는 별칭을 만들어서, `$(...)`로 출력을 담으면 `stdout is not a tty`로 실패한다. `command node …`(별칭 무시)로 쓴다.
6. 응답이 이상하면: `mail_not_configured`(503) = `.dev.vars`에 키가 없다/서버를 키를 넣기 전에 띄웠다(`.dev.vars`를 고치면 서버를 다시 띄운다), `mail_not_configured`(502) = 키가 틀렸다, `mail_rejected` = 위 5번.

## 도메인을 산 뒤

> 어떤 도메인을 어디서 왜 샀는지는 `docs/domain-decision.md`(결정 기록과 구매·연결 절차 전체).

1. Cloudflare Registrar에서 도메인을 산다(원가 판매, 연 $10 안팎).
2. Resend에서 그 도메인을 추가하고, 알려 주는 **SPF·DKIM(·DMARC) DNS 레코드**를 Cloudflare DNS에 넣어 인증을 마친다. 발신 주소의 도메인이 서명 도메인과 같아야(정렬) 스팸함으로 가지 않는다.
3. `wrangler.toml`의 `MAIL_FROM_DOMAIN`을 채우고 배포한다(`deploy-server` 워크플로가 마이그레이션과 함께 한다, `docs/deploy.md`). 운영 키는 `wrangler secret put RESEND_API_KEY`.
4. 시험 메일을 다시 보내 메일 헤더의 `spf=pass dkim=pass dmarc=pass`를 확인한다.

## 비용 가드

- 무료 구성(Workers Free + D1 Free + Resend Free)은 한도에 닿으면 **청구가 아니라 멈춤**이다. Paid로 올리기 전에 `LIMITS`를 먼저 점검한다.
- 수신자 고정 + 사용자별·서버 전체 한도(계정 삭제로 초기화되지 않는다) + 확실한 실패에서만 자리 반환이 폭주를 막는다.
- 보고서 메일을 붙일 때는 한 사용자의 여러 목표를 **한 통으로 묶고**(다이제스트), 보낼 시각을 분산한다(하루 100통 한도).

## 보고서 메일 구독 (D)

결정의 근거는 `docs/goal-management.md`의 "D·E. 메일 구독". 여기서는 서버의 모양을 적는다. 발송(Cron)·보고서 본문·화면은 E다.

| 주소 | 인증 | 하는 일 |
| --- | --- | --- |
| `GET /mail/subscription` | 토큰 | `{subscription \| null, daily_available}` |
| `PUT /mail/subscription` | 토큰 | 신청·변경 `{goal_id, frequency, weekday, day_of_month, send_time, timezone, replace}` → `{subscription, created, welcome}` |
| `PATCH /mail/subscription` | 토큰 | `{status: "active" \| "paused"}` 켜고 끄기 |
| `DELETE /mail/subscription` | 토큰 | 그만두기(행을 지운다) |
| `GET·POST /mail/unsubscribe?s=&t=` | 서명 | 메일의 수신 거부 링크. GET은 확인 페이지만, POST(원클릭 포함)가 끊는다 |
| `POST /mail/webhooks/resend` | Svix 서명 | 반송·스팸 신고 → 보내지 않을 주소 |

- **사용자당 하나**는 `mail_subscriptions.user_id UNIQUE`가 지킨다. 저장은 `INSERT … ON CONFLICT(user_id) DO UPDATE … WHERE`의 한 문장이고, 다른 목표를
  구독 중이면 `replace`일 때만 옮긴다(아니면 409 `subscription_exists`와 지금 구독 — 화면이 "옮길까요?"를 묻는다). 가드(`withSubscriptionGuard`)는
  계정을 읽고 보내지 않을 주소를 거르는 읽기 쉬운 껍데기이고, 보장은 DB가 한다.
- **주기**: `daily`(전날) / `weekly`(지난 월~일, `weekday` 0=월…6=일) / `monthly`(지난달, `day_of_month` 1~28). `send_time`은 `HH:MM`, `timezone`은 IANA 이름.
  맞지 않는 칸(매일에 요일 등)은 400이다.
- **상태**: `active` / `paused`(사용자가 끔) / `ended`(`goal_deleted`·`goal_ended`·`unsubscribed`·`suppressed`). 목표를 지우면 같은 배치에서 `goal_deleted`로
  끝난다. 끝난 구독은 다시 켤 수 없고 새로 신청한다. 기간이 이미 끝난 목표에는 신청할 수 없다(사용자 시간대의 오늘 기준). 기간 종료 처리(마지막 보고서
  뒤 `goal_ended`)는 발송과 함께 E에서 한다.
- **매일 상한**: 무료 요금제(`users.plan = 'free'`)에서 매일 구독자는 `LIMITS.dailySubscribers`(50)명까지다. 상한 확인은 저장과 같은 문장에서 한다.
  이미 매일인 사용자가 시각만 바꾸는 것은 막지 않고, 꺼 둔 매일 구독을 다시 켤 때는 다시 확인한다.
- **첫 신청 확인 메일**: 안내형. Google 계정당 한 번(`mail_welcomes`, 계정과 무관한 키 — 신청·해지·계정 삭제를 되풀이해도 다시 가지 않는다).
  발송 한도(`mail_sends.kind = 'welcome'`, 서버 전체 하루 상한에 들어간다)를 거치고, 멱등 키는 `welcome-<구독 id>`다. 실패해도 구독은 저장되고 다음
  신청·변경 때 다시 시도한다(접수됐을 수 있는 실패는 자리를 유지해 같은 날 다시 보내지 않는다). 결과는 응답의 `welcome`(`sent`·`already`·`suppressed`·
  `not_configured`·`limited`·`failed`).
- **수신 거부**: 메일마다 `List-Unsubscribe`(서명 링크)와 `List-Unsubscribe-Post: List-Unsubscribe=One-Click`을 단다. 링크의 서명은
  HMAC-SHA256(`MAIL_LINK_SECRET`, `unsubscribe:<구독 id>`)이고 만료가 없다. GET은 확인 페이지만 보인다 — 메일 보안 검사기가 링크를 미리 열어도 끊기지 않게.
- **반송·신고**: Resend 웹훅의 `email.bounced`(일시적 반송 제외)·`email.complained`가 오면 그 주소의 해시를 `mail_suppressions`에 넣고 그 주소를 쓰는
  사용자의 구독을 `suppressed`로 끝낸다. 막힌 주소는 신청·다시 켜기를 409 `mail_suppressed`로 거절한다(조회·끄기·지우기는 된다). 계정을 지워도 남는다.
- **설정(운영)**: `SERVER_PUBLIC_URL`(wrangler.toml), 비밀 `MAIL_LINK_SECRET`(긴 무작위 문자열)·`RESEND_WEBHOOK_SECRET`(Resend 대시보드 → Webhooks에서
  `https://<서버>/mail/webhooks/resend`를 `email.bounced`·`email.complained`로 등록하면 주는 `whsec_…`). 링크 비밀이 없으면 구독은 되지만 확인 메일을
  보내지 않고(`not_configured`), 웹훅 비밀이 없으면 웹훅은 503이다.
- **로컬의 옛 일정(`goal_report_schedules`)**: 서버로 자동으로 옮기지 않는다. E에서 화면을 서버 구독으로 바꿀 때, 이 PC에 저장된 일정이 있으면 신청 폼을
  그 값으로 채워 사용자가 한 번 확인해 신청하게 하고, 그 뒤 로컬 테이블을 비운다(사용자 몰래 서버로 보내는 값이 생기지 않게).

## 보고서 발송 (E1)

Cloudflare Cron(`wrangler.toml`의 `[triggers] crons = ["*/10 * * * *"]`)이 10분마다 `dispatchReports`(`src/mail/dispatch.ts`)를 부른다.

- **언제 보내나**: 켜진 구독마다 구독 시간대 기준 **지금 이전의 가장 최근 발송**(보낼 날·시각)을 구한다(`schedule.ts`). 매일은 그날, 매주는 그 요일, 매월은 그날(1~28)의
  `send_time`. 그 시각이 구독을 신청·변경한 시각(`updated_at`)보다 이르면 건너뛴다 — 신청하자마자 지난 보고서가 가지 않는다.
- **구간**: 매일 = 보낼 날의 전날, 매주 = 보낼 날 이전의 가장 최근 월~일, 매월 = 보낼 날의 지난달.
- **한 번만**: `mail_reports`의 (구독, 보낼 날) 기본 키에 먼저 넣은 실행만 보낸다(Cron이 겹쳐도). 멱등 키는 `report-<구독 id>-<보낼 날>`.
- **밀린 발송은 따라잡지 않는다**: 서버가 오래 멈췄다 돌아와도 가장 최근 구간 하나만 보낸다(옛 보고서가 몰려 오지 않게). 구독을 끄면(`paused`) 그동안의
  보고서도 가지 않는다.
- **내용**: 목표 이름, 구간, `목표 N 중 M (P%)`, 매주·매월은 날짜별 줄, "마지막 동기화 시각 기준" 안내, 수신 거부 링크(`List-Unsubscribe` 원클릭 포함).
  달성은 모든 기기의 합, 목표량은 그날 기기가 올린 값(가장 최근)을 쓰고, 기록이 없는 날은 서버가 아는 목표(요일·기간·만든 날)로 정한다. 목표를 적용하지
  않는 날의 시간은 달성에만 더한다(PC 화면과 같은 규칙).
- **기간 종료**: 구간이 목표 종료일을 덮으면 마지막 보고서("이번이 마지막")를 보낸 뒤 `goal_ended`로 끝낸다. 구간이 종료일보다 뒤면 보내지 않고 끝낸다.
- **막힌 주소**: 보내기 전에 다시 보고, 막혔으면 보내지 않고 `suppressed`로 끝낸다.
- **한도와 실패**: 사용자당 하루 보고서 2통(`LIMITS.reportPerUserPerDay`), 서버 전체 하루 상한(시험·확인과 합계), 한 실행에 20통(`reportsPerRun` — 나머지는
  다음 실행). 거절된 구간은 `failed`로 두고 다시 보내지 않는다. 일시적 실패·서비스 한도는 자리를 풀어 다음 실행이 같은 멱등 키로 다시 보낸다(접수됐을 수
  있는 실패는 발송 한도의 자리를 유지해 하루 2통에서 멈춘다). 키 오류는 그 실행을 멈춘다.
- 결과는 개수만 로그에 남긴다(`reports: {...}`). 발송 기록은 90일 지나면 지운다.
- 로컬 확인: `wrangler dev --test-scheduled` 뒤 `curl "http://127.0.0.1:8798/__scheduled?cron=*/10+*+*+*+*"`.

## 아직 없는 것 (E2)

- hub 중개와 화면(신청 폼, "옮길까요?", 상태·끝난 이유 표시, 로컬 옛 일정으로 폼 채우기, 시험 메일 요청). 그때 서버의 `API_VERSION`과 앱의 요구를 올린다.
