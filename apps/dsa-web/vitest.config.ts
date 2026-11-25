import { configDefaults, defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/setupTests.ts',
    // Leaves room for several 5 s findBy/waitFor waits in one test.
    testTimeout: 20000,
    exclude: [...configDefaults.exclude, 'e2e/**', 'playwright.config.ts'],
  },
});
