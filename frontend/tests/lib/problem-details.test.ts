import { describe, expect, it } from "vitest";
import { toApiError } from "../../src/lib/problem-details";

describe("toApiError", () => {
  it.each([
    undefined,
    null,
    "plain text",
    new TypeError("fetch failed"),
    422,
    [],
    {},
    { status: "422", title: "Invalid" },
    { status: 422, title: null },
  ])("treats an unrecognized thrown value as unknown: %j", (error) => {
    expect(toApiError(error)).toEqual({ kind: "unknown" });
  });

  it("keeps correctly typed Problem Details members", () => {
    const error = {
      status: 422,
      title: "Unprocessable Content",
      detail: "Invalid title",
      code: "invalid_todo",
      request_id: "request-123",
    };

    expect(toApiError(error)).toEqual({
      kind: "problem",
      status: 422,
      title: "Unprocessable Content",
      detail: "Invalid title",
      code: "invalid_todo",
      requestId: "request-123",
      fieldErrors: {},
    });
  });

  it.each([undefined, null, 7, false, {}])(
    "omits malformed optional members: %j",
    (value) => {
      expect(
        toApiError({
          status: 400,
          title: "Bad Request",
          detail: value,
          code: value,
          request_id: value,
          errors: value,
        }),
      ).toEqual({
        kind: "problem",
        status: 400,
        title: "Bad Request",
        fieldErrors: {},
      });
    },
  );

  it("groups body messages by the last location element and drops malformed entries", () => {
    const error = {
      status: 422,
      title: "Unprocessable Content",
      errors: [
        { loc: ["body", "title"], message: "Required" },
        { loc: ["body", "items", 0, "title"], message: "Too long" },
        { loc: ["body", "items", 1], message: "Invalid item" },
        { loc: ["query", "title"], message: "Not a body field" },
        { loc: [], message: "Missing location" },
        { loc: "title", message: "Wrong location type" },
        { loc: ["body", null], message: "Wrong part type" },
        { loc: ["body", "title"], message: 3 },
        null,
        "invalid entry",
      ],
    };

    expect(toApiError(error)).toEqual({
      kind: "problem",
      status: 422,
      title: "Unprocessable Content",
      fieldErrors: { title: ["Required", "Too long"], "1": ["Invalid item"] },
    });
  });

  it("handles a field named like an object prototype member without crashing", () => {
    const error = toApiError({
      status: 422,
      title: "Invalid",
      errors: [{ loc: ["body", "__proto__"], message: "Field error" }],
    });

    expect(error.kind).toBe("problem");
    if (error.kind === "problem") {
      expect(Object.hasOwn(error.fieldErrors, "__proto__")).toBe(true);
      expect(
        Object.getOwnPropertyDescriptor(error.fieldErrors, "__proto__")?.value,
      ).toEqual(["Field error"]);
    }
  });
});
