---
name: running-the-app
description: >
  Covers observing the real my-app process when no test shows the behavior: running
  `uv run --locked my-app` commands against a scratch SQLite file, and starting
  `my-app serve` on a free port, capturing curl output as evidence, and stopping it
  before the turn ends, without starting, stopping, or reusing the developer's own
  server (`just dev`, port 8000). Use when asked to run the app, try a command or an
  endpoint by hand, check a change against a live server, or put command output in a
  pull request.
---

# Running the App

**Owns:** how an agent observes the running application — which evidence first, how to
start and stop a server of its own, and what the evidence looks like in a pull request.
**Does not own:** writing a route or its `TestClient` test (`building-api-routes`);
writing a command or its `CliRunner` test (`designing-clis`); the pull request's
mechanics (`create-pr`). The rule this skill carries out is AGENTS.md's "Quick
Reference", under "Long-running — human-run".

## Evidence, cheapest first

Stop at the first tier that shows what the change does.

1. **A test.** `TestClient` and `CliRunner` exercise the same code as a live process
   and the result outlives the turn. If a lasting assertion would show it, write one.
2. **The CLI, run for real,** against a scratch database (below). It shows the console
   script, the environment, and the exit codes exactly as a user meets them.
3. **A server of your own, then `curl`,** for what only a listening process shows: the
   served headers, the startup path through `my-app serve`, a request from outside the
   process.

## The developer's server is not yours

- `just dev` is the developer's: never start, stop, or restart it, and never bind its
  port, 8000, which is also `my-app serve`'s default — always pass `--port`.
- **Let the OS pick the port** (bind to port 0), then check that nothing accepts
  connections on it. If something does, or the check itself fails, abort: start
  nothing and send nothing. A sibling worktree's server may hold any port.
- **Send requests only to a server you just started** from this checkout, in this
  command, after its log says it is running on that port. Never reuse a server that is
  already answering, even one that looks like this app.
- **Stop only the process you launched** — the `uv` whose pid `$!` gave you, which
  passes the signal on to the server it runs — before the turn ends, including when a
  step failed. Never by name (`pkill -f uvicorn`, `killall python`), and never "whatever
  listens on the port": if a listener remains after your own process has stopped,
  report it and stop; do not kill it.
- **Loopback only.** `my-app serve` binds `127.0.0.1` by default; never pass
  `--host 0.0.0.0`.

## Set every `MY_APP_*` setting explicitly

The developer's shell may export `MY_APP_*` variables — `MY_APP_DATABASE_URL` pointing
at their real data, for one. Every run clears the whole prefix and sets exactly the
settings it depends on:

```bash
env $(env | sed -n 's/^\(MY_APP_[^=]*\)=.*/-u \1/p') MY_APP_DATABASE_URL="$db" uv run --locked my-app ...
```

Leave `MY_APP_DATABASE_URL` out for the in-memory store, or point it at a file in a
directory from `mktemp -d`, outside the checkout; a relative `sqlite:///todos.db` would
create the file in the working directory.

## Running the CLI

Each command is its own process, so the in-memory store forgets between commands; use a
scratch file to see state carry over. Run the whole sequence as one shell command: an
agent's shell does not keep an exported variable from one call to the next, so a
command run later would silently use the developer's environment instead. Observed
under bash and zsh with a bogus `MY_APP_DATABASE_URL` exported, 2026-10-06:

```bash
db="sqlite:///$(mktemp -d)/todos.db"
run() { env $(env | sed -n 's/^\(MY_APP_[^=]*\)=.*/-u \1/p') MY_APP_DATABASE_URL="$db" uv run --locked my-app "$@"; echo "exit=$?"; }
run todo add "buy milk"
run todo list
run todo complete 999
```

```console
Added 1 [ ] buy milk
exit=0
1 [ ] buy milk
exit=0
Error: To-do 999 not found
exit=1
```

## Running a server of your own

Run the server's whole life as one foreground shell command — pick a port, check it,
start, wait, request, stop, check again. The `trap` stops the server even when the
command is interrupted part way; do not use `set -e`, so a failed `curl` still reaches
the stop. The script runs under bash and zsh (zsh reserves `status`, hence `rc`).

