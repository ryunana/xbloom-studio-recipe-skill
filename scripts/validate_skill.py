#!/usr/bin/env python3
"""Validate the xBloom Studio Recipe Skill package.

This is a lightweight repository hygiene checker. It does not judge coffee taste;
it verifies SKILL.md packaging constraints and the presence/shape of public
release assets.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    import yaml
except Exception as exc:  # pragma: no cover
    print(f"ERROR: PyYAML is required: {exc}")
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f"ERROR: {message}")
    sys.exit(1)


def main() -> None:
    skill_path = ROOT / "SKILL.md"
    if not skill_path.exists():
        fail("SKILL.md missing")

    content = skill_path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        fail("SKILL.md must start with YAML frontmatter delimiter")

    match = re.search(r"\n---\s*\n", content[3:])
    if not match:
        fail("SKILL.md missing closing YAML frontmatter delimiter")
    assert match is not None

    frontmatter_text = content[3 : match.start() + 3]
    body = content[match.end() + 3 :]
    frontmatter = yaml.safe_load(frontmatter_text)
    if not isinstance(frontmatter, dict):
        fail("frontmatter must parse as a YAML mapping")

    required = ["name", "description", "version", "author", "license", "metadata"]
    missing = [key for key in required if not frontmatter.get(key)]
    if missing:
        fail(f"frontmatter missing required fields: {', '.join(missing)}")

    if frontmatter["name"] != "xbloom-studio-recipe":
        fail("frontmatter name must be xbloom-studio-recipe")
    if len(frontmatter["name"]) > 64:
        fail("frontmatter name exceeds 64 chars")
    if len(frontmatter["description"]) > 1024:
        fail("frontmatter description exceeds 1024 chars")
    if frontmatter["license"] != "MIT":
        fail("frontmatter license must be MIT")
    if not body.strip():
        fail("SKILL.md body is empty")
    if len(content) > 100_000:
        fail("SKILL.md exceeds 100,000 chars")

    for path in ["README.md", "LICENSE", "SOURCES.md", "test-prompts.json", "examples/ethiopia-duwancho.md"]:
        if not (ROOT / path).exists():
            fail(f"{path} missing")

    prompts = json.loads((ROOT / "test-prompts.json").read_text(encoding="utf-8"))
    if not isinstance(prompts, list) or len(prompts) < 3:
        fail("test-prompts.json must contain at least 3 prompt cases")
    for item in prompts:
        if not item.get("name") or not item.get("prompt"):
            fail("each test prompt must include name and prompt")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    required_readme_sections = {
        "installation": ["Installation", "安装"],
        "example prompt": ["Example prompt", "示例 Prompt", "示例 prompt"],
        "non-affiliation disclaimer": ["not affiliated", "没有关联", "未获得 xBloom"],
        "license": ["License", "许可证"],
    }
    for section_name, variants in required_readme_sections.items():
        if not any(phrase in readme for phrase in variants):
            fail(f"README.md missing required section: {section_name}")

    print("PASS: xBloom Studio Recipe Skill package is valid")
    print(f"SKILL.md chars: {len(content)}")
    print(f"test prompts: {len(prompts)}")


if __name__ == "__main__":
    main()
