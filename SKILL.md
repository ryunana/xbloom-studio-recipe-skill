---
name: xbloom-studio-recipe
description: Use when generating executable xBloom Studio App brew recipes from coffee-bean parameters. Produces device-constrained Copilot/recipe settings with grind/C40 conversion, pours, temperature, flow, vibration, RO-water compensation, WAIT avoidance, and one-variable troubleshooting routes.
version: 1.0.0
author: ryunana
license: MIT
platforms: [linux, macos, windows]
metadata:
  tags: [coffee, xbloom, xbloom-studio, brewing, recipe, pourover]
  compatibility: [agent-skills, skill-md]
  related_skills: []
---

# xBloom Studio Recipe Engineer

## Overview

Use this skill to turn coffee bean information into a complete, directly executable xBloom Studio recipe for the xBloom Coffee App / Copilot 创作模式. The output must respect real xBloom Studio constraints, prioritize flavor accuracy and repeatability, and avoid obvious over-extraction, hollow extraction, slow drawdown, or machine `WAIT` / overflow problems.

The user usually provides some or all of:

- Origin / farm / producer
- Variety
- Process
- Altitude
- Roast level
- Roast date / rest age
- Flavor notes
- User preference
- Drinking style
- Optional previous grinder reference such as C40 clicks

When bean flavor notes conflict with the user's preference, prioritize the user's preference.

## When to Use

Use this skill when the user asks for:

- A xBloom Studio brew recipe
- xBloom App parameters
- Omni Dripper / xBloom original dripper recipe design
- Conversion from C40 clicks to xBloom Studio grind setting
- Dial-in advice for xBloom Studio: sour, bitter, astringent, thin, muted, clogging, or `WAIT`
- A reusable recipe template for a given coffee bean

Do not use this for espresso recipes unless the user explicitly wants to use the xBloom grinder as a standalone grinder. This skill is for xBloom Studio automated pour-over / Copilot recipes.

## Hard Device Constraints

Treat these as hard limits unless the user explicitly says they are using a different xBloom firmware/app version.

### Machine and defaults

- Machine: xBloom Studio
- Target mode: Copilot / App custom recipe, unless user asks Auto Mode or Freesolo
- Default brewer: xBloom Omni Dripper / original xBloom dripper
- Default water: RO water if user does not specify otherwise
- Default dose: 15 g
- Default total water: 240 ml
- Default ratio: 1:16
- App-safe dose: 5-18 g
- Omni Dripper 2 recommended dose range: 5-18 g
- App-created recipes can be saved; machine Auto Mode can store 3 preset recipes.

### Grinder

- xBloom Studio grind size range: 1-80
- Larger number = coarser grind
- 80 stepped settings; about 18.75 μm per step
- RPM range: 60-120 RPM, 10 RPM increments only
- Official/manual guidance: 1 is fine for espresso-like grinding; 80 is coarse for French press / cold brew

### Pouring / brewer

- Flow rate: 3.0-3.5 ml/s, usually 0.1 ml/s increments
- Pour pattern choices:
  - Center / Centered / 中心
  - Spiral / 螺旋
  - Circular / 环绕
- Per pour step fields:
  - Volume in ml
  - Display temperature
  - Flow rate
  - Pour pattern
  - Vibration before: ON/OFF
  - Vibration after: ON/OFF
  - Pause / dwell after pour: 0-59 s for conservative App-compatible recipes
- Freesolo brewer mode supports up to 500 ml water, but App coffee recipes should keep all pour volumes aligned to the target beverage.
- Official temperature capability: RT, 40-98°C, or BP. Nucleus user testing notes BP behaves closer to about 95-98°C, not guaranteed 100°C at the coffee bed.

### Scale / vessel

- Scale max: 2000 g
- Scale resolution: 0.1 g from 0.5-1000 g; 1 g from 1000-2000 g
- Use a receiving vessel >300 ml capacity and <=100-105 mm height.
- Do not place the cup tight against the machine wall; it can interfere with weight sensing and trigger overflow protection / WAIT.

## C40 to xBloom Studio Grind Conversion

If the user provides C40 clicks, convert to xBloom Studio grind setting before recipe design. Use the official xBloom conversion table below. Interpolate linearly between anchor points and round to the nearest whole xBloom setting, then adjust by bean logic if needed.

