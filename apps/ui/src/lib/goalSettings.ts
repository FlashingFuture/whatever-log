// 목표의 알림 규칙·보고서 일정을 화면에 보이는 글자로 바꾸는 순수 로직(lib 층). 규칙(무엇이 올바른 값인지)은 서버가 갖고, 여기는 보여 주기만 한다.

import { formatWeekdays, WEEKDAY_LABELS } from "./goalText.ts";

export interface AlertLike {
  target_process: string | null;
  deadline: string;
  min_minutes: number;
  weekdays: readonly number[];
  enabled: boolean;
}

export interface ScheduleLike {
  enabled: boolean;
  frequency: string;
  weekday: number | null;
  day_of_month: number | null;
  send_time: string;
}

/** 알림 규칙을 한 줄로: "23:00까지 · 목표 전체 30분 · 매일". 대상이 프로세스면 그 이름이 앞에 온다. */
export function describeAlert(alert: AlertLike): string {
  const target = alert.target_process ?? "목표 전체";
  return `${alert.deadline}까지 · ${target} ${alert.min_minutes}분 · ${formatWeekdays(alert.weekdays)}`;
}

/** 보고서 일정을 한 줄로: "매주 월요일 09:00", "매일 21:30", "매달 15일 09:00". 모르는 주기는 그대로 보여 준다. */
export function describeSchedule(schedule: ScheduleLike): string {
  switch (schedule.frequency) {
    case "daily":
      return `매일 ${schedule.send_time}`;
    case "weekly": {
      const label =
        schedule.weekday === null
          ? "?"
          : (WEEKDAY_LABELS[schedule.weekday] ?? "?");
      return `매주 ${label}요일 ${schedule.send_time}`;
    }
    case "monthly":
      return `매달 ${schedule.day_of_month ?? "?"}일 ${schedule.send_time}`;
    default:
      return `${schedule.frequency} ${schedule.send_time}`;
  }
}

/**
 * 분 칸의 글자를 서버에 보낼 값으로: 10진 정수로만 이뤄진 글자(앞의 0 없이)면 숫자, 아니면 글자 그대로(그러면 서버가 칸별로 알려 준다).
 * Number()는 공백·"1e2"·"0x10"도 숫자로 받아 주므로 쓰지 않는다.
 */
export function integerValue(text: string): number | string {
  return /^(0|[1-9]\d*)$/.test(text) ? Number(text) : text;
}
