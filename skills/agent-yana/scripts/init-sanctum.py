#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
First Breath — Deterministic sanctum scaffolding for YANA.

This script runs BEFORE the conversational awakening. It creates the sanctum
folder structure, copies template files with config values substituted,
copies all capability files into the sanctum, and auto-generates
CAPABILITIES.md from capability prompt frontmatter.

After this script runs, the sanctum is fully self-contained — YANA does
not depend on the skill bundle location for normal operation.

Usage:
    python3 init-sanctum.py <project-root> <skill-path>

    project-root: The root of the project (where _bmad/ lives)
    skill-path:   Path to the skill directory (where SKILL.md, references/, assets/ live)
"""

import argparse
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

# --- Agent-specific configuration ---

SKILL_NAME = "agent-yana"
SANCTUM_DIR = SKILL_NAME

# Files that stay in the skill bundle (only used during First Breath, not copied to sanctum)
SKILL_ONLY_FILES = {"first-breath.md"}

TEMPLATE_FILES = [
    "INDEX-template.md",
    "PERSONA-template.md",
    "CREED-template.md",
    "BOND-template.md",
    "MEMORY-template.md",
    "PULSE-template.md",
]

# Non-template assets copied as-is (no -template suffix removal, no uppercasing)
ASSET_FILES = [
    "pulse-config.yaml",
]

# Owner can teach YANA new capabilities over time
EVOLVABLE = True

# --- End agent-specific configuration ---


def parse_yaml_config(config_path: Path) -> dict:
    """Simple YAML key-value parser. Handles top-level scalar values only."""
    config = {}
    if not config_path.exists():
        return config
    with open(config_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, _, value = line.partition(":")
                value = value.strip().strip("'\"")
                if value:
                    config[key.strip()] = value
    return config


def parse_toml_config(config_path: Path) -> dict:
    """Simple TOML key-value parser for _bmad/config.toml. Handles [core] section."""
    config = {}
    if not config_path.exists():
        return config
    in_core = False
    with open(config_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("["):
                in_core = line == "[core]"
                continue
            if in_core and "=" in line:
                key, _, value = line.partition("=")
                value = value.strip().strip("'\"")
                if value:
                    config[key.strip()] = value
    return config


def parse_frontmatter(file_path: Path) -> dict:
    """Extract YAML frontmatter from a markdown file."""
    meta = {}
    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return meta

    for line in match.group(1).strip().split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip("'\"")
    return meta


def copy_references(source_dir: Path, dest_dir: Path) -> list[str]:
    """Copy all reference files (except skill-only files) into the sanctum."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = []

    for source_file in sorted(source_dir.iterdir()):
        if source_file.name in SKILL_ONLY_FILES:
            continue
        if source_file.is_file():
            shutil.copy2(source_file, dest_dir / source_file.name)
            copied.append(source_file.name)

    return copied


def copy_scripts(source_dir: Path, dest_dir: Path) -> list[str]:
    """Copy any scripts the capabilities might use into the sanctum."""
    if not source_dir.exists():
        return []
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = []

    for source_file in sorted(source_dir.iterdir()):
        if source_file.is_file() and source_file.name != "init-sanctum.py":
            shutil.copy2(source_file, dest_dir / source_file.name)
            copied.append(source_file.name)

    return copied


def discover_capabilities(references_dir: Path, sanctum_refs_path: str) -> list[dict]:
    """Scan references/ for capability prompt files with frontmatter code field."""
    capabilities = []

    for md_file in sorted(references_dir.glob("*.md")):
        if md_file.name in SKILL_ONLY_FILES:
            continue
        meta = parse_frontmatter(md_file)
        if meta.get("name") and meta.get("code"):
            capabilities.append(
                {
                    "name": meta["name"],
                    "description": meta.get("description", ""),
                    "code": meta["code"],
                    "source": f"{sanctum_refs_path}/{md_file.name}",
                }
            )
    return capabilities


def generate_capabilities_md(capabilities: list[dict], evolvable: bool) -> str:
    """Generate CAPABILITIES.md content from discovered capabilities."""
    lines = [
        "# Capabilities",
        "",
        "## Built-in",
        "",
        "| Code | Name | Description | Source |",
        "|------|------|-------------|--------|",
    ]
    for cap in capabilities:
        lines.append(
            f"| [{cap['code']}] | {cap['name']} | {cap['description']} | `{cap['source']}` |"
        )

    if evolvable:
        lines.extend(
            [
                "",
                "## Learned",
                "",
                "_Capabilities added by the owner over time. Prompts live in `capabilities/`._",
                "",
                "| Code | Name | Description | Source | Added |",
                "|------|------|-------------|--------|-------|",
                "",
                "## How to Add a Capability",
                "",
                'Tell me "I want you to be able to do X" and we\'ll create it together.',
                "I'll write the prompt, save it to `capabilities/`, and register it here.",
                "Next session, I'll know how.",
                "Load `references/capability-authoring.md` for the full creation framework.",
            ]
        )

    lines.extend(
        [
            "",
            "## Tools",
            "",
            "Prefer crafting your own tools over depending on external ones where possible.",
            "",
            "### User-Provided Tools",
            "",
            "_MCP servers, APIs, or services the owner has made available. Document them here._",
            "",
            "### Configured Connections",
            "",
            "| Service | Account | Purpose | Status |",
            "|---------|---------|---------|--------|",
            "| Google Calendar | personal | Personal agenda | Not yet configured |",
            "| Google Calendar | work | Work agenda | Not yet configured |",
            "| Gmail | personal | Personal email digest | Not yet configured |",
            "| Gmail | work | Work newsletters | Not yet configured |",
            "| Garmin Connect | — | Health & stress data | Not yet configured |",
            "| Home Assistant | local | Home automation | Not yet configured |",
        ]
    )

    return "\n".join(lines) + "\n"


