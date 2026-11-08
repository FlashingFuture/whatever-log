// hub 응답의 모양(apps/hub의 JSON). 값은 모두 초 단위, 시각은 ISO 8601 문자열이다.

export interface ProcessUsage {
  process: string;
  active_seconds: number;
  idle_seconds: number;
  background_seconds: number;
  total_seconds: number;
}

/** 사이트(도메인) 하나의 사용 시간. 사이트는 foreground일 때만 알 수 있어 background가 없다. */
export interface SiteUsage {
  domain: string;
  active_seconds: number;
  idle_seconds: number;
  total_seconds: number;
}

export interface SiteRangeUsage {
  start: string;
  end: string;
  by_site: SiteUsage[];
}

/**
 * 구간 전체의 요약. 서버(packages/aggregation)가 계산한 값을 그대로 보여 준다 — "총 사용 시간"이
 * 무엇의 합인지 같은 정의를 화면이 다시 계산하면 목표 달성률·보고서와 갈라질 수 있다.
 */
export interface RangeSummary {
  /** 집중(active) 시간의 합. */
  active_seconds: number;
  idle_seconds: number;
  /** 집중 시간이 가장 긴 프로세스(전부 0이면 null). */
  top: { process: string; active_seconds: number } | null;
}

export interface RangeUsage {
  start: string;
  end: string;
  by_process: ProcessUsage[];
  summary: RangeSummary;
}

/** 한 프로세스의 칸 하나(시간 하나, 날짜 하나)의 사용 시간. */
export interface BucketUsage {
  start: string;
  end: string;
  active_seconds: number;
  idle_seconds: number;
  background_seconds: number;
  total_seconds: number;
}

export interface ProcessSeries {
  process: string;
  buckets: BucketUsage[];
}

/** 입력 한 칸의 오류(서버 검증 결과). 화면이 그 칸 옆에 그대로 보여 준다. */
export interface FieldError {
  field: string;
  code: string;
  message: string;
}

/** 어느 브라우저(프로세스 이름)에서 본 어느 사이트(도메인)인지. 사용 시간이 브라우저별로 따로 집계돼서 둘을 함께 든다. */
export interface SiteLink {
  browser: string;
  domain: string;
}

/** 사용자의 목표 하나. 규칙의 원본은 packages/goals다. */
export interface Goal {
  id: number;
  name: string;
  daily_target_minutes: number;
  /** 적용 요일(월=0 … 일=6). */
  weekdays: number[];
  /** 연결된 프로세스 이름들. 한 프로세스는 하나의 목표에만 연결된다. */
  processes: string[];
  /** 연결된 브라우저 사이트(세부 페이지). 브라우저 전체와 그 안의 사이트는 함께 연결할 수 없다. */
  sites: SiteLink[];
  created_at: string;
  updated_at: string;
}

/**
 * 목표를 만들거나 바꿀 때 보내는 값. 화면은 값을 고쳐 주지 않고 사용자가 넣은 그대로 보낸다 —
 * 형식 검증은 서버가 엄격하게 하므로 숫자 칸에 문자열이 올 수도 있다(그러면 서버가 칸별로 알려 준다).
 */
export interface GoalInput {
  name: string;
  daily_target_minutes: number | string;
  weekdays: number[];
  processes: string[];
  sites: SiteLink[];
}

export interface ProcessTime {
  process: string;
  active_seconds: number;
}

export interface SiteTime extends SiteLink {
  active_seconds: number;
}

/** 가장 길게 수행한 연결 대상. 사이트면 site에 도메인이 있고 process는 그 사이트를 본 브라우저다. */
export interface TopTarget extends ProcessTime {
  site: string | null;
}

/** 목표 하나의 구간 수행 시간(연결한 프로세스·사이트의 활성 시간 합). */
export interface GoalProgress {
  id: number;
  name: string;
  active_seconds: number;
  processes: ProcessTime[];
  sites: SiteTime[];
}

/** 구간의 목표별 수행 시간과 요약. 계산(정의)은 서버(packages/goals)가 한다. */
export interface GoalProgressResponse {
  start: string;
  end: string;
  goals: GoalProgress[];
  summary: {
    /** 모든 목표의 수행 시간 합. */
    active_seconds: number;
    /** 연결된 프로세스·사이트 중 활성 시간이 가장 긴 것(전부 0이면 null). */
    top: TopTarget | null;
  };
}

/** 로그인 방식 하나(화면의 로그인 버튼 하나). id는 요청에 쓰고 label은 버튼에 보인다. */
export interface LoginProvider {
  id: string;
  label: string;
}

/**
 * hub가 알려 주는 로그인 상태(`GET /api/account`). 로그인 토큰은 여기에 없다 — 토큰은 이 PC의 자격 증명
 * 관리자에만 있고 화면은 보지 못한다. login.state: idle(진행 안 함) / pending(브라우저에서 로그인 중) /
 * failed(직전 시도가 실패, message에 사유).
 */
