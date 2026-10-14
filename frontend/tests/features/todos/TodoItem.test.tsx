import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import type {
  ProblemDetails,
  TodoPageResponse,
  TodoResponse,
} from "../../../src/api/generated/types.gen";
import { TodosScreen } from "../../../src/features/todos";
import { deferred, renderWithQuery, todo } from "../../msw/helpers";
import { server } from "../../msw/server";

const secondId = "0199c1f0-0000-7000-8000-000000000002";
const actions = ["Complete", "Delete"] as const;

function serve(items: TodoResponse[]) {
  const state = { items, gets: 0 };
  server.use(
    http.get("/api/todos", () => {
      state.gets += 1;
      return HttpResponse.json<TodoPageResponse>({
        items: state.items,
        next_cursor: null,
      });
    }),
  );
  return state;
}

// The first render waits on the initial list request, which on a machine busy with
// the full `just verify` has taken longer than Testing Library's default 1000 ms
// (#120). Every row action first waits here for the loaded row, with room for that
// load (kept under Vitest's 5000 ms test timeout), so no test depends on the
// first render landing within 1000 ms.
const firstRenderTimeout = 4000;

function loadedRow(name: string) {
  return screen.findByRole("button", { name }, { timeout: firstRenderTimeout });
}

function problem(status: number): ProblemDetails {
  return {
    type: "about:blank",
    title: status === 404 ? "Not Found" : "Internal Server Error",
    status,
    code: status === 404 ? "todo_not_found" : "internal_error",
    detail: "Private diagnostic detail",
    request_id: "row-error",
  };
}

