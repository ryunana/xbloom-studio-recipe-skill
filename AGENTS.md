# 协作规则（所有 agent 与人类通用）

## 唯一真源
GitHub 上的 `main`（https://github.com/ryunana/xbloom-studio-recipe-skill）是本项目唯一真源。
本地不保留"另一个版本"：不长期维护 `codex/*`、`workbuddy/*` 之类的本地私有分支，不在别处放独立拷贝。

## 开工流程
1. `git fetch origin`，从最新 `origin/main` 开分支：`agent/<工具名>-<主题>`，例如 `agent/claude-fix-timeout`。
2. 小步提交，推到 origin，用 PR 合并到 `main`（squash）。
3. CI（`validate-skill`）必须通过才能合并；合并后分支自动删除。
4. 合并后本地删掉该分支和 worktree；下一个任务重新从 `origin/main` 开始。

## 禁止
- 直接推 `main`、force-push `main`。
- 基于旧的本地分支继续开发。开工前发现本地有未推送的旧工作，先推成 PR 或明确丢弃，不要带着走。
- 未经用户确认发布版本、打 tag。

## 验证
改动前后都跑：

```bash
python scripts/validate_skill.py
python -m unittest discover -s tests -v
```

## 安装使用
技能的使用与安装见 [README.md](README.md)，行为规范见 [SKILL.md](SKILL.md)。改 SKILL.md 时同步 CHANGELOG.md。

## 发版
版本号以 `SKILL.md` 的 `metadata.version` 为准，`CHANGELOG.md` 同步。发版 = 在 `main` 上打 `vX.Y.Z` tag 并建 GitHub Release，必须由用户明确同意后再做。

## 运行时数据不进仓库
`runs/`（真机冲煮记录）和 `recipes/*.json`（用户自己的配方，含 `current.json`）都在 `.gitignore`，不进仓库。测试和示例只用 `examples/ethiopia-duwancho.recipe.json`；不要为了测试去改用户配方，也不要把示例改成某次冲煮的参数。
