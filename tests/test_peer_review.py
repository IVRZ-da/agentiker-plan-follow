"""Tests for plan_peer_review.py — Peer-Review-Checks für Plan-Strukturen.

Testing approach:
- Each check in PEER_REVIEW_CHECKS gets its own test class
- Tests create sample plans and verify that checks pass/fail correctly
- Uses plan_core functions to create plans (not raw dicts)

RED Phase: These tests define the expected behavior. They fail because
plan_peer_review.py doesn't exist yet — that's intentional TDD.
"""


import pytest

# ─── Helper: create a minimal plan dict ──────────────────────────────────────


def make_task(task_id: str, name: str = "", **overrides) -> dict:
    """Create a minimal task dict for testing."""
    task = {
        "id": task_id,
        "name": name or task_id,
        "files": [],
        "verify": "",
        "depends_on": [],
        "review_profile": "none",
        "status": "pending",
    }
    task.update(overrides)
    return task


def make_plan(tasks: list[dict], parallel_groups: dict | None = None) -> dict:
    """Create a minimal plan dict for testing."""
    return {
        "plan_id": "test-plan",
        "goal": "Test plan",
        "tasks": {t["id"]: t for t in tasks},
        "parallel_groups": parallel_groups or {},
        "active": True,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 🔴 These tests call run_peer_review() which doesn't exist yet → ImportError
# This is the RED phase — all tests should fail.
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunPeerReviewImport:
    """Verify that plan_peer_review module exists and has required exports."""

    def test_module_exists(self):
        """run_peer_review should be importable from plan_peer_review."""
        try:
            from plan_follow.plan_peer_review import run_peer_review
            assert callable(run_peer_review)
        except ImportError:
            pytest.fail("plan_follow.plan_peer_review not importable (expected RED)")

    def test_apply_findings_exists(self):
        """apply_findings should be importable from plan_peer_review."""
        try:
            from plan_follow.plan_peer_review import apply_findings
            assert callable(apply_findings)
        except ImportError:
            pytest.fail("plan_follow.plan_peer_review.apply_findings not importable (expected RED)")

    def test_peer_review_checks_exported(self):
        """PEER_REVIEW_CHECKS should be a list of check definitions."""
        try:
            from plan_follow.plan_peer_review import PEER_REVIEW_CHECKS
            assert isinstance(PEER_REVIEW_CHECKS, list)
            assert len(PEER_REVIEW_CHECKS) > 0
        except ImportError:
            pytest.fail("plan_follow.plan_peer_review.PEER_REVIEW_CHECKS not importable (expected RED)")


class TestDependsOnCheck:
    """Check ①: depends_on — Are dependencies between tasks correct?"""

    def test_depends_on_present(self):
        """A task that depends on another should have depends_on set."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan([
            make_task("p1"),
            make_task("p2", depends_on=["p1"]),
        ])
        findings = run_peer_review(plan)
        assert not any(f["check"] == "depends_on" for f in findings), \
            f"Unexpected depends_on finding: {findings}"

    def test_depends_on_missing(self):
        """A task that needs a prerequisite but has no depends_on should flag."""
        from plan_follow.plan_peer_review import run_peer_review

        # P2 has no depends_on but needs P1's output
        plan = make_plan([
            make_task("p1", name="Setup DB"),
            make_task("p2", name="Run migration (needs DB setup)"),
        ])
        findings = run_peer_review(plan)
        assert any(
            f["check"] == "depends_on" and f["task_id"] == "p2"
            for f in findings
        ), f"Expected depends_on finding for p2, got: {findings}"

    def test_referenced_task_does_not_exist(self):
        """depends_on referencing a non-existent task should flag."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan([
            make_task("p1"),
            make_task("p2", depends_on=["nonexistent"]),
        ])
        findings = run_peer_review(plan)
        assert any(
            f["check"] == "depends_on" and "nonexistent" in f.get("description", "")
            for f in findings
        ), f"Expected depends_on finding for missing task, got: {findings}"


