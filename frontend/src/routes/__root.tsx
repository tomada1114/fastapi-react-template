import type { QueryClient } from "@tanstack/react-query";
import { createRootRouteWithContext, Outlet } from "@tanstack/react-router";

/** What every route's loader and beforeLoad receive as `context`. */
export interface RouterContext {
  queryClient: QueryClient;
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootLayout,
});

function RootLayout() {
  return (
    <>
      <header className="border-b border-gray-200 px-4 py-3 font-semibold">
        <p>My App</p>
      </header>
      <main className="p-4">
        <Outlet />
      </main>
    </>
  );
}