def substitute_vars(content: str, variables: dict) -> str:
    """Replace {var_name} placeholders with values from the variables dict."""
    for key, value in variables.items():
        content = content.replace(f"{{{key}}}", value)
    return content


def main():
    parser = argparse.ArgumentParser(
        description="YANA First Breath — scaffold the sanctum before the conversational awakening.",
        epilog="Run this once before the first YANA session. Safe to re-run: exits early if sanctum exists.",
    )
    parser.add_argument("project_root", help="Root of the project (where _bmad/ lives)")
    parser.add_argument("skill_path", help="Path to the skill directory (where SKILL.md lives)")
    parser.add_argument("--json", action="store_true", help="Output structured JSON result")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    skill_path = Path(args.skill_path).resolve()
    json_output = args.json

    result: dict = {"status": "ok", "sanctum": "", "files_created": [], "warnings": []}

    # Paths
    bmad_dir = project_root / "_bmad"
    memory_dir = bmad_dir / "memory"
    sanctum_path = memory_dir / SANCTUM_DIR
    assets_dir = skill_path / "assets"
    references_dir = skill_path / "references"
    scripts_dir = skill_path / "scripts"

    # Sanctum subdirectories
    sanctum_refs = sanctum_path / "references"
    sanctum_scripts = sanctum_path / "scripts"

    # Path used in CAPABILITIES.md source column
    sanctum_refs_path = "./references"

    # Check if sanctum already exists
    if sanctum_path.exists():
        msg = {
            "status": "skipped",
            "reason": "sanctum already exists",
            "sanctum": str(sanctum_path),
        }
        if json_output:
            print(json.dumps(msg))
        else:
            print(f"Sanctum already exists at {sanctum_path}")
            print("YANA has already been born. Skipping First Breath scaffolding.")
        sys.exit(0)

    # Load config — try TOML first (config.toml), then YAML fallback
    config = {}
    config.update(parse_toml_config(bmad_dir / "config.toml"))
    config.update(parse_toml_config(bmad_dir / "config.user.toml"))
    config.update(parse_yaml_config(bmad_dir / "config.yaml"))
    config.update(parse_yaml_config(bmad_dir / "config.user.yaml"))

    # Build variable substitution map
    today = date.today().isoformat()
    variables = {
        "user_name": config.get("user_name", "Fred"),
        "communication_language": config.get("communication_language", "Portugues"),
        "birth_date": today,
        "project_root": str(project_root),
        "sanctum_path": str(sanctum_path),
    }

    # Create sanctum structure
    sanctum_path.mkdir(parents=True, exist_ok=True)
    (sanctum_path / "capabilities").mkdir(exist_ok=True)
    (sanctum_path / "sessions").mkdir(exist_ok=True)
    result["sanctum"] = str(sanctum_path)

    # Copy reference files into sanctum (skip first-breath.md)
    copied_refs = copy_references(references_dir, sanctum_refs)
    result["files_created"].extend(copied_refs)

    # Copy supporting scripts into sanctum
    copied_scripts = copy_scripts(scripts_dir, sanctum_scripts)
    result["files_created"].extend(copied_scripts)

    # Copy and substitute template files → sanctum root (ALLCAPS files)
    for template_name in TEMPLATE_FILES:
        template_path = assets_dir / template_name
        if not template_path.exists():
            result["warnings"].append(f"template {template_name} not found, skipping")
            continue

        # Remove "-template" suffix, uppercase name, fix extension
        output_name = template_name.replace("-template", "").upper()
        output_name = output_name[:-3] + ".md"  # .MD -> .md

        content = template_path.read_text(encoding="utf-8")
        content = substitute_vars(content, variables)

        output_path = sanctum_path / output_name
        output_path.write_text(content, encoding="utf-8")
        result["files_created"].append(output_name)

    # Copy plain asset files as-is
    for asset_name in ASSET_FILES:
        asset_path = assets_dir / asset_name
        if not asset_path.exists():
            result["warnings"].append(f"asset {asset_name} not found, skipping")
            continue
        content = asset_path.read_text(encoding="utf-8")
        content = substitute_vars(content, variables)
        output_path = sanctum_path / asset_name
        output_path.write_text(content, encoding="utf-8")
        result["files_created"].append(asset_name)

    # Auto-generate CAPABILITIES.md from references/ frontmatter
    capabilities = discover_capabilities(references_dir, sanctum_refs_path)
    capabilities_content = generate_capabilities_md(capabilities, evolvable=EVOLVABLE)
    (sanctum_path / "CAPABILITIES.md").write_text(capabilities_content, encoding="utf-8")
    result["files_created"].append("CAPABILITIES.md")
    result["capabilities_discovered"] = len(capabilities)

    if json_output:
        print(json.dumps(result))
    else:
        print(f"Created sanctum at {sanctum_path}")
        print(f"  Copied {len(copied_refs)} reference files")
        if copied_scripts:
            print(f"  Copied {len(copied_scripts)} scripts")
        for name in [n for n in result["files_created"] if n.endswith(".md") and n == n.upper()]:
            print(f"  Created {name}")
        print(f"  Created CAPABILITIES.md ({len(capabilities)} built-in capabilities)")
        if result["warnings"]:
            for w in result["warnings"]:
                print(f"  Warning: {w}")
        print()
        print("=" * 60)
        print("First Breath scaffolding complete. YANA is ready to be born.")
        print("Next step: start a new conversation with YANA.")
        print("She will load references/first-breath.md and introduce herself.")
        print(f"Sanctum: {sanctum_path}")
        print("=" * 60)


if __name__ == "__main__":
    main()
