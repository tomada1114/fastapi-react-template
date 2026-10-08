"""Self-checks of the agent harness: cross-file drift fails CI, not an agent.

`just check-harness` runs this package (and `tests/test_product_section.py`);
`just verify` and CI's Coverage job run it too. Each check passes on the
repository and fails on a fixture built under ``tmp_path``:

- (a) ``test_skills.py``: every ``.agents/skills/<dir>/SKILL.md`` frontmatter
  holds only ``name`` (equal to ``<dir>``) and an ASCII ``description`` within
  the authoring-skills limit, the body is at most 200 lines, and no nested
  ``SKILL.md`` exists;
- (b) ``test_skills.py``: AGENTS.md's Skills table lists exactly those skills;
- (c) ``test_just_recipes.py``: every ``just <recipe>`` in command position
  in the top-level Markdown, ``docs/**`` (bar the ADRs, the roadmap, and
  ``docs/product/``), the skills, the agent definitions, ``.github/**``
  (composite actions' ``run:`` included), ``.pre-commit-config.yaml``, and
  the scripts exists in the justfile (its docstring lists what is not read);
- (d) ``test_ruleset_contexts.py``: every required context in
  ``.github/rulesets/main.json`` is a job that runs on every pull request and
  cannot be skipped, and one with ``needs:`` has a step, in one of the
  shapes ``_needs.py`` lists, that fails when a needed job's result is not
  ``success``;
- (e) ``test_labels.py``: every label pr-label.yml, the issue forms, and
  dependabot.yml apply is declared exactly once in ``.github/labels.yml``,
  and with more than one Dependabot ecosystem each update sets ``labels:``;
- (f) ``test_workflow_hygiene.py``: workflow hygiene (SHA pins, timeouts,
  top-level permissions, checkout credentials, no fail-open constructs, push
  runs on main never cancelled by concurrency), and the same pin, checkout,
  ``continue-on-error``, and ``|| true`` rules for a composite action under
  ``.github/actions/``;
- (h) ``test_dependabot_cooldown.py``: the Dependabot ``uv`` update's
  ``cooldown.default-days`` equals ``[tool.uv] exclude-newer``'s day count;
- (i) ``test_quick_reference.py``: AGENTS.md's Quick Reference names every
  justfile recipe but ``default``, and its ``just verify`` line lists
  ``verify``'s dependencies in order;
- (g) the Product section check is ``tests/test_product_section.py`` (#95),
  not duplicated here.

The checks hold in the template and in an app the bootstrap cut from it, so
none assumes a template-only file exists. ``_yaml.py`` loads YAML safely and
validates consumed value shapes; ``_workflows.py`` interprets workflow triggers
and matrices on top of that shared boundary.
"""
