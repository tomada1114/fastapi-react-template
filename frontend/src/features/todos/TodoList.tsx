import type { TodoResponse } from "../../api/generated/types.gen";

export function TodoList({
  todos,
  headingId,
}: {
  todos: ReadonlyArray<TodoResponse>;
  headingId: string;
}) {
  return (
    <>
      {todos.length === 0 && (
        <p className="text-gray-600">No to-dos yet. Add one above.</p>
      )}
      <ul aria-labelledby={headingId} className="divide-y divide-gray-200">
        {todos.map((todo) => (
          <li key={todo.id} className="break-words py-3">
            {todo.title}
          </li>
        ))}
      </ul>
    </>
  );
}
