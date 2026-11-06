import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";

const MIGRATION = new URL("../../migrations/0001_init.sql", import.meta.url);

/**
 * 테스트용 D1. 실제 마이그레이션 SQL을 메모리 SQLite에 적용하고, 서버 코드가 쓰는 D1 모양(prepare·bind·
 * run·first·all·batch)을 어댑터로 맞춘다 — 서버의 SQL을 모킹 없이 실제로 실행해 본다.
 */
export function createFakeD1() {
  const sqlite = new DatabaseSync(":memory:");
  sqlite.exec("PRAGMA foreign_keys = ON");
  sqlite.exec(readFileSync(MIGRATION, "utf-8"));

  function statement(sql: string, values: unknown[] = []) {
    return {
      bind: (...next: unknown[]) => statement(sql, next),
      async run() {
        sqlite.prepare(sql).run(...(values as never[]));
        return {};
      },
      async first() {
        return sqlite.prepare(sql).get(...(values as never[])) ?? null;
      },
      async all() {
        return { results: sqlite.prepare(sql).all(...(values as never[])) };
      },
    };
  }

  const db = {
    prepare: (sql: string) => statement(sql),
    async batch(statements: { run(): Promise<unknown> }[]) {
      sqlite.exec("BEGIN");
      try {
        for (const item of statements) {
          await item.run();
        }
        sqlite.exec("COMMIT");
      } catch (error) {
        sqlite.exec("ROLLBACK");
        throw error;
      }
      return [];
    },
  };
  return { sqlite, db };
}
