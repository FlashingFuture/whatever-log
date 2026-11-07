# 로그인 설계 (서버 계정)

서버에 목표 달성 수치를 보내 AI 보고서를 받으려면 "누가 요청했는지"를 알아야 한다. 이 문서는 그 로그인을
어떻게 만들지(그리고 **로그인이 없어도 기록·집계·목표는 그대로 돌아가게** 하는 경계)를 정리한다.
서버로 무엇이 나가는지는 `docs/data-handling.md`가 기준이다.

## 왜 로그인이 필요한가

서버에 올라가는 것은 기간·목표 이름·목표량·달성 시간·달성률뿐이다. 로그인이 필요한 이유는 셋이다.

- 보고서를 메일로 보내려면 **검증된 이메일 주소**가 있어야 한다.
- AI 호출에 비용이 드니 "하루 한 통" 같은 한도를 사람 단위로 걸어야 한다.
- 남의 보고서를 받지 못하게 요청한 사람을 구분해야 한다.

세 가지 모두 이메일이 검증된 계정이면 충족되고, 비밀번호는 필요 없다.

## 결정

| 항목 | 결정 | 이유 |
| --- | --- | --- |
| 로그인 방식 | 소셜 로그인만. 첫 제공자는 **Google** | 이메일 검증이 이미 끝나 있고, 비밀번호를 저장하지 않는다 |
| 비밀번호 로그인 | **만들지 않는다** | "서버에서 민감정보를 다루지 않는다" 원칙과 충돌(해시 저장·재설정 메일·유출 책임), 무료 서버에서 봇 가입이 AI 비용으로 이어진다 |
| 나중에 더할 수 있는 것 | 이메일 링크(매직링크) 로그인, Kakao 등 | 필요해질 때. 인증은 인터페이스 뒤에 두어 바꿀 수 있게 한다 |
| 서버 | **Cloudflare Workers**(무료 플랜) | 작고 이벤트 중심인 서버라 맞고, 잠들지 않는다 |
| 토큰 검증 | 서버가 코드 교환과 Google ID 토큰 검증을 **직접** 한다 | 제공자가 하나라 단순하고 외부 인증 서비스 의존이 없으며, 클라이언트 비밀이 서버에만 있다 |

## 로그인 흐름

1. 데스크톱 앱이 **시스템 브라우저**로 Google 로그인 페이지를 연다. pywebview 창 안에서 하지 않는다 — Google은
   임베디드 웹뷰 로그인을 막는다(구현 전에 현재 정책을 다시 확인한다).
2. 로그인이 끝나면 `http://127.0.0.1:<임시 포트>`로 돌아온다(루프백 리디렉션). 인증 코드는 **PKCE**로 교환한다
   (데스크톱 앱은 클라이언트 비밀을 숨길 수 없는 공개 클라이언트다).
3. 앱이 인증 코드와 `code_verifier`, `redirect_uri`를 서버 `POST /auth/google`에 보낸다. **코드 교환은 서버가
   한다** — 클라이언트 비밀(`GOOGLE_CLIENT_SECRET`)을 배포되는 앱에 넣지 않고 서버 시크릿으로만 두기 위해서다.
   앱은 클라이언트 ID(공개 값)만 안다. 서버가 코드·`code_verifier`·비밀로 Google에서 ID 토큰을 받는다.
4. 서버가 Google 공개키(JWKS)로 서명을 확인하고 `aud`(우리 클라이언트 ID), `exp`, `iss`,
   `email_verified`를 검사한다. 통과하면 `sub`(Google의 사용자 고유 값)를 키로 사용자를 만들거나 찾는다.
5. 서버가 **자체 토큰**을 발급해 돌려준다. 이후 요청은 이 토큰만 쓴다(Google 토큰은 보관하지 않는다).
6. 앱은 자체 토큰을 **Windows 자격 증명 관리자**에 둔다. `goals.db`·`recorder.db`에는 두지 않는다.

## 설정 값의 위치

| 값 | 비밀 | 위치 |
| --- | --- | --- |
| `GOOGLE_CLIENT_ID` | 아니요 | `apps/server/wrangler.toml`의 `[vars]`(커밋), 데스크톱 설정 |
| `GOOGLE_CLIENT_SECRET` | **예** | 로컬 개발: `apps/server/.dev.vars`(gitignore됨). 운영: `wrangler secret put GOOGLE_CLIENT_SECRET` |

`apps/server/.dev.vars.example`(커밋)에 키 이름만 두고 값은 비운다. 자체 토큰은 무작위 불투명 토큰이고 해시만
저장하므로 서명 키는 필요 없다.

