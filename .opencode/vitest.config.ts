import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    globals: true,
    environment: "node",
    include: ["tests/**/*.test.ts"],
    typecheck: {
      enabled: true,
      tsconfig: "./tsconfig.json",
    },
    coverage: {
      provider: "v8",
      include: ["plugins/quality-gate.ts", "plugins/pxcli-quality.ts"],
      exclude: [],
      thresholds: {
        lines: 85,
        statements: 85,
        functions: 85,
        branches: 85,
        perFile: true,
      },
    },
  },
});