export interface AccountSnapshot {
  /** false면 이 설치에서는 로그인 기능을 쓸 수 없다(나머지 기능은 그대로 동작한다). */
  available: boolean;
  signed_in: boolean;
  email: string | null;
  login: { state: "idle" | "pending" | "failed"; message: string | null };
  providers: LoginProvider[];
  /** 사용자가 확인 창에서 목표 동기화를 켰는지(이 PC의 설정). 켜기 전에 만든 목표는 서버로 가지 않는다. */
  sync_enabled: boolean;
  /** 지금 로그인을 가리키는 불투명한 키(토큰이 아니다). 확인 창에서 받아 되돌려 보내, 그 사이 로그인이 바뀌면 hub가 거절하게 한다. */
  session: string | null;
  /** 이 로그인에서 보낸 계정 삭제의 결과를 알 수 없는 채로 남아 있는가(서버에서 지워졌을 수 있다). 다시 시도하면 확인된다. */
  deletion_uncertain: boolean;
}

/** 로그아웃 응답: 상태에 더해, 서버의 토큰까지 폐기됐는지. */
export interface LogoutResponse extends AccountSnapshot {
  revoked_on_server: boolean;
}

/** 화면이 시스템 브라우저로 열어 달라고 요청할 수 있는 링크의 이름(hub가 고정 목록으로 주소를 정한다). */
export type ExternalLink = "privacy";

/**
 * 동기화 확인 창의 한 줄(`GET /api/sync/plan`). 올라가는 값(이름·목표 시간·요일)만 있고, 프로세스·사이트 연결은 없다.
 * kind: upload(이 PC에만 있는 목표를 서버에 추가) / merge(서버의 같은 이름 목표와 합침) / download(서버에만 있는 목표를
 * 이 PC에 추가). merge에서만 local_*에 이 PC의 값이 있다. declined는 전에 "올리지 않기"를 골랐던 목표다.
 */
export interface SyncItem {
  key: string;
  kind: "upload" | "merge" | "download";
  name: string;
  daily_target_minutes: number;
  weekdays: number[];
  local_daily_target_minutes: number | null;
  local_weekdays: number[] | null;
  declined: boolean;
}

export interface SyncPlan {
  email: string | null;
  session: string | null;
  /** 이 계정에서 이미 한 번 확인을 마쳤는지(처음이면 로그인 직후 자동으로 창을 연다). */
  enabled: boolean;
  items: SyncItem[];
}

/** 적용 결과(`POST /api/sync/apply`): 항목별 개수와 실패한 항목(key와 사용자용 사유). */
export interface SyncResult {
  uploaded: number;
  merged: number;
  downloaded: number;
  kept_local: number;
  errors: { key: string; message: string }[];
}

/**
 * 동기화가 잘 되고 있는지(`GET /api/sync/status`). off(켜지 않음) / waiting(켰지만 에이전트가 아직 한 번도 안 돎) / ok / error(마지막
 * 시도가 실패, result가 종류) / stale(에이전트가 한동안 돌지 않음). 목표 이름·프로세스는 없다 — 개수와 종류와 시각뿐이다.
 */
export interface SyncStatus {
  enabled: boolean;
  state: "off" | "waiting" | "ok" | "error" | "stale";
  /** 마지막 시도의 결과 종류(ok, signed_out, not_enabled, account_changed, unreachable, not_authorized, server_error, internal). */
  result: string | null;
  last_attempt_at: string | null;
  last_success_at: string | null;
  /** 이번 주기에 올리지 못한 항목 수. */
  problems: number;
}

/** 달성도를 보낸 기기 하나. 이름은 없다 — 무작위 기기 ID와 마지막으로 보낸 시각, 서버에 있는 줄 수뿐이다. */
export interface DeviceRow {
  device_id: string;
  last_sent_at: string;
  rows: number;
  is_this_device: boolean;
}

/** 기기 목록과, 목록을 받은 계정(지우기 요청에 되돌려 보내 그 사이 계정이 바뀌면 거절하게 한다). */
export interface DeviceList {
  email: string | null;
  session: string | null;
  devices: DeviceRow[];
}

/** 계정 삭제 결과: 서버에서 지웠고, 이 PC의 정리가 어디까지 됐는지. */
export interface DeleteAccountResult extends AccountSnapshot {
  deleted_on_server: boolean;
  signed_out: boolean;
  connections_cleared: boolean;
  /** false면 삭제 뒤 계정 상태를 읽지 못한 것이다 — 로그인 여부 등 나머지 칸을 믿지 말고 화면이 다시 읽어야 한다. */
  state_known?: boolean;
}
