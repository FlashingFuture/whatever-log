import {
  ApiError,
  createAlert,
  deleteAlert,
  deleteMailSubscription,
  fetchAlerts,
  fetchGoals,
  fetchMailSubscription,
  fetchReportSchedule,
  type Goal,
  type GoalAlert,
  type MailScheduleFields,
  type MailSubscriptionState,
  type ReportSchedule,
  saveMailSubscription,
  sendTestMail,
  setMailSubscriptionStatus,
  updateAlert,
} from "../../api";
import { describeAlert } from "../../lib/goalSettings";
import {
  canChooseDaily,
  describeSubscription,
  endedReasonText,
  initialFields,
  savedText,
  sectionKind,
} from "../../lib/mailSubscription";
import { createButton } from "../common/Button";
import { createErrorView } from "../common/ErrorView";
import { createIconButton } from "../common/IconButton";
import { createModal } from "../common/Modal";
import { createAlertForm } from "./AlertForm";
import styles from "./GoalSettings.module.css";
import { createScheduleForm } from "./ScheduleForm";

export interface GoalSettings {
  element: HTMLElement;
  /** 서버에서 다시 불러와 다시 그린다(연결 프로세스가 바뀐 뒤 등). */
  reload: () => void;
  destroy: () => void;
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function paragraph(text: string, className: string): HTMLParagraphElement {
  const element = document.createElement("p");
  element.className = className;
  element.textContent = text;
  return element;
}

/** 보고서 메일 구독을 불러온 결과. 로그인하지 않았거나(signedOut) 서버에 닿지 못해도 알림 구역은 그대로 보인다. */
type MailLoad =
  | { ok: true; state: MailSubscriptionState }
  | { ok: false; signedOut: boolean; message: string };

interface Loaded {
  goal: Goal;
  alerts: GoalAlert[];
  /** 이 PC에 저장해 둔 옛 보고서 일정(서버 구독으로 옮기기 전) — 신청 폼의 처음 값으로만 쓴다. */
  legacy: ReportSchedule | null;
  mail: MailLoad;
}

/** 이 PC의 시간대(IANA). 보낼 시각은 이 시간대 기준이다. */
function localZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

async function loadMail(): Promise<MailLoad> {
  try {
    return { ok: true, state: await fetchMailSubscription() };
  } catch (error) {
    // 로그인하지 않았으면 hub가 409(invalid_request)로 답한다. 로그인 기능이 없는 설치는 503.
    const signedOut =
      error instanceof ApiError &&
      error.status === 409 &&
      error.code === "invalid_request";
    return { ok: false, signedOut, message: message(error) };
  }
}

/**
 * 목표의 알림 규칙과 보고서 메일을 보고 고치는 두 구역(목표 개요 화면 아래). 15초마다 다시 그려지는 차트 바깥에 두어, 열려 있는 폼이 갱신에
 * 지워지지 않는다. 규칙의 원본은 서버(packages/goals, apps/server)이고 여기서는 보여 주고 입력만 받는다(docs/goal-management.md).
 * 알림은 이 PC의 알림 에이전트가 띄운다. 보고서 메일은 **서버의 구독**이다(사용자당 하나, 서버가 정한 시각에 보낸다 — docs/mail-design.md).
 */
export function createGoalSettings(goalId: number): GoalSettings {
  const element = document.createElement("div");
  element.className = styles.settings;
  let destroyed = false;
  // 불러오기를 연달아 시작했을 때 먼저 시작한 것의 늦은 응답이 나중 것을 덮지 않게 하는 순번.
  let load = 0;

  // 모달에 지금 보이는 장면의 번호. 장면을 열거나 닫을 때마다 올린다 — 저장·삭제 요청이 끝났을 때 **그 요청을 시작한 장면이 아직 그대로일 때만** 모달을 닫는다
  // (요청이 도는 동안 취소하고 다른 폼을 열었다면, 늦게 끝난 요청이 새 폼을 닫아 입력을 지우면 안 된다).
  let scene = 0;
  const modal = createModal({
    label: "알림·보고서 설정",
    onClose: () => {
      scene++;
    },
  });

  function openScene(view: Parameters<typeof modal.show>[0]): void {
    scene++;
    modal.show(view);
    modal.open();
  }

  async function fetchAll(): Promise<Loaded | null> {
    const [goals, alerts, legacy, mail] = await Promise.all([
      fetchGoals(),
      fetchAlerts(goalId),
      fetchReportSchedule(goalId),
      loadMail(),
    ]);
    const goal = goals.find((candidate) => candidate.id === goalId);
    return goal === undefined ? null : { goal, alerts, legacy, mail };
  }

  async function reload(): Promise<void> {
    const id = ++load;
    let loaded: Loaded | null;
    try {
      loaded = await fetchAll();
    } catch (error) {
      if (id === load && !destroyed) {
        element.replaceChildren(
          createErrorView(message(error), () => void reload()),
        );
      }
      return;
    }
    if (id !== load || destroyed) {
      return;
    }
    // 목표가 지워졌다면(다른 곳에서) 이 구역은 비운다 — 화면 위쪽이 "목표를 찾을 수 없어요"를 보여 준다.
    element.replaceChildren(
      ...(loaded === null ? [] : [alertsSection(loaded), mailSection(loaded)]),
    );
  }

  /** 저장·삭제가 끝났다 — 요청을 시작한 장면(startedScene)이 아직 그대로면 모달을 닫고, 어느 쪽이든 목록은 다시 불러온다. */
  async function done(startedScene: number): Promise<void> {
    if (scene === startedScene) {
      modal.close();
    }
    await reload();
  }

  function section(title: string, ...children: HTMLElement[]): HTMLElement {
    const root = document.createElement("section");
    root.className = styles.section;
    const heading = document.createElement("h2");
    heading.className = styles.title;
    heading.textContent = title;
    root.append(heading, ...children);
    return root;
  }

  function row(
    text: string,
    muted: boolean,
    ...actions: HTMLElement[]
  ): HTMLElement {
    const item = document.createElement("li");
    item.className = styles.row;
    const label = document.createElement("span");
    label.className = muted ? `${styles.label} ${styles.off}` : styles.label;
    label.textContent = text; // 프로세스 이름 같은 값이 들어 있어 textContent로만 넣는다
    const buttons = document.createElement("span");
    buttons.className = styles.actions;
    buttons.append(...actions);
    item.append(label, buttons);
    return item;
  }

  // --- 알림 ---

  function alertsSection({ goal, alerts }: Loaded): HTMLElement {
    const list = document.createElement("ul");
    list.className = styles.list;
    for (const alert of alerts) {
      const text = `${describeAlert(alert)}${alert.enabled ? "" : " · 꺼짐"}`;
      list.append(
        row(
          text,
          !alert.enabled,
          createIconButton({
            icon: "pencil",
            label: `알림 수정: ${describeAlert(alert)}`,
            onClick: () => showAlertForm(goal, alert),
          }),
          createIconButton({
            icon: "trash",
            label: `알림 삭제: ${describeAlert(alert)}`,
            tone: "danger",
            onClick: () => showDeleteAlert(alert),
          }),
        ),
      );
    }
    const add = createButton({
      label: "알림 추가",
      onClick: () => showAlertForm(goal, null),
    });
    add.dataset.addAlert = "";
    return section(
      "알림",
      paragraph(
        "정해 둔 시각까지 목표나 프로세스를 하지 않았으면 이 PC에서 알려 줘요. 알림 에이전트가 떠 있어야 해요.",
        styles.hint,
      ),
      alerts.length === 0
        ? paragraph("아직 알림이 없어요.", styles.empty)
        : list,
      add,
    );
  }

  function showAlertForm(goal: Goal, alert: GoalAlert | null): void {
    openScene({
      title: alert ? "알림 수정" : "알림 추가",
      content: createAlertForm({
        alert,
        processes: goal.processes,
        onCancel: () => modal.close(),
        onSubmit: async (input) => {
          const startedScene = scene;
          await (alert
            ? updateAlert(goalId, alert.id, input)
            : createAlert(goalId, input));
          await done(startedScene);
        },
      }),
    });
  }

  function showDeleteAlert(alert: GoalAlert): void {
    showConfirm({
      title: "알림 삭제",
      question: "이 알림을 삭제하시겠습니까?",
      detail: describeAlert(alert),
      onConfirm: () => deleteAlert(goalId, alert.id),
    });
  }

  // --- 보고서 메일(서버 구독) ---

  // 구역 아래에 잠깐 보일 결과 문장(신청·시험 메일·실패). 다시 그려도 남고, 다른 동작을 하면 바뀐다.
  let mailNotice = "";

  function mailSection({ legacy, mail }: Loaded): HTMLElement {
    const body: HTMLElement[] = [
      paragraph(
        "정한 일정에 이 목표의 달성도를 메일로 받아요. 보고서는 한 목표만 받을 수 있어요.",
        styles.hint,
      ),
    ];
    if (!mail.ok) {
      body.push(
        paragraph(
          mail.signedOut
            ? "보고서 메일은 로그인한 뒤, 이 목표를 서버와 동기화하면 받을 수 있어요."
            : `보고서 메일 상태를 불러오지 못했어요: ${mail.message}`,
          styles.empty,
        ),
      );
      return section("보고서 메일", ...body);
    }
    const { subscription, daily_available: dailyAvailable } = mail.state;
    const kind = sectionKind(subscription, goalId);
    const mine = kind === "mine" ? subscription : null;

    if (mine !== null) {
      const list = document.createElement("ul");
      list.className = styles.list;
      const actions: HTMLElement[] = [];
      if (mine.status !== "ended") {
        actions.push(
          createIconButton({
            icon: "pencil",
            label: "보고서 일정 수정",
            onClick: () => showMailForm(mail.state, legacy, false),
          }),
          createButton({
            label: mine.status === "active" ? "끄기" : "켜기",
            onClick: (button) =>
              void runMailAction(button, async () => {
                await setMailSubscriptionStatus(
                  mine.status === "active" ? "paused" : "active",
                );
                mailNotice =
                  mine.status === "active"
                    ? "보고서 메일을 껐어요. 켜면 다음 일정부터 다시 보내요."
                    : "보고서 메일을 켰어요.";
              }),
          }),
          createIconButton({
            icon: "trash",
            label: "보고서 그만 받기",
            tone: "danger",
            onClick: () => showStopMail(mail.state),
          }),
        );
      }
      list.append(
        row(
          describeSubscription(mine, localZone()),
          mine.status !== "active",
          ...actions,
        ),
      );
      body.push(list);
      if (mine.status === "ended") {
        body.push(paragraph(endedReasonText(mine.ended_reason), styles.empty));
        body.push(
          createButton({
            label: "다시 신청",
            onClick: () => showMailForm(mail.state, legacy, false),
          }),
        );
      } else {
        const test = createButton({
          label: "시험 메일 보내기",
          onClick: (button) =>
            void runMailAction(button, async () => {
              const sent = await sendTestMail();
              mailNotice = `${sent.to}로 시험 메일을 보냈어요.`;
            }),
        });
        test.dataset.testMail = "";
        body.push(test);
      }
    } else if (kind === "other" && subscription !== null) {
      body.push(
        paragraph(
          `지금은 '${subscription.goal_name ?? "다른 PC의 목표"}' 목표의 보고서를 받고 있어요.`,
          styles.empty,
        ),
        createButton({
          label: "이 목표로 받기",
          onClick: () => showMailForm(mail.state, legacy, true),
        }),
      );
    } else {
      body.push(paragraph("신청한 보고서 메일이 없어요.", styles.empty));
      if (legacy !== null) {
        body.push(
          paragraph(
            "이 PC에 저장해 둔 일정이 있어요. 신청하면 그 일정으로 서버에 옮겨지고, 이 PC의 일정은 지워져요.",
            styles.hint,
          ),
        );
      }
      const subscribe = createButton({
        label: "보고서 받기",
        onClick: () => showMailForm(mail.state, legacy, false),
      });
      subscribe.dataset.subscribeMail = "";
      body.push(subscribe);
      if (!dailyAvailable) {
        body.push(
          paragraph(
            "지금은 매일 보고서의 자리가 다 찼어요. 매주나 매달로 신청할 수 있어요.",
            styles.hint,
          ),
        );
      }
    }
    if (mailNotice) {
      const notice = paragraph(mailNotice, styles.hint);
      notice.setAttribute("role", "status");
      body.push(notice);
    }
    return section("보고서 메일", ...body);
  }

  /** 구역의 버튼 동작(켜고 끄기·시험 메일): 누르는 동안 잠그고, 끝나면 결과 문장과 함께 다시 그린다. */
  async function runMailAction(
    button: HTMLButtonElement,
    action: () => Promise<void>,
  ): Promise<void> {
    button.disabled = true;
    try {
      await action();
    } catch (error) {
      mailNotice = message(error);
    }
    await reload();
  }

  function showMailForm(
    state: MailSubscriptionState,
    legacy: ReportSchedule | null,
    replace: boolean,
  ): void {
    const mine =
      sectionKind(state.subscription, goalId) === "mine"
        ? state.subscription
        : null;
    openScene({
      title: "보고서 메일",
      content: createScheduleForm({
        initial: initialFields(mine, legacy),
        allowDaily: canChooseDaily(state.daily_available, mine),
        timezone: localZone(),
        submitLabel: mine !== null && mine.status !== "ended" ? "저장" : "신청",
        onCancel: () => modal.close(),
        onSubmit: async (fields) => {
          const startedScene = scene;
          try {
            await subscribe(fields, replace, state, startedScene);
          } catch (error) {
            // 그사이 다른 목표를 신청했다(다른 PC 등) — 옮길지 묻는다. 단, 이 신청 장면이 아직 그대로일 때만(취소하고 다른 폼을 열었으면 그 폼을 덮지 않는다).
            if (
              error instanceof ApiError &&
              error.code === "subscription_exists" &&
              !replace
            ) {
              if (scene === startedScene && !destroyed) {
                showMoveMail(fields, state);
              }
              return;
            }
            throw error;
          }
        },
      }),
    });
  }

  async function subscribe(
    fields: MailScheduleFields,
    replace: boolean,
    state: MailSubscriptionState,
    startedScene: number,
  ): Promise<void> {
    const saved = await saveMailSubscription({
      ...fields,
      goal_id: goalId,
      timezone: localZone(),
      replace,
      // 옮기기는 이 화면을 그린 로그인을 함께 보낸다(그사이 계정이 바뀌었으면 hub가 거절한다)
      ...(replace ? { email: state.email, session: state.session } : {}),
    });
    mailNotice = savedText(saved.created, saved.welcome);
    await done(startedScene);
  }

  function showMoveMail(
    fields: MailScheduleFields,
    state: MailSubscriptionState,
  ): void {
    showConfirm({
      title: "보고서 옮기기",
      question: "다른 목표의 보고서를 받고 있어요. 이 목표로 옮길까요?",
      detail:
        "보고서는 한 목표만 받을 수 있어요. 옮기면 그 목표의 보고서는 더 오지 않아요.",
      confirmLabel: "옮기기",
      danger: false,
      onConfirm: async () => {
        const saved = await saveMailSubscription({
          ...fields,
          goal_id: goalId,
          timezone: localZone(),
          replace: true,
          email: state.email,
          session: state.session,
        });
        mailNotice = savedText(saved.created, saved.welcome);
      },
    });
  }

  function showStopMail(state: MailSubscriptionState): void {
    showConfirm({
      title: "보고서 그만 받기",
      question: "보고서 메일을 그만 받으시겠습니까?",
      detail: "다시 받으려면 새로 신청하면 돼요. 잠시 쉬려면 '끄기'를 쓰세요.",
      confirmLabel: "그만 받기",
      onConfirm: async () => {
        await deleteMailSubscription(state.email, state.session);
        mailNotice = "보고서 메일을 그만 받아요.";
      },
    });
  }

  function showConfirm(options: {
    title: string;
    question: string;
    detail: string;
    onConfirm: () => Promise<void>;
    /** 확인 버튼의 글자(기본 "삭제")와, 되돌리기 어려운 동작으로 칠할지(기본 true). */
    confirmLabel?: string;
    danger?: boolean;
  }): void {
    const content = document.createElement("div");
    content.className = styles.confirm;
    const startedScene = scene + 1; // 아래 openScene이 이 장면의 번호를 이 값으로 올린다
    const error = paragraph("", styles.error);
    error.hidden = true;
    error.setAttribute("role", "alert");
    const remove = createButton({
      label: options.confirmLabel ?? "삭제",
      onClick: (button) => {
        button.disabled = true;
        options
          .onConfirm()
          .then(() => done(startedScene))
          .catch((failure: unknown) => {
            error.hidden = false;
            error.textContent = message(failure);
            button.disabled = false;
          });
      },
    });
    if (options.danger !== false) {
      remove.classList.add(styles.danger);
    }
    const actions = document.createElement("div");
    actions.className = styles.confirmActions;
    actions.append(
      createButton({ label: "취소", onClick: () => modal.close() }),
      remove,
    );
    content.append(
      paragraph(options.question, styles.question),
      paragraph(options.detail, styles.hint),
      error,
      actions,
    );
    openScene({ title: options.title, content });
  }

  void reload();
  return {
    element,
    reload: () => void reload(),
    destroy() {
      destroyed = true;
      load++;
      modal.destroy();
    },
  };
}
