# Accessibility checklist for a screen

Read before a screen ships, and when reviewing one. Each item is a rule first; the
example after it comes from the sample to-do screen under
`frontend/src/features/todos/` and can be deleted with it. A component test checks each
item through Testing Library's role and name queries (`writing-tests`), with the states
[testing-screens.md](testing-screens.md) lists.

## Labels and names

- **Every input has a visible label** tied to it with `htmlFor` and an id from
  `useId()`. A placeholder is not a label. The to-do form's `Title` label points at its
  text input.
- **Every button has an accessible name.** The visible text is enough when it is unique
  on the screen; a button repeated per row gets an `aria-label` naming its item. The
  to-do rows' buttons are named `Complete <title>` and `Delete <title>`.
- **A form, list, or section has a name** when the screen has more than one: the to-do
  form has `aria-label="Add a to-do"`, and the list and its section are
  `aria-labelledby` the `To-dos` heading.

## Focus

- **Focus moves to a defined element after an item is removed**, never to the document
  body. Pick an element that still exists after the removal and give it
  `tabIndex={-1}` when it is not focusable by itself. After a delete, the to-do screen
  focuses its `To-dos` heading.
- **Focus returns to the input after a successful submit** that clears it, so the next
  entry can be typed at once. The to-do form refocuses its title input after a create.
- **Every interactive element shows a visible focus style** (`focus-visible:` utilities).

## Announcements

- **An error is announced:** it renders with `role="alert"`. `ErrorMessage` does this,
  and so does a field message next to its input. The input gets `aria-invalid` and
  `aria-describedby` pointing at the message.
- **A status message is announced:** a `role="status"` region (with `aria-atomic`) stays
  mounted for the screen's whole life, and only its content changes. To announce the
  same text twice, replace its child (a new React `key`) rather than leaving it in
  place, and clear the region when the user starts a new action. The to-do screen's
  region shows `Loading to-dos…` and, after a stale row, its refresh notice, re-keyed
  for each one.
- **A notice is announced only once it is true:** the to-do screen announces the refresh
  only after the list's invalidation succeeded; when the refetch fails, the list shows
  its own error instead.

## Keyboard and pending state

- **Every action works from the keyboard:** use a `<button>` for an action and a
  `<form>` with a submit button for input, never a clickable `<div>` or `<span>`. Enter
  submits the to-do form.
- **A control whose request is in flight is disabled**, and its label says so where it
  helps (`Adding…`). A row whose actions change the same item disables all of them while
  either request is pending, as each to-do row does with Complete and Delete.
- **A double submit sends one request:** guard with a ref as well as the pending flag,
  because a second submit can arrive before React renders the disabled state. The to-do
  form's `submissionInFlight` ref does this.
