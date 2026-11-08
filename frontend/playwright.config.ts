import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  workers: 1,
  retries: 0,
  timeout: 45000,
  use: {
    baseURL: "http://127.0.0.1:5173",
    viewport: { width: 1440, height: 900 },
    launchOptions: {
      executablePath:
        process.env.ATL_BROWSER_PATH ||
        "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  reporter: [
    ["list"],
    ["json", { outputFile: "../docs/evidence/final-playwright-results.json" }],
  ],
});