```bash
probe='import socket, sys; s = socket.socket(); s.settimeout(1); sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)'
ready='import pathlib, sys, time
log, line = pathlib.Path(sys.argv[1]), f"running on http://127.0.0.1:{sys.argv[2]} "
for _ in range(300):
    text = log.read_text()
    if line in text:
        sys.exit(0)
    if "ERROR" in text:
        sys.exit(1)
    time.sleep(0.1)
sys.exit(1)'
port=$(uv run --locked python -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
log=$(mktemp)
uv run --locked python -c "$probe" "$port"; rc=$?
if [ "$rc" = 1 ]; then
  env $(env | sed -n 's/^\(MY_APP_[^=]*\)=.*/-u \1/p') uv run --locked my-app serve --port "$port" >"$log" 2>&1 &
  pid=$!
  trap 'kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null' EXIT
  if uv run --locked python -c "$ready" "$log" "$port" && kill -0 "$pid" 2>/dev/null; then
    curl -sS -i "http://127.0.0.1:$port/healthz"; echo
    curl -sS -i -X POST "http://127.0.0.1:$port/todos" -H 'content-type: application/json' -d '{"title": "buy milk"}'; echo
  else
    echo "the server did not start; nothing was sent"
  fi
  kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
  uv run --locked python -c "$probe" "$port"; rc=$?
  case "$rc" in
    1) echo "nothing listening on $port" ;;
    0) echo "something still listens on $port: report it, do not kill it" ;;
    *) echo "could not check port $port (status $rc)" ;;
  esac
  grep -E 'Uvicorn running|Finished server process' "$log"
else
  echo "port $port is taken or could not be checked (status $rc): nothing started"
fi
```

- **The port check** is a Python probe run through `uv`, which the app needs anyway,
  rather than `lsof` or `ss`, which a host may lack. Exit 1 means nothing accepts
  connections; 0 means something does; anything else means the check failed, and only
  exit 1 counts as proof. `lsof` (macOS) or `ss -ltnp` (Linux), where installed, can
  name an unexpected listener for the report — never to pick something to kill.
- **Waiting** reads the server's own log for uvicorn's "running on" line, so no request
  goes out before your server holds the port; it gives up after 30 seconds or on an
  `ERROR` line, such as a failed bind.
- **Stopping.** `$!` is the pid of `uv`, not of the Python process that listens; `uv`
  passes the `SIGTERM` on and uvicorn shuts down cleanly. Observed with this script,
  2026-10-06, including the `trap` stopping a server when the command exited early.
- **A host that runs long commands in the background** follows the same steps; the stop
  and the final check still happen before the turn ends.

The output of that script, observed 2026-10-06 (the port and timestamps vary):

```console
HTTP/1.1 200 OK
date: Tue, 06 Oct 2026 21:46:13 GMT
server: uvicorn
content-length: 15
content-type: application/json

{"status":"ok"}
HTTP/1.1 201 Created
date: Tue, 06 Oct 2026 21:46:13 GMT
server: uvicorn
content-length: 88
content-type: application/json

{"id":1,"title":"buy milk","completed":false,"created_at":"2026-10-06T21:46:13.394917Z"}
nothing listening on 51826
INFO:     Uvicorn running on http://127.0.0.1:51826 (Press CTRL+C to quit)
INFO:     Finished server process [8239]
```

The in-memory store starts empty on every start; create what a request needs with a
`POST` first. Without the CLI there is no `my-app serve`: start the server with
`uv run --locked uvicorn my_app.api.app:create_app --factory --port "$port"`, the
command `just dev` runs, minus `--reload`. Without the API, only the CLI half applies.

## The evidence a pull request carries

Under the pull request's Test Plan, for each behavior observed rather than asserted:

- the exact command or request, as run;
- the lines of output that show the behavior — the status line, the body, the exit
  code, the stderr line — not the whole log;
- where it ran: `my-app serve` or the CLI, from this checkout, and the database
  (in-memory or a scratch file).

Redact before pasting: a home directory becomes `~/…`, a temporary path a placeholder,
and no credential or environment value appears.

## Before the turn ends

- [ ] The final port check printed "nothing listening" for every port you used, or you
      reported the listener that remained, untouched.
- [ ] The developer's server, if one was running, was never touched.
- [ ] `git status --porcelain` shows only the change: logs and databases live outside
      the checkout.
