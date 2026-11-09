// 상단 막대의 동기화 상태 칩: 어떤 글자를 어떤 톤으로 보여 줄지. DOM·hub를 모르는 순수 함수(lib 층)라 그대로 단위 테스트한다.

export interface StatusLike {
  enabled: boolean;
  state: "off" | "waiting" | "pending" | "ok" | "error" | "stale";
  result: string | null;
  last_attempt_at: string | null;
  last_success_at: string | null;
  problems: number;
  interval_seconds: number | null;
}

/** 칩의 톤: neutral(회색), good(정상), warn(주의), bad(오류). 색에만 기대지 않도록 글자도 항상 함께 보여 준다. */
export type Tone = "neutral" | "good" | "warn" | "bad";

export interface Chip {
  label: string;
  /** 마우스를 올렸을 때 보이는 자세한 설명(무엇을 하면 되는지 포함). */
  detail: string;
  tone: Tone;
}

/** "방금", "5분 전", "3시간 전", "2일 전". 미래이거나 읽을 수 없는 시각은 null. */
export function relativeTime(stamp: string | null, now: Date): string | null {
  if (stamp === null) {
    return null;
  }
  const then = new Date(stamp).getTime();
  if (Number.isNaN(then)) {
    return null;
  }
  const seconds = Math.floor((now.getTime() - then) / 1000);
  if (seconds < -60) {
    return null;
  }
  if (seconds < 60) {
    return "방금";
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return `${minutes}분 전`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours}시간 전`;
  }
  return `${Math.floor(hours / 24)}일 전`;
}

/** 에이전트의 주기를 "5분마다"처럼. 모르면 "주기마다". */
export function everyText(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds) || seconds <= 0) {
    return "주기마다";
  }
  if (seconds < 60) {
    return `${Math.round(seconds)}초마다`;
  }
  return `${Math.round(seconds / 60)}분마다`;
}

/** 오류 종류를 사용자가 할 일이 보이는 문장으로. 모르는 종류는 일반 문장으로 둔다. */
function errorDetail(result: string | null, every: string): string {
  switch (result) {
    case "unreachable":
      return "서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요. 연결되면 자동으로 이어서 동기화해요.";
    case "not_authorized":
      return "로그인이 만료됐어요. 로그아웃한 뒤 다시 로그인해 주세요.";
    case "signed_out":
      // 로그인한 뒤의 주기에서도 에이전트가 로그인 정보를 찾지 못했다(로그인 전 주기의 기록이면 hub가 pending으로 준다).
      // 한 번은 순간적인 문제일 수 있어 다시 시도한다는 것을 먼저 알리고, 계속될 때 할 일을 그다음에 적는다.
      return `아직 동기화되지 않았어요. 동기화 에이전트가 로그인 정보를 찾지 못해 이 PC의 목표 변경과 달성 시간이 서버에 반영되지 않았어요. 에이전트는 ${every} 다시 시도해요. 계속 이 안내가 보이면 에이전트가 Windows 자격 증명 관리자에서 로그인 정보를 읽지 못하는 것일 수 있어요 — 로그아웃한 뒤 다시 로그인해 주세요.`;
    case "server_error":
      return "서버가 요청을 처리하지 못했어요. 잠시 뒤 자동으로 다시 시도해요.";
    default:
      return "동기화 중 문제가 생겼어요. 잠시 뒤 자동으로 다시 시도해요.";
  }
}

/**
 * 상태를 칩 하나로. 켜지 않았으면 null(칩을 그리지 않는다 — 동기화를 안 쓰는 사람에게 상태를 들이밀지 않는다).
 * - ok: "동기화됨 · 5분 전"(올리지 못한 항목이 있으면 주의)
 * - waiting: 켰지만 에이전트가 아직 한 번도 안 돌았다 → 에이전트를 실행해야 한다
 * - pending: 방금 로그인했다 → 에이전트의 다음 주기에 동기화된다(오류가 아니다)
 * - stale: 에이전트가 한동안 돌지 않았다 → 마지막 성공 시각과 함께 알린다
 * - error: 마지막 시도가 실패 → 종류별 안내
 */
export function chipFor(status: StatusLike, now: Date): Chip | null {
  if (!status.enabled || status.state === "off") {
    return null;
  }
  const lastSuccess = relativeTime(status.last_success_at, now);
  const since = lastSuccess ? ` 마지막으로 동기화된 때: ${lastSuccess}.` : "";
  const every = everyText(status.interval_seconds);
  switch (status.state) {
    case "pending":
      return {
        label: "곧 동기화돼요",
        detail: `아직 동기화되지 않았어요. 동기화 에이전트는 ${every} 서버와 맞춰서, 로그인 직후에는 다음 차례까지 기다려요. 그때 자동으로 동기화돼요.`,
        tone: "neutral",
      };
    case "waiting":
      return {
        label: "동기화 대기 중",
        detail:
          "동기화를 켰지만 동기화 에이전트가 아직 한 번도 실행되지 않았어요. 터미널에서 uv run python -m sync_agent 를 실행해 주세요.",
        tone: "warn",
      };
    case "stale":
      return {
        label: lastSuccess ? `에이전트 멈춤 · ${lastSuccess}` : "에이전트 멈춤",
        detail: `동기화 에이전트가 한동안 실행되지 않았어요. 이 PC의 목표 변경과 달성 시간이 서버에 반영되지 않고 있어요.${since} 터미널에서 uv run python -m sync_agent 를 실행해 주세요.`,
        tone: "warn",
      };
    case "error":
      return {
        label: "동기화 오류",
        detail: `${errorDetail(status.result, every)}${since}`,
        tone: "bad",
      };
    case "ok": {
      const when = relativeTime(status.last_success_at, now);
      if (status.problems > 0) {
        return {
          label: `일부만 동기화됨 · ${status.problems}건`,
          detail: `올리지 못한 목표가 ${status.problems}개 있어요(이름이 서버의 다른 목표와 겹치는 경우 등). '목표 동기화'에서 확인해 주세요.${since}`,
          tone: "warn",
        };
      }
      // 마지막 시도가 "건너뜀"(로그인 전, 동기화 꺼짐 등)이라 성공한 적이 없으면 시각이 없다.
      return {
        label: when ? `동기화됨 · ${when}` : "동기화 준비됨",
        detail: when
          ? "목표와 날짜별 달성 시간이 서버와 맞춰져 있어요."
          : "에이전트가 실행 중이에요. 첫 동기화를 기다리고 있어요.",
        tone: "good",
      };
    }
  }
}

/** 상태를 얼마나 자주 다시 물을지(ms): 정상일 때는 느긋하게, 문제가 있을 때는 조금 더 자주. */
export function pollIntervalMs(status: StatusLike | null): number {
  if (status === null || status.state === "off") {
    return 60_000;
  }
  return status.state === "ok" ? 30_000 : 15_000;
}
