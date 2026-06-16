import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  retries: process.env.CI ? 2 : 0,
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "on-first-retry",
  },
  webServer: {
    command: "npm run dev -- --hostname 127.0.0.1",
    env: {
      BACKEND_INTERNAL_URL: "http://127.0.0.1:8000",
      NEXT_PUBLIC_BACKEND_URL: "http://127.0.0.1:8000",
      NEXT_PUBLIC_SITE_URL: "http://127.0.0.1:3000",
    },
    url: "http://127.0.0.1:3000",
    reuseExistingServer: !process.env.CI,
  },
});
