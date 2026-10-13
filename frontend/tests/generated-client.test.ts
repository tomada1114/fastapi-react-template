import { describe, expect, it } from "vitest";
import { listTodosOptions } from "../src/api/generated/@tanstack/react-query.gen";
import { client } from "../src/api/generated/client.gen";

describe("generated API contract", () => {
  it("keeps relative requests and stable list operation keys", () => {
    expect(client.getConfig().baseUrl || "").toBe("");
    expect(listTodosOptions().queryKey[0]._id).toBe("listTodos");
  });
});