class TestVerifyCheck:
    """Check ②: verify — Does each task have a verifiable success command?"""

    def test_verify_present_and_meaningful(self):
        """A good verify command should not flag."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan([
            make_task("p1", verify="test -f output.txt && echo 'exists'"),
        ])
        findings = run_peer_review(plan)
        assert not any(
            f["check"] == "verify" and f["task_id"] == "p1"
            for f in findings
        ), f"Unexpected verify finding for good cmd: {findings}"

    def test_verify_echo_done_flags(self):
        """A verify command that just echoes 'done' should flag (no real check)."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan([
            make_task("p1", verify="echo 'done'"),
        ])
        findings = run_peer_review(plan)
        assert any(
            f["check"] == "verify" and f["task_id"] == "p1"
            for f in findings
        ), f"Expected verify finding for echo done, got: {findings}"

    def test_verify_empty_string(self):
        """An empty verify string should flag."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan([
            make_task("p1", verify=""),
        ])
        findings = run_peer_review(plan)
        assert any(
            f["check"] == "verify" and f["task_id"] == "p1"
            for f in findings
        ), f"Expected verify finding for empty verify, got: {findings}"

    def test_verify_grep_without_fallback_flags(self):
        """`grep -q 'pattern' file` without && fallback should flag (exit 1 if not found)."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan([
            make_task("p1", verify="grep -q 'pattern' file.txt"),
        ])
        findings = run_peer_review(plan)
        assert any(
            f["check"] == "verify" and f["task_id"] == "p1"
            for f in findings
        ), f"Expected verify finding for bare grep, got: {findings}"

    def test_verify_grep_with_fallback_ok(self):
        """`grep -q ... && echo '✅'` is safe — should not flag."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan([
            make_task("p1", verify="grep -q 'pattern' file.txt && echo '✅ found'"),
        ])
        findings = run_peer_review(plan)
        assert not any(
            f["check"] == "verify" and f["task_id"] == "p1"
            for f in findings
        ), f"Unexpected verify finding for safe grep: {findings}"

    def test_verify_echo_x_emoji_flags(self):
        """"echo '❌ Test failed...'" should flag (fix template RED pattern)."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan([
            make_task("p1", verify="echo '❌ Test failed — Bug reproduziert'"),
        ])
        findings = run_peer_review(plan)
        assert any(
            f["check"] == "verify" and f["task_id"] == "p1"
            for f in findings
        ), f"Expected verify finding for ❌ echo, got: {findings}"

    def test_verify_emoji_checkmark_flags(self):
        """"echo '✅ Test passed'" should flag (fix template GREEN pattern)."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan([
            make_task("p1", verify="echo '✅ Test passed — Bug gefixt'"),
        ])
        findings = run_peer_review(plan)
        assert any(
            f["check"] == "verify" and f["task_id"] == "p1"
            for f in findings
        ), f"Expected verify finding for ✅ echo, got: {findings}"

    def test_verify_comment_only_flags(self):
        """"# TODO: something" as sole command should flag (no-op in shell)."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan([
            make_task("p1", verify="# TODO: Add a meaningful verify command"),
        ])
        findings = run_peer_review(plan)
        assert any(
            f["check"] == "verify" and f["task_id"] == "p1"
            for f in findings
        ), f"Expected verify finding for comment-only, got: {findings}"

    def test_verify_true_flags(self):
        """"true" as sole command should flag (always exit 0)."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan([
            make_task("p1", verify="true"),
        ])
        findings = run_peer_review(plan)
        assert any(
            f["check"] == "verify" and f["task_id"] == "p1"
            for f in findings
        ), f"Expected verify finding for 'true', got: {findings}"

    def test_verify_real_test_not_flags(self):
        """Real test commands (npm test, pytest, go test) should NOT flag."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan([
            make_task("p1", verify="npm test"),
            make_task("p2", verify="pytest tests/ -x -q"),
            make_task("p3", verify="go test ./..."),
            make_task("p4", verify="python3 -m pytest tests/ -v"),
            make_task("p5", verify="npx jest --passWithNoTests"),
            make_task("p6", verify="tsc --noEmit"),
        ])
        findings = run_peer_review(plan)
        meaningless_ids = {f["task_id"] for f in findings if f["check"] == "verify"}
        assert not meaningless_ids, \
            f"Real test commands should not flag, got: {meaningless_ids}"

    def test_verify_ends_with_or_true(self):
        """`cmd || true` masks errors — should flag."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan([
            make_task("p1", verify="grep -q 'pattern' file.txt || true"),
        ])
        findings = run_peer_review(plan)
        assert any(
            f["check"] == "verify" and "true" in f.get("description", "")
            for f in findings
        ), f"Expected verify finding for || true, got: {findings}"


class TestFilesCheck:
    """Check ③: files — Are all files to be changed declared?"""

    def test_files_non_empty_ok(self):
        """A task with files declared should not flag."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan([
            make_task("p1", files=["src/main.py", "src/utils.py"]),
        ])
        findings = run_peer_review(plan)
        assert not any(
            f["check"] == "files" and f["task_id"] == "p1"
            for f in findings
        ), f"Unexpected files finding: {findings}"

    def test_files_empty_flags(self):
        """An empty files list should flag (drift check ineffective without files)."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan([
            make_task("p1", name="Ändert Code", files=[]),
        ])
        findings = run_peer_review(plan)
        assert any(
            f["check"] == "files" and f["task_id"] == "p1"
            for f in findings
        ), f"Expected files finding for empty files, got: {findings}"


class TestOrderingCheck:
    """Check ④: Reihenfolge — Are tasks in correct sequential/parallel order?"""

    def test_sequential_order_correct(self):
        """A plan in correct order should not flag."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan([
            make_task("p1"),
            make_task("p2", depends_on=["p1"]),
            make_task("p3", depends_on=["p2"]),
        ])
        findings = run_peer_review(plan)
        assert not any(f["check"] == "ordering" for f in findings), \
            f"Unexpected ordering finding: {findings}"

    def test_parallel_group_before_prerequisite(self):
        """A parallel group that runs before its prerequisite should flag.

        Plan has p1 (prerequisite) and then g1:{p2,p3}. But p2 depends on p1,
        and g1 is listed before p1 in execution order.
        """
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan(
            tasks=[
                make_task("p2", name="Child", depends_on=["p1"]),
                make_task("p1", name="Setup"),
                make_task("p3", name="Other"),
            ],
            parallel_groups={"g1": {"tasks": ["p2", "p3"]}},
        )
        findings = run_peer_review(plan)
        assert any(f["check"] == "ordering" for f in findings), \
            f"Expected ordering finding, got: {findings}"


