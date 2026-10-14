# Testing a screen: rendering and the states to cover

Read when writing a component test for a screen under `frontend/tests/`. Where the file
goes and the coverage floor are `placing-tests`'; how the test itself is written — its
`it` sentence, the query order, `userEvent.setup()`, the `jest-dom` matchers, MSW handlers,
waiting, and the `baseUrl` trap under `jsdom` — is `writing-tests`'
`references/frontend-tests.md`. This file holds only what is particular to a screen.

## Rendering

- Render the feature component, not the router, with `renderWithQuery` from
  `frontend/tests/msw/helpers.tsx`. It wraps the component in a fresh `QueryClient`
  with retries off for queries and mutations, returns it as `queryClient`, and clears
  every client it made after each test.
- A route test renders `createAppRouter(createQueryClient(), { history })` with
  `createMemoryHistory({ initialEntries: [path] })` inside a `QueryClientProvider`, as
  `frontend/tests/routes/index.test.tsx` does.
- `todo(...)` in the same helpers builds a typed to-do for a handler's response, so a
  contract change fails `tsc` in the test as well.

## The states a screen's test covers

Each state the screen renders gets its own `it`, with the handler that produces it:

- **Loading:** hold the handler on `deferred()`, assert the loading message or the
  disabled control, then `release()` it and wait for the settled state.
- **Empty and data:** the default `GET /api/todos` handler answers an empty page; a
  `server.use(...)` handler answers with items.
- **A 422 next to its field:** a Problem Details body with `errors[].loc` naming the
  field; assert the message by `getByRole("alert")` and the input's `aria-invalid` and
  `aria-describedby`.
- **A 5xx:** the generic message and the request id the body carries.
- **A network failure:** `HttpResponse.error()`, and the generic connection message.
- **A mutation:** what the screen sent (collected in the handler) and the refetched
  state it renders afterwards; a cache detail through `queryClient` only when no visible
  state shows it.
- **Focus:** after an item is removed, `toHaveFocus()` on the element the accessibility
  checklist names ([accessibility.md](accessibility.md)).
