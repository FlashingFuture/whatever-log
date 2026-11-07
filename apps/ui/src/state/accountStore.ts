// 로그인 상태를 화면 전체가 같이 쓰는 저장소. 전략은 docs/ui-state.md에 정리했다.
//
// 핵심 두 가지:
// 1) 진실은 hub에 있다. 이 저장소는 hub가 마지막으로 알려 준 값을 들고 있는 "사본"이라서, 토큰은 물론
//    로그인 여부도 브라우저 저장소(localStorage 등)에 따로 저장하지 않는다. 앱을 다시 열면 hub에 다시 묻는다.
// 2) 상태는 몇 개의 이름 붙은 단계(phase)뿐이고, 어떤 단계에서 어떤 단계로 가는지가 `reduce` 한 곳에 있다.
//    화면은 단계만 보고 그린다(여러 불리언을 조합해 추측하지 않는다).

import type { AccountSnapshot, LoginProvider } from "../api";

/**
 * - loading: 처음 hub에 묻는 중. 아직 아무것도 모른다.
 * - signedOut: 로그인 안 됨. error가 있으면 직전 로그인 시도가 실패한 사유다.
 * - signingIn: 시스템 브라우저에서 로그인하는 중. hub에 주기적으로 결과를 묻는다.
 * - signedIn: 로그인됨(email은 서버가 알려 준 값, 없을 수 있다).
 * - unavailable: 로그인 기능을 지금 쓸 수 없다. reason이 hub(연결 안 됨)인지 cloud(이 설치에 기능 없음)인지 구분한다.
 */
export type AccountPhase =
  | "loading"
  | "signedOut"
  | "signingIn"
  | "signedIn"
  | "unavailable";

export interface AccountState {
  phase: AccountPhase;
  email: string | null;
  providers: readonly LoginProvider[];
  /** 사용자에게 보여 줄 오류 문장(로그인 실패, 로그아웃 실패 등). 없으면 null. */
  error: string | null;
  /** phase가 unavailable일 때만 의미가 있다. */
  reason: "hub" | "cloud" | null;
  /** 로그인·로그아웃·취소 요청이 오가는 중(버튼을 잠깐 막는 데 쓴다). */
  busy: boolean;
  /** 목표 동기화를 켰는지(로그인했을 때만 의미가 있다). */
  syncEnabled: boolean;
}

export const INITIAL_STATE: AccountState = {
  phase: "loading",
  email: null,
  providers: [],
  error: null,
  reason: null,
  busy: false,
  syncEnabled: false,
};

export type AccountEvent =
  /** hub가 현재 상태를 알려 줬다(조회·로그인 시작·취소·로그아웃의 응답 모두 같은 모양이다). */
  | { type: "snapshot"; snapshot: AccountSnapshot }
  /** hub에 닿지 못했다(꺼짐, 시간 초과 등). */
  | { type: "unreachable" }
  /** 요청을 보내기 시작했다(응답이 올 때까지 버튼을 막는다). */
  | { type: "requestStarted" }
  /** 요청이 실패했지만 상태는 그대로다(오류 문장만 보여 준다). */
  | { type: "requestFailed"; message: string };

/** hub가 준 스냅샷을 단계로 옮긴다. 단계 결정 규칙은 여기 한 곳에만 있다. */
function fromSnapshot(snapshot: AccountSnapshot): AccountState {
  const base = {
    providers: snapshot.providers,
    busy: false,
    reason: null,
  } as const;
  if (!snapshot.available) {
    return {
      ...INITIAL_STATE,
      ...base,
      phase: "unavailable",
      reason: "cloud",
      providers: [],
    };
  }
  if (snapshot.signed_in) {
    return {
      ...INITIAL_STATE,
      ...base,
      phase: "signedIn",
      email: snapshot.email,
      syncEnabled: snapshot.sync_enabled,
    };
  }
  if (snapshot.login.state === "pending") {
    return { ...INITIAL_STATE, ...base, phase: "signingIn" };
  }
  return {
    ...INITIAL_STATE,
    ...base,
    phase: "signedOut",
    error: snapshot.login.state === "failed" ? snapshot.login.message : null,
  };
}

/** 순수 함수: 이벤트가 오면 다음 상태를 돌려준다(DOM·네트워크를 모른다 — 그래서 그대로 테스트한다). */
export function reduce(state: AccountState, event: AccountEvent): AccountState {
  switch (event.type) {
    case "snapshot":
      return fromSnapshot(event.snapshot);
    case "unreachable":
      return {
        ...INITIAL_STATE,
        phase: "unavailable",
        reason: "hub",
        error: null,
      };
    case "requestStarted":
      return { ...state, busy: true, error: null };
    case "requestFailed":
      return { ...state, busy: false, error: event.message };
  }
}

