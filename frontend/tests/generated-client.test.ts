import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import {
  listTodosInfiniteOptions,
  listTodosOptions,
} from "../src/api/generated/@tanstack/react-query.gen";
import { createClient, createConfig } from "../src/api/generated/client";
import { client } from "../src/api/generated/client.gen";

describe("generated API contract", () => {
  it("keeps relative requests and stable list operation keys", () => {
    expect(client.getConfig().baseUrl || "").toBe("");
    expect(listTodosOptions().queryKey[0]._id).toBe("listTodos");
  });

  it.each([null, {}, "next-page"])(
    "requests a page with the supported parameter %j",
    async (pageParam) => {
      const requests: URL[] = [];
      const testClient = createClient(
        createConfig({
          baseUrl: "http://localhost",
          fetch: async (request) => {
            requests.push(
              new URL(request instanceof Request ? request.url : String(request)),
            );
            return Response.json({ items: [], next_cursor: null });
          },
        }),
      );
      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });

      const result = await queryClient.fetchInfiniteQuery({
        ...listTodosInfiniteOptions({ client: testClient }),
        initialPageParam: pageParam,
        getNextPageParam: () => undefined,
      });

      expect(result.pages).toEqual([{ items: [], next_cursor: null }]);
      expect(requests).toHaveLength(1);
      expect(requests[0]?.pathname).toBe("/api/todos");
      expect(requests[0]?.searchParams.get("cursor")).toBe(
        typeof pageParam === "string" ? pageParam : null,
      );
      queryClient.clear();
    },
  );
});
