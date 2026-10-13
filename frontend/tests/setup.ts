import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Testing Library cleans up on its own only when the runner injects a global
// afterEach, which Vitest does not without `globals: true`.
afterEach(cleanup);
