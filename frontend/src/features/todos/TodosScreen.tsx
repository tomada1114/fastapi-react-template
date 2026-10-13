import { useInfiniteQuery } from "@tanstack/react-query";
import { useId } from "react";
import { listTodosInfiniteOptions } from "../../api/generated/@tanstack/react-query.gen";
import { ErrorMessage } from "../../lib/ErrorMessage";
import { toApiError } from "../../lib/problem-details";
import { CreateTodoForm } from "./CreateTodoForm";
import { TodoList } from "./TodoList";

export const TODO_PAGE_SIZE = 20;

export function TodosScreen() {
  const headingId = useId();
  const query = useInfiniteQuery({
    ...listTodosInfiniteOptions({ query: { limit: TODO_PAGE_SIZE } }),
    initialPageParam: {},
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });

  return (
    <section aria-labelledby={headingId} className="max-w-2xl space-y-6">
      <CreateTodoForm />
      <div className="space-y-3">
        <h2 id={headingId} tabIndex={-1} className="text-xl font-semibold">
          To-dos
        </h2>
        {query.isPending ? (
          <p role="status" className="text-gray-600">
            Loading to-dos…
          </p>
        ) : query.isError ? (
          <>
            <ErrorMessage error={toApiError(query.error)} />
            <button
              type="button"
              disabled={query.isFetching}
              onClick={() => void query.refetch()}
              className="rounded-md border border-gray-300 px-3 py-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900 disabled:opacity-50"
            >
              Try again
            </button>
          </>
        ) : (
          <TodoList todos={query.data.pages[0]?.items ?? []} headingId={headingId} />
        )}
      </div>
    </section>
  );
}
