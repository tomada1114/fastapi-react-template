import { fireEvent, screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import type {
  ProblemDetails,
  TodoPageResponse,
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
          .map((item) => item.textContent),
      ).toEqual(["buy milk", "buy bread"]);
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "To-dos" })).toHaveAttribute(
        "tabindex",
        "-1",
      );
      expect(requests).toHaveLength(1);
      expect(requests[0]?.searchParams.get("limit")).toBe(String(TODO_PAGE_SIZE));
      expect(TODO_PAGE_SIZE).toBe(20);
      expect(requests[0]?.searchParams.has("cursor")).toBe(false);
      expect(
        screen.queryByRole("button", { name: "Load more" }),
      ).not.toBeInTheDocument();
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

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

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
});
