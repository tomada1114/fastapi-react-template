import { MutationObserver, QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import {
  deleteTodoMutation,
  listTodosInfiniteOptions,
  listTodosOptions,
} from "../src/api/generated/@tanstack/react-query.gen";
import { createClient, createConfig } from "../src/api/generated/client";
import { client } from "../src/api/generated/client.gen";
import { deleteTodo } from "../src/api/generated/sdk.gen";

describe("generated API contract", () => {
  it("keeps relative requests and stable list operation keys", () => {
    expect(client.getConfig().baseUrl || "").toBe("");
    expect(listTodosOptions().queryKey[0]._id).toBe("listTodos");
  });

  it("keeps an explicit empty base URL instead of the client's default host", () => {
    const testClient = createClient(createConfig({ baseUrl: "https://other.example" }));

    const options = { client: testClient, baseUrl: "" };

    expect(listTodosOptions(options).queryKey[0].baseUrl).toBe("");
    expect(listTodosInfiniteOptions(options).queryKey[0].baseUrl).toBe("");
    expect(listTodosOptions({ client: testClient }).queryKey[0].baseUrl).toBe(
      "https://other.example",
    );
  });

  it.each(["auto", "json", "text"] as const)(
    "returns undefined for a 204 parsed as %s",
    async (parseAs) => {
      const testClient = createClient(
        createConfig({
          baseUrl: "http://localhost",
          fetch: async () => new Response(null, { status: 204 }),
        }),
      );

      const result = await deleteTodo({
        client: testClient,
        path: { todo_id: "0199c1f0-0000-7000-8000-000000000001" },
        parseAs,
        throwOnError: true,
      });

      expect(result.response.status).toBe(204);
      expect(result.data).toBeUndefined();
    },
  );

  it("passes undefined to a successful delete mutation callback", async () => {
    const testClient = createClient(
      createConfig({
        baseUrl: "http://localhost",
        fetch: async () => new Response(null, { status: 204 }),
      }),
    );
    const queryClient = new QueryClient();
    let successData: unknown = "not called";
    const mutation = new MutationObserver(queryClient, {
      ...deleteTodoMutation({ client: testClient }),
      onSuccess: (data) => {
        successData = data;
      },
    });

    await mutation.mutate({
      path: { todo_id: "0199c1f0-0000-7000-8000-000000000001" },
    });

    expect(successData).toBeUndefined();
    queryClient.clear();
  });

  it.each([
    { parseAs: "json", expected: {} },
    { parseAs: "text", expected: "" },
  ] as const)(
    "keeps other empty responses parsed as $parseAs",
    async ({ parseAs, expected }) => {
      const testClient = createClient(
        createConfig({
          baseUrl: "http://localhost",
          fetch: async () => new Response(null, { headers: { "Content-Length": "0" } }),
        }),
      );

      const result = await testClient.get({ url: "/empty", parseAs });

      expect(result.data).toEqual(expected);
    },
  );

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
