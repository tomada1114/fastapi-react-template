import { screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

// On a line of its own: the bootstrap rewrites it to a display name of up to
// 60 characters, which must not push any line past Biome's 88 columns.
const APP_NAME = "My App";

beforeEach(() => {
  // main.tsx runs on import, so each test imports a fresh copy.
  vi.resetModules();
});

afterEach(() => {
  // cleanup() unmounts only what render() mounted, not main.tsx's own root.
  document.body.innerHTML = "";
});

test("main renders the index route through the router into #root", async () => {
  const root = document.createElement("div");
  root.id = "root";
  document.body.append(root);

  await import("../src/main");

  const heading = await screen.findByRole("heading", { name: APP_NAME });
  expect(heading).toBeInTheDocument();
  expect(screen.getByRole("banner")).toHaveTextContent(APP_NAME);
});

test("main without #root throws naming the element", async () => {
  await expect(import("../src/main")).rejects.toThrow("root element #root not found");
});
