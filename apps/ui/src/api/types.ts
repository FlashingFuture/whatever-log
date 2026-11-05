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

/** 사용자의 목표 하나. 규칙의 원본은 packages/goals다. */
export interface Goal {
  id: number;
  name: string;
  daily_target_minutes: number;
  /** 적용 요일(월=0 … 일=6). */
  weekdays: number[];
  /** 연결된 프로세스 이름들. 한 프로세스는 하나의 목표에만 연결된다. */
  processes: string[];
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
}

export interface ProcessTime {
  process: string;
  active_seconds: number;
}

/** 목표 하나의 구간 수행 시간(연결 프로세스의 활성 시간 합). */
export interface GoalProgress {
  id: number;
  name: string;
  active_seconds: number;
  processes: ProcessTime[];
}

/** 구간의 목표별 수행 시간과 요약. 계산(정의)은 서버(packages/goals)가 한다. */
export interface GoalProgressResponse {
  start: string;
  end: string;
  goals: GoalProgress[];
  summary: {
    /** 모든 목표의 수행 시간 합. */
    active_seconds: number;
    /** 연결된 프로세스 중 활성 시간이 가장 긴 것(전부 0이면 null). */
    top: ProcessTime | null;
  };
}
