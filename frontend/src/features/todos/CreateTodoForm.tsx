import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState } from "react";
import { createTodoMutation } from "../../api/generated/@tanstack/react-query.gen";
import { ErrorMessage } from "../../lib/ErrorMessage";
import { toApiError } from "../../lib/problem-details";

const TITLE_FIELD = "title";

export function CreateTodoForm({ onAction }: { onAction?: () => void } = {}) {
  const [title, setTitle] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const submissionInFlight = useRef(false);
  const inputId = useId();
  const errorId = `${inputId}-error`;
  const queryClient = useQueryClient();
  const mutation = useMutation({
    ...createTodoMutation(),
    onSuccess: () => {
      setTitle("");
      input.current?.focus();
      void queryClient.invalidateQueries({ queryKey: [{ _id: "listTodos" }] });
    },
    onSettled: () => {
      submissionInFlight.current = false;
    },
  });
  const error = mutation.isError ? toApiError(mutation.error) : undefined;
  const titleErrors =
    error?.kind === "problem" && error.status === 422
      ? (error.fieldErrors[TITLE_FIELD] ??
        (error.code === "invalid_todo" ? [error.detail ?? error.title] : undefined))
      : undefined;
  const hasTitleError = Boolean(titleErrors?.length);

  return (
    <form
      aria-label="Add a to-do"
      className="space-y-2"
      onSubmit={(event) => {
        event.preventDefault();
        // The ref also guards a second submit before React renders pending state.
        if (submissionInFlight.current || mutation.isPending) return;
        submissionInFlight.current = true;
        onAction?.();
        mutation.mutate({ body: { title } });
      }}
    >
      <label htmlFor={inputId} className="block text-sm font-medium">
        Title
      </label>
      <div className="flex flex-wrap gap-2">
        <input
          ref={input}
          id={inputId}
          name={TITLE_FIELD}
          type="text"
          autoComplete="off"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          aria-invalid={hasTitleError || undefined}
          aria-describedby={hasTitleError ? errorId : undefined}
          className="min-w-0 flex-1 rounded-md border border-gray-300 px-3 py-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900"
        />
        <button
          type="submit"
          disabled={mutation.isPending}
          className="rounded-md bg-gray-900 px-4 py-2 font-medium text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900 disabled:cursor-wait disabled:opacity-50"
        >
          {mutation.isPending ? "Adding…" : "Add"}
        </button>
      </div>
      {hasTitleError && (
        <p id={errorId} role="alert" className="text-sm text-red-700">
          {titleErrors?.join(" ")}
        </p>
      )}
      {error && !hasTitleError && <ErrorMessage error={error} />}
    </form>
  );
}
