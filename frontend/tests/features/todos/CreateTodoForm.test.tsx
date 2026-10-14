import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { listTodosOptions } from "../../../src/api/generated/@tanstack/react-query.gen";
import type {
  ProblemDetails,
  TodoPageResponse,
  TodoResponse,
} from "../../../src/api/generated/types.gen";
import { TodosScreen } from "../../../src/features/todos";
import { CreateTodoForm } from "../../../src/features/todos/CreateTodoForm";
import { deferred, renderWithQuery, todo } from "../../msw/helpers";
import { server } from "../../msw/server";

// The parser also supports older error bodies with absent detail/request ID;
// their remaining members still come from the current generated contract.
type LegacyProblemDetails = Omit<ProblemDetails, "detail" | "request_id"> & {
  detail?: string;
  request_id?: string;
};

async function submit(title: string) {
  const user = userEvent.setup();
  await user.type(screen.getByRole("textbox", { name: "Title" }), title);
  await user.click(screen.getByRole("button", { name: "Add" }));
}

describe("CreateTodoForm", () => {
  it.each(["buy milk", "a".repeat(200)])(
    "creates the unchanged title %s and refetches lists",
    async (title) => {
      const bodies: unknown[] = [];
      let items: TodoResponse[] = [];
      let lists = 0;
      server.use(
        http.get("/api/todos", () => {
          lists += 1;
          return HttpResponse.json<TodoPageResponse>({ items, next_cursor: null });
        }),
        http.post("/api/todos", async ({ request }) => {
          bodies.push(await request.json());
          const item = todo(title);
          items = [item];
          return HttpResponse.json<TodoResponse>(item, { status: 201 });
        }),
      );
      const { queryClient } = renderWithQuery(<TodosScreen />);
      const plainKey = listTodosOptions({ query: { limit: 7 } }).queryKey;
      queryClient.setQueryData(plainKey, { items: [], next_cursor: null });
      await screen.findByText("No to-dos yet. Add one above.");
      const input = screen.getByRole("textbox", { name: "Title" });
      expect(input).not.toHaveAttribute("required");
      expect(input).not.toHaveAttribute("maxlength");

      await submit(title);

      expect(await screen.findByRole("listitem")).toHaveTextContent(title);
      await waitFor(() => expect(input).toHaveValue(""));
      expect(input).toHaveFocus();
      expect(bodies).toEqual([{ title }]);
      expect(lists).toBe(2);
      expect(queryClient.getQueryState(plainKey)?.isInvalidated).toBe(true);
    },
  );

  it("submits from the keyboard with Enter in the title field", async () => {
    const bodies: unknown[] = [];
    server.use(
      http.post("/api/todos", async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json<TodoResponse>(todo("buy milk"), { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderWithQuery(<CreateTodoForm />);

    await user.tab();
    expect(screen.getByRole("textbox", { name: "Title" })).toHaveFocus();
    await user.keyboard("buy milk{Enter}");

    await waitFor(() => expect(bodies).toEqual([{ title: "buy milk" }]));
  });

  it("blocks duplicate submits while keeping the pending input editable", async () => {
    const gate = deferred();
    const entered = deferred();
    let posts = 0;
    server.use(
      http.post("/api/todos", async () => {
        posts += 1;
        entered.release();
        await gate.promise;
        return HttpResponse.json<TodoResponse>(todo("first"), { status: 201 });
      }),
    );
    const user = userEvent.setup();
    try {
      renderWithQuery(<CreateTodoForm />);
      const input = screen.getByRole("textbox", { name: "Title" });
      await user.type(input, "first");
      const form = screen.getByRole("form", { name: "Add a to-do" });
      fireEvent.submit(form);
      fireEvent.submit(form);
      await entered.promise;
      expect(await screen.findByRole("button", { name: "Adding…" })).toBeDisabled();
      expect(input).not.toBeDisabled();
      await user.clear(input);
      await user.type(input, "editable");
      expect(input).toHaveValue("editable");
      expect(posts).toBe(1);

      gate.release();

      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Add" })).toBeEnabled(),
      );
      expect(input).toHaveValue("");
      expect(posts).toBe(1);
    } finally {
      gate.release();
    }
  });

  it.each([
    {
      title: "bad",
      problem: {
        type: "about:blank",
        status: 422,
        title: "Unprocessable Content",
        code: "request_invalid",
        detail: "Request validation failed",
        request_id: "validation-422",
        errors: [
          { loc: ["body", "title"], message: "Title field error", type: "string_type" },
        ],
      },
      message: "Title field error",
    },
    {
      title: "   ",
      problem: {
        type: "about:blank",
        status: 422,
        title: "Unprocessable Content",
        code: "invalid_todo",
        detail: "Title must be 1-200 characters after stripping whitespace, got 0",
        request_id: "domain-422",
      },
      message: "Title must be 1-200 characters after stripping whitespace, got 0",
    },
    {
      title: "bad",
      problem: {
        type: "about:blank",
        status: 422,
        title: "Invalid title",
        code: "invalid_todo",
        request_id: "fallback-422",
      },
      message: "Invalid title",
    },
  ] satisfies ReadonlyArray<{
    title: string;
    problem: LegacyProblemDetails;
    message: string;
  }>)(
    "shows the server's title error: $message",
    async ({ title, problem, message }) => {
      const bodies: unknown[] = [];
      let lists = 0;
      server.use(
        http.get("/api/todos", () => {
          lists += 1;
          return HttpResponse.json<TodoPageResponse>({ items: [], next_cursor: null });
        }),
        http.post("/api/todos", async ({ request }) => {
          bodies.push(await request.json());
          return HttpResponse.json<LegacyProblemDetails>(problem, { status: 422 });
        }),
      );
      renderWithQuery(<TodosScreen />);
      await screen.findByText("No to-dos yet. Add one above.");

      await submit(title);

      const error = await screen.findByRole("alert");
      expect(error).toHaveTextContent(message);
      const input = screen.getByRole("textbox", { name: "Title" });
      expect(input).toHaveAttribute("aria-invalid", "true");
      expect(input).toHaveAttribute("aria-describedby", error.id);
      expect(bodies).toEqual([{ title }]);
      expect(lists).toBe(1);
    },
  );

  it.each([
    {
      status: 403,
      title: "Forbidden",
      detail: "This action is unavailable",
      message: "This action is unavailable",
    },
    { status: 409, title: "Conflict", message: "Conflict" },
  ])(
    "shows another 4xx problem at form level: $status",
    async ({ status, title, message, ...rest }) => {
      const problem: LegacyProblemDetails = {
        type: "about:blank",
        status,
        title,
        code: "http_error",
        request_id: "form-4xx",
        ...rest,
      };
      server.use(
        http.post("/api/todos", () =>
          HttpResponse.json<LegacyProblemDetails>(problem, { status }),
        ),
      );
      renderWithQuery(<CreateTodoForm />);

      await submit("buy milk");

      expect(await screen.findByRole("alert")).toHaveTextContent(message);
      expect(screen.getByRole("textbox", { name: "Title" })).not.toHaveAttribute(
        "aria-invalid",
      );
    },
  );

  it.each(["request-500", undefined])(
    "shows a generic 500 with optional request ID %s",
    async (requestId) => {
      const problem: LegacyProblemDetails = {
        type: "about:blank",
        status: 500,
        title: "Internal Server Error",
        detail: "Private diagnostic detail",
        code: "internal_error",
        ...(requestId === undefined ? {} : { request_id: requestId }),
      };
      server.use(
        http.post("/api/todos", () =>
          HttpResponse.json<LegacyProblemDetails>(problem, { status: 500 }),
        ),
      );
      renderWithQuery(<CreateTodoForm />);

      await submit("buy milk");

      const error = await screen.findByRole("alert");
      expect(error).toHaveTextContent("Something went wrong on our side. Try again.");
      expect(error).not.toHaveTextContent("Private diagnostic detail");
      if (requestId) expect(error).toHaveTextContent(`Request ID: ${requestId}`);
      else expect(screen.queryByText(/^Request ID:/)).not.toBeInTheDocument();
    },
  );

  it.each(["text", "network"])(
    "shows the connection message for a %s failure",
    async (failure) => {
      server.use(
        http.post("/api/todos", () =>
          failure === "text"
            ? new HttpResponse("not JSON", { status: 422 })
            : HttpResponse.error(),
        ),
      );
      renderWithQuery(<CreateTodoForm />);

      await submit("buy milk");

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Could not reach the server. Check your connection and try again.",
      );
    },
  );
});
