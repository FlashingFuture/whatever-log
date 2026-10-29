import { mountUsagePage } from "./components/UsagePage";
import { injectStyle } from "./styles/injectStyle";
import { theme } from "./theme";

injectStyle(
  "global",
  `
  body {
    font: 16px/1.5 system-ui, "Segoe UI", Roboto, sans-serif;
    margin: 2rem;
    background: ${theme.colors.background};
    color: ${theme.colors.text};
  }
`,
);

const app = document.querySelector("#app");
if (app) {
  mountUsagePage(app);
}
