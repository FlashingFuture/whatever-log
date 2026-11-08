import {
  ApiError,
  type DeviceRow,
  deleteDevice,
  fetchDevices,
} from "../../api";
import {
  canDelete,
  deleteWarning,
  deviceLabel,
  sortDevices,
} from "../../lib/devices";
import { relativeTime } from "../../lib/syncStatus";
import { createButton } from "../common/Button";
import { createModal } from "../common/Modal";
import styles from "./DevicesDialog.module.css";

export interface DevicesDialogProps {
  /** 로그인이 필요한 상황(만료 등)이라는 응답을 받았다 — 계정 상태를 다시 확인하게 한다. */
  onSignedOut: () => void;
}

export interface DevicesDialog {
  open: () => Promise<void>;
  destroy: () => void;
}

function message(error: unknown): string {
  return error instanceof ApiError && error.message
    ? error.message
    : "처리하지 못했습니다. 잠시 뒤 다시 시도해 주세요.";
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
 * "기기 관리" 창: 서버에 달성 기록을 보낸 기기들을 보여 주고, 쓰지 않는 기기의 기록을 지운다(기기는 10대까지라 자리를 비우는 용도다).
 *
 * 기기에는 이름이 없다 — 이름을 받으면 PC 이름 같은 새 개인 정보가 서버에 생기므로, 무작위 기기 ID의 앞 6글자와 마지막으로 보낸 시각으로
 * 구분한다. 이 기기의 기록은 에이전트가 곧 다시 보내므로 지울 수 없다. 지우기는 두 번 눌러야 한다(되돌릴 수 없다).
 * 목록·확인 중인 기기·오류는 이 창 안의 일시적 상태라 클로저에 둔다(docs/ui-state.md).
 */
export function createDevicesDialog(props: DevicesDialogProps): DevicesDialog {
  const modal = createModal({ label: "기기 관리", onClose: () => {} });
  let devices: DeviceRow[] | null = null;
  // 목록을 받았을 때의 계정. 지우기 요청에 되돌려 보낸다(그 사이 계정이 바뀌면 hub가 거절한다).
  let listEmail: string | null = null;
  // 목록을 받았을 때의 로그인 키. 이메일이 같거나 없어도 다른 로그인을 가려낸다.
  let listSession: string | null = null;
  // 지우는 중에 창을 닫았다 다시 열었다. 그 사이 다른 계정으로 바뀌었을 수 있어서, 지우기가 끝나면 목록을 새로 받는다.
  let reloadAfterBusy = false;
  let failure: string | null = null;
  let confirming: string | null = null;
  let busy = false;
  let loadId = 0;

  // 다시 그린 뒤 포커스를 둘 곳. 창 안의 버튼이 교체되면 포커스가 제목으로 빠지므로, 누른 자리의 짝 버튼으로 옮겨 준다.
  type Focus = { device: string; role: "ask" | "confirm" | "cancel" };

  function row(device: DeviceRow, position: number): HTMLLIElement {
    const li = document.createElement("li");
    li.className = styles.row;
    const info = document.createElement("div");
    info.className = styles.info;
    const name = document.createElement("span");
    name.className = styles.name;
    name.textContent = deviceLabel(device, position);
    const meta = document.createElement("span");
    meta.className = styles.meta;
    const when = relativeTime(device.last_sent_at, new Date());
    meta.textContent = `${when ? `${when} 보냄` : "보낸 시각을 알 수 없음"} · 기록 ${device.rows}줄`;
    info.append(name, meta);
    li.append(info);

    if (!canDelete(device)) {
      li.append(
        paragraph(
          "이 기기의 기록은 동기화 에이전트가 계속 보내서 지울 수 없어요.",
          styles.note,
        ),
      );
      return li;
    }
    if (confirming === device.device_id) {
      li.append(paragraph(deleteWarning(device), styles.warning));
      const actions = document.createElement("div");
      actions.className = styles.actions;
      actions.append(
        tag(
          createButton({
            label: busy ? "지우는 중…" : "기록 지우기",
            disabled: busy,
            onClick: () => void remove(device.device_id),
          }),
          device.device_id,
          "confirm",
        ),
        tag(
          createButton({
            label: "취소",
            disabled: busy,
            onClick: () => {
              confirming = null;
              // 취소하면 처음의 "지우기" 버튼으로 돌아간다
              render({ device: device.device_id, role: "ask" });
            },
          }),
          device.device_id,
          "cancel",
        ),
      );
      li.append(actions);
      return li;
    }
    li.append(
      tag(
        createButton({
          label: "지우기",
          ariaLabel: `${deviceLabel(device, position)}의 기록 지우기`,
          disabled: busy,
          onClick: () => {
            confirming = device.device_id;
            failure = null;
            // 확인을 열면 안전한 쪽(취소)에 포커스를 둔다 — 실수로 Enter를 눌러도 지워지지 않는다
            render({ device: device.device_id, role: "cancel" });
          },
        }),
        device.device_id,
        "ask",
      ),
    );
    return li;
  }

  /** 버튼에 "어느 기기의 어느 버튼인지"를 적어 둔다(다시 그린 뒤 포커스를 되돌릴 때 찾는다). */
  function tag(button: HTMLButtonElement, device: string, role: Focus["role"]) {
    button.dataset.device = device;
    button.dataset.role = role;
    return button;
  }

  async function remove(deviceId: string): Promise<void> {
    if (busy) {
      return;
    }
    busy = true;
    failure = null;
    render({ device: deviceId, role: "confirm" });
    let focus: Focus | undefined;
    try {
      await deleteDevice(deviceId, listEmail, listSession);
      confirming = null;
      devices = (devices ?? []).filter((item) => item.device_id !== deviceId);
    } catch (error) {
      failure = message(error);
      focus = { device: deviceId, role: "confirm" }; // 실패하면 다시 시도할 수 있는 자리에 둔다
      if (error instanceof ApiError && error.status === 409) {
        props.onSignedOut();
      }
    } finally {
      busy = false;
      render(focus);
    }
    if (reloadAfterBusy) {
      reloadAfterBusy = false;
      await load();
      render();
    }
  }

  function render(focus?: Focus): void {
    const content = document.createElement("div");
    content.className = styles.root;
    if (devices === null) {
      content.append(paragraph(failure ?? "불러오는 중…"));
      if (failure) {
        content.append(
          createButton({
            label: "다시 시도",
            onClick: () => void load().then(() => render()),
          }),
        );
      }
    } else {
      content.append(
        paragraph(
          "서버에 달성 기록을 보낸 기기들이에요. 기기는 이름 없이 무작위 번호로만 구분해요(PC 이름을 서버로 보내지 않으려는 거예요). 쓰지 않는 기기의 기록을 지우면 자리가 비어요(10대까지).",
          styles.intro,
        ),
      );
      if (devices.length === 0) {
        content.append(
          paragraph("아직 달성 기록을 보낸 기기가 없어요.", styles.empty),
        );
      } else {
        const list = document.createElement("ul");
        list.className = styles.list;
        let other = 0;
        list.append(
          ...sortDevices(devices).map((device) => {
            if (!device.is_this_device) {
              other += 1;
            }
            return row(device, other);
          }),
        );
        content.append(list);
      }
      if (failure) {
        const alert = paragraph(failure, styles.error);
        alert.setAttribute("role", "alert");
        content.append(alert);
      }
    }
    modal.show({ title: "기기 관리", content });
    if (focus) {
      modal.body
        .querySelector<HTMLElement>(
          `button[data-device="${CSS.escape(focus.device)}"][data-role="${focus.role}"]`,
        )
        ?.focus({ preventScroll: true });
    }
  }

  /** 목록을 불러온다. 가장 최근 호출의 응답만 반영한다. */
  async function load(): Promise<void> {
    const id = ++loadId;
    failure = null;
    try {
      const loaded = await fetchDevices();
      if (id === loadId) {
        devices = loaded.devices;
        listEmail = loaded.email;
        listSession = loaded.session;
        confirming = null;
      }
    } catch (error) {
      if (id === loadId) {
        devices = null;
        failure = message(error);
        if (error instanceof ApiError && error.status === 409) {
          props.onSignedOut();
        }
      }
    }
  }

  return {
    async open() {
      // 지우는 중에 창을 닫았다 다시 연 경우: 목록을 새로 받지 않고 진행 중인 화면을 그대로 보여 준다. 새로 받으면 처리 중 표시가
      // 사라져 다른 기기를 또 지울 수 있고, 먼저 보낸 삭제가 끝났을 때 새 화면의 상태를 덮어쓰게 된다.
      if (busy) {
        reloadAfterBusy = true;
        render();
        modal.open();
        return;
      }
      devices = null;
      render(); // "불러오는 중…"을 먼저 보여 준다
      modal.open();
      await load();
      render();
    },
    destroy: () => modal.destroy(),
  };
}
