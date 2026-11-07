import assert from "node:assert/strict";
import { test } from "node:test";

import { ApiError } from "../../src/api/client.ts";
import type { AccountSnapshot } from "../../src/api/types.ts";
import {
  type AccountApi,
  type AccountState,
  createAccountStore,
  createLoginWatcher,
  INITIAL_STATE,
  reduce,
} from "../../src/state/accountStore.ts";

const GOOGLE = { id: "google", label: "Google" };

function snapshot(over: Partial<AccountSnapshot> = {}): AccountSnapshot {
  return {
    available: true,
    signed_in: false,
    email: null,
    login: { state: "idle", message: null },
    providers: [GOOGLE],
    sync_enabled: false,
    ...over,
  };
}

const SIGNED_IN = snapshot({ signed_in: true, email: "a@example.com" });
const PENDING = snapshot({ login: { state: "pending", message: null } });

// --- reduce: 단계 결정 규칙 -------------------------------------------------------------------

test("처음 상태는 loading이다", () => {
  assert.equal(INITIAL_STATE.phase, "loading");
});

test("스냅샷은 단계로 옮겨진다", () => {
  const cases: [AccountSnapshot, Partial<AccountState>][] = [
    [snapshot(), { phase: "signedOut", error: null, providers: [GOOGLE] }],
    [SIGNED_IN, { phase: "signedIn", email: "a@example.com" }],
    [PENDING, { phase: "signingIn" }],
    [
      snapshot({
        login: { state: "failed", message: "서버에 연결하지 못했습니다." },
      }),
      { phase: "signedOut", error: "서버에 연결하지 못했습니다." },
    ],
    [
      snapshot({ available: false, providers: [GOOGLE] }),
      { phase: "unavailable", reason: "cloud", providers: [] },
    ],
  ];
  for (const [input, expected] of cases) {
    const next = reduce(INITIAL_STATE, { type: "snapshot", snapshot: input });
    for (const [key, value] of Object.entries(expected)) {
      assert.deepEqual(
        next[key as keyof AccountState],
        value,
        `${input.login.state}/${key}`,
      );
    }
    assert.equal(next.busy, false);
  }
});

test("로그인되어 있으면 진행 중 표시가 남아 있어도 signedIn이다", () => {
  const next = reduce(INITIAL_STATE, {
    type: "snapshot",
    snapshot: snapshot({
      signed_in: true,
      email: "a@example.com",
      login: { state: "pending", message: null },
    }),
  });

  assert.equal(next.phase, "signedIn");
});

test("hub에 닿지 못하면 unavailable(hub)이고 이전 로그인 정보는 비운다", () => {
  const before = reduce(INITIAL_STATE, {
    type: "snapshot",
    snapshot: SIGNED_IN,
  });

  const next = reduce(before, { type: "unreachable" });

  assert.deepEqual(
    [next.phase, next.reason, next.email],
    ["unavailable", "hub", null],
  );
});

test("요청을 보내면 busy가 되고 이전 오류가 지워지며, 실패하면 단계는 그대로 두고 오류만 보인다", () => {
  const failed = reduce(
    reduce(INITIAL_STATE, {
      type: "snapshot",
      snapshot: snapshot({ login: { state: "failed", message: "옛 오류" } }),
    }),
    { type: "requestStarted" },
  );
  assert.deepEqual([failed.busy, failed.error], [true, null]);

  const next = reduce(failed, {
    type: "requestFailed",
    message: "다시 시도해 주세요.",
  });

  assert.deepEqual(
    [next.phase, next.busy, next.error],
    ["signedOut", false, "다시 시도해 주세요."],
  );
});

// --- store: 호출 순서와 폴링 ------------------------------------------------------------------

type Responses = Partial<
  Record<keyof AccountApi, (...args: string[]) => Promise<AccountSnapshot>>
>;

/** 직접 움직이는 시계와, 호출을 기록하는 가짜 API. */
function setup(responses: Responses = {}) {
  const calls: string[] = [];
  const timers: { callback: () => void; ms: number; cancelled: boolean }[] = [];
  const fallback = () => Promise.resolve(snapshot());
  const api: AccountApi = {
    fetchAccount() {
      calls.push("fetch");
      return (responses.fetchAccount ?? fallback)();
    },
    startLogin(provider) {
      calls.push(`login:${provider}`);
      return (responses.startLogin ?? fallback)(provider);
    },
    cancelLogin() {
      calls.push("cancel");
      return (responses.cancelLogin ?? fallback)();
    },
    logout() {
      calls.push("logout");
      return (responses.logout ?? fallback)();
    },
  };
  const store = createAccountStore({
    api,
    pollMs: 1000,
    setTimer(callback, ms) {
      const timer = { callback, ms, cancelled: false };
      timers.push(timer);
      return () => {
        timer.cancelled = true;
      };
    },
  });
  const active = () => timers.filter((timer) => !timer.cancelled);
  /** 예약된 타이머를 모두 울리고 비동기 처리가 끝나기를 기다린다. */
  async function tick() {
    for (const timer of active()) {
      timer.cancelled = true;
      timer.callback();
    }
    await flush();
  }
  return { store, calls, timers, active, tick };
}