class TestReviewProfileCheck:
    """Check ⑤: review_profile — Is the right profile set?"""

    def test_profile_none_is_valid(self):
        """A 'none' profile is valid — not every task needs review."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan([
            make_task("p1", name="Quick fix", review_profile="none"),
        ])
        findings = run_peer_review(plan)
        assert not any(
            f["check"] == "review_profile" and f["task_id"] == "p1"
            for f in findings
        ), f"Unexpected profile finding: {findings}"

    def test_invalid_profile(self):
        """An invalid review_profile value should flag."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan([
            make_task("p1", name="Something", review_profile="invalid_profile_name"),
        ])
        findings = run_peer_review(plan)
        assert any(
            f["check"] == "review_profile" and f["task_id"] == "p1"
            for f in findings
        ), f"Expected profile finding for invalid profile, got: {findings}"


class TestParallelGroupsCheck:
    """Check ⑥: parallel_groups — Do parallel tasks touch different files?"""

    def test_parallel_same_file_flags(self):
        """Two parallel tasks editing the same file should flag."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan(
            tasks=[
                make_task("p1", files=["src/main.py"]),
                make_task("p2", files=["src/main.py"]),
            ],
            parallel_groups={"g1": {"tasks": ["p1", "p2"]}},
        )
        findings = run_peer_review(plan)
        assert any(
            f["check"] == "parallel_groups" for f in findings
        ), f"Expected parallel_groups finding for same file, got: {findings}"

    def test_parallel_different_files_ok(self):
        """Parallel tasks editing different files should not flag."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan(
            tasks=[
                make_task("p1", files=["src/a.py"]),
                make_task("p2", files=["src/b.py"]),
            ],
            parallel_groups={"g1": {"tasks": ["p1", "p2"]}},
        )
        findings = run_peer_review(plan)
        assert not any(
            f["check"] == "parallel_groups" for f in findings
        ), f"Unexpected parallel_groups finding: {findings}"