/** 이 저장소가 hub와 주고받는 것. 실제로는 `../api`의 함수들을 넣고, 테스트는 가짜를 넣는다. */
export interface AccountApi {
  fetchAccount(): Promise<AccountSnapshot>;
  startLogin(provider: string): Promise<AccountSnapshot>;
  cancelLogin(): Promise<AccountSnapshot>;
  logout(): Promise<AccountSnapshot>;
}

export interface AccountStoreOptions {
  api: AccountApi;
  /** 로그인 중에 결과를 묻는 간격(ms). */
  pollMs?: number;
  /** hub에 닿지 못했을 때 다시 묻는 간격(ms). hub가 늦게 뜨거나 재시작해도 화면이 스스로 돌아오게 한다. */
  retryMs?: number;
  /** 타이머. 테스트가 시간을 직접 움직이려고 바꿀 수 있다. 취소 함수를 돌려준다. */
  setTimer?: (callback: () => void, ms: number) => () => void;
}

export interface AccountStore {
  getState(): AccountState;
  /** 상태가 바뀔 때마다 부른다. 해제 함수를 돌려준다. 등록 직후에는 부르지 않는다. */
  subscribe(listener: (state: AccountState) => void): () => void;
  /** hub에 지금 상태를 묻는다(앱을 열 때, 창으로 돌아올 때). */
  refresh(): Promise<void>;
  login(providerId: string): Promise<void>;
  cancelLogin(): Promise<void>;
  logout(): Promise<void>;
  /** 타이머와 구독을 정리한다. */
  dispose(): void;
}

const DEFAULT_POLL_MS = 1000;
const DEFAULT_RETRY_MS = 5000;

// ApiError는 api/client.ts에 있는데, `../api`에서 클래스 값을 가져오면 이 파일이 api 폴더 전체(fetch를 쓰는
// 통신 코드)를 끌고 와서 DOM·네트워크 없이 테스트하기 어려워진다. 그래서 이름과 상태 코드로만 알아본다.
function isApiError(error: unknown): error is Error & { status: number } {
  return (
    error instanceof Error &&
    error.name === "ApiError" &&
    typeof (error as { status?: unknown }).status === "number"
  );
}

/** hub가 사유를 준 오류(ApiError)는 그 문장을, 연결 실패 같은 나머지는 우리가 정한 문장을 보여 준다. */
function messageOf(error: unknown, fallback: string): string {
  return isApiError(error) && error.message ? error.message : fallback;
}

