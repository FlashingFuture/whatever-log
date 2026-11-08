// 기기 목록 창의 순수 로직: 표시 순서, 기기를 가리키는 짧은 이름, 지울 수 있는지. DOM·hub를 모른다(lib 층).

export interface DeviceLike {
  device_id: string;
  last_sent_at: string;
  rows: number;
  is_this_device: boolean;
}

/** 이 기기가 맨 위, 나머지는 최근에 보낸 순(같으면 기기 ID 순). */
export function sortDevices<T extends DeviceLike>(devices: readonly T[]): T[] {
  return [...devices].sort((a, b) => {
    if (a.is_this_device !== b.is_this_device) {
      return a.is_this_device ? -1 : 1;
    }
    if (a.last_sent_at !== b.last_sent_at) {
      return a.last_sent_at < b.last_sent_at ? 1 : -1;
    }
    return a.device_id < b.device_id ? -1 : 1;
  });
}

/**
 * 기기에는 이름이 없다(이름을 받으면 PC 이름 같은 새 개인 정보가 서버에 생긴다). 그래서 목록에서 서로 구분할 수 있게 기기 ID의
 * 앞 6글자를 "기기 a1b2c3"처럼 보여 준다. 이 기기는 "이 기기"로 부른다.
 */
export function deviceLabel(device: DeviceLike, position: number): string {
  if (device.is_this_device) {
    return "이 기기";
  }
  return `다른 기기 ${position} (${device.device_id.slice(0, 6)})`;
}

/** 지울 수 있는지: 이 기기의 기록은 에이전트가 곧 다시 보내므로 지워도 소용이 없어 지울 수 없다. */
export function canDelete(device: DeviceLike): boolean {
  return !device.is_this_device;
}

/** 삭제 확인 문장: 무엇이 지워지고 무엇은 그대로인지. */
export function deleteWarning(device: DeviceLike): string {
  return `이 기기가 서버에 보낸 달성 기록 ${device.rows}줄이 지워져요. 목표와 다른 기기의 기록은 그대로예요. 그 기기를 다시 쓰면 기록이 다시 쌓여요.`;
}
