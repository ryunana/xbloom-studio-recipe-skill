# xBloom Studio 冲煮方案 Skill / xBloom Studio Recipe Skill

[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-xBloom%20Studio-blueviolet)](SKILL.md)
[![skills.sh](https://skills.sh/b/ryunana/xbloom-studio-recipe-skill)](https://skills.sh/ryunana/xbloom-studio-recipe-skill)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

这是一个通用 Agent Skill，不绑定特定 agent。它用于根据咖啡豆基础参数，生成可直接填入 xBloom Studio App / Copilot 创作模式的完整冲煮方案。

This is a general-purpose Agent Skill, not tied to any specific agent runtime. It turns coffee-bean parameters into a complete xBloom Studio App / Copilot recipe that can be entered directly into the app.

![演示](assets/demo.gif)

这个 Skill 内置了 xBloom Studio 的真实设备约束与手冲调参逻辑，包括：

This skill encodes real xBloom Studio device constraints and pour-over dial-in logic, including:

- xBloom Studio 的粉量、研磨、RPM、流速、温度、注水模式与振动限制
- xBloom Studio ↔ Comandante C40 的官方研磨转换锚点
- RO 水补偿规则
- Omni Dripper / 平底滤杯注水逻辑
- WAIT / 防溢出避坑
- 埃塞日晒 / 花香莓果型咖啡的配方 archetype
- 针对偏酸、偏苦涩、风味空薄的“每次只改一个变量”修正路线

- xBloom Studio dose, grind, RPM, flow-rate, temperature, pour-pattern, and vibration constraints
- Official xBloom Studio ↔ Comandante C40 grind-conversion anchors
- RO-water compensation rules
- Omni Dripper / flat-bottom pour-pattern logic
- WAIT / overflow avoidance
- An Ethiopian natural / floral-berry recipe archetype
- One-variable-at-a-time troubleshooting routes for sour, bitter/astringent, or hollow cups

## 安装 / Installation

推荐通过 Skills CLI 从 GitHub 安装，适用于支持 Agent Skills / `SKILL.md` 格式的 agent 环境：

Install from GitHub with the Skills CLI. This works for agent environments that support the Agent Skills / `SKILL.md` format:

```bash
npx skills add ryunana/xbloom-studio-recipe-skill -g
```

也可以手动安装：

Manual installation is also possible:

把 `SKILL.md` 复制到你正在使用的 agent 会读取的 skills 目录。不同 agent 的目录不一样，下面用 `AGENT_SKILLS_DIR` 代指你的实际 skills 根目录：

Copy `SKILL.md` into the skills directory read by your agent. Different agents use different paths, so `AGENT_SKILLS_DIR` below stands for your actual skills root:

```bash
export AGENT_SKILLS_DIR="$HOME/.config/agent-skills"
mkdir -p "$AGENT_SKILLS_DIR/xbloom-studio-recipe"
cp SKILL.md "$AGENT_SKILLS_DIR/xbloom-studio-recipe/SKILL.md"
```

安装后开启一个新的 agent 会话，直接请求生成 xBloom Studio 冲煮方案即可。

After installation, start a new agent session and ask for an xBloom Studio brew recipe.

## 示例 Prompt / Example Prompt

```text
用 xbloom-studio-recipe 给这支豆子出一套 xBloom Studio App 可直接填写的方案：
ETHIOPIA DUWANCHO / 74158 / Natural / 花香、杨梅、蔓越莓、橙子、油桃、青芒。默认 15g、240ml、RO 水。
```

English example:

```text
Use xbloom-studio-recipe to create a directly enterable xBloom Studio App recipe for this coffee:
ETHIOPIA DUWANCHO / 74158 / Natural / floral, bayberry, cranberry, orange, nectarine, green mango. Use the default 15 g dose, 240 ml water, and RO water.
```

## 输出内容 / Output

默认输出为简体中文，结构包括：

The default output language is Simplified Chinese. The response structure includes:

1. 基础参数
2. 分段注水参数
3. 目标总萃取时间
4. 理论风味顺序
5. 三条翻车修正路线（每条只改一个变量）

1. Base parameters
2. Step-by-step pour settings
3. Target total brew time
4. Expected flavor progression
5. Three troubleshooting routes, changing only one variable at a time

## 校验 / Validation

```bash
bash scripts/validate.sh
```

## 资料来源与依据 / Sources

这个 Skill 基于 xBloom 官方文档、xBloom Studio / C40 研磨转换数据、xBloom App 参数限制、Nucleus Coffee 的 xBloom Studio 控制变量笔记、Standout Coffee 的 xBloom Studio dial-in 案例，以及公开的研磨档位参考资料整理而成。

This skill is based on xBloom official documentation, xBloom Studio / C40 grind-conversion data, xBloom App parameter limits, Nucleus Coffee's notes on xBloom Studio control variables, Standout Coffee's xBloom Studio dial-in case study, and public grind-setting references.

更多研究笔记和来源类别见 [SOURCES.md](SOURCES.md)。

See [SOURCES.md](SOURCES.md) for source categories and research notes.

本仓库与 xBloom 没有关联，也未获得 xBloom 的赞助、背书或官方认可。

This repository is not affiliated with, sponsored by, endorsed by, or officially recognized by xBloom.

## 许可证 / License

MIT。详见 [LICENSE](LICENSE)。

MIT. See [LICENSE](LICENSE).
