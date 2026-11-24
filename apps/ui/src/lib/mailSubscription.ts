// 보고서 메일 구역의 순수 로직: 어떤 모습을 보일지, 상태·끝난 이유·확인 메일 결과의 문장, 폼의 처음 값. DOM·hub를 모른다(lib 층).

import { describeSchedule } from "./goalSettings.ts";

export interface SubscriptionLike {
  goal_id: number | null;
  goal_name: string | null;
  frequency: "daily" | "weekly" | "monthly";
  weekday: number | null;
  day_of_month: number | null;
  send_time: string;
  timezone: string;
  status: "active" | "paused" | "ended";
  ended_reason: string | null;
}

export interface ScheduleFieldsLike {
  frequency: string;
  weekday: number | null;
  day_of_month: number | null;
  send_time: string;
}

/**
 * 이 목표 화면에서 보일 모습:
 * - `none`: 신청한 구독이 없다(또는 다른 목표의 구독이 끝났다 — 끝난 구독은 새로 신청하면 바뀐다).
 * - `mine`: 이 목표의 구독(켜짐·꺼짐·끝남).
 * - `other`: 다른 목표의 살아 있는 구독 — 보고서는 한 목표만 받으므로 "이 목표로 옮기기"를 보인다.
 */
export type SectionKind = "none" | "mine" | "other";

export function sectionKind(
  subscription: SubscriptionLike | null,
  goalId: number,
): SectionKind {
  if (subscription === null) return "none";
  if (subscription.goal_id === goalId) return "mine";
  return subscription.status === "ended" ? "none" : "other";
}

const ENDED: Record<string, string> = {
  goal_deleted: "목표를 지워서 보고서가 끝났어요.",
  goal_ended: "목표 기간이 끝나 마지막 보고서를 보냈어요.",
  unsubscribed: "메일의 '더 받지 않기'로 보고서를 그만 받았어요.",
  suppressed:
    "메일이 반송됐거나 스팸으로 신고되어 보고서를 보낼 수 없어요. 받은편지함 주소를 확인해 주세요.",
};

/** 구독 한 줄: "매주 월요일 09:00 · 켜짐" (끝났으면 끝남). 시간대가 이 PC와 다르면 덧붙인다. */
export function describeSubscription(
  subscription: SubscriptionLike,
  localZone: string,
): string {
  const zone =
    subscription.timezone === localZone ? "" : ` (${subscription.timezone})`;
  const state =
    subscription.status === "active"
      ? "켜짐"
      : subscription.status === "paused"
        ? "꺼짐"
        : "끝남";
  return `${describeSchedule(subscription)}${zone} · ${state}`;
}

/** 끝난 이유를 사용자에게. 모르는 이유면 일반 문장. */
export function endedReasonText(reason: string | null): string {
  return (reason && ENDED[reason]) ?? "보고서 구독이 끝났어요.";
}

/** 신청한 뒤 알려 줄 문장(확인 메일 결과 포함). */
export function savedText(created: boolean, welcome: string): string {
  const head = created
    ? "보고서 메일을 신청했어요."
    : "보고서 메일 일정을 바꿨어요.";
  switch (welcome) {
    case "sent":
      return `${head} 확인 메일을 보냈어요.`;
    case "already":
      return head;
    case "suppressed":
      return `${head} 이 주소로는 메일을 보낼 수 없는 상태라 확인 메일은 보내지 않았어요.`;
    case "limited":
    case "failed":
    case "not_configured":
      return `${head} 확인 메일은 지금 보내지 못했어요(다음에 다시 보내요). 보고서는 일정대로 가요.`;
    default:
      return head;
  }
}

/** 신청 폼의 처음 값: 이 목표의 구독 → 이 PC에 저장해 둔 옛 일정 → 기본(매주 월요일 09:00). */
export function initialFields(
  mine: ScheduleFieldsLike | null,
  legacy: ScheduleFieldsLike | null,
): ScheduleFieldsLike {
  const source = mine ?? legacy;
  if (source && ["daily", "weekly", "monthly"].includes(source.frequency)) {
    return {
      frequency: source.frequency,
      weekday: source.weekday,
      day_of_month: source.day_of_month,
      send_time: source.send_time,
    };
  }
  return {
    frequency: "weekly",
    weekday: 0,
    day_of_month: null,
    send_time: "09:00",
  };
}

/** 매일을 고를 수 있는가: 상한이 남았거나, 이미 이 목표를 매일 받고 있다(시각만 바꾸는 것은 막지 않는다). */
export function canChooseDaily(
  dailyAvailable: boolean,
  mine: SubscriptionLike | null,
): boolean {
  return (
    dailyAvailable ||
    (mine !== null && mine.frequency === "daily" && mine.status === "active")
  );
}
