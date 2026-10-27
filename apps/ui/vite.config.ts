import { defineConfig } from "vite";

export default defineConfig({
  // apps/desktop이 --dev일 때 이 포트를 고정 문자열로 가리킨다. 포트가 막혀
  // 있으면 Vite가 조용히 다음 포트로 옮기지 않고 바로 실패하게 해서, 셸이
  // 엉뚱한(또는 존재하지 않는) 포트를 열어버리는 걸 막는다.
  server: { port: 5173, strictPort: true },
  // apps/desktop이 dist를 로컬 HTTP 서버로 서빙하므로 꼭 필요하진 않지만,
  // 상대 경로를 쓰면 서빙 경로가 바뀌어도(서브패스 등) 안전하다.
  base: "./",
});
