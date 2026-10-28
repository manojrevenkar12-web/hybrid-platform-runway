import { defineConfig, devices } from "@playwright/test";

// Runs the console against the real runway API (demo mode: the fictional estate and a fake
// Proxmox that fails on purpose), as CI does.
export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  retries: 0,
  workers: 1,
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  use: { baseURL: "http://localhost:5173", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "phone", use: { ...devices["Pixel 7"] } },
  ],
  webServer: [
    {
      command: "../.venv/bin/runway serve --port 8070",
      url: "http://localhost:8070/healthz",
      reuseExistingServer: !process.env.CI,
      env: { RUNWAY_PLAN_START: "2026-11-16T00:00:00+01:00", RUNWAY_DEMO_IMPORT_FAILURES: "0.1" },
    },
    { command: "npm run preview", url: "http://localhost:5173", reuseExistingServer: !process.env.CI },
  ],
});
