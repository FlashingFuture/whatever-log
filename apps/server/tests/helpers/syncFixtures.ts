import { loginGoogleUser } from "../../src/auth/accounts.ts";
import { generateToken, hashToken } from "../../src/auth/sessionToken.ts";
import { type ApiDeps, handleApi } from "../../src/sync/api.ts";
import { createFakeD1 } from "./fakeD1.ts";

// biome-ignore lint/suspicious/noExplicitAny: 테스트가 응답 JSON의 칸을 자유롭게 읽는다
export type Json = Record<string, any>;

export const T0 = new Date("2026-11-06T03:00:00.000Z");
export const DAY_MS = 24 * 60 * 60 * 1000;

let counter = 0;
/** 테스트용 UUID v4(서로 다르다). */
export function uuid(): string {
  counter += 1;
  const tail = counter.toString(16).padStart(12, "0");
  return `00000000-0000-4000-8000-${tail}`;
}

export const GOAL = {
  name: "공부",
  daily_target_minutes: 120,
  weekdays: [0, 1, 2, 3, 4],
  base_revision: 0,
};

export function setup() {
  const { db, sqlite } = createFakeD1();
  const clock = { now: new Date(T0) };
  const deps: ApiDeps = { db: db as never, now: () => clock.now };

  /** 사용자를 만들고 로그인 토큰 원문을 돌려준다. */
  async function signIn(sub = "sub-1", email = "a@example.com") {
    const token = generateToken();
    await loginGoogleUser(db as never, {
      sub,
      email,
      tokenHash: await hashToken(token),
      now: clock.now,
      expiresAt: new Date(clock.now.getTime() + 30 * DAY_MS),
    });
    return token;
  }

  /** 요청을 보내 상태와 JSON 본문을 돌려준다. 이 모듈의 주소가 아니면 status가 null이다. */
  async function call(
    method: string,
    path: string,
    options: { token?: string; body?: unknown; headers?: HeadersInit } = {},
  ) {
    const headers = new Headers(options.headers);
    if (options.token) headers.set("Authorization", `Bearer ${options.token}`);
    let body: BodyInit | undefined;
    if (options.body !== undefined) {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(options.body);
    }
    const request = new Request(`https://server.example${path}`, {
      method,
      headers,
      body,
    });
    const response = await handleApi(request, new URL(request.url), deps);
    if (response === null) {
      return { status: null, json: null as never, response: null as never };
    }
    const text = await response.text();
    return {
      status: response.status,
      json: (text ? JSON.parse(text) : null) as Json,
      response,
    };
  }

  return { db, sqlite, clock, deps, signIn, call };
}
