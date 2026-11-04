import { getJson, requestTimeoutMs } from "./client.ts";
import type { ProcessSeries, RangeUsage, SiteRangeUsage } from "./types";

export function fetchUsage(start: Date, end: Date): Promise<RangeUsage> {
  // toISOString()은 항상 UTC("...Z")라 오프셋의 "+"가 쿼리 문자열에서 공백으로
  // 깨질 일이 없다. URLSearchParams가 나머지 인코딩을 맡는다.
  const query = new URLSearchParams({
    start: start.toISOString(),
    end: end.toISOString(),
  });
  return getJson<RangeUsage>(
    `/api/usage?${query}`,
    requestTimeoutMs(end.getTime() - start.getTime()),
  ).then(requireSummary);
}

/**
 * 구간 요약(summary)이 없는 응답을 알아보기 쉬운 오류로 바꾼다. 요약은 서버가 계산해 내려 주는데,
 * 앱보다 오래된 hub(앱만 새로 띄우고 이미 떠 있던 hub를 그대로 쓰는 경우)는 이 필드가 없다 —
 * 그대로 두면 화면이 "Cannot destructure property …" 같은 알 수 없는 오류로 깨진다.
 */
function requireSummary(usage: RangeUsage): RangeUsage {
  if (!usage.summary) {
    throw new Error(
      "hub가 이 앱보다 오래된 버전이라 구간 요약을 받을 수 없습니다. 앱을 완전히 종료했다가 다시 실행해 주세요.",
    );
  }
  return usage;
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
