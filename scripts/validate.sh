#!/usr/bin/env bash
# 检查包结构。有 PyYAML 就完整校验 frontmatter，没有也能跑（降级为粗略检查）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 - <<'PY'
from pathlib import Path
import re
import sys

try:
    import yaml
except Exception:
    yaml = None

errors = []
warnings = []

skill_path = Path("SKILL.md")
content = skill_path.read_text(encoding="utf-8")

if not content.startswith("---"):
    errors.append("SKILL.md must start with YAML frontmatter delimiter")

match = re.search(r"\n---\s*\n", content[3:])
if not match:
    errors.append("SKILL.md missing closing YAML frontmatter delimiter")
else:
    raw = content[3:match.start() + 3]
    body = content[match.end() + 3:]
    if yaml is None:
        warnings.append("没装 PyYAML，frontmatter 只做了文本级检查（装一下可完整校验：python3 -m pip install pyyaml）")
        for key in ("name", "description", "license", "metadata"):
            if not re.search(rf"^{key}\s*:", raw, re.M):
                errors.append(f"frontmatter missing {key}")
        if not re.search(r"^\s+version\s*:", raw, re.M):
            errors.append("metadata must include version")
        if not re.search(r"^\s+author\s*:", raw, re.M):
            errors.append("metadata must include author")
    else:
        frontmatter = yaml.safe_load(raw)
        if not isinstance(frontmatter, dict):
            errors.append("frontmatter must be a YAML mapping")
        else:
            for key in ["name", "description", "license", "metadata"]:
                if not frontmatter.get(key):
                    errors.append(f"frontmatter missing {key}")
            metadata = frontmatter.get("metadata")
            if not isinstance(metadata, dict) or not metadata.get("version") or not metadata.get("author"):
                errors.append("metadata must include version and author")
            if len(str(frontmatter.get("name", ""))) > 64:
                errors.append("frontmatter name exceeds 64 characters")
            if len(str(frontmatter.get("description", ""))) > 1024:
                errors.append("frontmatter description exceeds 1024 characters")
    if not body.strip():
        errors.append("SKILL.md body is empty")

if len(content) > 100_000:
    errors.append("SKILL.md exceeds 100,000 characters")

for required in ["README.md", "LICENSE", "SOURCES.md", "CHANGELOG.md", "examples/ethiopia-duwancho.md",
                 "references/bluetooth-bridge.md", "references/device-facts.md",
                 "scripts/xbloom_proto.py", "scripts/recipe_preview.py",
                 "scripts/xbloom_brew.py", "scripts/brew.sh", "recipes/current.json"]:
    if not Path(required).exists():
        errors.append(f"missing {required}")

if Path("scripts/xbloom_bridge.py").exists():
    errors.append("scripts/xbloom_bridge.py must not ship (skips handshake and dose frame)")

# 打包发出去之前容易漏掉的一件事：本机绝对路径写进包里。
private = re.compile(r"/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/")
for path in Path(".").rglob("*"):
    if not path.is_file() or "__pycache__" in path.parts or path.suffix in {".png", ".gif", ".zip"}:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        continue
    for hit in private.findall(text):
        warnings.append(f"{path} 里有本机绝对路径：{hit}")
        break

for warning in warnings:
    print(f"WARN: {warning}")

if errors:
    print("FAIL")
    for error in errors:
        print(f"- {error}")
    sys.exit(1)

print("PASS: xBloom Studio recipe skill structure is valid")
PY
