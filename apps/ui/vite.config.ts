import { defineConfig } from "vite";

export default defineConfig({
  // pywebview가 빌드 결과(dist/index.html)를 file://로 직접 열기 때문에,
  // 절대 경로(/assets/...)가 아니라 상대 경로로 에셋을 참조해야 한다.
  base: "./",
});
