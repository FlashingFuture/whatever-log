import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import ts from "typescript";

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

/**
 * 파일이 실제로 가져오는 상대 경로들(import·export from·import()·import type). TypeScript가 스스로
 * 쓰는 import 스캐너(preProcessFile)로 읽어서 주석과 문자열 속의 예시는 세지 않고, 여러 줄 import도
 * 정확히 잡는다 — 정규식은 둘 다 틀리기 쉽다.
 */
export function relativeImports(sourceText: string): string[] {
  return ts
    .preProcessFile(sourceText, true, true)
    .importedFiles.map((file) => file.fileName)
    .filter((specifier) => specifier.startsWith("."));
}

function importsOf(file: string): string[] {
  return relativeImports(readFileSync(file, "utf8"));
}

test("relativeImports는 실제 import만 센다(주석·문자열 속 예시는 제외, 여러 줄은 포함)", () => {
  const source = `
    // import "../pages/UsagePage";
    /* import { x } from "../layouts/Layouts"; */
    const example = 'import "../pages/Fake"';
    const text = \`from "../pages/Template"\`;
    import { a } from "./a";
    import type { B } from "../b";
    import {
      c,
      d,
    } from "../../c";
    import "./side-effect.css";
    export { e } from "./e";
    const lazy = () => import("./lazy");
    import pkg from "typescript";
  `;

  assert.deepEqual(relativeImports(source).sort(), [
    "../../c",
    "../b",
    "./a",
    "./e",
    "./lazy",
    "./side-effect.css",
  ]);
});

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
    for (const specifier of importsOf(file)) {
      // 루트의 파일(main.ts)도 층이다("."): 아래 층이 진입점을 가져다 쓰면 위반이다.
      const target = layerOf(resolve(dirname(file), specifier));
      if (!allowed.has(target)) {
        violations.push(
          `${relative(SRC, file)} → ${specifier} (${layer}/가 ${target}/를 가져다 쓰면 안 된다)`,
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
    for (const specifier of importsOf(file)) {
      const target = resolve(dirname(file), specifier);
      const inside = relative(join(SRC, "api"), target);
      if (!inside.startsWith("..") && inside !== "") {
        violations.push(`${relative(SRC, file)} → ${specifier}`);
      }
    }
  }
  assert.deepEqual(violations, []);
});
