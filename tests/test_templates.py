"""Tests for plan_templates.py — Template-Engine."""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


# ─── expand_template ──────────────────────────────────────────────────────────

class TestExpandTemplate:
    """Tests for expand_template — the main public API."""

    def test_deploy_template(self):
        from plan_follow.plan_templates import expand_template
        result = expand_template("deploy")
        assert "error" not in result
        assert len(result["tasks"]) == 5  # p0 + 4 deploy-Tasks
        assert result["review_profile"] == "api-route"
        assert "Deployment" in result["description"]

    def test_bugfix_template(self):
        from plan_follow.plan_templates import expand_template
        result = expand_template("bugfix")
        assert "error" not in result
        assert len(result["tasks"]) == 4  # p0 + 3 bugfix-Tasks
        assert result["review_profile"] == "unit-test"

    def test_feature_template(self):
        from plan_follow.plan_templates import expand_template
        result = expand_template("feature")
        assert len(result["tasks"]) == 5  # p0 + 4 feature-Tasks
        assert result["review_profile"] == "unit-test"

    def test_refactoring_template(self):
        from plan_follow.plan_templates import expand_template
        result = expand_template("refactoring")
        assert len(result["tasks"]) == 5  # p0 + 4 refactoring-Tasks
        assert result["review_profile"] == "full"

    def test_research_template(self):
        from plan_follow.plan_templates import expand_template
        result = expand_template("research")
        assert len(result["tasks"]) == 4  # p0 + 3 research-Tasks
        assert result["review_profile"] == "none"

    def test_analysis_template(self):
        from plan_follow.plan_templates import expand_template
        result = expand_template("analysis")
        assert len(result["tasks"]) == 5  # p0 + 4 analysis-Tasks
        assert result["review_profile"] == "unit-test"

    def test_unknown_template(self):
        from plan_follow.plan_templates import expand_template
        result = expand_template("nonexistent")
        assert "error" in result
        assert "not found" in result["error"]

    def test_parameter_substitution(self):
        from plan_follow.plan_templates import expand_template
        result = expand_template("deploy", params={"env": "production", "service": "medusa-prod"})
        deploy_task = result["tasks"][3]  # [p0, d1, d2, d3, d4] → d3
        assert "production" in deploy_task["name"]
        assert "medusa-prod" in deploy_task["verify"]

    def test_default_params(self):
        from plan_follow.plan_templates import expand_template
        result = expand_template("deploy")
        # Default values from TEMPLATE_DEFAULTS
        deploy_task = result["tasks"][3]  # [p0, d1, d2, d3, d4] → d3
        assert "app-service" in deploy_task["verify"]

    def test_parameter_override(self):
        from plan_follow.plan_templates import expand_template
        # User param overrides default
        result = expand_template("deploy", params={"service": "medusa-custom"})
        deploy_task = result["tasks"][3]  # [p0, d1, d2, d3, d4] → d3
        assert "medusa-custom" in deploy_task["verify"]
        assert "app-service" not in deploy_task["verify"]


# ─── _substitute_params ───────────────────────────────────────────────────────

class TestSubstituteParams:
    """Tests for _substitute_params — {{param}} placeholder replacement."""

    def test_string_substitution(self):
        from plan_follow.plan_templates import _substitute_params
        result = _substitute_params("Hello {{name}}!", {"name": "World"})
        assert result == "Hello World!"

    def test_no_placeholder(self):
        from plan_follow.plan_templates import _substitute_params
        result = _substitute_params("Plain text", {"key": "val"})
        assert result == "Plain text"

    def test_list_substitution(self):
        from plan_follow.plan_templates import _substitute_params
        result = _substitute_params(["a_{{n}}", "b_{{n}}"], {"n": "1"})
        assert result == ["a_1", "b_1"]

    def test_dict_substitution(self):
        from plan_follow.plan_templates import _substitute_params
        result = _substitute_params({"key": "val_{{x}}"}, {"x": "99"})
        assert result == {"key": "val_99"}

    def test_multiple_placeholders(self):
        from plan_follow.plan_templates import _substitute_params
        result = _substitute_params("{{a}}-{{b}}-{{c}}", {"a": "1", "b": "2", "c": "3"})
        assert result == "1-2-3"

    def test_unknown_placeholder_left_untouched(self):
        from plan_follow.plan_templates import _substitute_params
        result = _substitute_params("{{unknown}}", {"known": "val"})
        assert result == "{{unknown}}"


# ─── get_template_names ───────────────────────────────────────────────────────

class TestGetTemplateNames:
    """Tests for get_template_names."""

    def test_returns_sorted_list(self):
        from plan_follow.plan_templates import get_template_names
        names = get_template_names()
        assert isinstance(names, list)
        assert "deploy" in names
        assert "bugfix" in names
        assert "feature" in names
        assert "analysis" in names
        assert len(names) >= 6

    def test_names_are_sorted(self):
        from plan_follow.plan_templates import get_template_names
        names = get_template_names()
        assert names == sorted(names)