const flush = () => new Promise((resolve) => setImmediate(resolve));

test("refresh는 hub의 상태를 반영하고 구독자에게 알린다", async () => {
  const { store } = setup({ fetchAccount: () => Promise.resolve(SIGNED_IN) });
  const seen: string[] = [];
  store.subscribe((state) => seen.push(state.phase));

  await store.refresh();

  assert.deepEqual(seen, ["signedIn"]);
  assert.equal(store.getState().email, "a@example.com");
});

test("구독 해제 후에는 알리지 않는다", async () => {
  const { store } = setup();
  const seen: string[] = [];
  const unsubscribe = store.subscribe((state) => seen.push(state.phase));
  unsubscribe();

  await store.refresh();

  assert.deepEqual(seen, []);
});

test("조회가 실패하면 hub에 닿지 못한 것으로 본다", async () => {
  const { store } = setup({
    fetchAccount: () => Promise.reject(new TypeError("Failed to fetch")),
  });

  await store.refresh();

  assert.deepEqual(
    [store.getState().phase, store.getState().reason],
    ["unavailable", "hub"],
  );
});

test("hub에 닿지 못하면 5초마다 다시 묻다가, 닿으면 스스로 돌아온다", async () => {
  let up = false;
  const { store, active, tick } = setup({
    fetchAccount: () =>
      up
        ? Promise.resolve(snapshot())
        : Promise.reject(new TypeError("Failed to fetch")),
  });
  await store.refresh();
  assert.equal(store.getState().phase, "unavailable");
  assert.equal(active().length, 1);
  assert.equal(active()[0].ms, 5000);

  await tick();
  assert.equal(store.getState().phase, "unavailable");

  up = true;
  await tick();

  assert.equal(store.getState().phase, "signedOut");
  assert.equal(active().length, 0, "돌아오면 더 묻지 않는다");
});

test("로그인 기능이 없는 설치(cloud)는 다시 묻지 않는다", async () => {
  const { store, active } = setup({
    fetchAccount: () => Promise.resolve(snapshot({ available: false })),
  });

  await store.refresh();

  assert.equal(store.getState().reason, "cloud");
  assert.equal(active().length, 0);
});

test("로그인을 시작하면 signingIn이 되고, 끝날 때까지 1초마다 hub에 묻는다", async () => {
  let answer = PENDING;
  const { store, calls, active, tick } = setup({
    startLogin: () => Promise.resolve(PENDING),
    fetchAccount: () => Promise.resolve(answer),
  });

  await store.login("google");
  assert.equal(store.getState().phase, "signingIn");
  assert.equal(active().length, 1);
  assert.equal(active()[0].ms, 1000);

  await tick();
  await tick();
  assert.deepEqual(calls, ["login:google", "fetch", "fetch"]);
  assert.equal(store.getState().phase, "signingIn");

  answer = SIGNED_IN;
  await tick();

  assert.equal(store.getState().phase, "signedIn");
  assert.equal(active().length, 0, "끝나면 더 묻지 않는다");
});

test("로그인이 실패하면 사유를 보여 주고 폴링을 멈춘다", async () => {
  const failed = snapshot({
    login: { state: "failed", message: "서버에 연결하지 못했습니다." },
  });
  const { store, active, tick } = setup({
    startLogin: () => Promise.resolve(PENDING),
    fetchAccount: () => Promise.resolve(failed),
  });
  await store.login("google");

  await tick();

  assert.deepEqual(
    [store.getState().phase, store.getState().error],
    ["signedOut", "서버에 연결하지 못했습니다."],
  );
  assert.equal(active().length, 0);
});

test("로그인 요청 중에는 busy이고, 응답이 오면 풀린다", async () => {
  let release: (value: AccountSnapshot) => void = () => {};
  const { store } = setup({
    startLogin: () => new Promise((resolve) => (release = resolve)),
  });

  const pending = store.login("google");
  assert.equal(store.getState().busy, true);
  release(PENDING);
  await pending;

  assert.equal(store.getState().busy, false);
});

