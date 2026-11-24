import type { Db } from "../db.ts";
import { daysOf, localParts, type Period, weekdayOf } from "./schedule.ts";
import type { Frequency } from "./subscriptionInput.ts";

/** 보고서가 다루는 목표(서버가 아는 칸만 — 프로세스·사이트는 서버에 없다). */
export interface ReportGoal {
  name: string;
  daily_target_minutes: number;
  /** 월=bit0 … 일=bit6 */
  weekdays: number;
  start_date: string | null;
  end_date: string | null;
  created_at: string;
}

export interface ReportDay {
  day: string;
  minutes: number;
  /** 그날의 목표량. 목표를 적용하지 않는 날(요일·기간 밖, 만들기 전)은 0. */
  target: number;
}

export interface ReportData {
  days: ReportDay[];
  minutes: number;
  target: number;
  /** 달성률(%). 목표량이 0이면 null. */
  percent: number | null;
  /** 이 사용자의 기기가 마지막으로 달성도를 올린 시각(UTC ISO). 없으면 null. */
  lastSync: string | null;
}

/**
 * 구간의 달성도: 날짜별로 모든 기기의 달성 분을 더하고, 목표량은 기기가 올린 그날의 값(최근 것)을 쓰되 기록이 없는 날은 서버가 아는 목표
 * (요일·기간·만든 날)로 정한다. 목표를 적용하지 않는 날의 시간도 달성에는 더한다(이 PC의 화면과 같은 규칙 — 목표량에만 넣지 않는다).
 */
export async function buildReport(
  db: Db,
  userId: number,
  goalId: string,
  goal: ReportGoal,
  period: Period,
  timezone: string,
): Promise<ReportData> {
  const { results } = await db
    .prepare(
      "SELECT p.day AS day, SUM(p.minutes) AS minutes, " +
        "(SELECT t.target_minutes FROM progress t WHERE t.user_id = p.user_id AND t.goal_id = p.goal_id AND t.day = p.day " +
        "ORDER BY t.updated_at DESC, t.device_id DESC LIMIT 1) AS target " +
        "FROM progress p WHERE p.user_id = ? AND p.goal_id = ? AND p.day >= ? AND p.day <= ? GROUP BY p.day",
    )
    .bind(userId, goalId, period.start, period.end)
    .all<{ day: string; minutes: number; target: number }>();
  const recorded = new Map(results.map((row) => [row.day, row]));
  const createdOn = localParts(new Date(goal.created_at), timezone).date;
  const applies = (day: string) =>
    (goal.weekdays & (1 << weekdayOf(day))) !== 0 &&
    day >= createdOn &&
    (goal.start_date === null || day >= goal.start_date) &&
    (goal.end_date === null || day <= goal.end_date);

  const days = daysOf(period).map((day) => {
    const row = recorded.get(day);
    return {
      day,
      minutes: row?.minutes ?? 0,
      target: applies(day) ? (row?.target ?? goal.daily_target_minutes) : 0,
    };
  });
  const minutes = days.reduce((sum, day) => sum + day.minutes, 0);
  const target = days.reduce((sum, day) => sum + day.target, 0);
  const last = await db
    .prepare("SELECT MAX(updated_at) AS at FROM progress WHERE user_id = ?")
    .bind(userId)
    .first<{ at: string | null }>();
  return {
    days,
    minutes,
    target,
    percent: target > 0 ? Math.round((minutes * 100) / target) : null,
    lastSync: last?.at ?? null,
  };
}

// --- 본문 ---

const WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"];
const KIND = { daily: "일간", weekly: "주간", monthly: "월간" } as const;

export function formatMinutes(total: number): string {
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  if (hours === 0) return `${minutes}분`;
  return minutes === 0 ? `${hours}시간` : `${hours}시간 ${minutes}분`;
}

const monthDay = (day: string) =>
  `${Number(day.slice(5, 7))}월 ${Number(day.slice(8, 10))}일`;

