import { defineConfig, devices } from "@playwright/test";
import {
  e2eRun,
  REPOSITORY_ROOT,
  settingsEnvironment,
  shellQuote,
  variable,
} from "./environment.ts";

// `just e2e` sets up the run: it clears every inherited MY_APP_* variable, makes
// a throwaway SQLite file, picks two free ports, and checks both are free again
// once this exits. Without it, this throws rather than touch the developer's
// database or servers.
const run = e2eRun();
const just = shellQuote(run.just);
const isCi = variable("CI") !== undefined;

export default defineConfig({
  testDir: "tests",
  outputDir: "test-results",
  // One serial flow: a flaky failure fails the run instead of hiding behind a retry.
  workers: 1,
  retries: 0,
  forbidOnly: isCi,
  reporter: isCi ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${run.webPort}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // Never a server that is already running: a taken port fails the run.
  webServer: [
    {
      name: "API",
      // Migrations run explicitly, never at startup; then `just backend dev`'s
      // uvicorn command without --reload, on this run's port.
      command: [
        `${just} backend db-upgrade ${shellQuote(run.databaseUrl)}`,
        "&& uv run --locked --directory backend uvicorn my_app.api.app:create_app",
        `--factory --no-access-log --host 127.0.0.1 --port ${run.apiPort}`,
      ].join(" "),
      cwd: REPOSITORY_ROOT,
      env: settingsEnvironment(run.databaseUrl),
      url: `http://127.0.0.1:${run.apiPort}/healthz`,
      reuseExistingServer: false,
      timeout: 120_000,
      gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      name: "Web",
      // The production build, served by Vite's preview server, whose proxy
      // (vite.config.ts) sends /api and /healthz to this run's API.
      command: [
        `${just} frontend build`,
        "&& pnpm --dir frontend exec vite preview",
        `--host 127.0.0.1 --port ${run.webPort} --strictPort`,
      ].join(" "),
      cwd: REPOSITORY_ROOT,
      env: { MY_APP_API_PORT: String(run.apiPort) },
      url: `http://127.0.0.1:${run.webPort}/`,
      reuseExistingServer: false,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
