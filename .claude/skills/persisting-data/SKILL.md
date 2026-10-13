---
name: persisting-data
description: >
  Covers SQL persistence in backend/: the Core Table metadata and UtcDateTime in
  backend/src/my_app/adapters/sql/tables.py, statements as module constants in a SQL
  repository, the AsyncEngine from make_engine and its disposal, Alembic under
  backend/migrations/ (env.py, script.py.mako, revisions, render_as_batch), just
  backend db-upgrade and db-revision, the drift test, and why the app never migrates
  at start-up. Use when adding or changing a table or column, writing or reviewing a
  revision, alembic check failing, "no such table" errors, or a SQL test leaking an
  engine.
---

# Persisting Data

**Owns:** how state reaches a SQL database here — the table metadata, the column
types, the statements a SQL repository runs, the engine's lifecycle, and every
migration from writing it to applying it. **Does not own:** what a repository port may
ask of a store, ids, cursor pages, and the shared contract suite (`designing-core-logic`'s
"Ports any store can implement"); `MY_APP_DATABASE_URL`'s validation
(`designing-core-logic`'s "Settings are read once, at the boundary"); a new package
such as a driver (`managing-dependencies`).

## Where each piece lives

| Piece | Home |
|---|---|
| Tables, the naming convention, `UtcDateTime` | `backend/src/my_app/adapters/sql/tables.py` |
| The engine (`make_engine`) | `backend/src/my_app/adapters/sql/engine.py` |
| One repository per port, its statements beside it | `backend/src/my_app/adapters/sql/repository.py` |
| Alembic's settings, without a URL | `backend/alembic.ini` |
| How Alembic reaches the database; the revision template | `backend/migrations/env.py`, `backend/migrations/script.py.mako` |
| The revisions | `backend/migrations/versions/` |

SQLAlchemy, Alembic, and aiosqlite are imported only there and in tests. Enforced by:
`backend/pyproject.toml`'s `banned-api` entries and its `migrations/**` per-file
ignore.

## Tables are Core metadata

A table is a `Table` on the one `metadata` in `tables.py` — never an ORM class and
never SQLModel, so no mapped object can escape the adapter, and rows become core
models (`Todo`) before a method returns. `metadata` carries a naming convention, so
every constraint and index has a predictable name (`pk_todos`) that a later
revision can drop or alter on every database, SQLite included
(https://alembic.sqlalchemy.org/en/latest/naming.html, checked 2026-10-09).

- A column's limits come from the core's constants (`String(MAX_TITLE_LENGTH)`), so
  the database and the domain rule cannot disagree.
- Ids are `Uuid` primary keys the application generates; never an autoincrement.
- A timestamp is `UtcDateTime`: it refuses a naive `datetime` on bind (a bug in a clock
  or a caller), stores an aware one as naive UTC, and attaches UTC on read — the
  same on SQLite and PostgreSQL (SQLAlchemy's "Store Timezone Aware Timestamps as
  Timezone Naive UTC" recipe,
  https://docs.sqlalchemy.org/en/21/core/custom_types.html, checked 2026-10-09).

## Statements are constants

Each statement a repository runs is a module-level constant built once with
`bindparam` — first page, page after a cursor, one by id, insert, update, delete — and
each call passes only values. Nothing assembles SQL per call, so no request can change
a statement's shape. Two traps met here:

- A `bindparam` named after a column (`title`) is reserved for an UPDATE's SET values;
  name the key `todo_id`, not `id`.
- An `update()` without `.values()` takes its SET clause from the column-named values
  passed with it, so one constant writes every column.

Each method takes its own pooled connection — `engine.begin()` for a write, which
commits or rolls back, `engine.connect()` for a read — so concurrent calls never share
a transaction. A driver error with a domain meaning is translated there (an
`IntegrityError` on `add` becomes the port's `ValueError`; **BACKGROUND:**
`designing-errors`); any other propagates as a bug.

## The engine has one owner

`make_engine(url)` returns an `AsyncEngine` that opens nothing until first used, with
SQLite's busy timeout raised so a burst of concurrent writes queues for the write lock
instead of failing with "database is locked". `build_container` makes one per
container, hands it to every SQL repository, and registers
`resources.push_async_callback(engine.dispose)` — the shape
`designing-core-logic`'s `references/adding-a-port.md` gives a resource-holding adapter.

- `dispose()` must be awaited on the loop that used the engine; an engine left to
  garbage collection can warn `Event loop is closed`
  (https://docs.sqlalchemy.org/en/21/orm/extensions/asyncio.html, checked 2026-10-09),
  and `filterwarnings = ["error"]` turns that into an intermittent test failure.
- Pooled connections belong to one event loop. Each `TestClient` context runs the app
  on a loop of its own, so a SQL API test builds its app with `create_app(settings)`,
  whose lifespan disposes the engine on that loop; never pass it a SQL container
  from `make_container`.
- In tests, `make_container` closes every container it built; a test that builds an
  engine itself disposes it in a `finally` or a yielding fixture.

## The app never migrates

Neither `create_app`, `build_container`, nor the lifespan runs Alembic or
`metadata.create_all`. Migrations run explicitly, before the app starts:
`just backend db-upgrade`, which `just backend dev` runs first. A database nobody
migrated fails its first request with a 500 ("no such table"): that is a deployment
bug, and the fix is the migration, never a start-up `create_all`, which would mask a
missing revision and race between processes. Only the contract suite's own fixture
builds a schema with `metadata.create_all`, on a throwaway file.

## Changing the schema

1. Change the table in `tables.py`, test-first through the repository's behavior
   (**REQUIRED:** `tdd`).
2. `just backend db-revision "add due date"`. It migrates the development database to
   head (`db-upgrade`), autogenerates a revision from the difference, and lints and
   formats it through `alembic.ini`'s post-write hooks.
3. Review the revision by hand. Autogenerate reads a renamed table or column as a
   drop and an add, which loses the data
   (https://alembic.sqlalchemy.org/en/latest/autogenerate.html, checked 2026-10-09),
   and cannot know a backfill: edit `upgrade()` and `downgrade()` until both are what
   you mean. A new `NOT NULL` column on a table with rows needs a `server_default` or
   a backfill.
4. `just backend db-upgrade`, then `just backend test`; commit `tables.py`, the
   revision, and their tests together.

`db-upgrade`, `db-revision`, and `dev` use `MY_APP_DATABASE_URL`, or
`sqlite+aiosqlite:///./var/dev.db` (`backend/var/dev.db`, gitignored) when it is unset
or empty. A revision imports nothing from the app: `env.py`'s `render_item` renders
`UtcDateTime` as `sa.DateTime()`, so a later change to `tables.py` cannot change what
an old revision does. Never edit a revision that has reached `main`; write a new one.

## Batch mode

SQLite has almost no `ALTER TABLE`
(https://alembic.sqlalchemy.org/en/latest/batch.html, checked 2026-10-09), so `env.py`
sets `render_as_batch=True`: autogenerate writes `with op.batch_alter_table(...)`
blocks, which Alembic runs on SQLite by copying the table and as plain `ALTER`
statements elsewhere. Keep a hand-written change inside such a block too.

## The drift test

`backend/tests/adapters/test_sql_migrations.py` migrates an empty file to head and runs
`command.check`, which fails when autogenerate would render any operation — a table
changed without its revision (`alembic check`, added in Alembic 1.9.0,
https://alembic.sqlalchemy.org/en/latest/autogenerate.html, checked 2026-10-09). It
also downgrades to base and checks that nothing is left. Keep autogenerate's
comparisons on: turning off `compare_type` or excluding a table to quiet it is a
weakened gate (`changing-gates`).

These tests are plain `def`: `env.py` runs `asyncio.run`, which cannot start inside the
loop an async test runs on. The `alembic_config` and `migrated_sqlite_url` fixtures in
`backend/tests/conftest.py` give a test a migrated file; `env.py` reads the URL from
`MY_APP_DATABASE_URL` (failing with "MY_APP_DATABASE_URL must be set to run
migrations" without it) unless a caller passes a connection in
`config.attributes["connection"]`.

## PostgreSQL

The optional `postgres` extra installs asyncpg, approved in tracker #3. It supplies
the async PostgreSQL driver without making a server part of the first run; its
Apache-2.0 license fits the dependency gate, unlike psycopg's LGPL license
(https://pypi.org/project/asyncpg/0.31.0/ and https://pypi.org/project/psycopg/,
checked 2026-10-09).

`compose.yml` supplies an optional disposable database: run `docker compose up -d --wait`,
then `just backend test-postgres`. The recipe includes the extra and defaults to
that database; `MY_APP_TEST_POSTGRES_URL` selects another disposable database.
Never point it at application data: the shared contract empties the todos table
before each test and the migration test drops and recreates it.

Database migration and development recipes select the `postgres` extra when
the resolved URL uses PostgreSQL; SQLite keeps the default environment.

The `postgres` marker is deselected by default, so `just verify` needs no server.
Selecting it with `-m postgres` fails when the URL is absent. The CI `PostgreSQL`
job runs serially against its service; its session fixture migrates through Alembic's
connection-sharing path, and the contract tests use their own engine and connection
per call, as the app does.

## Verify

```bash
uv run --locked --directory backend pytest tests/adapters/
just backend lint
just backend test
```
