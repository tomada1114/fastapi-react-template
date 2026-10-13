import type { TodoResponse } from "../../api/generated/types.gen";
import { TodoItem } from "./TodoItem";

export function TodoList({
  todos,
  headingId,
  onDeleted,
  onStale,
}: {
  todos: ReadonlyArray<TodoResponse>;
  headingId: string;
  onDeleted: () => void;
  onStale: () => void;
}) {
  return (
    <>
      {todos.length === 0 && (
        <p className="text-gray-600">No to-dos yet. Add one above.</p>
      )}
      <ul aria-labelledby={headingId} className="divide-y divide-gray-200">
        {todos.map((todo) => (
          <TodoItem key={todo.id} todo={todo} onDeleted={onDeleted} onStale={onStale} />
        ))}
      </ul>
    </>
  );
}