## 서버에 저장되는 것

- `sub`, 이메일(메일 발송에 필요), 가입 시각, 자체 토큰의 **해시**(원문은 저장하지 않는다)
- 보고서 요청에 담긴 집계 수치(`docs/data-handling.md`의 표)
- 이메일은 처음으로 서버에 가는 **사용자 식별 값**이다. 구현할 때 `docs/data-handling.md`의 "전송되지 않는
  내용"과 표를 먼저 고친다.
- **계정 삭제**: 서버가 사용자와 그에 딸린 데이터(목표·달성도·토큰)를 모두 지운다(국내 개인정보 보호 요건).
  서버 API(`DELETE /account`)는 만들어져 있고(`docs/sync-design.md`), 화면의 버튼은 아직 없다.

## 로그인이 없어도 돌아가야 한다

로그인은 서버 기능(보고서)에만 필요하다. recorder·집계·hub 핵심·목표(`goals`)·화면은 로그인 없이, 오프라인
이어도 전부 동작해야 한다. 지키는 규칙은 다음과 같다.

- **의존 방향**: 서버와 통신하는 코드는 `packages/cloud`에만 둔다. recorder, aggregation, goals, chromium,
  supervision과 `apps/recorder`는 `cloud`를 **import하지 않고 의존성에도 넣지 않는다**(테스트가 검사한다).
  서버를 부르는 쪽만 `cloud`에 의존한다. 지금은 **hub 하나**가 예외다(화면의 로그인 버튼이 hub의 계정 API를
  거친다). 그래도 hub의 기록·집계·목표가 로그인에 묶이지 않도록, hub가 `cloud`를 아는 곳을 어댑터
  `apps/hub/src/hub/cloud_adapter.py` 하나로 좁히고 그 import를 함수 안에만 둔다. `cloud`를 불러오지 못하면 계정
  기능만 "사용할 수 없음"이 되고 hub의 나머지는 그대로 뜬다(테스트가 `cloud` import를 막은 프로세스에서 실제로
  hub를 띄워 확인한다).
- **로그인 요구는 호출 지점에서**: 서버를 부르는 함수에만 `@require_login`을 붙인다. 로그인이 안 되어 있거나
  토큰이 만료됐으면 네트워크에 가기 전에 `NotSignedIn`이 난다. 화면은 보고서 자리에만 "로그인하면 쓸 수
  있어요"를 보여 준다.
- **실패는 격리**: 서버 통신 실패·오프라인은 기록에 영향을 주지 않는다. 전송은 별도 에이전트에서 큐에 쌓아
  재시도한다(예정).
- **토큰 저장은 인터페이스**: `TokenStore`가 저장 위치를 감춘다. 운영 구현은 `KeyringTokenStore`(OS 자격
  증명 관리자)이고, 평문 파일에 남기는 백엔드(예: `PlaintextKeyring`)는 저장을 거부한다. 메모리 구현
  (`InMemoryTokenStore`)은 테스트용이다.

## `POST /auth/google` (apps/server)

요청: `{"code", "code_verifier", "redirect_uri"}` (JSON, 4KB 이하, 모르는 칸 거부). `redirect_uri`는
`http://127.0.0.1|localhost|[::1]:<포트>[/경로]`만 받는다.

| 응답 | 의미 |
| --- | --- |
| 200 `{token, expires_at, email}` | 성공. 토큰 원문은 이 응답에서만 나간다(DB에는 SHA-256 해시만). 유효 기간 30일 |
| 400 `invalid_request` | 본문 형식 오류 / 413·415는 크기·Content-Type |
| 400 `invalid_grant` | 코드가 만료됐거나 이미 쓰였다 — 다시 로그인하면 된다 |
| 403 `email_not_verified` | Google이 이메일을 검증하지 않은 계정 |
| 502 `upstream_error` | Google 쪽·우리 설정 문제. 응답에는 상세 내용을 담지 않는다 |

- 토큰은 무작위 32바이트(서명 키 불필요). 사용자당 유효 토큰은 5개까지이고 넘으면 오래된 것부터, 만료된 것은
  다음 로그인 때 지운다. 모든 응답은 `Cache-Control: no-store`다.
- 저장소는 D1(`users`, `tokens`; `apps/server/migrations/`). 사용자를 지우면 토큰도 함께 지워진다(계정 삭제).
- Google 공개키(JWKS)는 Worker 인스턴스에서 1시간 캐시하고, 모르는 `kid`는 1분에 한 번만 다시 받는다.
- 코드·토큰·비밀은 로그에 남기지 않는다.

