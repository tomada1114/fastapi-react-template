import { fireEvent, screen, waitFor, within } from "@testing-library/react";
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

    fireEvent.click(await screen.findByRole("button", { name: "Complete buy milk" }));

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

      fireEvent.click(await screen.findByRole("button", { name: "Delete buy milk" }));

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
      fireEvent.click(
        await screen.findByRole("button", { name: `${action} buy milk` }),
      );
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

      fireEvent.click(
        await screen.findByRole("button", { name: `${action} buy milk` }),
      );

      expect(await screen.findByRole("status")).toHaveTextContent(
        "That to-do no longer exists. The list has been refreshed.",
      );
      await screen.findByText("No to-dos yet. Add one above.");
      expect(state.gets).toBe(2);
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    },
  );

  it.each(
    actions.flatMap((action) =>
      ["server", "network"].map((failure) => ({ action, failure })),
    ),
  )(
    "shows the row error and re-enables controls after $action $failure failure",
    async ({ action, failure }) => {
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

      fireEvent.click(
        await screen.findByRole("button", { name: `${action} buy milk` }),
      );

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
