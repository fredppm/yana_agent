#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Unit tests for init-sanctum.py

Tests the deterministic scaffolding functions in isolation.
Run with: python scripts/tests/test-init-sanctum.py
"""

import sys
import tempfile
import unittest
from pathlib import Path

# Add parent directory to path so we can import init-sanctum functions
sys.path.insert(0, str(Path(__file__).parent.parent))

# init-sanctum uses a hyphen which makes standard import fail — load via importlib
import importlib.util

spec = importlib.util.spec_from_file_location(
    "init_sanctum",
    Path(__file__).parent.parent / "init-sanctum.py",
)
init_sanctum = importlib.util.module_from_spec(spec)
spec.loader.exec_module(init_sanctum)


class TestParseYamlConfig(unittest.TestCase):
    def test_parses_simple_key_value(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("user_name: Fred\ncommunication_language: Portugues\n")
            f.flush()
            result = init_sanctum.parse_yaml_config(Path(f.name))
        self.assertEqual(result["user_name"], "Fred")
        self.assertEqual(result["communication_language"], "Portugues")

    def test_ignores_comments_and_blanks(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("# comment\n\nkey: value\n")
            f.flush()
            result = init_sanctum.parse_yaml_config(Path(f.name))
        self.assertEqual(result["key"], "value")
        self.assertNotIn("# comment", result)

    def test_missing_file_returns_empty(self):
        result = init_sanctum.parse_yaml_config(Path("/nonexistent/config.yaml"))
        self.assertEqual(result, {})

    def test_strips_quotes(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write('name: "Fred"\n')
            f.flush()
            result = init_sanctum.parse_yaml_config(Path(f.name))
        self.assertEqual(result["name"], "Fred")


class TestParseTomlConfig(unittest.TestCase):
    def test_parses_core_section(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write('[core]\nuser_name = "Fred"\ncommunication_language = "Portugues"\n')
            f.flush()
            result = init_sanctum.parse_toml_config(Path(f.name))
        self.assertEqual(result["user_name"], "Fred")
        self.assertEqual(result["communication_language"], "Portugues")

    def test_ignores_non_core_sections(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write('[other]\nkey = "val"\n[core]\nname = "Fred"\n')
            f.flush()
            result = init_sanctum.parse_toml_config(Path(f.name))
        self.assertEqual(result.get("name"), "Fred")
        self.assertNotIn("key", result)

    def test_missing_file_returns_empty(self):
        result = init_sanctum.parse_toml_config(Path("/nonexistent/config.toml"))
        self.assertEqual(result, {})


class TestParseFrontmatter(unittest.TestCase):
    def test_extracts_frontmatter_fields(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("---\nname: day-planning\ncode: DA\ndescription: Test cap\n---\n\n# Body\n")
            f.flush()
            result = init_sanctum.parse_frontmatter(Path(f.name))
        self.assertEqual(result["name"], "day-planning")
        self.assertEqual(result["code"], "DA")
        self.assertEqual(result["description"], "Test cap")

    def test_returns_empty_for_no_frontmatter(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Just a heading\n\nNo frontmatter here.\n")
            f.flush()
            result = init_sanctum.parse_frontmatter(Path(f.name))
        self.assertEqual(result, {})


class TestSubstituteVars(unittest.TestCase):
    def test_substitutes_known_variables(self):
        content = "Hello {user_name}, born on {birth_date}."
        result = init_sanctum.substitute_vars(
            content, {"user_name": "Fred", "birth_date": "2026-06-10"}
        )
        self.assertEqual(result, "Hello Fred, born on 2026-06-10.")

    def test_leaves_unknown_placeholders_intact(self):
        content = "Hello {unknown_var}."
        result = init_sanctum.substitute_vars(content, {"user_name": "Fred"})
        self.assertEqual(result, "Hello {unknown_var}.")

    def test_empty_vars_dict(self):
        content = "No substitution {here}."
        result = init_sanctum.substitute_vars(content, {})
        self.assertEqual(result, "No substitution {here}.")


class TestDiscoverCapabilities(unittest.TestCase):
    def test_discovers_capability_files_with_code(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            refs_dir = Path(tmpdir)
            cap_file = refs_dir / "day-planning.md"
            cap_file.write_text(
                "---\nname: day-planning\ncode: DA\ndescription: Manage agenda\n---\n\n# Day Planning\n"
            )

            result = init_sanctum.discover_capabilities(refs_dir, "./references")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["code"], "DA")
        self.assertEqual(result[0]["name"], "day-planning")

    def test_skips_files_without_code(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            refs_dir = Path(tmpdir)
            (refs_dir / "memory-guidance.md").write_text(
                "---\nname: memory-guidance\n---\n\n# Guidance\n"
            )

            result = init_sanctum.discover_capabilities(refs_dir, "./references")

        self.assertEqual(len(result), 0)

    def test_skips_skill_only_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            refs_dir = Path(tmpdir)
            (refs_dir / "first-breath.md").write_text(
                "---\nname: first-breath\ncode: FB\n---\n\n# First Breath\n"
            )

            result = init_sanctum.discover_capabilities(refs_dir, "./references")

        self.assertEqual(len(result), 0)


class TestGenerateCapabilitiesMd(unittest.TestCase):
    def test_generates_table_with_capabilities(self):
        caps = [
            {
                "code": "DA",
                "name": "day-planning",
                "description": "Test",
                "source": "./references/day-planning.md",
            }
        ]
        result = init_sanctum.generate_capabilities_md(caps, evolvable=False)
        self.assertIn("| [DA] | day-planning |", result)
        self.assertNotIn("## Learned", result)

    def test_includes_learned_section_when_evolvable(self):
        caps = []
        result = init_sanctum.generate_capabilities_md(caps, evolvable=True)
        self.assertIn("## Learned", result)
        self.assertIn("capability-authoring.md", result)

    def test_includes_configured_connections(self):
        result = init_sanctum.generate_capabilities_md([], evolvable=False)
        self.assertIn("Google Calendar", result)
        self.assertIn("Garmin Connect", result)
        self.assertIn("Home Assistant", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