배포 전에 할 일: `wrangler d1 create whatever-log`로 만든 id를 `wrangler.toml`의 `database_id`에 넣고,
`wrangler d1 migrations apply DB --remote`, `wrangler secret put GOOGLE_CLIENT_SECRET`, `wrangler deploy`.
로컬 확인은 `wrangler d1 migrations apply DB --local` 뒤 `wrangler dev`.

## 데스크톱 로그인 (packages/cloud)

`sign_in_with_google(config)`가 한 번에 진행한다.

1. PKCE `code_verifier`(무작위 86자)와 `state`를 만들고 `127.0.0.1`의 빈 포트에 일회용 서버를 연다.
2. 시스템 브라우저로 Google 로그인 주소를 연다. 범위는 `openid email`뿐이다. 브라우저를 못 열어도 쓸 수 있게
   주소를 `show_url`로도 알린다.
3. 돌아온 `/callback`에서 `state`가 맞는 첫 콜백만 받는다(틀린 `state`·코드 없음·다른 경로는 응답만 하고
   계속 기다린다). 사용자가 취소하면(`error=`) `LoginCancelled`, 180초가 지나면 `LoginFailed`.
4. 코드·`code_verifier`·`redirect_uri`를 서버 `POST /auth/google`에 보내 토큰을 받는다. 앱은 클라이언트 비밀을
   갖지 않는다. 서버 주소는 https(또는 개발용 로컬 http)만 받는다.
5. 호출부가 `Account.sign_in(session)`으로 저장한다. 운영 저장소는 `KeyringTokenStore`(Windows 자격 증명
   관리자, 서비스 `whatever.log`)다. 저장된 값이 깨졌거나 자격 증명 관리자를 쓸 수 없으면 `load`는 "로그인 안 됨"으로
   보고(로컬 기능은 로그인에 의존하지 않는다), `save`는 실패를 숨기지 않는다.

직접 해 보기: `uv run python -m cloud login | status | logout`. 로컬 서버(`wrangler dev`)로 시험하려면
환경 변수 `WHATEVER_LOG_SERVER_URL=http://127.0.0.1:8790`을 준다(다른 서버를 쓸 때는 Google 클라이언트 ID도
`WHATEVER_LOG_GOOGLE_CLIENT_ID`로 맞춘다). 명령줄의 `logout`은 이 PC의 로그인 정보만 지운다. 서버의 토큰까지
폐기하는 것은 화면(hub)의 로그아웃이다(아래).

## 화면과 hub의 계정 API (apps/hub)

화면(UI)의 상단 막대 로그인 버튼은 hub의 계정 API를 부른다. 로그인은 사용자가 브라우저에서 끝낼 때까지 최대 3분이
걸려서, hub가 별도 스레드에서 진행하고 화면은 결과를 주기적으로 묻는다(상태 관리는 `docs/ui-state.md`).