test("로그인을 시작하지 못하면(hub 오류) 로그아웃 상태에서 오류를 보여 준다", async () => {
  const { store } = setup({
    startLogin: () =>
      Promise.reject(
        new ApiError(
          503,
          "unavailable",
          "이 설치에서는 로그인 기능을 쓸 수 없습니다.",
        ),
      ),
  });
  await store.refresh(); // 로그인 버튼은 첫 조회가 끝난 뒤에야 보인다

  await store.login("google");

  assert.deepEqual(
    [store.getState().phase, store.getState().error, store.getState().busy],
    ["signedOut", "이 설치에서는 로그인 기능을 쓸 수 없습니다.", false],
  );
});

test("연결이 끊겨 로그인을 시작하지 못하면 우리 문장으로 안내한다(영어 예외 문구를 노출하지 않는다)", async () => {
  const { store } = setup({
    startLogin: () => Promise.reject(new TypeError("Failed to fetch")),
  });

  await store.login("google");

  assert.equal(store.getState().error, "로그인을 시작하지 못했습니다.");
});

test("이미 진행 중이라는 409는 실패가 아니라 상태를 다시 물어 맞춘다", async () => {
  const { store, calls } = setup({
    startLogin: () =>
      Promise.reject(
        new ApiError(409, "invalid_request", "이미 로그인이 진행 중입니다."),
      ),
    fetchAccount: () => Promise.resolve(PENDING),
  });

  await store.login("google");

  assert.deepEqual(calls, ["login:google", "fetch"]);
  assert.deepEqual(
    [store.getState().phase, store.getState().error],
    ["signingIn", null],
  );
});

test("취소하면 hub가 알려 준 상태를 따른다", async () => {
  const { store, active } = setup({
    startLogin: () => Promise.resolve(PENDING),
    cancelLogin: () => Promise.resolve(snapshot()),
  });
  await store.login("google");

  await store.cancelLogin();

  assert.equal(store.getState().phase, "signedOut");
  assert.equal(active().length, 0);
});

test("취소 응답이 아직 진행 중이라고 해도(스레드가 끝나는 중) 계속 묻다가 idle을 받는다", async () => {
  let answer = PENDING;
  const { store, tick } = setup({
    startLogin: () => Promise.resolve(PENDING),
    cancelLogin: () => Promise.resolve(PENDING),
    fetchAccount: () => Promise.resolve(answer),
  });
  await store.login("google");
  await store.cancelLogin();
  assert.equal(store.getState().phase, "signingIn");

  answer = snapshot();
  await tick();

  assert.equal(store.getState().phase, "signedOut");
});

test("로그아웃하면 signedOut이 된다", async () => {
  const { store } = setup({
    fetchAccount: () => Promise.resolve(SIGNED_IN),
    logout: () => Promise.resolve(snapshot()),
  });
  await store.refresh();

  await store.logout();

  assert.deepEqual(
    [store.getState().phase, store.getState().email],
    ["signedOut", null],
  );
});

test("로그아웃이 실패하면 로그인 상태를 유지하고 오류를 보여 준다", async () => {
  const { store } = setup({
    fetchAccount: () => Promise.resolve(SIGNED_IN),
    logout: () =>
      Promise.reject(
        new ApiError(
          500,
          "internal",
          "이 PC의 로그인 정보를 지우지 못했습니다.",
        ),
      ),
  });
  await store.refresh();

  await store.logout();

  const state = store.getState();
  assert.deepEqual(
    [state.phase, state.email, state.error],
    ["signedIn", "a@example.com", "이 PC의 로그인 정보를 지우지 못했습니다."],
  );
});

test("늦게 도착한 오래된 응답이 새 상태를 덮어쓰지 못한다", async () => {
  let releaseOld: (value: AccountSnapshot) => void = () => {};
  const { store } = setup({
    fetchAccount: () => new Promise((resolve) => (releaseOld = resolve)),
    logout: () => Promise.resolve(snapshot()),
  });

  const oldRefresh = store.refresh(); // 로그인 상태를 담은 응답이 아직 오는 중
  await store.logout(); // 그 사이 로그아웃이 끝났다
  releaseOld(SIGNED_IN);
  await oldRefresh;

  assert.equal(store.getState().phase, "signedOut");
});

