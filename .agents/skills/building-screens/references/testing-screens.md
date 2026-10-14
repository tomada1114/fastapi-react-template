# Testing a screen: the helpers and the traps

Read when writing a component test under `frontend/tests/`. Where the file goes and the
coverage floor are `placing-tests`' and `frontend/AGENTS.md`'s "Tests and the coverage
floor"; how a test is named and what it asserts is `writing-tests`'.

## Rendering

- Render the feature component, not the router, with `renderWithQuery` from
  `frontend/tests/msw/helpers.tsx`. It wraps the component in a fresh `QueryClient`
  with retries off for queries and mutations, returns it as `queryClient`, and clears
  every client it made after each test.
- A route test renders `createAppRouter(createQueryClient(), { history })` with
  `createMemoryHistory({ initialEntries: [path] })` inside a `QueryClientProvider`, as
  `frontend/tests/routes/index.test.tsx` does.
- `frontend/tests/setup.ts` registers the `jest-dom` matchers and runs Testing Library's
  `cleanup` after each test, because Vitest runs without `globals`. Import `describe`,
  `it`, `test`, and `expect` from `vitest` in every file.

## Querying

Query by what a user perceives, in Testing Library's priority order: `getByRole`,
`getByLabelText`, `getByPlaceholderText`, `getByText`, `getByDisplayValue`, then
`getByAltText` and `getByTitle`; `getByTestId` only when neither role nor text can match
(https://testing-library.com/docs/queries/about/#priority, checked 2026-10-13).

- A query by role and name is also a check of the accessible name:
  `getByRole("button", { name: "Delete buy milk" })` fails when the button's
  `aria-label` is missing.
- `getByRole("alert")` finds an error from `ErrorMessage` or a field message;
  `getByRole("status")` finds a live status region.
- Assert focus with `toHaveFocus()` after an action that moves it.

## Input

Drive input with `fireEvent` from `@testing-library/react`: `fireEvent.change(input,
{ target: { value } })`, then `fireEvent.click(button)` or `fireEvent.submit(form)`.
`@testing-library/user-event` is not installed; adding it is a new package
(`managing-dependencies`).

## MSW

- Import `server` from `frontend/tests/msw/server.ts` in every test that renders
  something that fetches. Its default handler answers `GET /api/todos` with an empty
  page; add per-test handlers with `server.use(...)`, which the module resets after each
  test.
- Type each response with the generated types so a contract change fails `tsc`:
  `HttpResponse.json<TodoPageResponse>({ items, next_cursor: null })`,
  `HttpResponse.json<ProblemDetails>(problem, { status: 500 })`.
- The server listens with `onUnhandledFrame: "error"`. The default, `"warn"`, logs and
  lets the request through; `"error"` stops it, so a request no handler covers fails the
  test instead of reaching the network
  (https://mswjs.io/docs/api/setup-server/listen, checked 2026-10-13).
- The module points the generated client's `baseUrl` at `window.location.origin`
  (`http://localhost:5173`, from `vitest.config.ts`'s `environmentOptions`): under jsdom,
  `fetch` and `Request` are Node's and cannot resolve a relative URL. Production keeps
  the relative base. Never change the base URL in a test of its own.
- To read what the screen sent, collect it inside the handler
  (`bodies.push(await request.json())`) and assert after the screen settles.

## Waiting

- Wait for what the user would see: `findBy...` or `waitFor`, never a timer or `sleep`.
- To observe a pending state (a disabled button, a loading message), hold the handler on
  a `deferred()` barrier from the helpers, assert, then `release()` it and wait for the
  settled state.
- A cache detail (an invalidated key) is asserted through `queryClient` from
  `renderWithQuery` only when no visible state shows it.
