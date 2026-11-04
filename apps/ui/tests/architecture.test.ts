import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

/**
 * src 폴더의 층(layer) 규칙. 각 폴더가 어느 폴더를 가져다 써도 되는지 정해 두고, 어기는 import가
 * 생기면 실패한다 — 폴더 구조가 시간이 지나며 슬금슬금 뒤엉키지 않게 하려는 것이다
 * (예: lib가 api를 알게 되거나, 컴포넌트가 화면(pages)을 가져다 쓰는 일).
 *
 * 아래쪽 층일수록 위를 모른다: lib·api < router < components < layouts·pages < main.
 */
const ALLOWED: Record<string, string[]> = {
  // DOM·hub를 모르는 순수 로직(시간 형식, 로컬 시간 구간 계산 등)
  lib: [],
  // hub 통신
  api: [],
  // 주소 ↔ 화면 대응, 스크롤 복원
  router: [],
  components: ["lib", "api", "router", "components"],
  layouts: ["components", "router", "lib"],
  pages: ["lib", "api", "router", "components"],
  // 진입점은 전부 엮는다
  ".": ["lib", "api", "router", "components", "layouts", "pages", "styles"],
};

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..", "src");
// 스타일 파일은 어느 층에서든 가져올 수 있다(같은 폴더 옆의 *.module.css, styles/ 공용).
const ANY_LAYER = new Set(["styles"]);

function* sourceFiles(directory: string): Generator<string> {
  for (const entry of readdirSync(directory)) {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) {
      yield* sourceFiles(path);
    } else if (path.endsWith(".ts")) {
      yield path;
    }
  }
}

function layerOf(path: string): string {
  const [first] = relative(SRC, path).split(sep);
  return first.endsWith(".ts") ? "." : first;
}

const IMPORT = /(?:from|import)\s*\(?\s*["'](\.{1,2}\/[^"']*|\.{1,2})["']/g;

test("src의 모든 폴더는 층 규칙에 등록돼 있다", () => {
  const known = new Set(Object.keys(ALLOWED));
  const layers = new Set<string>();
  for (const file of sourceFiles(SRC)) {
    layers.add(layerOf(file));
  }
  for (const layer of layers) {
    assert.ok(
      known.has(layer),
      `${layer}/ 폴더가 이 테스트의 ALLOWED에 없다 — 어느 층을 가져다 써도 되는지 정해서 추가하세요`,
    );
  }
});

test("import는 허용된 층만 가리킨다", () => {
  const violations: string[] = [];
  for (const file of sourceFiles(SRC)) {
    const layer = layerOf(file);
    const allowed = new Set([layer, ...(ALLOWED[layer] ?? []), ...ANY_LAYER]);
    const text = readFileSync(file, "utf8");
    for (const match of text.matchAll(IMPORT)) {
      const target = layerOf(resolve(dirname(file), match[1]));
      if (target !== "." && !allowed.has(target)) {
        violations.push(
          `${relative(SRC, file)} → ${match[1]} (${layer}/가 ${target}/를 가져다 쓰면 안 된다)`,
        );
      }
    }
  }
  assert.deepEqual(violations, []);
});

test("api 바깥에서는 api/index.ts(`../api`)만 가져다 쓴다", () => {
  const violations: string[] = [];
  for (const file of sourceFiles(SRC)) {
    if (layerOf(file) === "api") {
      continue;
    }
    for (const match of readFileSync(file, "utf8").matchAll(IMPORT)) {
      const target = resolve(dirname(file), match[1]);
      const inside = relative(join(SRC, "api"), target);
      if (!inside.startsWith("..") && inside !== "") {
        violations.push(`${relative(SRC, file)} → ${match[1]}`);
      }
    }
  }
  assert.deepEqual(violations, []);
});
