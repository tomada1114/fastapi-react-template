import { useInfiniteQuery } from "@tanstack/react-query";
import { useId, useRef, useState } from "react";
import { listTodosInfiniteOptions } from "../../api/generated/@tanstack/react-query.gen";
import { ErrorMessage } from "../../lib/ErrorMessage";
import { toApiError } from "../../lib/problem-details";
import { CreateTodoForm } from "./CreateTodoForm";
import { TodoList } from "./TodoList";

export const TODO_PAGE_SIZE = 20;

export function TodosScreen() {
  const headingId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const [staleNotice, setStaleNotice] = useState({ version: 0, visible: false });
  const clearNotice = () =>
    setStaleNotice((notice) =>
      notice.visible ? { ...notice, visible: false } : notice,
    );
  const query = useInfiniteQuery({
    ...listTodosInfiniteOptions({ query: { limit: TODO_PAGE_SIZE } }),
    initialPageParam: {},
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });

  return (
    <section aria-labelledby={headingId} className="max-w-2xl space-y-6">
      <CreateTodoForm onAction={clearNotice} />
      <div className="space-y-3">
        <h2
          ref={heading}
          id={headingId}
          tabIndex={-1}
          className="text-xl font-semibold"
        >
          To-dos
        </h2>
        <p
          role="status"
          aria-atomic="true"
          className={
            query.isPending || staleNotice.visible ? "text-gray-600" : "sr-only"
          }
        >
          {query.isPending
            ? "Loading to-dos…"
            : staleNotice.visible && (
                <span key={staleNotice.version}>
                  That to-do no longer exists. The list has been refreshed.
                </span>
              )}
        </p>
        {query.isPending ? null : query.isError && !query.data ? (
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
          <>
            <TodoList
              todos={query.data?.pages.flatMap((page) => page.items) ?? []}
              headingId={headingId}
              onDeleted={() => heading.current?.focus()}
              onAction={clearNotice}
              onStale={() =>
                setStaleNotice((notice) => ({
                  version: notice.version + 1,
                  visible: true,
                }))
              }
            />
            {query.hasNextPage && (
              <button
                type="button"
                disabled={query.isFetching}
                onClick={() => {
                  clearNotice();
                  void query.fetchNextPage();
                }}
                className="rounded-md border border-gray-300 px-3 py-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900 disabled:opacity-50"
              >
                {query.isFetchingNextPage ? "Loading more…" : "Load more"}
              </button>
            )}
            {query.isError && <ErrorMessage error={toApiError(query.error)} />}
          </>
        )}
      </div>
    </section>
  );
}
