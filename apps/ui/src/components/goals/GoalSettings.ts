import {
  createAlert,
  deleteAlert,
  deleteReportSchedule,
  fetchAlerts,
  fetchGoals,
  fetchReportSchedule,
  type Goal,
  type GoalAlert,
  type ReportSchedule,
  saveReportSchedule,
  updateAlert,
} from "../../api";
import { describeAlert, describeSchedule } from "../../lib/goalSettings";
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

interface Loaded {
  goal: Goal;
  alerts: GoalAlert[];
  schedule: ReportSchedule | null;
}

/**
 * 목표의 알림 규칙과 보고서 메일 일정을 보고 고치는 두 구역(목표 개요 화면 아래). 15초마다 다시 그려지는 차트 바깥에 두어, 열려 있는 폼이 갱신에
 * 지워지지 않는다. 규칙의 원본은 서버(packages/goals)이고 여기서는 보여 주고 입력만 받는다(docs/goal-management.md).
 * 알림은 이 PC의 알림 에이전트가 띄운다. 보고서 메일은 **일정만 저장**하고 실제 발송은 아직 연결되지 않았다 — 화면이 그 사실을 알린다.
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
    const [goals, alerts, schedule] = await Promise.all([
      fetchGoals(),
      fetchAlerts(goalId),
      fetchReportSchedule(goalId),
    ]);
    const goal = goals.find((candidate) => candidate.id === goalId);
    return goal === undefined ? null : { goal, alerts, schedule };
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
      ...(loaded === null
        ? []
        : [alertsSection(loaded), scheduleSection(loaded)]),
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

  // --- 보고서 일정 ---

  function scheduleSection({ schedule }: Loaded): HTMLElement {
    const body: HTMLElement[] = [
      paragraph(
        "보고서를 메일로 받을 일정을 정해 둬요. 메일 발송은 아직 연결되지 않아서 지금은 일정만 저장돼요.",
        styles.hint,
      ),
    ];
    if (schedule === null) {
      body.push(paragraph("설정된 일정이 없어요.", styles.empty));
    } else {
      const list = document.createElement("ul");
      list.className = styles.list;
      const text = `${describeSchedule(schedule)}${schedule.enabled ? "" : " · 꺼짐"}`;
      list.append(
        row(
          text,
          !schedule.enabled,
          createIconButton({
            icon: "trash",
            label: "보고서 일정 삭제",
            tone: "danger",
            onClick: () => showDeleteSchedule(schedule),
          }),
        ),
      );
      body.push(list);
    }
    const edit = createButton({
      label: schedule === null ? "일정 설정" : "일정 수정",
      onClick: () => showScheduleForm(schedule),
    });
    edit.dataset.editSchedule = "";
    body.push(edit);
    return section("보고서 메일", ...body);
  }

  function showScheduleForm(schedule: ReportSchedule | null): void {
    openScene({
      title: "보고서 메일 일정",
      content: createScheduleForm({
        schedule,
        onCancel: () => modal.close(),
        onSubmit: async (input) => {
          const startedScene = scene;
          await saveReportSchedule(goalId, input);
          await done(startedScene);
        },
      }),
    });
  }

  function showDeleteSchedule(schedule: ReportSchedule): void {
    showConfirm({
      title: "보고서 일정 삭제",
      question: "이 보고서 일정을 삭제하시겠습니까?",
      detail: describeSchedule(schedule),
      onConfirm: () => deleteReportSchedule(goalId),
    });
  }

  function showConfirm(options: {
    title: string;
    question: string;
    detail: string;
    onConfirm: () => Promise<void>;
  }): void {
    const content = document.createElement("div");
    content.className = styles.confirm;
    const startedScene = scene + 1; // 아래 openScene이 이 장면의 번호를 이 값으로 올린다
    const error = paragraph("", styles.error);
    error.hidden = true;
    error.setAttribute("role", "alert");
    const remove = createButton({
      label: "삭제",
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
    remove.classList.add(styles.danger);
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
