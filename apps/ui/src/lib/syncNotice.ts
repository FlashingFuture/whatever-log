// 목표를 만들고 고치는 화면에 보여 줄 동기화 안내. 로그인했는지, 동기화를 켰는지에 따라 이 목표가 서버로 가는지가 달라서 문장도 달라진다.
// DOM·hub를 모르는 순수 함수라 lib에 둔다(구조만 받는다 — 계정 상태가 그대로 들어온다).

export interface SyncNoticeState {
  phase: string;
  syncEnabled: boolean;
}

/** 로그인하지 않았으면 null(서버와 상관없으니 안내하지 않는다). */
export function syncNotice(state: SyncNoticeState): string | null {
  if (state.phase !== "signedIn") {
    return null;
  }
  return state.syncEnabled
    ? "이 목표의 이름·목표 시간·요일이 서버에도 저장돼요. 연결하는 프로세스·사이트는 이 PC에만 있어요."
    : "아직 목표 동기화를 켜지 않아서 이 목표는 서버로 가지 않아요. 서버와 맞추려면 상단 막대의 '목표 동기화'에서 먼저 확인해 주세요.";
}
