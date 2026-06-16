#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 - <<'PY'
from pathlib import Path
import re
import sys

try:
    import yaml
except Exception as exc:
    print(f"FAIL: PyYAML is required: {exc}")
    sys.exit(2)

errors = []
skill_path = Path("SKILL.md")
content = skill_path.read_text(encoding="utf-8")

if not content.startswith("---"):
    errors.append("SKILL.md must start with YAML frontmatter delimiter")

match = re.search(r"\n---\s*\n", content[3:])
if not match:
    errors.append("SKILL.md missing closing YAML frontmatter delimiter")
else:
    frontmatter = yaml.safe_load(content[3:match.start() + 3])
    body = content[match.end() + 3:]
    if not isinstance(frontmatter, dict):
        errors.append("frontmatter must be a YAML mapping")
    else:
        for key in ["name", "description", "version", "author", "license", "metadata"]:
            if not frontmatter.get(key):
                errors.append(f"frontmatter missing {key}")
        if len(str(frontmatter.get("name", ""))) > 64:
            errors.append("frontmatter name exceeds 64 characters")
        if len(str(frontmatter.get("description", ""))) > 1024:
            errors.append("frontmatter description exceeds 1024 characters")
    if not body.strip():
        errors.append("SKILL.md body is empty")

if len(content) > 100_000:
    errors.append("SKILL.md exceeds 100,000 characters")

for required in ["README.md", "LICENSE", "SOURCES.md", "examples/ethiopia-duwancho.md"]:
    if not Path(required).exists():
        errors.append(f"missing {required}")

if errors:
    print("FAIL")
    for error in errors:
        print(f"- {error}")
    sys.exit(1)

print("PASS: xBloom Studio recipe skill structure is valid")
PY
