import path from "node:path";

import { defineConfig } from "vitest/config";

export default defineConfig({
  // React 19's automatic JSX runtime: no React import needed in each file, and no extra plugin.
  oxc: { jsx: { runtime: "automatic" } },
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "src") }, // the same "@/..." paths as tsconfig
  },
  test: {
    environment: "jsdom", // a simulated browser DOM, so components render without a real browser
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // e2e/ belongs to Playwright, which drives a real browser - not Vitest's.
  },
});
