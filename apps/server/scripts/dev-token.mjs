// 개발 전용: **로컬** D1에 시험용 사용자와 로그인 토큰을 직접 넣고, 토큰 원문을 출력한다.
//
// Google 로그인은 비밀 키와 브라우저가 필요해서 시험(동기화 에이전트의 통합 시험 등)에서는 쓸 수 없다. 서버 코드에 인증을
// 건너뛰는 길을 만드는 대신, 서버가 로그인 때 하는 것과 똑같이(토큰은 SHA-256 해시만 저장) 로컬 DB에 한 줄을 넣는다.
// 운영 DB는 건드리지 않는다: 이 스크립트는 `--local`만 쓰고, `--remote` 같은 인자는 거부한다.
//
// 사용법(apps/server에서):  node scripts/dev-token.mjs [이메일]
//   예) TOKEN=$(node scripts/dev-token.mjs dev@example.com)
//   컨테이너:  docker compose exec server node scripts/dev-token.mjs

import { execFileSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const args = process.argv.slice(2);
if (args.length > 1 || args.some((arg) => arg.startsWith("-"))) {
  console.error(
    "사용법: node scripts/dev-token.mjs [이메일]  (옵션은 받지 않습니다. 로컬 DB에만 씁니다.)",
  );
  process.exit(2);
}
const email = args[0] ?? "dev@example.com";
// SQL에 그대로 넣으므로 따옴표·세미콜론·공백이 없는 단순한 이메일만 받는다.
if (!/^[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+$/.test(email)) {
  console.error(`이메일 모양이 올바르지 않습니다: ${email}`);
  process.exit(2);
}

const token = randomBytes(32).toString("base64url"); // 서버의 generateToken과 같은 모양(43자)
const hash = createHash("sha256").update(token).digest("hex"); // 서버의 hashToken과 같다
const now = new Date();
const expires = new Date(now.getTime() + 30 * 24 * 60 * 60 * 1000);
const sub = `dev-${email}`;

const sql = [
  `INSERT INTO users (google_sub, email, created_at, updated_at) VALUES ('${sub}', '${email}', '${now.toISOString()}', '${now.toISOString()}') ` +
    "ON CONFLICT(google_sub) DO UPDATE SET updated_at = excluded.updated_at;",
  `INSERT INTO tokens (token_hash, user_id, created_at, expires_at) SELECT '${hash}', id, '${now.toISOString()}', '${expires.toISOString()}' FROM users WHERE google_sub = '${sub}';`,
].join(" ");

// wrangler의 JS 진입점을 node로 직접 실행한다(Windows의 .cmd 래퍼와 셸 인용 문제를 피한다).
const require = createRequire(import.meta.url);
const wrangler = join(
  dirname(require.resolve("wrangler/package.json")),
  "bin",
  "wrangler.js",
);
try {
  execFileSync(
    process.execPath,
    [wrangler, "d1", "execute", "DB", "--local", "--command", sql],
    {
      stdio: ["ignore", "ignore", "pipe"],
      env: { ...process.env, WRANGLER_SEND_METRICS: "false" },
    },
  );
} catch (error) {
  console.error(
    "로컬 D1에 쓰지 못했습니다. 먼저 마이그레이션을 적용했는지 확인하세요(wrangler d1 migrations apply DB --local).",
  );
  console.error(String(error.stderr ?? error.message).slice(0, 600));
  process.exit(1);
}
console.log(token);
