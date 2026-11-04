import { getJson, requestTimeoutMs } from "./client";
import type { ProcessSeries, RangeUsage, SiteRangeUsage } from "./types";

export function fetchUsage(start: Date, end: Date): Promise<RangeUsage> {
  // toISOString()은 항상 UTC("...Z")라 오프셋의 "+"가 쿼리 문자열에서 공백으로
  // 깨질 일이 없다. URLSearchParams가 나머지 인코딩을 맡는다.
  const query = new URLSearchParams({
    start: start.toISOString(),
    end: end.toISOString(),
  });
  return getJson(
    `/api/usage?${query}`,
    requestTimeoutMs(end.getTime() - start.getTime()),
  );
}

/** 구간의 사이트(도메인)별 사용 시간(그 브라우저가 foreground였던 시간 기준). */
export function fetchSiteUsage(
  process: string,
  start: Date,
  end: Date,
): Promise<SiteRangeUsage> {
  const query = new URLSearchParams({
    process,
    start: start.toISOString(),
    end: end.toISOString(),
  });
  return getJson(
    `/api/sites?${query}`,
    requestTimeoutMs(end.getTime() - start.getTime()),
  );
}

/**
 * 한 프로세스의 사용 시간을 칸별로 받는다. 칸 경계는 로컬 타임존으로 계산한
 * 것을 넘긴다(hub는 달력을 모른다) — 맨 앞 칸의 시작부터 맨 뒤 칸의 끝까지
 * 이어진 경계 목록이다.
 */
export function fetchProcessUsage(
  process: string,
  buckets: { start: Date; end: Date }[],
): Promise<ProcessSeries> {
  const edges = [
    ...buckets.map((b) => b.start),
    buckets[buckets.length - 1].end,
  ];
  const query = new URLSearchParams({
    edges: edges.map((edge) => edge.toISOString()).join(","),
  });
  return getJson(
    `/api/processes/${encodeURIComponent(process)}/usage?${query}`,
    requestTimeoutMs(edges[edges.length - 1].getTime() - edges[0].getTime()),
  );
}
