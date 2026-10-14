# Seeing the screen against a real API: `just e2e`

Read when the evidence is the screen working against the real API and database: a
change to the screen's flow, Vite's proxy, the API a screen calls, or a migration the
screen depends on. `just e2e` runs `e2e/tests/` in Chromium (Playwright) against the
built frontend, served by Vite's preview server, and the real API on a throwaway SQLite
file. It is a check, not a server: it ends on its own, so it needs none of the start,
wait, and stop steps of a server of your own.

## What it does for you

Everything `SKILL.md`'s "The developer's server is not yours" asks, the recipe does:

- **Its own two ports.** It picks two free ports (or takes `E2E_API_PORT` and
  `E2E_WEB_PORT`), refuses 8000, 5173, and one port for both, and refuses to start when
  either already accepts connections on `127.0.0.1` or `::1`. Both servers run with
  `reuseExistingServer: false` and Vite with `--strictPort`, so a taken port fails the
  run instead of attaching to someone else's server. The developer's `just dev` keeps
  running, untouched.
- **A throwaway database.** It migrates a fresh SQLite file in a `mktemp -d` directory
  (`just backend db-upgrade` with that URL), and removes the directory afterwards.
- **Every setting explicit.** It drops every inherited `MY_APP_*` variable and sets each
  `Settings` field for the run, so neither the shell nor `backend/.env` reaches the API,
  the migration, or the persistence check (`e2e/environment.ts`,
  `e2e/verify_persistence.py`).
- **Proof the data was stored.** Before deleting the to-do it created and completed, the
  spec runs `e2e/verify_persistence.py`, a process of its own that reads the same file
  through a fresh container: a reload alone cannot tell a database from an API that keeps
  to-dos in memory.
- **Its own stop.** Playwright stops both servers. `INT`, `TERM`, and `HUP` reach
  Playwright as `SIGINT`, the one signal on which it stops them, and the recipe exits
  128 + the signal. Then, on success, failure, and interruption alike, it checks both
  ports, naming any listener without killing it, and removes the directory. A failed
  check turns only a passing run into exit 1; a failing run keeps its own status.

`pnpm --dir e2e exec playwright test` without the recipe fails at once, with an error
naming the variables it lacks and `just e2e`.

## Running it

Once per machine, download the Chromium build the installed `@playwright/test` needs
(from Playwright's own host, `cdn.playwright.dev`, not the npm registry); CI adds
`--with-deps` for the Linux packages:

```bash
pnpm --dir e2e exec playwright install chromium
```

Then, in the foreground; arguments go to `playwright test`:

```bash
just e2e
just e2e --grep "a to-do"
```

A failure leaves its trace under `e2e/test-results/` (`trace: 'retain-on-failure'`);
open one with `pnpm --dir e2e exec playwright show-trace <path>/trace.zip`. CI uploads
that directory and the HTML report as the `e2e-traces` artifact when the job fails.

## What it prints

The last lines, observed 2026-10-14 on macOS (the ports, the path, the id, and the
timing vary):

```console
to-do 01a138a4-d42f-71c4-9e4d-393dd02223c8 is stored, completed, in /var/folders/…/T/tmp.eqQ5Aly1Bo/e2e.db
  ✓  1 [chromium] › tests/todos.spec.ts:41:1 › a to-do goes from the screen to the database and away again (1.1s)
[API] INFO:     Finished server process [93335]

  1 passed (6.9s)
nothing listening on 49279
nothing listening on 49280
removed /var/folders/…/T/tmp.eqQ5Aly1Bo
```

A `SIGTERM` to `just` while the API was starting, observed the same day, ended with
exit 143, "nothing listening" on both ports, and the directory removed.

In a pull request's Test Plan, these lines are the evidence: the passing test, both
"nothing listening" lines, and the removed directory.
