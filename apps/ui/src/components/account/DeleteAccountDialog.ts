import { ApiError, type DeleteAccountResult, deleteAccount } from "../../api";
import { canConfirmDelete, outcomeLines } from "../../lib/deleteAccount";
import { createButton } from "../common/Button";
import { createModal } from "../common/Modal";
import styles from "./DeleteAccountDialog.module.css";

export interface DeleteAccountDialogProps {
  /** 서버에서 계정을 지웠다(이 PC의 정리가 일부 실패했더라도) — 계정 상태를 다시 확인하게 한다. */
  onDeleted: () => void;
  /** 로그인이 필요한 상황(만료, 계정이 바뀜)이라는 응답을 받았다 — 계정 상태를 다시 확인하게 한다. */
  onSignedOut: () => void;
}

export interface DeleteAccountDialog {
  /** 지울 계정(지금 로그인한 계정의 이메일, 모르면 null)을 보여 주며 확인 창을 연다. */
  open: (email: string | null) => void;
  destroy: () => void;
}

function paragraph(text: string, className?: string): HTMLParagraphElement {
  const element = document.createElement("p");
  element.textContent = text;
  if (className) {
    element.className = className;
  }
  return element;
}

function list(items: string[]): HTMLUListElement {
  const element = document.createElement("ul");
  element.className = styles.list;
  for (const text of items) {
    element.append(
      Object.assign(document.createElement("li"), { textContent: text }),
    );
  }
  return element;
}

// hub가 "요청은 보냈지만 결과를 알 수 없다"고 알릴 때의 상태 코드(apps/hub의 STATUS_OUTCOME_UNKNOWN).
const OUTCOME_UNKNOWN = 504;

/**
 * 실패 문장. hub가 사유를 준 실패(ApiError)는 서버 삭제가 끝나지 않은 것이라 이 PC의 로그인 정보가 그대로라고 말할 수 있다. 다만 결과를 알 수
 * 없는 실패(504)와 응답을 아예 받지 못한 경우는 서버가 이미 지웠을 수도 있어서, 지우지 못했다고 단정하지 않고 상태를 확인하라고 안내한다.
 */
function message(error: unknown): string {
  if (
    error instanceof ApiError &&
    error.status === OUTCOME_UNKNOWN &&
    error.message
  ) {
    return error.message;
  }
  if (error instanceof ApiError && error.message) {
    return `${error.message} 이 PC의 로그인 정보는 그대로 두었어요.`;
  }
  return "응답을 받지 못했어요. 계정이 지워졌는지 확인하려면 잠시 뒤 상단 막대의 로그인 상태를 봐 주세요.";
}

/**
 * "계정 삭제" 확인 창. 무엇이 지워지고 무엇이 남는지를 먼저 보여 주고, 되돌릴 수 없다는 점에 체크하고 계정 이메일을 직접 입력해야 삭제 버튼이
 * 눌린다. 서버 삭제가 실패하면 이 PC의 로그인·동기화는 그대로 둔다(계정은 남아 있는데 지울 방법을 잃지 않게). 성공하면 결과를 알리고
 * 닫는다. 입력·체크·처리 상태는 이 창 안의 일시적 상태라 클로저에 둔다(docs/ui-state.md).
 */