| Approx particle | xBloom Studio | xBloom Original | C40 clicks | Description |
|---:|---:|---:|---:|---|
| 300 μm | 1 | / | 11 | Fine |
| 400 μm | 10 | / | 15 | Medium Fine |
| 500 μm | 20 | / | 18 | Medium Fine |
| 600 μm | 30 | / | 22 | Medium |
| 700 μm | 41 | 1 | 26 | Medium |
| 800 μm | 50 | 10 | 30 | Medium-Coarse |
| 900 μm | 60 | 20 | 33 | Medium-Coarse |
| 1000 μm | 70 | 30 | 36 | Medium-Coarse |
| 1100 μm | 80 | / | 40 | Coarse |

Important anchors:

- C40 30 ≈ xBloom 50
- C40 33 ≈ xBloom 60
- C40 36 ≈ xBloom 70
- C40 40 ≈ xBloom 80
- xBloom 54-60 ≈ roughly C40 31-33

If a user says "I normally use C40 30", start around xBloom 50, then adjust:

- RO water + light roast: 48-50
- balanced medium roast: 50-54
- darker or bitter-prone coffee: 54-58

## Grind Strategy

Do not treat 54-60 as the only pour-over range. It is a stable sweet zone, not a universal rule.

Use these starting ranges:

| Coffee / target | Initial xBloom grind |
|---|---:|
| Very light roast, high density, washed, floral/fruit clarity | 46-52 |
| Light-medium roast, balanced sweetness | 52-58 |
| Medium roast, nut/caramel/stable daily cup | 56-62 |
| Medium-dark / dark roast, low-acid, avoid bitterness | 62-68 |
| Natural / anaerobic / fermentation-heavy / astringency-prone | 52-60 |
| Standout-style high-expression natural coffee | 40-46 when deliberately chasing acidity and separation |
| Official Auto Mode coarse-safe style | 63-68 |

External grind references:

- Honest Coffee Guide lists xBloom Studio V60 around 21-47, pour-over around 22-68, French press around 47-80.
- Nucleus Coffee reports most filter recipes stay around 30-60.
- Standout Coffee's Papayo natural case dialed a double-bloom recipe around 46 → 40 → 42 → 44; 40 became more extracted but astringent, while 44 tasted best. This supports 2-step grind changes and trusting taste over highest TDS/EY.

### Grind adjustment rule

Use 2 xBloom steps as the default adjustment unit.

- Sour / sharp / hollow from under-extraction: 2 steps finer
- Bitter / astringent / dry: 2 steps coarser
- Slow drawdown / WAIT / bed flooding: 2-4 steps coarser
- Good but slightly muted: 1-2 steps finer or add dwell, not both in the same troubleshooting step

## RPM Strategy

RPM supports 60, 70, 80, 90, 100, 110, 120.

| Target | RPM |
|---|---:|
| Default stable recipe | 90 |
| Clean, bright, sweet, clear | 100-120 |
| Texture, complexity, less sharp acidity | 60-80 |
| Official Auto Mode reference | 120 |
| Dark roast / astringency-prone | 60-90 |

Nucleus Coffee's preliminary observation: lower RPM may yield more texture and complexity; higher RPM may yield more clarity and sweetness. Whole Latte Love notes slower RPMs are often preferable for filter sizes, while faster RPMs work well for espresso. Prefer the taste target over dogma.

## Temperature Strategy

Screen temperature is not the same as slurry / coffee-bed temperature. Assume coffee-bed temperature is roughly 2-4°C lower than display temperature.

Recommended coffee-bed targets:

- Floral / fruit / tea-like: 87-89°C bed → usually 91-93°C display
- Sweet balanced: 88-90°C bed → usually 92-94°C display
- Heavy / dense / high extraction: 90-92°C bed → usually 94-96°C display

Use display temperatures:

| Coffee / target | Display temp |
|---|---:|
| Very light / high-density washed | 94-96°C |
| Light-medium balanced | 92-94°C |
| Natural / anaerobic / fermentation-heavy | 89-92°C |
| Medium roast nut/caramel | 90-93°C |
| Medium-dark / dark | 86-90°C |
| RO water compensation | +0-1°C only after grind/dwell options |