test("dispose 후에는 타이머가 없고 더 알리지 않는다", async () => {
  const { store, active } = setup({
    startLogin: () => Promise.resolve(PENDING),
  });
  const seen: string[] = [];
  store.subscribe((state) => seen.push(state.phase));
  await store.login("google");

  store.dispose();
  await store.refresh();

  assert.equal(active().length, 0);
  assert.equal(seen.at(-1), "signingIn");
});

test("변경 요청이 오가는 동안 들어온 조회는 보내지 않고, 끝난 뒤 한 번 보내 결과를 따른다", async () => {
  let releaseLogout: (value: AccountSnapshot) => void = () => {};
  const fetches: string[] = [];
  const { store } = setup({
    fetchAccount: () => {
      fetches.push("fetch");
      return Promise.resolve(snapshot());
    },
    logout: () => new Promise((resolve) => (releaseLogout = resolve)),
  });

  const loggingOut = store.logout();
  void store.refresh(); // 로그아웃 중 창 포커스로 조회가 시작되는 경우
  void store.refresh();
  assert.deepEqual(fetches, [], "변경이 끝나기 전에는 조회를 보내지 않는다");

  releaseLogout(snapshot());
  await loggingOut;
  await flush();

  assert.deepEqual(fetches, ["fetch"], "끝난 뒤 한 번만 보낸다");
  assert.equal(store.getState().phase, "signedOut");
});

test("조회가 로그아웃 응답을 밀어내 로그인 상태가 계속 보이는 일이 없다", async () => {
  let stale = SIGNED_IN; // hub가 로그아웃을 처리하기 전에 읽으면 로그인 상태를 준다
  const { store } = setup({
    fetchAccount: () => Promise.resolve(stale),
    logout: () => {
      stale = snapshot();
      return Promise.resolve(snapshot());
    },
  });
  await store.refresh();
  assert.equal(store.getState().phase, "signedIn");

  const loggingOut = store.logout();
  void store.refresh();
  await loggingOut;
  await flush();

  assert.equal(store.getState().phase, "signedOut");
});

test("변경 요청이 실패해도 보류한 조회는 이어서 보낸다", async () => {
  let fetched = 0;
  const { store } = setup({
    fetchAccount: () => {
      fetched += 1;
      return Promise.resolve(SIGNED_IN);
    },
    logout: () =>
      Promise.reject(new ApiError(500, "internal", "지우지 못했습니다.")),
  });

  const loggingOut = store.logout();
  void store.refresh();
  await loggingOut;
  await flush();

  assert.equal(fetched, 1);
});

// --- 로그인 시도 감시 ---

const phase = (
  p: AccountState["phase"],
  over: Partial<AccountState> = {},
): AccountState => ({ ...INITIAL_STATE, phase: p, ...over });

test("로그인 중을 거쳐 로그인되면 한 번 알린다", () => {
  const watch = createLoginWatcher();

  assert.equal(watch(phase("signedOut", { busy: true })), false);
  assert.equal(watch(phase("signingIn")), false);
  assert.equal(watch(phase("signedIn")), true);
  assert.equal(
    watch(phase("signedIn")),
    false,
    "같은 로그인을 두 번 알리지 않는다",
  );
});

test("로그인이 시작 응답보다 먼저 끝나 로그인 중을 거치지 않아도 알린다", () => {
  const watch = createLoginWatcher();

  assert.equal(watch(phase("signedOut", { busy: true })), false); // 요청을 보내는 중
  assert.equal(watch(phase("signedIn", { email: "a@example.com" })), true);
});

test("앱을 열 때 이미 로그인되어 있거나 창으로 돌아와 다시 조회한 것은 알리지 않는다", () => {
  const watch = createLoginWatcher();

  assert.equal(watch(phase("loading")), false);
  assert.equal(watch(phase("signedIn")), false);
  assert.equal(watch(phase("signedIn")), false);
});

test("실패하거나 취소한 로그인 뒤의 시도는 다음 로그인과 섞이지 않는다", () => {
  const watch = createLoginWatcher();
  watch(phase("signedOut", { busy: true }));
  watch(phase("signingIn"));
  watch(phase("signedOut")); // 취소했거나 실패했다

  assert.equal(
    watch(phase("signedIn")),
    false,
    "시도 없이 로그인됨이 된 것(다른 곳에서 로그인)은 알리지 않는다",
  );
});

test("로그아웃은 로그인 시도로 세지 않는다", () => {
  const watch = createLoginWatcher();
  watch(phase("signedIn"));

  watch(phase("signedIn", { busy: true })); // 로그아웃 요청 중
  watch(phase("signedOut"));

  assert.equal(watch(phase("signedIn")), false);
});
