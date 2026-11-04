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