export function createAccountStore(options: AccountStoreOptions): AccountStore {
  const { api } = options;
  const pollMs = options.pollMs ?? DEFAULT_POLL_MS;
  const retryMs = options.retryMs ?? DEFAULT_RETRY_MS;
  const setTimer =
    options.setTimer ??
    ((callback, ms) => {
      const id = setTimeout(callback, ms);
      return () => clearTimeout(id);
    });

  let state = INITIAL_STATE;
  const listeners = new Set<(state: AccountState) => void>();
  let cancelPoll: (() => void) | null = null;
  // 요청마다 번호를 매겨, 늦게 도착한 오래된 응답이 더 새로운 상태를 덮어쓰지 못하게 한다
  // (예: 로그인 중 조회 응답이 로그아웃 응답보다 늦게 오는 경우).
  let latest = 0;
  let disposed = false;
  // 로그인·취소·로그아웃 요청이 오가는 동안에는 조회를 보내지 않고 끝난 뒤에 한 번 보낸다. 변경이 끝나기 전에 보낸 조회가
  // 변경 전 상태를 읽고 더 최근 요청이 되어 변경의 응답을 밀어내면(예: 로그아웃 응답이 무시되고 로그인 상태가 계속 보임),
  // 그 뒤에는 다시 묻는 타이머가 없어 화면이 틀린 채로 남는다.
  let mutating = 0;
  let refreshAfterMutation = false;

  function apply(event: AccountEvent): void {
    if (disposed) {
      return;
    }
    const next = reduce(state, event);
    state = next;
    for (const listener of [...listeners]) {
      listener(state);
    }
    // 다시 물어야 하는 단계만 타이머를 걸고, 나머지는 멈춘다: 로그인 중이면 결과를 자주,
    // hub에 닿지 못했으면 가끔(이 PC의 hub가 늦게 뜨거나 재시작하는 경우).
    cancelPoll?.();
    cancelPoll = null;
    const delay =
      state.phase === "signingIn"
        ? pollMs
        : state.phase === "unavailable" && state.reason === "hub"
          ? retryMs
          : null;
    if (delay !== null) {
      cancelPoll = setTimer(() => {
        cancelPoll = null;
        void refresh();
      }, delay);
    }
  }

  /** 요청을 보내고 응답이 "가장 최근에 보낸 요청의 것"일 때만 상태에 반영한다. */
  async function run(
    request: () => Promise<AccountSnapshot>,
    failureMessage: string,
    {
      keepStateOnFailure,
      conflictMeansRefresh = false,
    }: { keepStateOnFailure: boolean; conflictMeansRefresh?: boolean },
  ): Promise<void> {
    const ticket = ++latest;
    try {
      const snapshot = await request();
      if (ticket === latest) {
        apply({ type: "snapshot", snapshot });
      }
    } catch (error) {
      if (ticket !== latest) {
        return;
      }
      // 이미 로그인이 진행 중이라는 409는 실패가 아니라 "화면이 낡았다"는 뜻이다 — 다시 물어 맞춘다.
      if (conflictMeansRefresh && isApiError(error) && error.status === 409) {
        await refresh();
        return;
      }
      apply(
        keepStateOnFailure
          ? { type: "requestFailed", message: messageOf(error, failureMessage) }
          : { type: "unreachable" },
      );
    }
  }

  async function refresh(): Promise<void> {
    if (mutating > 0) {
      refreshAfterMutation = true;
      return;
    }
    // 조회가 실패하면 hub에 닿지 못한 것이다.
    await run(() => api.fetchAccount(), "", { keepStateOnFailure: false });
  }

  /** 변경 요청(로그인·취소·로그아웃)을 한다. 그동안 들어온 조회는 끝난 뒤에 한 번 보낸다. */
  async function mutate(
    request: () => Promise<AccountSnapshot>,
    failureMessage: string,
    options: { conflictMeansRefresh?: boolean } = {},
  ): Promise<void> {
    mutating += 1;
    apply({ type: "requestStarted" });
    try {
      await run(request, failureMessage, {
        keepStateOnFailure: true,
        conflictMeansRefresh: options.conflictMeansRefresh,
      });
    } finally {
      mutating -= 1;
    }
    if (mutating === 0 && refreshAfterMutation) {
      refreshAfterMutation = false;
      await refresh();
    }
  }

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    refresh,
    login: (providerId) =>
      mutate(
        () => api.startLogin(providerId),
        "로그인을 시작하지 못했습니다.",
        { conflictMeansRefresh: true },
      ),
    cancelLogin: () =>
      mutate(() => api.cancelLogin(), "로그인을 취소하지 못했습니다."),
    logout: () => mutate(() => api.logout(), "로그아웃하지 못했습니다."),
    dispose() {
      disposed = true;
      cancelPoll?.();
      cancelPoll = null;
      listeners.clear();
    },
  };
}

/**
 * "로그인이 방금 끝났는가"를 알려 주는 감시자(상태가 바뀔 때마다 부른다). 사용자가 로그인을 시도했고 그 결과 로그인됨이 된
 * 순간에만 true를 한 번 돌려준다 — 앱을 열 때 이미 로그인되어 있는 경우나 창으로 돌아올 때의 조회는 세지 않는다.
 *
 * 시도는 "로그인 중" 단계뿐 아니라 요청이 오가는 동안(`signedOut` + `busy`)도 센다. 브라우저에서 로그인이 시작 응답보다 먼저
 * 끝나면 `signedOut`에서 `signingIn`을 거치지 않고 바로 `signedIn`이 되는데, 그때도 확인 창을 열어야 한다.
 */
export function createLoginWatcher(): (state: AccountState) => boolean {
  let attempted = false;
  return (state) => {
    if (
      state.phase === "signingIn" ||
      (state.phase === "signedOut" && state.busy)
    ) {
      attempted = true;
      return false;
    }
    if (state.phase === "signedIn") {
      const finished = attempted;
      attempted = false;
      return finished;
    }
    if (state.phase === "signedOut" || state.phase === "unavailable") {
      attempted = false; // 실패·취소했거나 연결이 끊겼다
    }
    return false;
  };
}
