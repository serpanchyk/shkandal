import { defineConfig } from "@playwright/test";

const backendUrl = process.env.E2E_BACKEND_URL ?? "http://localhost:18001";
const frontendUrl = process.env.E2E_FRONTEND_URL ?? "http://localhost:13001";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  retries: process.env.CI ? 2 : 0,
  use: {
    baseURL: frontendUrl,
    trace: "on-first-retry",
  },
  webServer: {
    command: "npm run dev -- --hostname 127.0.0.1 --port 13001",
    env: {
      BACKEND_INTERNAL_URL: backendUrl,
      NEXT_PUBLIC_BACKEND_URL: backendUrl,
      NEXT_PUBLIC_SITE_URL: frontendUrl,
    },
    url: frontendUrl,
    reuseExistingServer: false,
  },
});