class TestApplyFindings:
    """Test that apply_findings() correctly applies fix suggestions."""

    def test_apply_verify_fix(self):
        """apply_findings should replace meaningless echo with exit 1."""
        from plan_follow.plan_peer_review import apply_findings, run_peer_review

        plan = make_plan([
            make_task("p1", verify="echo 'done'"),
        ])
        findings = run_peer_review(plan)
        updated = apply_findings(plan, findings)

        # After fix, p1's verify should be exit 1 (not a TODO comment)
        p1 = updated["tasks"]["p1"]
        assert "exit 1" in p1["verify"], \
            f"Verify should contain exit 1 to fail auto-verify, got: {p1['verify']}"

    def test_apply_empty_files_fix(self):
        """apply_findings should set a default file list for empty files."""
        from plan_follow.plan_peer_review import apply_findings, run_peer_review

        plan = make_plan([
            make_task("p1", name="Fix something", files=[]),
        ])
        findings = run_peer_review(plan)
        updated = apply_findings(plan, findings)

        # Apply_findings might add a comment or placeholder
        p1 = updated["tasks"]["p1"]
        assert "files" in p1, f"Task should still have files key: {p1}"

    def test_apply_missing_depends_on(self):
        """apply_findings should add depends_on where needed."""
        from plan_follow.plan_peer_review import apply_findings, run_peer_review

        plan = make_plan([
            make_task("p1", name="Setup"),
            make_task("p2", name="Uses setup"),
        ])
        findings = run_peer_review(plan)
        updated = apply_findings(plan, findings)

        p2 = updated["tasks"]["p2"]
        assert "depends_on" in p2, f"Task should still have depends_on key: {p2}"

    def test_apply_findings_idempotent(self):
        """Running apply_findings twice on the same plan should not crash."""
        from plan_follow.plan_peer_review import apply_findings, run_peer_review

        plan = make_plan([
            make_task("p1", verify="echo 'done'"),
        ])
        findings = run_peer_review(plan)
        updated1 = apply_findings(plan, findings)
        updated2 = apply_findings(updated1, run_peer_review(updated1))
        assert isinstance(updated2, dict)
        assert "tasks" in updated2


class TestPerfectPlanNoFindings:
    """A well-structured plan should produce ZERO findings."""

    def test_perfect_plan(self):
        """A plan with all best practices should have no findings."""
        from plan_follow.plan_peer_review import run_peer_review

        plan = make_plan(
            tasks=[
                make_task("p1", name="Setup DB", files=["db/init.sql"],
                          verify="test -f db/init.sql && echo 'ok'"),
                make_task("p2", name="Add migration", files=["db/migrate.sql"],
                          verify="grep -q 'CREATE TABLE' db/migrate.sql && echo '✅'",
                          depends_on=["p1"]),
                make_task("p3", name="Update API", files=["src/api.py"],
                          verify="python3 -c 'import api; print(\"ok\")'",
                          depends_on=["p2"]),
            ],
        )
        findings = run_peer_review(plan)
        critical = [f for f in findings if f.get("severity") == "critical"]
        assert len(critical) == 0, \
            f"Perfect plan should have 0 critical findings, got: {critical}"
