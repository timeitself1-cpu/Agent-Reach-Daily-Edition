const {defineConfig} = require('@playwright/test');
module.exports = defineConfig({
  testDir: './tests/browser',
  workers: 2,
  use: {
    baseURL: 'http://127.0.0.1:8874',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? {executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH} : {},
  },
  webServer: {command: 'node tests/browser/server.cjs', url: 'http://127.0.0.1:8874', reuseExistingServer: false},
});
