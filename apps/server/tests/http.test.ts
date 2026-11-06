import assert from "node:assert/strict";
import { test } from "node:test";
import { errorResponse, jsonResponse } from "../src/http.ts";

test("기본 헤더는 캐시를 막는 JSON이다", () => {
  const response = jsonResponse({ ok: true });

  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.match(
    response.headers.get("Content-Type") ?? "",
    /^application\/json/,
  );
});

test("추가 헤더는 객체, 배열, Headers 어느 형태로 줘도 같게 적용된다", () => {
  for (const extra of [
    { Allow: "POST" },
    [["Allow", "POST"]] as [string, string][],
    new Headers({ Allow: "POST" }),
  ]) {
    const response = errorResponse(405, "method_not_allowed", "x", extra);

    assert.equal(response.headers.get("Allow"), "POST");
    assert.equal(response.headers.get("Cache-Control"), "no-store");
  }
});

test("호출부가 기본 헤더를 덮어쓸 수 있다", () => {
  const response = jsonResponse({}, 200, { "Cache-Control": "private" });

  assert.equal(response.headers.get("Cache-Control"), "private");
});
