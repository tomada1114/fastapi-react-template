import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { createQueryClient } from "../../src/lib/query-client";
import { createAppRouter } from "../../src/router";
import "../msw/server";

// On a line of its own: the bootstrap rewrites it to a display name of up to
// 60 characters, which must not push any line past Biome's 88 columns.
const APP_NAME = "My App";

function renderAt(path: string) {
  const queryClient = createQueryClient();
  const history = createMemoryHistory({ initialEntries: [path] });
  const router = createAppRouter(queryClient, { history });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

test("index route renders the app heading inside the root layout", async () => {
  renderAt("/");

  const heading = await screen.findByRole("heading", { name: APP_NAME });
  expect(heading).toBeInTheDocument();
  const header = screen.getByRole("banner");
  expect(within(header).getByText(APP_NAME)).toBeInTheDocument();
});

test("the router carries the query client in its context", () => {
  const queryClient = createQueryClient();

  const router = createAppRouter(queryClient);

  expect(router.options.context.queryClient).toBe(queryClient);
});
