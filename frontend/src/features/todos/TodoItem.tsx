import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  completeTodoMutation,
  deleteTodoMutation,
} from "../../api/generated/@tanstack/react-query.gen";
import type { TodoResponse } from "../../api/generated/types.gen";
import { ErrorMessage } from "../../lib/ErrorMessage";
import { toApiError } from "../../lib/problem-details";

export function TodoItem({
  todo,
  onDeleted,
  onStale,
  onAction,
}: {
  todo: TodoResponse;
  onDeleted: () => void;
  onStale: () => void;
  onAction: () => void;
}) {
  const queryClient = useQueryClient();
  const onSettled = async (_data: unknown, error: unknown) => {
    const parsed = toApiError(error);
    try {
      await queryClient.invalidateQueries(
        { queryKey: [{ _id: "listTodos" }] },
        { throwOnError: true },
      );
      if (
        parsed.kind === "problem" &&
        parsed.status === 404 &&
        parsed.code === "todo_not_found"
      ) {
        onStale();
      }
    } catch {
      // The observed list query displays its refetch error; no success notice.
    }
  };
  const complete = useMutation({ ...completeTodoMutation(), onSettled });
  const remove = useMutation({
    ...deleteTodoMutation(),
    onSuccess: onDeleted,
    onSettled,
  });
  const pending = complete.isPending || remove.isPending;
  const error = complete.isError
    ? toApiError(complete.error)
    : remove.isError
      ? toApiError(remove.error)
      : undefined;
  const stale =
    error?.kind === "problem" &&
    error.status === 404 &&
    error.code === "todo_not_found";

  return (
    <li className="space-y-2 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`min-w-0 flex-1 break-words ${todo.completed ? "line-through text-gray-600" : ""}`}
        >
          {todo.title}
        </span>
        {todo.completed ? (
          <span className="text-sm text-gray-600">Completed</span>
        ) : (
          <button
            type="button"
            aria-label={`Complete ${todo.title}`}
            disabled={pending}
            onClick={() => {
              onAction();
              remove.reset();
              complete.mutate({ path: { todo_id: todo.id } });
            }}
            className="rounded-md border border-gray-300 px-3 py-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900 disabled:opacity-50"
          >
            Complete
          </button>
        )}
        <button
          type="button"
          aria-label={`Delete ${todo.title}`}
          disabled={pending}
          onClick={() => {
            onAction();
            complete.reset();
            remove.mutate({ path: { todo_id: todo.id } });
          }}
          className="rounded-md border border-gray-300 px-3 py-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900 disabled:opacity-50"
        >
          Delete
        </button>
      </div>
      {error && !stale && <ErrorMessage error={error} />}
    </li>
  );
}
