# 完整标准 Skill 示例（含逐块讲解）

> 所属模块：00 关键概念 ｜ 学习日期：2026-07-07
> 配套 [模块 00 README](README.md) 的 Skills 一节。这里给一个**结构完整、字段标准**的 Skill，照着就能自己写。

## 一个 Skill 长什么样

Skill 就是**一个文件夹**，里面至少有一个 `SKILL.md`，可选带脚本、模板、参考资料。以"把季度数据生成公司规范 PDF 报告"为例：

```
pdf-report/                      ← Skill 名 = 文件夹名（kebab-case）
├── SKILL.md                     ← 必需：入口，带 YAML 头 + 操作指令
├── scripts/
│   └── build_pdf.py             ← 可选：确定性动作交给脚本，别让模型手算
├── references/
│   └── brand-style.md           ← 可选：详细规范，按需才加载
└── assets/
    └── template.html            ← 可选：模板/字体/logo 等资源
```

## SKILL.md（核心文件，完整示例）

````markdown
---
name: pdf-report
description: >-
  当用户需要把结构化数据（CSV/表格/JSON）生成符合公司品牌规范的 PDF 报告时使用。
  涵盖季度报表、数据周报、对外汇报文档。涉及"导出 PDF""生成报告""按模板出文档"时触发。
license: MIT
allowed-tools:
  - Read
  - Write
  - Bash
---

# PDF 报告生成

## 何时用这个 Skill
用户提供结构化数据并要求生成正式 PDF 报告时。若只是要 Markdown 或纯文本，不要用本 Skill。

## 步骤
1. 确认拿到数据源（CSV / JSON / 表格）与报告标题、时间范围。
2. 品牌规范（配色、字号、页眉页脚、logo 位置）见 `references/brand-style.md`——
   **需要精确样式时再读它**，不要一上来全load。
3. 调用 `scripts/build_pdf.py` 生成 PDF：
   ```bash
   python scripts/build_pdf.py --data <数据文件> --title "<标题>" --out report.pdf
   ```
4. 脚本会套用 `assets/template.html` 模板。生成后向用户报告输出路径。

## 注意
- 金额/百分比等数字由脚本格式化，**不要让模型口算**，避免精度错误。
- 数据超过 50 行时脚本自动分页，无需手动处理。
- 生成失败先看脚本 stderr，再对照 `references/brand-style.md` 排查样式问题。
````

## 逐块讲解

### YAML frontmatter（头部元数据）—— 最关键
| 字段 | 作用 | 要点 |
|------|------|------|
| `name` | Skill 唯一标识 | kebab-case，和文件夹名一致 |
| `description` | **触发条件**——告诉模型"什么时候该用我" | 写清*场景 + 关键词*，这是渐进式披露里唯一常驻上下文的部分，写不好就不会被触发 |
| `license` | 许可（可选） | 开源分发时填 |
| `allowed-tools` | 限制本 Skill 可用工具（可选） | 收敛权限，安全 |

> `description` 是整个 Skill 里最该打磨的字段。模型平时**只看到 name + description** 来决定要不要加载这个 Skill，所以它必须同时说清"做什么"和"什么信号下触发"。

### 正文（Markdown 指令）
- 就是给模型的**操作手册**：何时用、分几步、调哪个脚本、注意什么。
- 关键写法：**把详细规范外置到 `references/`，正文只写"需要时去读哪个文件"**——这就是渐进式披露在正文层的体现。

### scripts/ —— 确定性动作外包
- 排版、算数、格式化这类**不该靠模型即兴发挥**的事，写成脚本。
- 模型负责"决定调用 + 传参"，脚本负责"精确执行"。既省 token 又稳。

### references/ 与 assets/ —— 按需加载的重资料
- `references/`：长文档（详细规范、字段字典、API 说明）。正文点名后模型才去读。
- `assets/`：模板、字体、logo 等静态资源，由脚本使用。

## 渐进式披露（Progressive Disclosure）三层

这是 Skill 不撑爆上下文的核心机制：

```
第 1 层  常驻   →  只有 name + description（几十字，几乎零成本）
                    模型据此判断"这个任务要不要用它"
第 2 层  命中后 →  加载完整 SKILL.md 正文（步骤、注意事项）
第 3 层  用到时 →  才读 references/*.md、才跑 scripts/*.py
```

好处：装几十上百个 Skill，平时上下文里也只是一串"名字+描述"，真正的重内容只在需要时才进窗口。

## 自查清单（写自己的 Skill 时对照）
- [x] 文件夹名 = `name` = kebab-case
- [x] `description` 说清了「做什么」+「什么信号触发」
- [x] 正文步骤清晰，详细规范外置到 `references/`
- [x] 确定性/易错动作交给 `scripts/`，不靠模型即兴
- [x] 用 `allowed-tools` 收敛权限
- [x] 遵守三层渐进式披露，别把重资料塞进正文

## 关联
- 概念总览见 [模块 00 README](README.md) 的 Skills 一节与 MCP vs Skills 对比
- Tool Calling / MCP 的深入见 [模块 04 · Agent](../04-agent-architecture/)
