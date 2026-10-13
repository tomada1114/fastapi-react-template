import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach } from "vitest";
import type { TodoResponse } from "../../src/api/generated/types.gen";

const clients = new Set<QueryClient>();
afterEach(() => {
  for (const client of clients) client.clear();
  clients.clear();
});

export function renderWithQuery(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.add(queryClient);
  return {
    ...render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>),
    queryClient,
  };
}

export function todo(
  title: string,
  id = "0199c1f0-0000-7000-8000-000000000001",
): TodoResponse {
  return { id, title, completed: false, created_at: "2026-10-08T09:00:00Z" };
}

export function deferred() {
  let resolve: (() => void) | undefined;
  const promise = new Promise<void>((release) => {
    resolve = release;
  });
  return {
    promise,
    release: () => {
      if (!resolve) throw new Error("Deferred barrier was not initialized");
      resolve();
    },
  };
}