/** 구간의 이름: "11월 22일" / "11월 10일 ~ 11월 16일" / "2026년 10월". */
export function describePeriod(frequency: Frequency, period: Period): string {
  if (frequency === "daily") return monthDay(period.start);
  if (frequency === "weekly") {
    return `${monthDay(period.start)} ~ ${monthDay(period.end)}`;
  }
  return `${period.start.slice(0, 4)}년 ${Number(period.start.slice(5, 7))}월`;
}

const escapeHtml = (text: string) =>
  text.replace(/[&<>"']/g, (char) => `&#${char.charCodeAt(0)};`);

export interface RenderedReport {
  subject: string;
  text: string;
  html: string;
}

/**
 * 보고서 메일의 본문. **집계값만** 담는다(목표 이름·목표량·달성 시간) — 프로세스·사이트는 서버에 없다(docs/data-handling.md).
 * 달성도는 PC의 동기화가 올린 값이라 "마지막 동기화 시각 기준"을 적는다.
 */
export function renderReport(options: {
  goalName: string;
  frequency: Frequency;
  period: Period;
  data: ReportData;
  timezone: string;
  unsubscribeUrl: string;
  final: boolean;
}): RenderedReport {
  const { goalName, frequency, period, data, timezone } = options;
  const label = describePeriod(frequency, period);
  const subject = `[whatever.log] ${goalName} ${KIND[frequency]} 보고서 · ${label}`;
  const summary =
    data.target > 0
      ? `목표 ${formatMinutes(data.target)} 중 ${formatMinutes(data.minutes)} (${data.percent}%)`
      : `이 기간에는 목표를 적용하는 날이 없었어요. 기록된 시간: ${formatMinutes(data.minutes)}`;
  const rows =
    frequency === "daily"
      ? []
      : data.days
          .filter((day) => day.target > 0 || day.minutes > 0)
          .map(
            (day) =>
              `${monthDay(day.day)} (${WEEKDAYS[weekdayOf(day.day)]}) ${formatMinutes(day.minutes)}` +
              (day.target > 0
                ? ` / ${formatMinutes(day.target)}`
                : " (목표 없는 날)"),
          );
  const sync = data.lastSync
    ? (() => {
        const at = localParts(new Date(data.lastSync), timezone);
        const time = `${String(Math.floor(at.minutes / 60)).padStart(2, "0")}:${String(at.minutes % 60).padStart(2, "0")}`;
        return `마지막 동기화 ${at.date} ${time} (${timezone}) 기준이에요. PC가 꺼져 있던 날은 아직 반영되지 않았을 수 있어요.`;
      })()
    : "아직 동기화된 달성 기록이 없어요. PC에서 동기화가 켜져 있는지 확인해 주세요.";
  const final = options.final
    ? ["목표 기간이 끝나 이번이 마지막 보고서예요."]
    : [];

  const text = [
    `"${goalName}" ${KIND[frequency]} 보고서 · ${label}`,
    "",
    summary,
    ...(rows.length > 0 ? ["", ...rows] : []),
    "",
    sync,
    ...final,
    "",
    `더 받지 않으려면: ${options.unsubscribeUrl}`,
  ].join("\n");
  const html =
    `<p><strong>${escapeHtml(`"${goalName}" ${KIND[frequency]} 보고서 · ${label}`)}</strong></p>` +
    `<p>${escapeHtml(summary)}</p>` +
    (rows.length > 0
      ? `<ul>${rows.map((row) => `<li>${escapeHtml(row)}</li>`).join("")}</ul>`
      : "") +
    `<p>${escapeHtml(sync)}</p>` +
    final.map((line) => `<p>${escapeHtml(line)}</p>`).join("") +
    `<p><a href="${escapeHtml(options.unsubscribeUrl)}">더 받지 않기</a></p>`;
  return { subject, text, html };
}
