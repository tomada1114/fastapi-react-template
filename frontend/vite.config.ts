import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Plugins live here only; vitest.config.ts merges this file into its own.
export default defineConfig({
  plugins: [react()],
});
