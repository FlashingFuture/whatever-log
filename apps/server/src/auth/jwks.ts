import type { FetchFn } from "./googleOAuth.ts";

export const GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs";
const TTL_MS = 60 * 60 * 1000;
// 모르는 kid가 올 때마다 Google에 가면, 가짜 토큰으로 우리 서버를 증폭기로 쓸 수 있다 — 새로 받는 간격에 하한을 둔다.
const MIN_REFETCH_MS = 60 * 1000;
const TIMEOUT_MS = 10_000;

/** ID 토큰 서명을 검증할 공개키를 kid로 찾아 준다. */
export interface KeyProvider {
  get(kid: string): Promise<JsonWebKey | undefined>;
}

/**
 * Google 공개키(JWKS) 제공자. 받아 온 키는 1시간 메모리에 두고(Worker 인스턴스가 살아 있는 동안 재사용되므로
 * 모듈 수준에서 한 번 만들어 쓴다), 모르는 kid가 오면 키가 교체됐을 수 있으니 다시 받아 본다(최대 1분에 한 번).
 */
export function createGoogleKeyProvider(
  fetchFn: FetchFn,
  now: () => number,
): KeyProvider {
  let keys = new Map<string, JsonWebKey>();
  let fetchedAt = Number.NEGATIVE_INFINITY;

  async function refresh(): Promise<void> {
    fetchedAt = now();
    try {
      await load();
    } catch (error) {
      // 키가 하나도 없는 채로 실패했다면 1분을 기다리게 하지 않고 다음 로그인에서 바로 다시 시도한다.
      // (키가 있을 때의 실패는 그대로 두어, 모르는 kid로 Google을 계속 두드리는 것을 막는다.)
      if (keys.size === 0) fetchedAt = Number.NEGATIVE_INFINITY;
      throw error;
    }
  }

  async function load(): Promise<void> {
    const response = await fetchFn(GOOGLE_JWKS_URL, {
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!response.ok) {
      throw new Error(`JWKS 요청이 실패했습니다(${response.status}).`);
    }
    const body = (await response.json()) as { keys?: unknown };
    const next = new Map<string, JsonWebKey>();
    for (const entry of Array.isArray(body.keys) ? body.keys : []) {
      const key = entry as JsonWebKey & { kid?: unknown };
      if (key.kty === "RSA" && typeof key.kid === "string") {
        next.set(key.kid, key);
      }
    }
    keys = next;
  }

  return {
    async get(kid) {
      const age = now() - fetchedAt;
      if (age >= TTL_MS || (!keys.has(kid) && age >= MIN_REFETCH_MS)) {
        await refresh();
      }
      return keys.get(kid);
    },
  };
}
