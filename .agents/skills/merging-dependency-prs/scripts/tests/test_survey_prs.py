#!/usr/bin/env python3
"""Tests for survey_prs.py. Stdlib-only (unittest).

Run: just test-skills
     (or python3 -m unittest discover -s scripts/tests -t scripts/tests
      from the merging-dependency-prs skill directory)
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import survey_prs as sp


def pr(number, title, *, login="app/dependabot", branch=None, rollup=None, files=()):
    return {
        "number": number,
        "title": title,
        "author": {"login": login},
        "headRefName": branch or f"dependabot/github_actions/x-{number}",
        "baseRefName": "main",
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "statusCheckRollup": rollup
        if rollup is not None
        else [
            {
                "name": "Lint & Type Check",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
            },
        ],
        "labels": [{"name": "dependencies"}],
        "files": [{"path": p} for p in files],
        "createdAt": "2026-10-01T00:00:00Z",
        "url": f"https://github.com/acme/widgets/pull/{number}",
    }


class ParseVersionsTest(unittest.TestCase):
    def test_bump_title(self):
        self.assertEqual(
            sp.parse_versions("chore(deps): bump actions/checkout from 7.0.0 to 7.1.0"),
            ("actions/checkout", "7.0.0", "7.1.0"),
        )

    def test_requirement_title(self):
        self.assertEqual(
            sp.parse_versions("update mypy requirement from >=2.1.0 to >=2.2.0"),
            ("mypy", ">=2.1.0", ">=2.2.0"),
        )

    def test_grouped_title_without_versions_is_unparsed(self):
        self.assertEqual(
            sp.parse_versions("chore(deps): bump the actions group with 3 updates"),
            (None, None, None),
        )


class SemverLevelTest(unittest.TestCase):
    def test_levels(self):
        cases = [
            ("7.0.0", "8.0.0", "major"),
            ("7.0.0", "7.1.0", "minor"),
            ("7.0.0", "7.0.1", "patch"),
            (">=3.7", ">=3.8", "minor"),
            ("v9", "v10", "unknown"),
            (None, "1.0.0", "unknown"),
        ]
        for old, new, expected in cases:
            with self.subTest(old=old, new=new):
                self.assertEqual(sp.semver_level(old, new), expected)

    def test_pre_one_minor_is_major_and_flagged(self):
        self.assertEqual(sp.semver_level("0.15.1", "0.16.0"), "major")
        self.assertTrue(sp.is_pre_one_minor_bump("0.15.1", "0.16.0"))

    def test_pre_one_patch_is_not_flagged(self):
        self.assertEqual(sp.semver_level("0.15.1", "0.15.2"), "patch")
        self.assertFalse(sp.is_pre_one_minor_bump("0.15.1", "0.15.2"))


class CheckSummaryTest(unittest.TestCase):
    def test_empty_rollup_is_none(self):
        self.assertEqual(sp.check_summary([]), ("NONE", []))
        self.assertEqual(sp.check_summary(None), ("NONE", []))

    def test_success_neutral_skipped_pass(self):
        rollup = [
            {"name": "a", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"name": "b", "status": "COMPLETED", "conclusion": "NEUTRAL"},
            {"name": "c", "status": "COMPLETED", "conclusion": "SKIPPED"},
            {"context": "d", "state": "SUCCESS"},
        ]
        self.assertEqual(sp.check_summary(rollup), ("PASSING", []))

    def test_in_flight_check_run_is_pending(self):
        rollup = [{"name": "a", "status": "IN_PROGRESS", "conclusion": ""}]
        self.assertEqual(sp.check_summary(rollup), ("PENDING", []))

    def test_commit_status_pending_is_pending(self):
        self.assertEqual(
            sp.check_summary([{"context": "a", "state": "PENDING"}]), ("PENDING", [])
        )

    def test_unrecognised_and_absent_conclusions_fail_closed(self):
        rollup = [
            {"name": "ok", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"name": "boot", "status": "COMPLETED", "conclusion": "STARTUP_FAILURE"},
            {"name": "old", "status": "COMPLETED", "conclusion": "STALE"},
            {"name": "blank", "status": "COMPLETED"},
        ]
        self.assertEqual(
            sp.check_summary(rollup),
            ("FAILING", ["boot=STARTUP_FAILURE", "old=STALE", "blank=UNKNOWN"]),
        )

    def test_failure_outranks_pending(self):
        rollup = [
            {"name": "a", "status": "QUEUED"},
            {"name": "b", "status": "COMPLETED", "conclusion": "FAILURE"},
        ]
        self.assertEqual(sp.check_summary(rollup), ("FAILING", ["b=FAILURE"]))


class EcosystemTest(unittest.TestCase):
    def test_actions_branch(self):
        self.assertEqual(
            sp.ecosystem_of("dependabot/github_actions/actions-abc"), "github_actions"
        )

    def test_pre_commit_branch_is_recognized(self):
        self.assertEqual(
            sp.ecosystem_of("dependabot/pre_commit/hooks-abc"), "pre_commit"
        )

    def test_pre_commit_as_a_package_name_is_other(self):
        self.assertEqual(sp.ecosystem_of("dependabot/pip/pre_commit-1.0.0"), "other")

    def test_uv_branch(self):
        self.assertEqual(sp.ecosystem_of("dependabot/uv/ruff-0.16.0"), "uv")

    def test_grouped_uv_branch(self):
        self.assertEqual(
            sp.ecosystem_of("dependabot/uv/python-minor-patch-1a2b3c4d5e"), "uv"
        )

    def test_uv_as_a_package_name_is_not_the_uv_ecosystem(self):
        self.assertEqual(sp.ecosystem_of("dependabot/pip/uv-0.12.1"), "other")

    def test_uv_branch_naming_github_actions_is_uv(self):
        self.assertEqual(
            sp.ecosystem_of("dependabot/uv/github_actions-helper-1.2.0"), "uv"
        )

    def test_github_actions_as_a_later_segment_is_other(self):
        self.assertEqual(
            sp.ecosystem_of("dependabot/pip/github_actions-1.0.0"), "other"
        )

    def test_anything_else_is_other(self):
        self.assertEqual(sp.ecosystem_of("dependabot/pip/requests-2.33.0"), "other")


class SelectRowsTest(unittest.TestCase):
    def test_keeps_only_dependabot_sorted_by_number(self):
        prs = [
            pr(9, "bump a from 1.0.0 to 1.1.0"),
            pr(3, "feat: human work", login="octocat"),
            pr(2, "bump b from 0.1.0 to 0.2.0"),
        ]
        rows = sp.select_bot_rows(prs)
        self.assertEqual([r["number"] for r in rows], [2, 9])
        self.assertTrue(rows[0]["pre_one_minor"])
        self.assertEqual(rows[0]["level"], "major")
        self.assertEqual(rows[1]["checks"], "PASSING")

    def test_contested_files(self):
        rows = sp.select_bot_rows(
            [
                pr(1, "bump a from 1.0.0 to 1.0.1", files=[".github/workflows/ci.yml"]),
                pr(
                    2,
                    "bump b from 1.0.0 to 1.0.1",
                    files=[".github/workflows/ci.yml", "x"],
                ),
                pr(3, "bump c from 1.0.0 to 1.0.1", files=["y"]),
            ]
        )
        self.assertEqual(sp.contested_files(rows), {".github/workflows/ci.yml": [1, 2]})


class MainTest(unittest.TestCase):
    def _run(self, argv, payload):
        completed = subprocess.CompletedProcess(
            args=["gh"], returncode=0, stdout=json.dumps(payload), stderr=""
        )
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.object(sp.subprocess, "run", return_value=completed) as run,
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            rc = sp.main(argv)
        return rc, out.getvalue(), err.getvalue(), run

    def test_json_output_and_read_only_call(self):
        rc, out, _, run = self._run(["--json"], [pr(5, "bump a from 1.0.0 to 2.0.0")])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)[0]["level"], "major")
        argv = run.call_args.args[0]
        self.assertEqual(argv[:3], ["gh", "pr", "list"])

    def test_text_report_flags_pre_one_minor_and_unknown(self):
        rc, out, _, _ = self._run(
            [],
            [
                pr(1, "bump a from 0.1.0 to 0.2.0"),
                pr(2, "bump the actions group with 2 updates"),
            ],
        )
        self.assertEqual(rc, 0)
        self.assertIn("2 open Dependabot PR(s)", out)
        self.assertIn("FLAG: 0.x minor change", out)
        self.assertIn("FLAG: versions not parsed", out)

    def test_text_report_lands_uv_lock_overlap_one_at_a_time(self):
        rc, out, _, _ = self._run(
            [],
            [
                pr(
                    1,
                    "bump a from 1.0.0 to 1.0.1",
                    branch="dependabot/uv/a-1.0.1",
                    files=["pyproject.toml", "uv.lock"],
                ),
                pr(
                    2,
                    "bump b from 1.0.0 to 2.0.0",
                    branch="dependabot/uv/b-2.0.0",
                    files=["pyproject.toml", "uv.lock"],
                ),
            ],
        )
        self.assertEqual(rc, 0)
        self.assertNotIn("favor a combined branch", out)
        self.assertIn("land one at a time", out)
        self.assertIn("uv.lock: #1, #2", out)

    def test_text_report_lands_workspace_member_manifest_one_at_a_time(self):
        rc, out, _, _ = self._run(
            [],
            [
                pr(
                    1,
                    "bump a from 1.0.0 to 1.0.1",
                    branch="dependabot/uv/a-1.0.1",
                    files=["backend/pyproject.toml", "uv.lock"],
                ),
                pr(
                    2,
                    "bump b from 1.0.0 to 2.0.0",
                    branch="dependabot/uv/b-2.0.0",
                    files=["backend/pyproject.toml", "uv.lock"],
                ),
            ],
        )
        self.assertEqual(rc, 0)
        self.assertNotIn("favor a combined branch", out)
        self.assertIn("land one at a time", out)
        self.assertIn("backend/pyproject.toml: #1, #2", out)

    def test_text_report_favors_combined_branch_for_workflow_overlap(self):
        rc, out, _, _ = self._run(
            [],
            [
                pr(1, "bump a from 1.0.0 to 1.0.1", files=[".github/workflows/ci.yml"]),
                pr(2, "bump b from 1.0.0 to 1.0.1", files=[".github/workflows/ci.yml"]),
            ],
        )
        self.assertEqual(rc, 0)
        self.assertIn("favor a combined branch", out)
        self.assertNotIn("land one at a time", out)

    def test_no_rows(self):
        rc, out, _, _ = self._run([], [])
        self.assertEqual(rc, 0)
        self.assertIn("No open Dependabot PRs.", out)

    def test_gh_failure_exits_1_with_next_step(self):
        failed = subprocess.CompletedProcess(
            args=["gh"], returncode=4, stdout="", stderr="auth required"
        )
        err = io.StringIO()
        with (
            patch.object(sp.subprocess, "run", return_value=failed),
            redirect_stdout(io.StringIO()),
            redirect_stderr(err),
        ):
            rc = sp.main([])
        self.assertEqual(rc, 1)
        self.assertIn("ERR_GH_FAILED", err.getvalue())
        self.assertIn("gh auth status", err.getvalue())

    def test_missing_gh_exits_1(self):
        err = io.StringIO()
        with (
            patch.object(sp.subprocess, "run", side_effect=FileNotFoundError("gh")),
            redirect_stdout(io.StringIO()),
            redirect_stderr(err),
        ):
            rc = sp.main([])
        self.assertEqual(rc, 1)
        self.assertIn("ERR_GH_UNAVAILABLE", err.getvalue())


if __name__ == "__main__":
    unittest.main()
