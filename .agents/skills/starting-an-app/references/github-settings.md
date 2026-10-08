# GitHub settings a new repository must enable

The list behind `starting-an-app`'s security-settings and ruleset steps. Every setting
here is a human step on GitHub: an agent lists it for the owner and never changes it.

## Main branch ruleset

`.github/rulesets/main.json` protects the default branch: no deletion, no force-push, a
pull request for every change (0 approvals), and the required status checks.
`just ruleset` creates it, or updates it by name, through `gh api`; it never deletes a
ruleset. Writing rulesets needs repository admin rights, so **`just ruleset` is a human
(admin) step** — an agent never runs it. Rerun it after editing `main.json`.

What makes a job fit to be a required check, and what a CI change owes `main.json`, is
`changing-gates`' "CI workflows and required checks".

## Security settings

Of the security workflows, only CodeQL (`codeql.yml`) uploads results, to code
scanning; OSV-Scanner (`osv-scanner.yml`) and gitleaks (`security-audit.yml`) just fail
the job. These are separate repository settings to turn on:

- Secret scanning, and its push protection
- Private vulnerability reporting (the route `SECURITY.md` gives)
- Dependabot alerts
- The dependency graph, which Dependency Review (`dependency-review.yml`) needs

Do not enable CodeQL "default setup": it rejects uploads from the advanced `codeql.yml`,
which fails the required "Analyze" checks.

On a private repository, CodeQL and Dependency Review need GitHub Code Security, and
secret scanning needs GitHub Secret Protection; `osv-scanner.yml`, `security-audit.yml`,
and `ci.yml`'s zizmor job run anywhere. Private vulnerability reporting works only on
public repositories. What a private repository does about both, in order, is
[private-repository.md](private-repository.md).