# ─── _load_user_templates ─────────────────────────────────────────────────────

class TestLoadUserTemplates:
    """Tests for _load_user_templates — loading YAML from disk."""

    def test_no_templates_dir(self, monkeypatch):
        import tempfile

        from plan_follow.plan_templates import _load_user_templates
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        monkeypatch.setattr("plan_follow.plan_templates.TEMPLATES_DIR", fake_dir)
        result = _load_user_templates()
        assert result == {}

    def test_load_valid_template(self, tmp_path, monkeypatch):
        from plan_follow.plan_templates import _load_user_templates
        monkeypatch.setattr("plan_follow.plan_templates.TEMPLATES_DIR", tmp_path)
        yaml_file = tmp_path / "my_template.yaml"
        yaml_file.write_text(yaml.dump({
            "name": "my_template",
            "description": "My custom template",
            "tasks": [{"id": "t1", "name": "Task 1", "files": [], "verify": "", "depends_on": []}],
            "review_profile": "unit-test",
        }))
        result = _load_user_templates()
        assert "my_template" in result
        assert result["my_template"]["description"] == "My custom template"
        assert len(result["my_template"]["tasks"]) == 1
        assert result["my_template"]["review_profile"] == "unit-test"

    def test_corrupt_yaml(self, tmp_path, monkeypatch, caplog):
        import logging

        from plan_follow.plan_templates import _load_user_templates
        caplog.set_level(logging.WARNING)
        monkeypatch.setattr("plan_follow.plan_templates.TEMPLATES_DIR", tmp_path)
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("{invalid: yaml: : : }")
        result = _load_user_templates()
        assert result == {}

    def test_multiple_templates(self, tmp_path, monkeypatch):
        from plan_follow.plan_templates import _load_user_templates
        monkeypatch.setattr("plan_follow.plan_templates.TEMPLATES_DIR", tmp_path)
        for name in ["alpha", "beta"]:
            (tmp_path / f"{name}.yaml").write_text(
                yaml.dump({"name": name, "tasks": [{"id": "t1", "name": name, "files": [], "verify": "", "depends_on": []}]})  # noqa: E501
            )
        result = _load_user_templates()
        assert "alpha" in result
        assert "beta" in result
        assert len(result) == 2

    def test_non_dict_yaml(self, tmp_path, monkeypatch):
        from plan_follow.plan_templates import _load_user_templates
        monkeypatch.setattr("plan_follow.plan_templates.TEMPLATES_DIR", tmp_path)
        yaml_file = tmp_path / "list.yaml"
        yaml_file.write_text("- just\n- a\n- list")
        result = _load_user_templates()
        assert result == {}


# ─── _get_all_templates ───────────────────────────────────────────────────────

class TestGetAllTemplates:
    """Tests for _get_all_templates — merge built-in and user templates."""

    def test_builtin_templates_present(self):
        from plan_follow.plan_templates import _get_all_templates
        all_tpl = _get_all_templates()
        assert "deploy" in all_tpl
        assert len(all_tpl) >= 6

    def test_user_template_overrides_builtin(self, tmp_path, monkeypatch):
        from plan_follow.plan_templates import _get_all_templates
        monkeypatch.setattr("plan_follow.plan_templates.TEMPLATES_DIR", tmp_path)
        # Create a user template with the same name as a built-in
        yaml_file = tmp_path / "deploy.yaml"
        yaml_file.write_text(yaml.dump({
            "name": "deploy",
            "description": "OVERRIDDEN by user",
            "tasks": [{"id": "x1", "name": "Custom step", "files": [], "verify": "", "depends_on": []}],
        }))
        all_tpl = _get_all_templates()
        assert all_tpl["deploy"]["description"] == "OVERRIDDEN by user"
        assert len(all_tpl["deploy"]["tasks"]) == 1


# ─── _parse_yaml_simple ───────────────────────────────────────────────────────

class TestParseYamlSimple:
    """Tests for _parse_yaml_simple — YAML parsing wrapper."""

    def test_parse_simple_key_value(self):
        from plan_follow.plan_templates import _parse_yaml_simple
        result = _parse_yaml_simple("name: test\ngoal: hello")
        assert result == {"name": "test", "goal": "hello"}

    def test_parse_list(self):
        from plan_follow.plan_templates import _parse_yaml_simple
        result = _parse_yaml_simple("- item1\n- item2")
        assert result == ["item1", "item2"]

    def test_parse_empty_string(self):
        from plan_follow.plan_templates import _parse_yaml_simple
        result = _parse_yaml_simple("")
        assert result is None

    def test_parse_json_string(self):
        """yaml.safe_load handles JSON too (JSON is valid YAML)."""
        from plan_follow.plan_templates import _parse_yaml_simple
        result = _parse_yaml_simple('{"key": "value"}')
        assert result == {"key": "value"}
