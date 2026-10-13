import { screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

beforeEach(() => {
  // main.tsx runs on import, so each test imports a fresh copy.
  vi.resetModules();
});

afterEach(() => {
  // cleanup() unmounts only what render() mounted, not main.tsx's own root.
  document.body.innerHTML = "";
});

test("main renders App into #root", async () => {
  const root = document.createElement("div");
  root.id = "root";
  document.body.append(root);

  await import("../src/main");

  expect(await screen.findByRole("heading", { name: "My App" })).toBeInTheDocument();
});

test("main without #root throws naming the element", async () => {
  await expect(import("../src/main")).rejects.toThrow("root element #root not found");
});
