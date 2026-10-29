# Why the core is shaped this way

Read before a design change to the layers beneath the entry points: an async path made
sync, a framework type let into `core/`, a port rule relaxed, configuration read
somewhere other than `Settings`, or a model provider added. `SKILL.md` holds the rules;
this page holds what each one protects and the alternative it rules out. Rewrite the
reason here in the same pull request that changes the rule.

## An async call path

Ports, services, routes, and repositories are `async def`, rather than synchronous
services over async adapters. The SQL drivers and the `AsyncEngine` need that path, and
a later outbound call — a remote API, a model provider — gets real cancellation and
concurrency without replacing the domain interfaces. A rule, a calculation, `Clock`, and
`IdFactory` stay `def`, since they do no I/O. Tests drive the async path through
AnyIO's pytest plugin.

## A framework-free core

The core imports the standard library and itself. Values are frozen dataclasses, ports
are `typing.Protocol`s, and the composition root wires adapters into services. Putting
API schemas or database models in the core would tie the domain rules to their entry
point or to their storage, so changing either would mean rewriting the rules. Pydantic
belongs at the edges — request and response models, `Settings` — and the banned-api
rule and the import test keep the boundary mechanical rather than a matter of review.

## Ports any store can implement

The six rules in `SKILL.md` keep a key-value adapter (DynamoDB, say) possible beside the
SQL one, so an app can move stores without touching its services. No key-value recipe
ships; an app that wants one adds the adapter under the same contract suite.

Timestamps are timezone-aware, not necessarily UTC: `Todo` rejects only a naive
`created_at`. The production clock (`composition.utc_now`) returns UTC and the SQL
adapter's `UtcDateTime` stores and returns UTC, but the in-memory adapter keeps
whatever aware offset it is given. UTC is therefore the production convention, not an
invariant every port implementation enforces.

## Settings at the boundary, with an optional dotenv file

Requiring a shell export for every local value makes setup cumbersome, so `Settings`
also reads an optional `backend/.env`, located from the module rather than the working
directory, with `MY_APP_*` environment values taking precedence; `backend/.env.example`
documents its shape and README's "Configuration" table each setting. A secret never goes
in a frontend variable: a `VITE_` value is compiled into the bundle every browser
downloads, so it is public by construction.

## No model-provider layer

The template ships no LLM port, adapter, or sample. The apps cut from it choose their
own provider, so a sample would be code each one deletes, and a port nothing exercises
would guess at needs no app has stated. An app that calls a model adds its own port and
adapter by [adding-a-port.md](adding-a-port.md), as a design change.
