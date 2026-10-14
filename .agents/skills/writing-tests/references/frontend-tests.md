# Writing a frontend test

Read when writing or reviewing a Vitest test under `frontend/tests/`. What `SKILL.md`
says about behavior over implementation, expected values from outside the code, edge
cases, fakes over mocks, and independence holds here unchanged; this file holds what
Vitest, Testing Library, and MSW change. Where the file goes is `placing-tests`'; how a
screen's test renders it and which states it covers is `building-screens`'.

## Naming and shape

- Name a test by the behavior sentence passed to `it`, under a `describe` naming the
  unit: `describe("TodoItem")`, then
  `it("completes through the API and renders the refetched completed row")`. Not the
  pytest `test_<what>_<scenario>_<expected>` form: `-t` filters on
  `<describe> > <it>`, and a failure report prints the sentence.
- Arrange, Act, Assert, in that order, one behavior per `it`.
- Vitest runs without `globals`: import from `vitest` the APIs the file uses
  (`describe`, `it`, `expect`, `vi`, ...) and no others, since Biome rejects an unused
  import. `frontend/tests/setup.ts` registers the `jest-dom` matchers and Testing
  Library's `cleanup` for every file.

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
- `queryBy...` only to assert that something is absent
  (`expect(screen.queryByRole("alert")).not.toBeInTheDocument()`).
- Assert with the `jest-dom` matchers, which name what a user sees:
  `toBeInTheDocument()`, `toHaveTextContent(...)`, `toBeDisabled()`,
  `toHaveAttribute("aria-invalid", "true")`, `toHaveFocus()` after an action that moves
  focus.

## Input

Drive input as a user does, with `@testing-library/user-event`: `const user =
userEvent.setup()` at the top of the test, then `await user.type(input, text)`,
`await user.click(button)`, `await user.keyboard("{Enter}")`, or `await user.tab()`.
It moves focus and fires the key and pointer events a real user would, so a flow a
keyboard user cannot complete fails the test. Keep `fireEvent` from
`@testing-library/react` only where the test needs one raw DOM event a user cannot
produce, such as two synchronous `fireEvent.submit(form)` calls proving a duplicate
submit is blocked.

## Faking the API with MSW

- Every request the code under test makes is answered by an MSW handler, never by a
  mocked `fetch` or a mocked generated SDK function: the generated client then runs as
  in production. Import `server` from `frontend/tests/msw/server.ts` in every test that
  renders something that fetches. Its default handler answers `GET /api/todos` with an
  empty page; add per-test handlers with `server.use(...)`, which the module resets
  after each test.
- Type each response with the generated types so a contract change fails `tsc`:
  `HttpResponse.json<TodoPageResponse>({ items, next_cursor: null })`,
  `HttpResponse.json<ProblemDetails>(problem, { status: 500 })`.
- The server listens with `onUnhandledFrame: "error"`. The default, `"warn"`, logs and
  lets the request through; `"error"` stops it, so a request no handler covers never
  reaches the network. Stopping it does not by itself fail the test: the code receives
  a network error (TanStack Query turns it into error state), and a test asserting the
  generic error message could still pass. So add a handler for every request the code
  makes (https://mswjs.io/docs/api/setup-server/listen, checked 2026-10-13).
- The module points the generated client's `baseUrl` at `window.location.origin`
  (`http://localhost:5173`, from `vitest.config.ts`'s `environmentOptions`): under
  Vitest's `jsdom` environment, `fetch` and `Request` are Node's and cannot resolve a
  relative URL such as `/api/todos` (observed 2026-10-14 on Node v24.21.0:
  `node -e "new Request('/api/todos')"` throws
  `TypeError: Failed to parse URL from /api/todos`; `frontend/vitest.config.ts` says the
  same beside `environmentOptions`). Production keeps the relative base. Never change
  the base URL in a test of its own.
- To assert what the code sent, collect it inside the handler
  (`bodies.push(await request.json())`) and assert after the screen settles.

## Waiting

- Wait for what the user would see: `findBy...` or `waitFor`, never a timer,
  `setTimeout`, or fake timers to skip a wait. A `findBy...` that needs longer than the
  default under load gets an explicit `timeout`, as
  `frontend/tests/features/todos/TodoItem.test.tsx`'s `loadedRow` does, never a sleep.
- To observe a pending state (a disabled button, a loading message), hold the handler on
  a `deferred()` barrier from `frontend/tests/msw/helpers.tsx`, assert, then
  `release()` it and wait for the settled state.
- A cache detail (an invalidated key) is asserted through the `queryClient` the render
  helper returns only when no visible state shows it.

## Nothing skipped or focused on `main`

No `it.only` / `describe.only`, `it.skip`, `it.todo`, or a commented-out test.
`vitest.config.ts`'s `allowOnly: false` fails a run that contains `.only`
(`Unexpected .only modifier`); `.skip` and `.todo` pass silently (a file holding only
those reports `skipped` and `todo` and exits 0); both observed with Vitest 5.0.3,
2026-10-14. Review is the only gate for `.skip` and `.todo`. Fix the test
or delete it: skipping one weakens a gate (AGENTS.md's "Security and human approval").