Avoid large temperature jumps across pours. Default max difference between adjacent pours: 0-2°C. Do not output chaotic sequences such as 88 → 96 → 90 unless there is a specific reason.

## RO Water Compensation

RO water has low mineral content and can produce lower perceived extraction and amplified acidity. Do not compensate only by raising temperature.

Priority order for RO water under-extraction:

1. Grind 1-2 steps finer.
2. Extend bloom or middle-pour dwell by 3-6 seconds.
3. Use bloom-after vibration ON.
4. Raise display temperature by only 1°C if needed.

When designing a recipe for RO water, bias slightly finer and/or slightly longer dwell than for moderately mineralized water.

## Pour Pattern Strategy

xBloom Studio / Omni Dripper is a flat-bottom brewer. Do not design it like a V60 with all center pouring.

Pattern guidelines:

- Bloom: Spiral or Center
- Main pour: Spiral
- Finish: Circular or Spiral
- Avoid all steps Center unless the user explicitly wants low agitation and very gentle extraction.
- Use Circular to improve edge extraction and bed leveling, but avoid overusing it on slow-filtering, fine-heavy, or astringency-prone coffees.

## Agitation / Vibration Strategy

Agitation can be applied before and/or after each pour. It moves the Omni Dripper side-to-side. It helps flatten the bed and can move fines; it is not a generic "make extraction better" button.

Default:

- Bloom before: OFF
- Bloom after: ON
- Later pour vibration: OFF

Use more agitation only with a clear reason:

| Situation | Vibration strategy |
|---|---|
| Light high-density washed, needs more extraction | Bloom after ON; optional one middle after ON |
| Balanced recipe | Bloom after ON only |
| Natural / anaerobic / heavy fermentation | Bloom after ON or all OFF |
| Dark roast | Usually all OFF or bloom after ON only |
| Slow drawdown / WAIT / clogging | Turn later vibration OFF; if needed all OFF |
| Bitter/astringent | Remove middle/final vibration before changing multiple variables |

## Recipe Archetypes

Choose the minimum effective pour count: 3-5 pours allowed; default 3. Use 4 for complex/high-density coffees or official-style repeatability. Use 5 only when clearly justified, such as double bloom for a competition-style floral/natural coffee.

When a coffee belongs to more than one archetype, combine them by priority:

1. User preference / drinking target
2. Roast level and density
3. Process risk: natural/anaerobic/fermentation-heavy
4. Water chemistry, especially RO water
5. Official coarse-safe baseline

For example, an Ethiopian natural 74158 with floral, berry, citrus, stone fruit, and green mango notes is both "floral/fruit clarity" and "natural/fermentation-control". Do not over-restrict it to the low-temperature natural template. Use a controlled expressive profile: medium-fine grind, moderate-high display temperature, high-ish RPM for clarity, limited vibration, and 4 pours only if needed for layering.

### A. Standard stable recipe

Use for most specialty coffees and when user preference is not extreme.

- Dose: 15 g
- Water: 240 ml
- Ratio: 1:16
- Grind: 52-60
- RPM: 90-120
- 3 or 4 pours
- Bloom flow 3.0; main flow 3.5
- Bloom after vibration ON; later OFF

Good 3-pour skeletons:

- 45 / 105 / 90 ml
- 50 / 100 / 90 ml

Good 4-pour skeleton:

- 50 / 70 / 65 / 55 ml

### B. Floral / fruit / tea-like clarity

Use for washed, high-altitude, high-density, Geisha, Ethiopian, Kenyan, Panamanian, SL varieties, or user preference for clarity/floral/tea.

- Grind: 46-52
- Display temp: 93-96°C
- Ratio: 1:16-1:16.5
- RPM: 100-120
- 3-4 pours
- Bloom flow 3.0; main flow 3.5
- Bloom after vibration ON; optional one middle after ON if not slow
- Consider double bloom only for competition-like coffees or when explicitly chasing high acidity and layered aromatics.

Good 4-pour skeleton:

- 45 / 65 / 65 / 65 ml

### C. Sweet balanced recipe

