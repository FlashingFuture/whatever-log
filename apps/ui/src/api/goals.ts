import {
  getJson,
  requestTimeoutMs,
  SHORT_REQUEST_TIMEOUT_MS,
  sendJson,
} from "./client.ts";
import type {
  Goal,
  GoalInput,
  GoalProgressResponse,
  GoalTotals,
  SiteLink,
} from "./types";

/** 저장된 목표 목록(만든 순서). */
export async function fetchGoals(): Promise<Goal[]> {
  const response = await getJson<{ goals: Goal[] }>(
    "/api/goals",
    SHORT_REQUEST_TIMEOUT_MS,
  );
  return response.goals;
}

/** 목표를 만든다. 입력 오류는 칸별 오류를 담은 ApiError(fields)로 온다. */
export function createGoal(input: GoalInput): Promise<Goal> {
  return sendJson("POST", "/api/goals", input, SHORT_REQUEST_TIMEOUT_MS);
}

/** 목표를 통째로 바꾼다(모든 칸을 보낸다 — 연결 프로세스를 바꿀 때도 나머지 칸은 그대로 다시 보낸다). */
export function updateGoal(id: number, input: GoalInput): Promise<Goal> {
  return sendJson("PUT", `/api/goals/${id}`, input, SHORT_REQUEST_TIMEOUT_MS);
}

/** 목표를 지운다(연결 정보도 같이). */
export async function deleteGoal(id: number): Promise<void> {
  await sendJson(
    "DELETE",
    `/api/goals/${id}`,
    undefined,
    SHORT_REQUEST_TIMEOUT_MS,
  );
}

/**
 * 구간의 목표별 수행 시간과 요약. 수행 시간의 정의(연결 프로세스의 활성 시간 합)는 서버가 갖고 있어
 * 화면은 다시 계산하지 않는다.
 */
export function fetchGoalProgress(
  start: Date,
  end: Date,
): Promise<GoalProgressResponse> {
  const query = new URLSearchParams({
    start: start.toISOString(),
    end: end.toISOString(),
  });
  return getJson(
    `/api/goals/progress?${query}`,
    requestTimeoutMs(end.getTime() - start.getTime()),
  );
}

/**
 * 목표별 모든 기기의 합계(분). from·to는 `YYYY-MM-DD`(끝날 포함)다. 다른 기기의 기록을 받을 수 없어도 오류가 아니라 state로 알려 준다
 * (그래서 이 요청이 실패한다면 hub에 닿지 못한 것이다) — 호출부는 실패하면 "전체"만 모르는 것으로 두고 나머지를 그대로 보여 준다.
 */
export function fetchGoalTotals(from: string, to: string): Promise<GoalTotals> {
  return getJson(
    `/api/goals/all-devices?${new URLSearchParams({ from, to })}`,
    SHORT_REQUEST_TIMEOUT_MS,
  );
}

/** 추적된(기록된) 프로세스 중 목표에 연결할 수 있는 이름들(이름 순). */
export async function fetchTrackedProcesses(): Promise<string[]> {
  const response = await getJson<{ processes: string[] }>(
    "/api/processes",
    SHORT_REQUEST_TIMEOUT_MS,
  );
  return response.processes;
}

/** 추적된 브라우저 사이트 중 목표에 연결할 수 있는 (브라우저, 도메인)들. */
export async function fetchTrackedSites(): Promise<SiteLink[]> {
  const response = await getJson<{ sites: SiteLink[] }>(
    "/api/tracked-sites",
    SHORT_REQUEST_TIMEOUT_MS,
  );
  return response.sites;
}
