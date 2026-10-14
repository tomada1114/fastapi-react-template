# Running a `just dev` pair of your own

Read when the evidence needs the screen's origin — Vite's proxy of `/api` and `/healthz`,
the served screen, or `just dev` itself. `just dev` runs `just backend dev` and
`just frontend dev` together and stops both when either exits or it receives `SIGINT`,
`SIGTERM`, or `SIGHUP`. Two process variables move its ports: `MY_APP_API_PORT`
(uvicorn's `--port`, and the port Vite proxies `/api` and `/healthz` to) and
`VITE_PORT` (Vite's port, with `strictPort`: a taken port fails instead of moving).
Neither is a setting: `Settings` never reads them.

## The rules

Everything in `SKILL.md`'s "The developer's server is not yours" holds, plus:

- **Two free ports, both checked** on `127.0.0.1` and `::1`, neither 8000 nor 5173.
- **A scratch database file, never empty.** `just dev` migrates first (`just backend
  db-upgrade`), and the database recipes turn an unset or empty `MY_APP_DATABASE_URL`
  into `backend/var/dev.db`, the developer's database. So the in-memory store is not
  available here: point the URL at a file in a `mktemp -d` directory.
- **Requests only to the pair just started:** `curl` the Vite port, after both
  uvicorn's "Application startup complete" and Vite's `Local:` line for that port are
  in the log; earlier, the proxy can answer 502.
- **Stop only the `just` you launched.** `$!` is the outer `just`; it passes `SIGTERM`
  on to the recipe, which stops both process groups it started (uv, uvicorn's reloader
  and worker, pnpm, Vite) and exits 143 once nothing of them is left.

## The script

One foreground shell command, under bash or zsh, with no `set -e`, so a failed `curl`
still reaches the stop; the `trap` stops the pair when the command is interrupted part
way, and is cleared once the pair is reaped, so a reused PID is never signalled:

```bash
probe='import socket, sys
port = int(sys.argv[1])
for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
    try:
        s = socket.socket(family)
    except OSError:
        continue
    s.settimeout(1)
    if s.connect_ex((host, port)) == 0:
        sys.exit(0)
    s.close()
sys.exit(1)'
ready='import os, pathlib, sys, time
log, api, vite, pid = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4])
lines = (f"running on http://127.0.0.1:{api} ", "Application startup complete", f"http://localhost:{vite}/")
for _ in range(600):
    text = log.read_text(errors="replace")
    if all(line in text for line in lines):
        sys.exit(0)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        sys.exit(1)
    time.sleep(0.1)
sys.exit(1)'
free='import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
api=$(uv run --locked python -c "$free"); vite=$(uv run --locked python -c "$free")
db="sqlite+aiosqlite:///$(mktemp -d)/todos.db"
log=$(mktemp)
uv run --locked python -c "$probe" "$api"; a=$?
uv run --locked python -c "$probe" "$vite"; v=$?
if [ "$a" = 1 ] && [ "$v" = 1 ] && [ "$api" != "$vite" ]; then
  env $(env | sed -n 's/^\(MY_APP_[^=]*\)=.*/-u \1/p') MY_APP_DATABASE_URL="$db" MY_APP_CORS_ORIGINS= MY_APP_LOG_LEVEL= MY_APP_LOG_FORMAT= MY_APP_API_PORT="$api" VITE_PORT="$vite" just dev >"$log" 2>&1 &
  pid=$!
  trap 'kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null' EXIT
  if uv run --locked python -c "$ready" "$log" "$api" "$vite" "$pid"; then
    curl -sS -i "http://localhost:$vite/healthz"; echo
    curl -sS -i -X POST "http://localhost:$vite/api/todos" -H 'content-type: application/json' -d '{"title": "buy milk"}'; echo
  else
    echo "the pair did not start; nothing was sent"
  fi
  kill "$pid" 2>/dev/null; wait "$pid"; rc=$?; trap - EXIT; echo "just dev exited $rc"
  for port in "$api" "$vite"; do
    uv run --locked python -c "$probe" "$port"; rc=$?
    case "$rc" in
      1) echo "nothing listening on $port" ;;
      0) echo "something still listens on $port: report it, do not kill it" ;;
      *) echo "could not check port $port (status $rc)" ;;
    esac
  done
  grep -E 'Uvicorn running|Local:|Finished server process' "$log"
else
  echo "port $api or $vite is taken or could not be checked ($a/$v): nothing started"
fi
```

## What it prints

The output, observed 2026-10-14 under bash and zsh (the ports, the timestamps, and the
ids vary; headers trimmed to the status line):

```console
HTTP/1.1 200 OK

{"status":"ok"}
HTTP/1.1 201 Created

{"id":"01a1385e-c7b2-7465-8688-af3c8fe99376","title":"buy milk","completed":false,"created_at":"2026-10-14T03:04:58.034427Z"}
just dev exited 143
nothing listening on 61985
nothing listening on 61986
INFO:     Uvicorn running on http://127.0.0.1:61985 (Press CTRL+C to quit)
  ➜  Local:   http://localhost:61986/
INFO:     Finished server process [53220]
```

A taken `VITE_PORT` shows the failure path: Vite prints `Port <port> is already in use`
and exits 1, `just dev` stops the API and exits 1, and the API's port is free again.