Use for light-medium to medium coffees with honey, caramel, nut, chocolate, yellow fruit, or when user wants sweetness and balance.

- Grind: 52-58
- Display temp: 90-94°C
- Ratio: 1:15.5-1:16
- RPM: 90-110
- 3 pours preferred
- Bloom after vibration ON; later OFF

Good 3-pour skeleton:

- 50 / 100 / 90 ml

### D. Heavy / low-bitter / dark roast recipe

Use for medium-dark/dark roasts, chocolate/nut profiles, or users avoiding acidity and bitterness.

- Grind: 60-68
- Display temp: 86-90°C
- Ratio: 1:14.5-1:15.5 unless user requires 1:16
- RPM: 60-90
- 3 pours
- Minimal vibration
- Avoid long final dwell

Good 3-pour skeleton:

- 40 / 110 / 90 ml

### E. Natural / anaerobic / fermentation-control recipe

Use for natural, anaerobic, thermal shock, extended fermentation, yeast/lactic fermentation, winey or boozy coffees.

- Grind: 50-58
- Display temp: 88-92°C for fermentation control; 92-93°C is allowed for high-altitude Ethiopian/natural coffees when the target is floral/berry/citrus clarity and the recipe limits vibration.
- Ratio: 1:15.5-1:16
- RPM: 80-100; use 100-110 when clarity and sweetness are more important than texture.
- 3 pours preferred, 4 max
- Avoid overusing vibration
- Avoid unnecessarily high temperature
- Avoid double bloom unless the user explicitly wants acid-forward light body

### F. Expressive Ethiopian natural / floral berry recipe

Use for Ethiopian or similar high-expression natural coffees with floral, berry, citrus, stone-fruit, tropical fruit, or green-mango notes, especially varieties such as 74110/74112/74158 when the user wants clear fruit rather than heavy fermented body.

- Grind: 48-52
- Display temp: 92-93°C
- Ratio: 1:16
- RPM: 100-110
- 4 pours when the notes include multiple fruit layers; 3 pours if the user prioritizes simplicity or the coffee drains slowly.
- Flow: Bloom 3.0, main pours 3.5
- Pattern: Bloom Spiral, main Spiral, finish Circular
- Vibration: Bloom after ON only; keep later vibration OFF to avoid astringency and WAIT.
- Good 4-pour skeleton: 45 / 65 / 65 / 65 ml

## WAIT / Overflow Avoidance

`WAIT` usually means the machine's overflow protection or weight logic was triggered. Causes include liquid weight in the dripper exceeding a threshold, wrong dripper selection in App, cup touching the machine wall, cup moved during brew, scale tape not removed, or slow drainage.

Recipe-level prevention:

- Do not combine fine grind + high temp + multiple vibrations + long dwell.
- Avoid too many small pours with long pauses.
- Avoid middle/final vibration for fine-heavy or slow-draining coffees.
- For slow filters, increase grind by 2-4 settings before changing temperature.
- Keep receiving vessel >300 ml and <=100-105 mm high.
- Ensure App dripper/cup type matches the actual brewer.

If user reports WAIT:

1. First check physical setup: scale tape removed, cup not touching wall, cup not moved, correct dripper selected.
2. If physical setup is fine, coarsen grind by 2 settings.
3. If it persists, turn middle/final vibration OFF.
4. If it persists, reduce pour count or reduce early water load.

## Output Contract

When generating a recipe, output in Chinese by default. Do not include an explanatory preface or summary if the user requests a strict recipe. Use the exact fields below unless the user asks for a different format.

All values must be executable concrete values, not vague ranges, except the requested micro-adjustment range in the grind field.

Before outputting, silently run a best-practice review:

- Does the recipe match the bean's dominant expression, not just the process label?
- If altitude data conflicts, assume the higher-density / more expressive case for the first recipe, but avoid extreme extraction settings.
- For floral Ethiopian naturals, avoid making the recipe too conservative; 92-93°C display, grind 48-52, RPM 100-110 is often a better first cup than a low-temperature fermentation-control profile.
- If a recipe is intentionally conservative, label it in your internal reasoning and consider whether an expressive version would better match the user request.
- Never claim a recipe is absolute "best" without tasting. Treat it as a best-practice starting point, and make the one-variable correction routes actionable.

