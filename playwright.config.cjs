// @ts-check
const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "e2e",
  timeout: 45_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: "http://127.0.0.1:8765",
    locale: "ru-RU",
  },
  webServer: {
    command: "python3 server.py",
    url: "http://127.0.0.1:8765/api/health",
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
    env: {
      ...process.env,
      PORT: "8765",
      BIND_HOST: "127.0.0.1",
      ADMIN_PASSWORD: "e2e-pass",
      ADMIN_SECRET: "e2e-secret-fixed",
      CRM_BACKUP_ON_START: "0",
    },
  },
});
