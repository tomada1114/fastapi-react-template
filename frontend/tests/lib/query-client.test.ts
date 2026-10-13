import { describe, expect, test } from "vitest";
import { createQueryClient, shouldRetry } from "../../src/lib/query-client";

describe("shouldRetry", () => {
  test.each([400, 404, 422, 499])("a %i error is never retried", (status) => {
    expect(shouldRetry(0, { status })).toBe(false);
  });

  test.each([
    { name: "a 500 error", error: { status: 500 } },
    { name: "a 399 error", error: { status: 399 } },
    { name: "a network error without status", error: new TypeError("fetch failed") },
    { name: "a non-numeric status", error: { status: "404" } },
    { name: "a non-object error", error: "boom" },
    { name: "a null error", error: null },
  ])("$name is retried after the first failure", ({ error }) => {
    expect(shouldRetry(0, error)).toBe(true);
  });

  test.each([
    { name: "a 500 error", error: { status: 500 } },
    { name: "a network error without status", error: new TypeError("fetch failed") },
    { name: "a 404 error", error: { status: 404 } },
  ])("$name is not retried a second time", ({ error }) => {
    expect(shouldRetry(1, error)).toBe(false);
  });
});

describe("createQueryClient", () => {
  test("queries retry through shouldRetry", () => {
    const client = createQueryClient();

    expect(client.getDefaultOptions().queries?.retry).toBe(shouldRetry);
  });

  test("mutations keep TanStack's default of no retry", () => {
    const client = createQueryClient();

    expect(client.getDefaultOptions().mutations?.retry).toBeUndefined();
  });

  test("each call returns a new client", () => {
    expect(createQueryClient()).not.toBe(createQueryClient());
  });
});
