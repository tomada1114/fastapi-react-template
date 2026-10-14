import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import type {
  ProblemDetails,
  TodoPageResponse,
  TodoResponse,
} from "../../../src/api/generated/types.gen";
import { TODO_PAGE_SIZE, TodosScreen } from "../../../src/features/todos";
import { deferred, renderWithQuery, todo } from "../../msw/helpers";
import { server } from "../../msw/server";

describe("TodosScreen", () => {
  it("shows loading, then the first page in server order with no initial cursor", async () => {
    const gate = deferred();
    const requests: URL[] = [];
    server.use(
      http.get("/api/todos", async ({ request }) => {
        requests.push(new URL(request.url));
        await gate.promise;
        return HttpResponse.json<TodoPageResponse>({
          items: [
            todo("buy milk"),
            todo("buy bread", "0199c1f0-0000-7000-8000-000000000002"),
          ],
          next_cursor: "another-page",
        });
      }),
    );
    try {
      renderWithQuery(<TodosScreen />);
      expect(screen.getByRole("status")).toHaveTextContent("Loading to-dos…");
      gate.release();

      const list = await screen.findByRole("list", { name: "To-dos" });
      expect(
        within(list)
          .getAllByRole("listitem")
          .map((item) => within(item).getByText(/^buy /).textContent),
      ).toEqual(["buy milk", "buy bread"]);
      expect(screen.getByRole("status")).toBeEmptyDOMElement();
      expect(screen.getByRole("heading", { name: "To-dos" })).toHaveAttribute(
        "tabindex",
        "-1",
      );
      expect(requests).toHaveLength(1);
      expect(requests[0]?.searchParams.get("limit")).toBe(String(TODO_PAGE_SIZE));
      expect(TODO_PAGE_SIZE).toBe(20);
      expect(requests[0]?.searchParams.has("cursor")).toBe(false);
      expect(screen.getByRole("button", { name: "Load more" })).toBeEnabled();
    } finally {
      gate.release();
    }
  });

  it("shows the empty state", async () => {
    renderWithQuery(<TodosScreen />);

    expect(
      await screen.findByText("No to-dos yet. Add one above."),
    ).toBeInTheDocument();
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });

  it("re-requests a failed list when Try again is clicked", async () => {
    const user = userEvent.setup();
    let requests = 0;
    const problem: ProblemDetails = {
      type: "about:blank",
      status: 500,
      title: "Internal Server Error",
      detail: "Private diagnostic detail",
      code: "internal_error",
      request_id: "list-500",
    };
    server.use(
      http.get<Record<string, never>, never, TodoPageResponse | ProblemDetails>(
        "/api/todos",
        () => {
          requests += 1;
          return requests === 1
            ? HttpResponse.json<ProblemDetails>(problem, { status: 500 })
            : HttpResponse.json<TodoPageResponse>({
                items: [todo("buy milk")],
                next_cursor: null,
              });
        },
      ),
    );
    renderWithQuery(<TodosScreen />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Something went wrong on our side. Try again.",
    );
    expect(screen.queryByText(problem.detail ?? "")).not.toBeInTheDocument();
    expect(requests).toBe(1);

    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("listitem")).toHaveTextContent("buy milk");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(requests).toBe(2);
  });

  it("shows a connection message for a network failure", async () => {
    server.use(http.get("/api/todos", () => HttpResponse.error()));

    renderWithQuery(<TodosScreen />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not reach the server. Check your connection and try again.",
    );
  });

  it("appends the next page with its cursor and limit, then hides Load more", async () => {
    const user = userEvent.setup();
    const items = Array.from({ length: 21 }, (_, index) =>
      todo(
        `task ${index + 1}`,
        `0199c1f0-0000-7000-8000-${String(index + 1).padStart(12, "0")}`,
      ),
    );
    const requests: URL[] = [];
    server.use(
      http.get("/api/todos", ({ request }) => {
        const url = new URL(request.url);
        requests.push(url);
        return HttpResponse.json<TodoPageResponse>(
          url.searchParams.has("cursor")
            ? { items: items.slice(20), next_cursor: null }
            : { items: items.slice(0, 20), next_cursor: "c1" },
        );
      }),
    );
    renderWithQuery(<TodosScreen />);
    const button = await screen.findByRole("button", { name: "Load more" });
    expect(screen.getAllByRole("listitem")).toHaveLength(20);

    await user.click(button);

    await screen.findByText("task 21");
    expect(
      screen
        .getAllByRole("listitem")
        .map((row) => within(row).getByText(/^task /).textContent),
    ).toEqual(items.map((item) => item.title));
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
    expect(
      requests.map((url) => [
        url.searchParams.get("cursor"),
        url.searchParams.get("limit"),
      ]),
    ).toEqual([
      [null, "20"],
      ["c1", "20"],
    ]);
  });

  it("disables Load more while its request is pending", async () => {
    const user = userEvent.setup();
    const gate = deferred();
    const entered = deferred();
    server.use(
      http.get("/api/todos", async ({ request }) => {
        if (!new URL(request.url).searchParams.has("cursor")) {
          return HttpResponse.json<TodoPageResponse>({
            items: [todo("first")],
            next_cursor: "c1",
          });
        }
        entered.release();
        await gate.promise;
        return HttpResponse.json<TodoPageResponse>({
          items: [todo("second", "0199c1f0-0000-7000-8000-000000000002")],
          next_cursor: null,
        });
      }),
    );
    try {
      renderWithQuery(<TodosScreen />);
      await user.click(await screen.findByRole("button", { name: "Load more" }));
      await entered.promise;

      expect(
        await screen.findByRole("button", { name: "Loading more…" }),
      ).toBeDisabled();
      expect(screen.getByText("first")).toBeInTheDocument();
      gate.release();
      await screen.findByText("second");
    } finally {
      gate.release();
    }
  });

  it.each(["server", "network"])(
    "keeps loaded rows and retries a %s next-page error",
    async (failure) => {
      const user = userEvent.setup();
      let nextRequests = 0;
      const problem: ProblemDetails = {
        type: "about:blank",
        status: 500,
        title: "Internal Server Error",
        code: "internal_error",
        detail: "Private diagnostic detail",
        request_id: "page-error",
      };
      server.use(
        http.get<Record<string, never>, never, TodoPageResponse | ProblemDetails>(
          "/api/todos",
          ({ request }) => {
            if (!new URL(request.url).searchParams.has("cursor")) {
              return HttpResponse.json<TodoPageResponse>({
                items: [todo("first")],
                next_cursor: "c1",
              });
            }
            nextRequests += 1;
            if (nextRequests === 1)
              return failure === "network"
                ? HttpResponse.error()
                : HttpResponse.json<ProblemDetails>(problem, { status: 500 });
            return HttpResponse.json<TodoPageResponse>({
              items: [todo("second", "0199c1f0-0000-7000-8000-000000000002")],
              next_cursor: null,
            });
          },
        ),
      );
      renderWithQuery(<TodosScreen />);
      await user.click(await screen.findByRole("button", { name: "Load more" }));

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(
        failure === "network"
          ? "Could not reach the server. Check your connection and try again."
          : "Something went wrong on our side. Try again.",
      );
      expect(screen.getByText("first")).toBeInTheDocument();
      const button = screen.getByRole("button", { name: "Load more" });
      expect(button).toBeEnabled();
      expect(
        button.compareDocumentPosition(alert) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();

      await user.click(button);

      await screen.findByText("second");
      expect(nextRequests).toBe(2);
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    },
  );

  it("has no Load more at exactly 20 terminal items", async () => {
    const items = Array.from({ length: 20 }, (_, index) =>
      todo(
        `task ${index + 1}`,
        `0199c1f0-0000-7000-8000-${String(index + 1).padStart(12, "0")}`,
      ),
    );
    server.use(
      http.get("/api/todos", () =>
        HttpResponse.json<TodoPageResponse>({ items, next_cursor: null }),
      ),
    );
    renderWithQuery(<TodosScreen />);

    await screen.findByText("task 20");

    expect(screen.getAllByRole("listitem")).toHaveLength(20);
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("focuses the heading when the last loaded page empties and stops refetching", async () => {
    const user = userEvent.setup();
    const items = Array.from({ length: 21 }, (_, index) =>
      todo(
        `task ${index + 1}`,
        `0199c1f0-0000-7000-8000-${String(index + 1).padStart(12, "0")}`,
      ),
    );
    let removed = false;
    let gets = 0;
    server.use(
      http.get("/api/todos", ({ request }) => {
        gets += 1;
        const next = new URL(request.url).searchParams.has("cursor");
        return HttpResponse.json<TodoPageResponse>({
          items: removed ? [] : next ? items.slice(20) : items.slice(0, 20),
          next_cursor: removed || next ? null : "c1",
        });
      }),
      http.delete("/api/todos/:todoId", () => {
        // Other tabs have removed the remaining items when this final delete lands.
        removed = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderWithQuery(<TodosScreen />);
    await user.click(await screen.findByRole("button", { name: "Load more" }));
    await user.click(await screen.findByRole("button", { name: "Delete task 21" }));

    await screen.findByText("No to-dos yet. Add one above.");
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    expect(screen.getByRole("heading", { name: "To-dos" })).toHaveFocus();
    expect(gets).toBe(3);
  });

  it("recomputes each loaded cursor after page-two deletion shifts the boundary", async () => {
    const user = userEvent.setup();
    let items: TodoResponse[] = Array.from({ length: 23 }, (_, index) =>
      todo(
        `task ${index + 1}`,
        `0199c1f0-0000-7000-8000-${String(index + 1).padStart(12, "0")}`,
      ),
    );
    const cursors: Array<string | null> = [];
    server.use(
      http.get("/api/todos", ({ request }) => {
        const cursor = new URL(request.url).searchParams.get("cursor");
        cursors.push(cursor);
        const start =
          cursor === null ? 0 : items.findIndex((item) => item.id === cursor) + 1;
        const page = items.slice(start, start + 20);
        return HttpResponse.json<TodoPageResponse>({
          items: page,
          next_cursor: start + 20 < items.length ? (page.at(-1)?.id ?? null) : null,
        });
      }),
      http.delete<{ todoId: string }>("/api/todos/:todoId", ({ params }) => {
        // Another tab removes an earlier item while this page-two delete succeeds.
        items = items.filter(
          (item) => item.id !== params.todoId && item.title !== "task 5",
        );
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const oldCursor = items[19]?.id;
    renderWithQuery(<TodosScreen />);
    await user.click(await screen.findByRole("button", { name: "Load more" }));
    await screen.findByText("task 23");

    await user.click(screen.getByRole("button", { name: "Delete task 21" }));

    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(21));
    expect(screen.queryByText("task 21")).not.toBeInTheDocument();
    expect(screen.queryByText("task 5")).not.toBeInTheDocument();
    for (const item of items)
      expect(
        screen.getAllByRole("button", { name: `Delete ${item.title}` }),
      ).toHaveLength(1);
    expect(cursors).toEqual([null, oldCursor, null, items[19]?.id]);
    expect(screen.getByRole("heading", { name: "To-dos" })).toHaveFocus();
  });
});
