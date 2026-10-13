import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll } from "vitest";
import { client } from "../../src/api/generated/client.gen";
import type { TodoPageResponse } from "../../src/api/generated/types.gen";

// jsdom's fetch and Request are Node's: relative Request URLs need an origin.
// Production keeps the generated client's relative base URL.
client.setConfig({ baseUrl: window.location.origin });
export const server = setupServer(
  http.get("/api/todos", () =>
    HttpResponse.json<TodoPageResponse>({ items: [], next_cursor: null }),
  ),
);

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
