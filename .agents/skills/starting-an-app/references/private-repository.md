# A private repository

The detail behind `starting-an-app`'s ruleset step. The workflows and the contact
routes assume a public repository. [github-settings.md](github-settings.md) ›
"Security settings" says which workflows need a paid GitHub security product
on a private repository and which run anywhere; this page is the order to act on it.
Do these steps after the bootstrap commit and before `just ruleset`.

The fix is to delete files, never to guard a job with an `if:` on visibility: a skipped
job never reports its check, and a required check that never reports blocks every pull
request.

## 1. Decide what the plan includes

If the repository's plan includes the products those workflows need, keep them and
skip to step 4. Otherwise continue.

## 2. Drop the required contexts first

Remove "Analyze (python)", "Analyze (actions)", and "Dependency Review" from
`required_status_checks` in `.github/rulesets/main.json`, keeping every other context.
`tests/test_apply_ruleset.py` pins the required list, so update its expected contexts in
the same change.

## 3. Delete the workflows

Delete `.github/workflows/codeql.yml` and `.github/workflows/dependency-review.yml`.
`osv-scanner.yml`, `security-audit.yml`, and `ci.yml`'s zizmor job stay: they run on any
repository.

## 4. Replace the public contact routes

Private vulnerability reporting works only on a public repository
([github-settings.md](github-settings.md) › "Security settings"), so every route
that points at it leads nowhere:

- `SECURITY.md`: replace the "Report it privately through GitHub's private
  vulnerability reporting" paragraph and its `[advisory]` link with the contact the
  owner names; if the bootstrap ran with `--contact-url`, the fallback paragraph already
  names it and can become the main route.
- `CODE_OF_CONDUCT.md`: the "Enforcement" paragraph points at the reporting form unless
  the bootstrap ran with `--contact-url`.
- `.github/ISSUE_TEMPLATE/config.yml`: the "Report a security vulnerability" contact
  link.

The owner names the contact: an agent never invents one, and never writes an email
address the owner did not give for this purpose.

## 5. Verify, then apply the ruleset

Run `just verify`, commit, and open a pull request: every check it waits for is now one
a job reports. Then a repository admin runs `just ruleset` (**human**). If the plan does
not allow rulesets on a private repository, `main` stays unprotected until the plan
changes: say so to the owner rather than working around it.
