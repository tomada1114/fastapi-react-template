import { defineConfig, mergeConfig } from "vitest/config";
import viteConfig from "./vite.config.ts";

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "jsdom",
      // Gives window.location an origin. It does not make a relative fetch
      // resolve: under jsdom, fetch and Request come from Node.
      environmentOptions: { jsdom: { url: "http://localhost:5173/" } },
      setupFiles: ["./tests/setup.ts"],
      include: ["tests/**/*.test.{ts,tsx}"],
      restoreMocks: true,
      unstubEnvs: true,
      unstubGlobals: true,
      allowOnly: false,
      coverage: {
        provider: "v8",
        reporter: ["text", "lcov"],
        reportsDirectory: "coverage",
        include: ["src/**/*.{ts,tsx}"],
        // Generated code, excluded now so later issues never edit this list.
        exclude: ["src/api/generated/**", "src/routeTree.gen.ts"],
        thresholds: { lines: 80, functions: 80, statements: 80, branches: 80 },
      },
    },
  }),
);
