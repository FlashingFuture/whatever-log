import { fetchGoals, type Goal, updateGoal } from "../../api";
import {
  addProcess,
  processLinkState,
  removeProcess,
} from "../../lib/processPick";
import { createErrorView } from "../common/ErrorView";
import { createModal } from "../common/Modal";
import { showToast } from "../common/Toast";
import { createGoalList } from "./GoalList";
import styles from "./GoalManager.module.css";

export interface ProcessGoalLinker {
  /** 목표 목록 팝업을 연다. 목표를 누르면 이 프로세스를 그 목표에 연결한다(이미 연결된 목표를 누르면 연결을 해제한다). */
  open: () => void;
  destroy: () => void;
}

export interface ProcessGoalLinkerProps {
  process: string;
  /** 연결하거나 해제했다(팝업은 닫혔다) — 화면의 수행 시간을 다시 불러오게 한다. */
  onLinked: () => void;
  /** 팝업이 닫혔다. 열었던 버튼으로 포커스를 돌려주는 데 쓴다(15초 갱신으로 버튼이 새로 그려졌을 수 있다). */
  onClose?: () => void;
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

/**
 * 프로세스 상세의 "프로세스 연결": 홈의 "목표 프로세스 관리"와 같은 목표 목록을 팝업으로 띄우고, 목표를 누르면 지금 보는 프로세스를
 * 그 목표에 연결한 뒤 팝업을 닫고 토스트로 알린다(화면은 그대로 프로세스 상세다).
 * 이미 연결된 목표를 누르면 연결을 해제한다(같은 방식으로 닫고 토스트로 알린다).
 * 한 프로세스는 한 목표에만 연결되므로, 이미 어느 목표에 있으면 다른 목표는 누를 수 없다(먼저 해제한다). 브라우저의 사이트가 연결돼 있으면
 * 브라우저 전체는 연결할 수 없어 목록 전체를 잠그고 이유를 적는다.
 */
export function createProcessGoalLinker(
  props: ProcessGoalLinkerProps,
): ProcessGoalLinker {
  // 화면을 연달아 바꿀 때 먼저 보낸 요청의 늦은 응답이 나중 화면을 덮지 않게 하는 순번.
  let sceneId = 0;
  let saving = false;
  let destroyed = false;
  const title = "프로세스 연결";

  const modal = createModal({
    label: title,
    onClose: () => {
      sceneId++;
      props.onClose?.();
    },
  });

  async function showList(error?: string): Promise<void> {
    const id = ++sceneId;
    modal.show({
      title,
      content: paragraph("불러오는 중…", styles.muted),
    });
    let goals: Goal[];
    try {
      goals = await fetchGoals();
    } catch (failure) {
      if (id === sceneId) {
        modal.show({
          title,
          content: createErrorView(message(failure), () => void showList()),
        });
      }
      return;
    }
    if (id !== sceneId) {
      return;
    }

    const state = processLinkState(props.process, goals);
    const content = document.createElement("div");
    content.className = styles.detail;
    content.append(
      paragraph(
        state.kind === "linked"
          ? `${props.process}은(는) '${state.goalName}' 목표에 연결되어 있어요. 그 목표를 누르면 연결이 해제돼요. 다른 목표로 옮기려면 먼저 해제하세요.`
          : state.kind === "sitesLinked"
            ? `${props.process}의 사이트가 '${state.goalName}' 목표에 연결되어 있어 브라우저 전체는 연결할 수 없어요.`
            : `${props.process}을(를) 연결할 목표를 고르세요.`,
        styles.muted,
      ),
    );
    if (error) {
      const banner = paragraph(error, styles.error);
      banner.setAttribute("role", "alert");
      content.append(banner);
    }
    content.append(
      goals.length === 0
        ? paragraph(
            "아직 목표가 없어요. 홈의 ‘목표 만들기’로 먼저 목표를 만들어 주세요.",
            styles.muted,
          )
        : createGoalList({
            goals,
            onOpen: (goal) =>
              void (state.kind === "linked" && goal.id === state.goalId
                ? save(
                    goal,
                    removeProcess(goal.processes, props.process),
                    `'${goal.name}' 목표에서 연결이 해제되었습니다.`,
                    "연결을 해제하지 못했습니다",
                  )
                : save(
                    goal,
                    addProcess(goal.processes, props.process),
                    `'${goal.name}' 목표에 등록되었습니다.`,
                    "연결하지 못했습니다",
                  )),
            status: (goal) => {
              if (state.kind === "linked") {
                return goal.id === state.goalId
                  ? { note: "연결됨 · 누르면 연결 해제", disabled: false }
                  : { note: "", disabled: true };
              }
              return state.kind === "sitesLinked"
                ? { note: "", disabled: true }
                : null;
            },
          }),
    );
    modal.show({ title, content });
  }

  /** 목표의 연결 프로세스를 processes로 바꿔 저장한다. 저장되면 팝업을 닫고 done을 토스트로, 실패하면 팝업에 failed와 이유를 보인다. */
  async function save(
    goal: Goal,
    processes: string[],
    done: string,
    failed: string,
  ): Promise<void> {
    if (saving) {
      return;
    }
    saving = true;
    const scene = sceneId;
    for (const button of modal.body.querySelectorAll("button")) {
      button.disabled = true;
    }
    try {
      await updateGoal(goal.id, {
        name: goal.name,
        daily_target_minutes: goal.daily_target_minutes,
        weekdays: goal.weekdays,
        processes,
        sites: goal.sites,
        // 연결만 바꾸는 수정이라 기간은 지금 값을 그대로 보낸다.
        start_date: goal.start_date,
        end_date: goal.end_date,
      });
    } catch (failure) {
      if (scene === sceneId && !destroyed) {
        await showList(`${failed}: ${message(failure)}`);
      }
      return;
    } finally {
      saving = false;
    }
    if (destroyed) {
      return;
    }
    // 닫혔든 아니든 저장은 됐다 — 화면을 다시 불러오고 알린다.
    if (scene === sceneId) {
      modal.close();
    }
    showToast(done);
    props.onLinked();
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
