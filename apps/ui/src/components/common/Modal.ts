import { createIconButton } from "./IconButton";
import styles from "./Modal.module.css";

/** 모달에 한 번에 보여 주는 한 장면(제목 + 내용). 장면을 바꿀 때마다 show로 통째로 갈아 끼운다. */
export interface ModalView {
  title: string;
  content: HTMLElement;
  /** 주면 제목 앞에 "뒤로" 버튼이 생긴다(목록 → 상세 → 편집처럼 겹겹이 들어간 장면에서). */
  onBack?: () => void;
  /** 제목 줄 오른쪽(닫기 버튼 앞)에 놓을 버튼들. */
  actions?: HTMLElement[];
}

export interface Modal {
  /** 모달을 연다(배경을 어둡게 하고 키보드 포커스를 안에 가둔다). */
  open: () => void;
  /** 모달을 닫고 열기 전에 포커스가 있던 곳으로 돌려보낸다. */
  close: () => void;
  /** 지금 보여 줄 장면으로 바꾼다. */
  show: (view: ModalView) => void;
  /** 장면의 내용이 들어 있는 영역(포커스를 옮기는 등 내용을 직접 만져야 할 때). */
  body: HTMLElement;
  /** DOM에서 떼어 낸다(화면을 떠날 때). */
  destroy: () => void;
}

export interface ModalProps {
  /** 모달의 이름(스크린 리더용 — 제목이 장면마다 바뀌므로 고정된 이름을 따로 둔다). */
  label: string;
  /** 어떤 방식으로든(닫기 버튼, Esc, 배경 클릭) 닫힌 뒤에 부른다. */
  onClose: () => void;
}

/**
 * <dialog> 기반 모달. 브라우저가 포커스 가두기·Esc 닫기·배경(backdrop)·열기 전 포커스 복귀를
 * 해 주므로 그걸 그대로 쓴다. 배경을 누르면 닫힌다(안쪽 패널은 눌러도 닫히지 않는다).
 */
export function createModal(props: ModalProps): Modal {
  const dialog = document.createElement("dialog");
  dialog.className = styles.dialog;
  dialog.setAttribute("aria-label", props.label);

  const panel = document.createElement("div");
  panel.className = styles.panel;
  const header = document.createElement("div");
  header.className = styles.header;
  const body = document.createElement("div");
  body.className = styles.body;
  panel.append(header, body);
  dialog.append(panel);

  // 배경은 dialog 자체의 가장자리다 — 안쪽 패널(panel)이 dialog를 꽉 채우므로, 패널 밖을 눌렀다는 것은
  // 패널이 덮지 않은 backdrop을 눌렀다는 뜻이다.
  // 글자를 끌어 선택하다 배경에서 손을 떼는 경우(누른 곳은 패널 안)에도 click이 배경에 생긴다 — 누른 곳도
  // 배경이었을 때만 닫는다.
  let pressedOnBackdrop = false;
  dialog.addEventListener("pointerdown", (event) => {
    pressedOnBackdrop = event.target === dialog;
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog && pressedOnBackdrop) {
      dialog.close();
    }
    pressedOnBackdrop = false;
  });
  dialog.addEventListener("close", () => props.onClose());

  function show(view: ModalView): void {
    // 장면을 통째로 갈아 끼우면 눌렀던 버튼이 사라져 포커스가 문서 맨 위로 빠진다 — 모달 안에 있던 포커스는
    // 새 제목으로 옮겨 키보드·스크린 리더 사용자가 모달 안에 머물게 한다.
    const hadFocus = dialog.contains(document.activeElement);
    const title = document.createElement("h2");
    title.tabIndex = -1;
    title.className = styles.title;
    title.textContent = view.title;
    header.replaceChildren(
      ...(view.onBack
        ? [
            createIconButton({
              icon: "back",
              label: "뒤로",
              onClick: view.onBack,
            }),
          ]
        : []),
      title,
      ...(view.actions ?? []),
      createIconButton({
        icon: "close",
        label: "닫기",
        onClick: () => dialog.close(),
      }),
    );
    body.replaceChildren(view.content);
    if (hadFocus && !dialog.contains(document.activeElement)) {
      title.focus({ preventScroll: true });
    }
  }

  return {
    open() {
      if (!dialog.isConnected) {
        document.body.append(dialog);
      }
      if (!dialog.open) {
        dialog.showModal();
      }
    },
    close() {
      if (dialog.open) {
        dialog.close();
      }
    },
    show,
    body,
    destroy() {
      if (dialog.open) {
        dialog.close();
      }
      dialog.remove();
    },
  };
}
