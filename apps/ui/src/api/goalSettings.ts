import { getJson, SHORT_REQUEST_TIMEOUT_MS, sendJson } from "./client.ts";
import type {
  GoalAlert,
  GoalAlertInput,
  ReportSchedule,
  ReportScheduleInput,
} from "./types";

/** 목표의 알림 규칙들(만든 순서). */
export async function fetchAlerts(goalId: number): Promise<GoalAlert[]> {
  const response = await getJson<{ alerts: GoalAlert[] }>(
    `/api/goals/${goalId}/alerts`,
    SHORT_REQUEST_TIMEOUT_MS,
  );
  return response.alerts;
}

/** 알림 규칙을 만든다. 입력 오류는 칸별 오류를 담은 ApiError(fields)로 온다. */
export function createAlert(
  goalId: number,
  input: GoalAlertInput,
): Promise<GoalAlert> {
  return sendJson(
    "POST",
    `/api/goals/${goalId}/alerts`,
    input,
    SHORT_REQUEST_TIMEOUT_MS,
  );
}

/** 알림 규칙을 통째로 바꾼다(모든 칸을 다시 보낸다). */
export function updateAlert(
  goalId: number,
  alertId: number,
  input: GoalAlertInput,
): Promise<GoalAlert> {
  return sendJson(
    "PUT",
    `/api/goals/${goalId}/alerts/${alertId}`,
    input,
    SHORT_REQUEST_TIMEOUT_MS,
  );
}

export async function deleteAlert(
  goalId: number,
  alertId: number,
): Promise<void> {
  await sendJson(
    "DELETE",
    `/api/goals/${goalId}/alerts/${alertId}`,
    undefined,
    SHORT_REQUEST_TIMEOUT_MS,
  );
}

/** 목표의 보고서 메일 일정(설정이 없으면 null). */
export async function fetchReportSchedule(
  goalId: number,
): Promise<ReportSchedule | null> {
  const response = await getJson<{ schedule: ReportSchedule | null }>(
    `/api/goals/${goalId}/report-schedule`,
    SHORT_REQUEST_TIMEOUT_MS,
  );
  return response.schedule;
}

/** 보고서 일정을 만들거나 통째로 바꾼다. */
export function saveReportSchedule(
  goalId: number,
  input: ReportScheduleInput,
): Promise<ReportSchedule> {
  return sendJson(
    "PUT",
    `/api/goals/${goalId}/report-schedule`,
    input,
    SHORT_REQUEST_TIMEOUT_MS,
  );
}

export async function deleteReportSchedule(goalId: number): Promise<void> {
  await sendJson(
    "DELETE",
    `/api/goals/${goalId}/report-schedule`,
    undefined,
    SHORT_REQUEST_TIMEOUT_MS,
  );
}
