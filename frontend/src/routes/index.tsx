import { createFileRoute } from "@tanstack/react-router";
import { TodosScreen } from "../features/todos";

const APP_NAME = "My App";

export const Route = createFileRoute("/")({
  component: Index,
});

function Index() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">{APP_NAME}</h1>
      <TodosScreen />
    </div>
  );
}
