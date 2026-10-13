import type { QueryClient } from "@tanstack/react-query";
import { createRouter, type RouterHistory } from "@tanstack/react-router";
import { routeTree } from "./routeTree.gen";

export interface AppRouterOptions {
  /** Defaults to the browser's history; tests pass createMemoryHistory(). */
  history?: RouterHistory;
}

/**
 * The app's router over the generated route tree. The caller owns the query
 * client, so the one QueryClientProvider serves and the router's context hold
 * the same instance.
 */
export function createAppRouter(queryClient: QueryClient, options?: AppRouterOptions) {
  return createRouter({ routeTree, context: { queryClient }, ...options });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