export function createDeleteAccountDialog(
  props: DeleteAccountDialogProps,
): DeleteAccountDialog {
  // 창을 닫을 때 끝난 결과는 비운다(다음에 열면 새 확인 창). 요청이 진행 중이면 그대로 둔다 — 닫았다 다시 열어도 같은 요청의 화면이다.
  const modal = createModal({
    label: "계정 삭제",
    onClose: () => {
      if (!busy) {
        result = null;
      }
    },
  });
  let email: string | null = null;
  let understood = false;
  let typed = "";
  let busy = false;
  let failure: string | null = null;
  let result: DeleteAccountResult | null = null;

  async function submit(): Promise<void> {
    if (busy || !canConfirmDelete(understood, typed, email)) {
      return;
    }
    busy = true;
    failure = null;
    render();
    try {
      result = await deleteAccount(email);
      props.onDeleted();
    } catch (error) {
      failure = message(error);
      // 실패해도 계정 상태를 다시 읽어 화면을 맞춘다: 로그인이 필요한 상황(409)이거나, 결과를 알 수 없거나(처리됐을 수도 있다),
      // 서버에서는 지워졌는데 이 PC의 정리·응답이 어긋난 경우까지, 틀린 로그인 상태가 남지 않게 한다.
      props.onSignedOut();
    } finally {
      busy = false;
      render();
    }
  }

  function renderForm(): HTMLElement {
    const root = document.createElement("div");
    root.className = styles.root;
    root.append(
      paragraph(
        "계정을 지우면 서버에서 아래 내용이 모두 사라지고, 되돌릴 수 없어요.",
        styles.lead,
      ),
      list([
        "계정(이메일 주소)과 로그인 토큰",
        "서버에 올린 목표(이름·목표 시간·요일)",
        "날짜별 달성 기록과 기기 기록",
      ]),
      paragraph(
        "이 PC의 기록, 목표, 연결한 프로세스·사이트는 그대로 남아요.",
        styles.keep,
      ),
    );

    const check = document.createElement("label");
    check.className = styles.check;
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = understood;
    box.disabled = busy;
    box.addEventListener("change", () => {
      understood = box.checked;
      // 창 전체를 다시 그리면 체크박스가 교체되어 포커스를 잃는다 — 삭제 버튼 상태만 바꾼다.
      remove.disabled = busy || !canConfirmDelete(understood, typed, email);
    });
    check.append(box, " 되돌릴 수 없다는 것을 이해했어요");
    root.append(check);

    if (email !== null) {
      const field = document.createElement("div");
      field.className = styles.field;
      const label = document.createElement("label");
      label.htmlFor = "delete-account-email";
      label.textContent = `확인하려면 이메일(${email})을 입력하세요`;
      const input = document.createElement("input");
      input.id = "delete-account-email";
      input.type = "text";
      input.className = styles.input;
      input.autocomplete = "off";
      input.value = typed;
      input.disabled = busy;
      input.addEventListener("input", () => {
        typed = input.value;
        // 입력 칸을 다시 그리면 커서를 잃으므로 버튼 상태만 갱신한다.
        remove.disabled = busy || !canConfirmDelete(understood, typed, email);
      });
      field.append(label, input);
      root.append(field);
    }

    if (failure) {
      const alert = paragraph(failure, styles.error);
      alert.setAttribute("role", "alert");
      root.append(alert);
    }

    const actions = document.createElement("div");
    actions.className = styles.actions;
    const remove = createButton({
      label: busy ? "지우는 중…" : "계정과 서버 데이터 삭제",
      disabled: busy || !canConfirmDelete(understood, typed, email),
      onClick: () => void submit(),
    });
    remove.classList.add(styles.danger);
    actions.append(
      remove,
      createButton({
        label: "취소",
        disabled: busy,
        onClick: () => modal.close(),
      }),
    );
    root.append(actions);
    return root;
  }

  function renderDone(done: DeleteAccountResult): HTMLElement {
    const root = document.createElement("div");
    root.className = styles.root;
    root.append(list(outcomeLines(done)));
    const close = createButton({ label: "닫기", onClick: () => modal.close() });
    close.dataset.autofocus = "true";
    root.append(close);
    return root;
  }

  function render(): void {
    const content = document.createElement("div");
    content.append(result ? renderDone(result) : renderForm());
    modal.show({ title: "계정 삭제", content });
    content.querySelector<HTMLElement>("[data-autofocus]")?.focus({
      preventScroll: true,
    });
  }

  return {
    open(next) {
      // 삭제 요청이 진행 중이거나 끝난 결과가 아직 보이지 않았다면 새 확인 창으로 바꾸지 않는다. 바꾸면 처리 중 표시가 사라져 같은 요청을
      // 다시 보낼 수 있고, 먼저 보낸 요청의 결과가 새 창에 덮어써진다.
      if (busy || result !== null) {
        render();
        modal.open();
        return;
      }
      email = next;
      understood = false;
      typed = "";
      failure = null;
      render();
      modal.open();
    },
    destroy: () => modal.destroy(),
  };
}