| 요청 | 설명 |
| --- | --- |
| `GET /api/account` | `{available, signed_in, email, login: {state, message}, providers: [{id, label}]}`. `login.state`는 `idle`·`pending`·`failed`. **토큰은 어디에도 없다** |
| `POST /api/account/login` | `{"provider": "google"}`. 시스템 브라우저를 열고 202. 이미 진행 중이면 409, 모르는 방식이면 400, 계정 기능이 없으면 503 |
| `DELETE /api/account/login` | 진행 중인 로그인을 취소한다(진행 중이 아니어도 200) |
| `POST /api/account/logout` | **이 PC의 로그인 정보를 먼저 지우고**(서버 주소 설정이 잘못됐거나 서버가 죽어 있어도 로그아웃은 이 PC에서 끝난다), 그 뒤 서버의 토큰 폐기를 시도한다(`POST /auth/logout`, 5초 제한, 어떤 실패도 무시). 응답에 `revoked_on_server`. 이 PC에서 지우지 못하면 500이고 이때는 서버 토큰도 폐기하지 않는다 |
| `GET /api/sync/plan` | 로그인 직후 "무엇을 서버에 올릴까요?" 확인 창의 내용: `{email, enabled, items: [{key, kind, name, daily_target_minutes, weekdays, local_*, declined}]}`. hub가 서버에서 목록을 받아 이 PC의 목표와 견준다. 올라가는 값만 있고 프로세스·사이트·내부 id·토큰은 없다. 로그인 전·만료는 409, 서버에 닿지 못하면 503 |
| `POST /api/sync/apply` | `{"accepted": [key…], "email"}`(`accepted`는 최대 100개, `email`은 확인 창의 계획에 있던 계정). 체크한 항목만 서버에 올리고·합치고·가져온다. 체크하지 않은 이 PC 목표는 `local_only`가 된다. **지금 로그인한 계정이 `email`과 다르면 서버를 부르지 않고 거절한다.** 응답 `{uploaded, merged, downloaded, kept_local, errors}`. 동시에 두 번 적용하면 409 |
| `GET /api/sync/status` | 동기화가 잘 되고 있는지: `{enabled, state, result, last_attempt_at, last_success_at, problems}`. `state`는 `off`·`waiting`·`ok`·`error`·`stale`. 이 PC의 `goals.db`만 읽고 서버를 부르지 않으며 로그인하지 않아도 답한다 |
| `GET /api/devices` | 달성도를 보낸 기기들(서버에서 받는다). 이 PC의 기기에는 `is_this_device`가 켜진다. 이름은 없다 |
| `DELETE /api/devices/<id>` | 그 기기가 보낸 달성 기록을 서버에서 지운다. 이 PC의 기기는 거절한다(에이전트가 다시 보낸다) |
| `POST /api/account/delete` | `{"email"}`(사용자가 확인한 계정). **서버의 계정과 모든 데이터를 지운다(되돌릴 수 없다).** 지금 로그인한 계정과 다르면 거절한다. 서버 삭제에 성공한 뒤에만 이 PC의 로그인 정보를 지우고 목표의 서버 연결을 끊는다. 응답 `{deleted_on_server, signed_out, connections_cleared}` |
| `POST /api/links/open` | `{"link": "privacy"}`. 고정된 목록의 바깥 링크만 시스템 브라우저로 연다(임의 주소는 400). 브라우저가 열리지 못하면 503을 돌려주어 화면이 직접 열기를 시도하게 한다 |

- 쓰기 요청은 기존 목표 API와 같은 방어를 적용한다: Host가 로컬이어야 하고, Origin이 허용된 UI와 **정확히** 같아야
  하며, 본문은 `application/json`(로그아웃·취소는 본문 없음)이다. 그래서 이 PC에서 도는 다른 웹페이지가 로그인을
  시작시키거나 로그아웃시킬 수 없다.
- **취소·로그아웃과 세션 저장은 한 잠금 안에서 일어난다.** 서버에서 토큰을 받는 사이에 취소·로그아웃이 일어났다면 그 세션은 저장하지 않고
  발급된 토큰의 폐기를 시도한 뒤(실패해도) 취소로 끝낸다. 로그아웃한 뒤에 로그인 정보가 되살아나는 일이 없다. 서버가 거부한 토큰(401)은 이 PC에서
  지워 로그인 버튼이 보이게 한다.
- 로그인 방식 목록은 `cloud.PROVIDERS`에서 오고 화면은 그 목록으로 버튼을 그린다. 새 방식은 `Provider` 한 줄과 서버의
  `/auth/<id>` 추가로 붙는다.
- 네이티브 창(webview)에서는 `target=_blank` 링크가 기본 브라우저로 열린다고 보장되지 않아서, 화면이 링크 이름만
  알리고 hub가 시스템 브라우저를 연다. 주소는 hub의 고정 목록(`hub/external_links.py`)에만 있다.

## 지금 있는 것 / 없는 것

- 있는 것: `packages/cloud`(`NotSignedIn`·`Session`·`TokenStore`·`Account`·`@require_login`, 위의 로그인 흐름,
  로그인 방식 목록, 자격 증명 관리자 저장소, 명령줄)와 격리 테스트, `apps/server`의 `POST /auth/google`(배포됨).
  토큰을 받아 쓰는 서버 API(목표·달성도·기기·`POST /auth/logout`·`DELETE /account`)는 서버 코드와 테스트가
  있다(`docs/sync-design.md`, 배포 전). hub의 계정 API와 화면의 상단 막대(로그인·로그아웃 버튼, 자세히 알아보기).
- 없는 것: desktop이 동기화 에이전트를 함께 띄우는 것, 요청
  횟수 제한, 전송 에이전트, 이메일 발송. 각각 만들 때 이 문서를 먼저 고친다.

## 확인해야 할 것

- Google OAuth 클라이언트 종류(데스크톱 앱)와 루프백 리디렉션의 현재 요구 사항, 임베디드 웹뷰 차단 정책.
- Cloudflare Workers 무료 한도(요청 수, 요청당 CPU 시간)와 Cron Trigger·D1 무료 한도. 무료 한도는 자주 바뀐다.
- Kakao 등 두 번째 제공자를 붙일 때 이메일 제공 조건(심사·사업자 등록 여부).