If the user asks to check or audit an already generated recipe, answer with a constraint check plus bean-fit review. If it is device-valid but not the best starting point, provide a revised recipe and explain the specific changes concisely.

### Required structure

```markdown
### 1️⃣ 基础参数

* 粉量：15 g
* 总水量：240 ml
* 粉水比：1:16
* 研磨档位：56（可微调区间：54–58）
* 磨豆转速：90 RPM

---

### 2️⃣ 分段注水参数

#### 第 1 段：Bloom

* 水量：50 ml
* 屏显温度：93 ℃
* 流速：3.0 ml/s
* 注水模式：螺旋
* 段前振动：OFF
* 段后振动：ON
* 段后驻留时间：12 s
* 核心风味职责：充分润湿粉床，建立甜感萃取基础，降低 RO 水导致的尖酸

#### 第 2 段：Main Pour

* 水量：100 ml
* 屏显温度：93 ℃
* 流速：3.5 ml/s
* 注水模式：螺旋
* 段前振动：OFF
* 段后振动：OFF
* 段后驻留时间：8 s
* 核心风味职责：提取主体甜感与中段结构

#### 第 3 段：Finish

* 水量：90 ml
* 屏显温度：92 ℃
* 流速：3.5 ml/s
* 注水模式：环绕
* 段前振动：OFF
* 段后振动：OFF
* 段后驻留时间：0 s
* 核心风味职责：补足尾段萃取并保持余韵干净，避免过萃涩感

---

### 3️⃣ 目标总萃取时间

* 目标时间窗口：2:35–3:05
* 时间过短的结果：酸感尖锐，甜感不足，中段空
* 时间过长的结果：尾段苦涩，口腔发干，风味边界变脏

---

### 4️⃣ 理论风味顺序

* 热时前口：...
* 中段主体：...
* 尾段余韵：...
* 冷却后变化：...

---

### 5️⃣ 三条翻车修正路线（只允许改一个变量）

* 偏酸：研磨档位从 56 调至 54
* 偏苦 / 涩：研磨档位从 56 调至 58
* 风味空 / 薄：第 1 段段后驻留时间从 12 s 调至 18 s
```

## Generation Checklist

Before finalizing a recipe, verify:

- [ ] Dose is 5-18 g unless explicitly using advanced workaround.
- [ ] Total water equals dose × ratio.
- [ ] Sum of all pour volumes exactly equals total water.
- [ ] Grind is 1-80.
- [ ] RPM is one of 60/70/80/90/100/110/120.
- [ ] Flow is 3.0-3.5 ml/s.
- [ ] Display temperature is RT, 40-98°C, or BP; normal coffee recipes usually stay 86-96°C.
- [ ] Pause is 0-59 s.
- [ ] Pour count is 3-5 and is the minimum effective count.
- [ ] Avoided risky combination: very fine grind + high temp + multiple vibrations + long dwell.
- [ ] If RO water is used, compensation favors grind/dwell before temperature.
- [ ] Troubleshooting routes each change exactly one variable.

## Common Pitfalls

1. **Treating 54-60 as the only xBloom pour-over range.** It is a stable sweet zone, but high-expression coffees may need 40-52 and dark coffees may need 62-68.

2. **Using flow rate as the main dial-in tool.** The xBloom range is only 3.0-3.5 ml/s, so grind, dwell, temperature, and vibration matter more.

3. **Adding 5 pours to look professional.** Use 3 pours by default; 4 for complexity or official-style stability; 5 only with a clear reason.

4. **Over-agitating natural or anaerobic coffees.** It can increase fines migration, astringency, and clogging.

5. **Compensating RO water only by raising temperature.** This can sharpen acidity and increase dryness. Adjust grind/dwell first.

6. **Ignoring ratio changes.** On-device ratio changes may add/subtract water from the final pour. Recalculate all pours instead of casually changing ratio before brew.

7. **Ignoring WAIT.** WAIT is often a physical/setup or slow-drainage issue; fix grind/vibration/setup before changing flavor variables.

8. **Chasing TDS/EY over taste.** Standout Coffee's xBloom case showed a higher extraction point could taste more astringent; the best cup was selected by taste.
