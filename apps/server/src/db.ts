/**
 * 서버 코드가 쓰는 D1의 작은 부분집합. Cloudflare의 `D1Database`가 이 모양을 만족하고, 테스트는 같은 모양의
 * SQLite 어댑터를 넣어 실제 SQL을 검증한다(Workers 밖에서도 돌 수 있게).
 */
export interface Statement {
  bind(...values: unknown[]): Statement;
  run(): Promise<unknown>;
  first<T>(): Promise<T | null>;
  all<T>(): Promise<{ results: T[] }>;
}

export interface Db {
  prepare(sql: string): Statement;
  /** 문장들을 한 트랜잭션으로 실행한다(하나라도 실패하면 모두 되돌린다). */
  batch(statements: Statement[]): Promise<unknown[]>;
}
