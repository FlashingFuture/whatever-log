import {
  createGoal,
  deleteGoal,
  fetchGoals,
  fetchTrackedProcesses,
  fetchTrackedSites,
  type Goal,
  type GoalInput,
  type SiteLink,
  updateGoal,
} from "../../api";
import {
  addProcess,
  addSite,
  type LinkTarget,
  removeProcess,
  removeSite,
  splitProcesses,
} from "../../lib/processPick";
import { createButton } from "../common/Button";
import { createErrorView } from "../common/ErrorView";
import { createIconButton } from "../common/IconButton";
import { createModal } from "../common/Modal";
import { createGoalForm } from "./GoalForm";
import { createGoalList } from "./GoalList";
import styles from "./GoalManager.module.css";
import {
  createGoalProcesses,
  readScroll,
  restoreScroll,
  type ScrollState,
} from "./GoalProcesses";

export interface GoalManager {
  /** "목표 프로세스 관리" 모달을 목록 화면으로 연다. */
  open: () => void;
  destroy: () => void;
}

export interface GoalManagerProps {
  /** 목표나 연결 프로세스가 바뀌었다 — 홈의 수행 시간을 다시 불러오게 한다. */
  onChange: () => void;
  /** 모달이 닫혔다(어떤 방식으로든). 열었던 버튼으로 포커스를 돌려주는 데 쓴다. */
  onClose?: () => void;
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function paragraph(text: string, className?: string): HTMLParagraphElement {
  const element = document.createElement("p");
  element.textContent = text;
  if (className) {
    element.className = className;
  }
  return element;
}

/**
 * 목표 관리 모달: 목록(+ 만들기) → 목표를 누르면 상세(연결 프로세스 관리), 수정·삭제 아이콘은 각각
 * 편집 폼과 삭제 확인으로. 목표 데이터의 원본은 서버(hub의 goals.db)이고, 여기서는 화면에 필요한 만큼만
 * 들고 있다가 바뀔 때마다 서버 응답으로 갈아 끼운다.
 */
export function createGoalManager(props: GoalManagerProps): GoalManager {
  let goals: Goal[] = [];
  // 화면을 연달아 바꿀 때 먼저 보낸 요청의 늦은 응답이 나중 화면을 덮지 않게 하는 순번.
  let sceneId = 0;
  // 연결을 저장하는 중인지. 저장이 끝나고 새 목록이 그려질 때까지 켜 둬서, 낡은 목록에서 연달아 누른 변경이
  // 서버의 최신 상태를 덮어쓰지 못하게 한다.
  let busy = false;
  let destroyed = false;

  const modal = createModal({
    label: "목표 프로세스 관리",
    onClose: () => {
      // 닫힌 뒤에 끝난 저장·불러오기가 닫힌 모달을 다시 그리지 않게 장면을 넘긴다.
      sceneId++;
      props.onClose?.();
    },
  });

  /** 홈을 다시 불러오게 한다. 화면을 떠난 뒤(해제)에는 요청을 보내지 않는다. */
  function notifyChange(): void {
    if (!destroyed) {
      props.onChange();
    }
  }

  function addButton(): HTMLButtonElement {
    return createIconButton({
      icon: "plus",
      label: "목표 만들기",
      onClick: () => showForm(null, showList),
    });
  }

  function showLoading(title: string): number {
    const id = ++sceneId;
    modal.show({
      title,
      content: paragraph("불러오는 중…", styles.muted),
    });
    return id;
  }

  async function showList(): Promise<void> {
    const id = showLoading("목표 프로세스 관리");
    try {
      goals = await fetchGoals();
    } catch (error) {
      if (id === sceneId) {
        modal.show({
          title: "목표 프로세스 관리",
          content: createErrorView(message(error), () => void showList()),
        });
      }
      return;
    }
    if (id !== sceneId) {
      return;
    }
    modal.show({
      title: "목표 프로세스 관리",
      actions: [addButton()],
      content: createGoalList({
        goals,
        onOpen: (goal) => void showDetail(goal.id),
        onEdit: (goal) => showForm(goal, showList),
        onDelete: (goal) => showDelete(goal),
      }),
    });
  }

  function showForm(goal: Goal | null, back: () => void | Promise<void>): void {
    const id = ++sceneId;
    modal.show({
      title: goal ? "목표 수정" : "목표 만들기",
      onBack: () => void back(),
      content: createGoalForm({
        goal,
        onCancel: () => void back(),
        onSubmit: async (input: GoalInput) => {
          // 저장 중에 다른 화면으로 옮겼다면(뒤로 가기, 닫기) 저장은 그대로 반영하되 화면은 바꾸지 않는다.
          if (goal) {
            await updateGoal(goal.id, input);
            notifyChange();
            if (id === sceneId) {
              await back();
            }
          } else {
            const created = await createGoal(input);
            notifyChange();
            if (id === sceneId) {
              await showDetail(created.id);
            }
          }
        },
      }),
    });
  }

  function showDelete(goal: Goal): void {
    const id = ++sceneId;
    const content = document.createElement("div");
    content.className = styles.confirm;
    const question = paragraph("정말 삭제하시겠습니까?");
    const detail = paragraph(
      `"${goal.name}" 목표와 프로세스 연결이 사라집니다. 기록된 사용 시간은 지워지지 않습니다.`,
      styles.muted,
    );
    const error = paragraph("", styles.error);
    error.hidden = true;
    error.setAttribute("role", "alert");

    const remove = createButton({
      label: "삭제",
      onClick: (button) => {
        button.disabled = true;
        deleteGoal(goal.id)
          .then(() => {
            notifyChange();
            return id === sceneId ? showList() : undefined;
          })
          .catch((failure: unknown) => {
            error.hidden = false;
            error.textContent = message(failure);
            button.disabled = false;
          });
      },
    });
    remove.classList.add(styles.danger);
    const actions = document.createElement("div");
    actions.className = styles.actions;
    actions.append(
      createButton({ label: "취소", onClick: () => void showList() }),
      remove,
    );
    content.append(question, detail, error, actions);
    modal.show({
      title: "목표 삭제",
      onBack: () => void showList(),
      content,
    });
  }

  async function showDetail(
    goalId: number,
    options: {
      focusTarget?: LinkTarget;
      error?: string;
      /** 다시 그리기 전의 스크롤 위치 — 하나를 옮길 때마다 목록이 맨 위로 되돌아가지 않게 한다. */
      scroll?: ScrollState;
    } = {},
  ): Promise<void> {
    const id = ++sceneId;
    let tracked: string[];
    let trackedSites: SiteLink[];
    try {
      [goals, tracked, trackedSites] = await Promise.all([
        fetchGoals(),
        fetchTrackedProcesses(),
        // 사이트 목록을 못 불러와도(옛 hub 등) 프로세스 연결은 할 수 있게 한다.
        fetchTrackedSites().catch(() => []),
      ]);
    } catch (error) {
      if (id === sceneId) {
        modal.show({
          title: "프로세스 관리",
          onBack: () => void showList(),
          content: createErrorView(
            message(error),
            () => void showDetail(goalId),
          ),
        });
      }
      return;
    }
    if (id !== sceneId) {
      return;
    }
    const goal = goals.find((candidate) => candidate.id === goalId);
    if (!goal) {
      await showList(); // 그새 지워졌다
      return;
    }

    const content = document.createElement("div");
    content.className = styles.detail;
    content.append(
      paragraph(
        "항목을 누르거나 반대쪽 칸으로 끌어다 놓으면 바로 저장됩니다.",
        styles.muted,
      ),
    );
    if (options.error) {
      const banner = paragraph(options.error, styles.error);
      banner.setAttribute("role", "alert");
      content.append(banner);
    }
    content.append(
      createGoalProcesses({
        goal,
        split: splitProcesses(tracked, goals, goal.id, trackedSites),
        focusTarget: options.focusTarget,
        busy: false, // 방금 서버에서 받은 최신 상태라 다시 누를 수 있다
        onMove: (target, link) => void move(goal, target, link),
      }),
    );

    modal.show({
      title: goal.name,
      onBack: () => void showList(),
      actions: [
        createIconButton({
          icon: "pencil",
          label: `${goal.name} 수정`,
          onClick: () => showForm(goal, () => showDetail(goal.id)),
        }),
      ],
      content,
    });
    if (options.scroll) {
      restoreScroll(modal.body, options.scroll);
    }
  }

  /** 저장하는 동안 지금 보이는 목록을 눌러도 아무 일도 없게 잠근다(새 목록이 그려지면 풀린 채로 나온다). */
  function lockPicker(): void {
    for (const button of modal.body.querySelectorAll("button")) {
      button.disabled = true;
    }
    for (const item of modal.body.querySelectorAll<HTMLElement>(
      '[draggable="true"]',
    )) {
      item.draggable = false;
    }
  }

  async function move(
    goal: Goal,
    target: LinkTarget,
    link: boolean,
  ): Promise<void> {
    if (busy) {
      return;
    }
    busy = true;
    lockPicker();
    const scene = sceneId;
    const scroll = readScroll(modal.body);
    let processes = goal.processes;
    let sites = goal.sites;
    if (target.kind === "process") {
      processes = link
        ? addProcess(processes, target.process)
        : removeProcess(processes, target.process);
    } else {
      sites = link
        ? addSite(sites, target.site)
        : removeSite(sites, target.site);
    }
    try {
      await updateGoal(goal.id, {
        name: goal.name,
        daily_target_minutes: goal.daily_target_minutes,
        weekdays: goal.weekdays,
        processes,
        sites,
      });
      notifyChange();
      if (scene === sceneId) {
        await showDetail(goal.id, { focusTarget: target, scroll });
      }
    } catch (error) {
      if (scene === sceneId) {
        await showDetail(goal.id, {
          focusTarget: target,
          scroll,
          error: `저장하지 못했습니다: ${message(error)}`,
        });
      }
    } finally {
      busy = false;
    }
  }

  return {
    open() {
      modal.open();
      void showList();
    },
    destroy() {
      destroyed = true;
      sceneId++;
      modal.destroy();
    },
  };
}