describe("TodoItem", () => {
  it("completes through the API and renders the refetched completed row", async () => {
    const user = userEvent.setup();
    const item = todo("buy milk");
    const state = serve([item]);
    const paths: string[] = [];
    server.use(
      http.post("/api/todos/:todoId/complete", ({ request }) => {
        paths.push(new URL(request.url).pathname);
        // The same response also covers another tab already completing the item.
        const completed = { ...item, completed: true };
        state.items = [completed];
        return HttpResponse.json<TodoResponse>(completed);
      }),
    );
    renderWithQuery(<TodosScreen />);

    await user.click(await loadedRow("Complete buy milk"));

    expect(await screen.findByText("Completed")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Complete buy milk" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("buy milk")).toHaveClass("line-through");
    expect(paths).toEqual([`/api/todos/${item.id}/complete`]);
    expect(state.gets).toBe(2);
  });

  it.each([false, true])(
    "deletes with 204 and focuses the heading, empty=%s",
    async (last) => {
      const user = userEvent.setup();
      const item = todo("buy milk");
      const remaining = todo("buy bread", secondId);
      const state = serve(last ? [item] : [item, remaining]);
      const paths: string[] = [];
      server.use(
        http.delete("/api/todos/:todoId", ({ request }) => {
          paths.push(new URL(request.url).pathname);
          state.items = last ? [] : [remaining];
          return new HttpResponse(null, { status: 204 });
        }),
      );
      renderWithQuery(<TodosScreen />);

      await user.click(await loadedRow("Delete buy milk"));

      await waitFor(() =>
        expect(screen.queryByText("buy milk")).not.toBeInTheDocument(),
      );
      expect(screen.getByRole("heading", { name: "To-dos" })).toHaveFocus();
      expect(paths).toEqual([`/api/todos/${item.id}`]);
      expect(state.gets).toBe(2);
      if (last)
        expect(screen.getByText("No to-dos yet. Add one above.")).toBeInTheDocument();
      else expect(screen.getByText("buy bread")).toBeInTheDocument();
    },
  );

  it.each(actions)("disables only that row while %s is pending", async (action) => {
    const user = userEvent.setup();
    const item = todo("buy milk");
    serve([item, todo("buy bread", secondId)]);
    const entered = deferred();
    const gate = deferred();
    const response = async () => {
      entered.release();
      await gate.promise;
      return action === "Complete"
        ? HttpResponse.json<TodoResponse>({ ...item, completed: true })
        : new HttpResponse(null, { status: 204 });
    };
    server.use(
      action === "Complete"
        ? http.post("/api/todos/:todoId/complete", response)
        : http.delete("/api/todos/:todoId", response),
    );
    try {
      renderWithQuery(<TodosScreen />);
      await user.click(await loadedRow(`${action} buy milk`));
      await entered.promise;

      await waitFor(() => {
        for (const name of actions) {
          expect(
            screen.getByRole("button", { name: `${name} buy milk` }),
          ).toBeDisabled();
          expect(
            screen.getByRole("button", { name: `${name} buy bread` }),
          ).toBeEnabled();
        }
      });
      gate.release();
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Delete buy milk" })).toBeEnabled(),
      );
    } finally {
      gate.release();
    }
  });

  it.each(actions)(
    "announces a stale id and refetches after %s returns 404",
    async (action) => {
      const user = userEvent.setup();
      const state = serve([todo("buy milk")]);
      const response = () => {
        state.items = [];
        return HttpResponse.json<ProblemDetails>(problem(404), { status: 404 });
      };
      server.use(
        action === "Complete"
          ? http.post("/api/todos/:todoId/complete", response)
          : http.delete("/api/todos/:todoId", response),
      );
      renderWithQuery(<TodosScreen />);

      await user.click(await loadedRow(`${action} buy milk`));

      await waitFor(() =>
        expect(screen.getByRole("status")).toHaveTextContent(
          "That to-do no longer exists. The list has been refreshed.",
        ),
      );
      await screen.findByText("No to-dos yet. Add one above.");
      expect(state.gets).toBe(2);
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    },
  );

  it("waits for a successful refetch before announcing a stale id", async () => {
    const user = userEvent.setup();
    const entered = deferred();
    const gate = deferred();
    let gets = 0;
    server.use(
      http.get("/api/todos", async () => {
        gets += 1;
        if (gets === 1)
          return HttpResponse.json<TodoPageResponse>({
            items: [todo("buy milk")],
            next_cursor: null,
          });
        entered.release();
        await gate.promise;
        return HttpResponse.json<TodoPageResponse>({ items: [], next_cursor: null });
      }),
      http.delete("/api/todos/:todoId", () =>
        HttpResponse.json<ProblemDetails>(problem(404), { status: 404 }),
      ),
    );
    try {
      renderWithQuery(<TodosScreen />);
      const button = await loadedRow("Delete buy milk");
      await act(async () => {
        await user.click(button);
        await entered.promise;
      });

      expect(screen.getByRole("status")).toBeEmptyDOMElement();
      gate.release();
      await waitFor(() =>
        expect(screen.getByRole("status")).toHaveTextContent(
          "The list has been refreshed.",
        ),
      );
      expect(gets).toBe(2);
    } finally {
      gate.release();
    }
  });

  it("reports a failed stale-id refetch without claiming the list refreshed", async () => {
    const user = userEvent.setup();
    let gets = 0;
    server.use(
      http.get<Record<string, never>, never, TodoPageResponse | ProblemDetails>(
        "/api/todos",
        () => {
          gets += 1;
          return gets === 1
            ? HttpResponse.json<TodoPageResponse>({
                items: [todo("buy milk")],
                next_cursor: null,
              })
            : HttpResponse.json<ProblemDetails>(problem(500), { status: 500 });
        },
      ),
      http.delete("/api/todos/:todoId", () =>
        HttpResponse.json<ProblemDetails>(problem(404), { status: 404 }),
      ),
    );
    renderWithQuery(<TodosScreen />);
    await user.click(await loadedRow("Delete buy milk"));

    expect(await screen.findByRole("alert")).toHaveTextContent("Request ID: row-error");
    expect(screen.getByText("buy milk")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Delete buy milk" })).toBeEnabled(),
    );
    expect(gets).toBe(2);
  });

  it("clears a stale notice when Load more starts", async () => {
    const user = userEvent.setup();
    let removed = false;
    const entered = deferred();
    const gate = deferred();
    server.use(
      http.get("/api/todos", async ({ request }) => {
        if (new URL(request.url).searchParams.has("cursor")) {
          entered.release();
          await gate.promise;
          return HttpResponse.json<TodoPageResponse>({
            items: [todo("last", secondId)],
            next_cursor: null,
          });
        }
        return HttpResponse.json<TodoPageResponse>({
          items: [todo(removed ? "remaining" : "buy milk")],
          next_cursor: "c1",
        });
      }),
      http.delete("/api/todos/:todoId", () => {
        removed = true;
        return HttpResponse.json<ProblemDetails>(problem(404), { status: 404 });
      }),
    );
    try {
      renderWithQuery(<TodosScreen />);
      await user.click(await loadedRow("Delete buy milk"));
      await waitFor(() =>
        expect(screen.getByRole("status")).toHaveTextContent(
          "The list has been refreshed.",
        ),
      );

      await user.click(screen.getByRole("button", { name: "Load more" }));
      await entered.promise;

      expect(screen.getByRole("status")).toBeEmptyDOMElement();
      gate.release();
      await screen.findByText("last");
      expect(screen.getByRole("status")).toBeEmptyDOMElement();
    } finally {
      gate.release();
    }
  });

  it("announces every stale response and clears the notice for a new action", async () => {
    const user = userEvent.setup();
    const third = todo("third", "0199c1f0-0000-7000-8000-000000000003");
    const state = serve([todo("buy milk"), todo("buy bread", secondId), third]);
    server.use(
      http.delete("/api/todos/:todoId", () => {
        state.items = state.items.slice(1);
        return HttpResponse.json<ProblemDetails>(problem(404), { status: 404 });
      }),
      http.post("/api/todos/:todoId/complete", () => {
        const completed = { ...third, completed: true };
        state.items = [completed];
        return HttpResponse.json<TodoResponse>(completed);
      }),
    );
    const { container } = renderWithQuery(<TodosScreen />);
    await loadedRow("Delete buy milk");
    const message = "That to-do no longer exists. The list has been refreshed.";
    const announcements: string[] = [];
    const observer = new MutationObserver((records) => {
      for (const record of records)
        for (const node of record.addedNodes) {
          if (node.textContent === message) announcements.push(message);
        }
    });
    observer.observe(container, { childList: true, subtree: true });
    try {
      await user.click(screen.getByRole("button", { name: "Delete buy milk" }));
      await waitFor(() =>
        expect(screen.queryByText("buy milk")).not.toBeInTheDocument(),
      );
      await waitFor(() => expect(announcements).toHaveLength(1));

      await user.click(screen.getByRole("button", { name: "Delete buy bread" }));

      await waitFor(() =>
        expect(screen.queryByText("buy bread")).not.toBeInTheDocument(),
      );
      await waitFor(() => expect(announcements).toHaveLength(2));
      expect(screen.getByRole("status")).toHaveTextContent(message);
      await user.click(screen.getByRole("button", { name: "Complete third" }));
      await screen.findByText("Completed");
      expect(screen.queryByText(message)).not.toBeInTheDocument();
      expect(state.gets).toBe(4);
    } finally {
      observer.disconnect();
    }
  });

  it.each(
    actions.flatMap((action) =>
      ["server", "network"].map((failure) => ({ action, failure })),
    ),
  )(
    "shows the row error and re-enables controls after $action $failure failure",
    async ({ action, failure }) => {
      const user = userEvent.setup();
      const state = serve([todo("buy milk"), todo("buy bread", secondId)]);
      const response = () =>
        failure === "network"
          ? HttpResponse.error()
          : HttpResponse.json<ProblemDetails>(problem(500), { status: 500 });
      server.use(
        action === "Complete"
          ? http.post("/api/todos/:todoId/complete", response)
          : http.delete("/api/todos/:todoId", response),
      );
      renderWithQuery(<TodosScreen />);

      await user.click(await loadedRow(`${action} buy milk`));

      const row = screen.getByText("buy milk").closest("li");
      if (!row) throw new Error("The title must belong to its row");
      const alert = await within(row).findByRole("alert");
      expect(alert).toHaveTextContent(
        failure === "network"
          ? "Could not reach the server. Check your connection and try again."
          : "Something went wrong on our side. Try again.",
      );
      if (failure === "server")
        expect(alert).toHaveTextContent("Request ID: row-error");
      expect(alert).not.toHaveTextContent("Private diagnostic detail");
      await waitFor(() =>
        expect(
          screen.getByRole("button", { name: `${action} buy milk` }),
        ).toBeEnabled(),
      );
      for (const name of actions)
        expect(screen.getByRole("button", { name: `${name} buy milk` })).toBeEnabled();
      await waitFor(() => expect(state.gets).toBe(2));
    },
  );
});
