# Prompt Version 管理：应用层版本治理 + Gateway 侧版本归因

> 所属项目：P2 · AI Gateway ｜ 对应模块 06（复用模块 02）｜ 日期：2026-07-23
> 代码：`p2gateway/prompt_client.py`（应用层 SDK），验收 `app.py` 第 10–14 段（全绿 EXIT:0）

## 一句话总结

**Prompt 管理不属于 Gateway，属于应用层。** 应用层 SDK（`PromptClient`）负责
「id+变量 → 解析版本 → 渲染 messages」；Gateway（Router/Cache）只吃「已渲染 messages +
一个不透明 `version_tag`」，做选型/缓存/**版本归因**，永不碰 prompt_id / 变量 / 模板。

## 0. 为什么这样分层（先讲清，这是本次的核心）

一个早期设计误区：把 Prompt 渲染塞进 Gateway 前端。问题在于——**渲染需要业务变量
（用户数据），是业务语义**；Gateway 是基础设施，本职是转发 messages + 路由/缓存/限流，
不该关心 messages 里装的是什么业务内容。把两者焊在一起 = 基础设施耦合业务语义。

正确的拆分：

| 关注点 | 干什么 | 放哪 | 为什么 |
|--------|--------|------|--------|
| **Prompt 解析+渲染** | `id+变量 → messages` | **应用层 SDK** | 要用业务变量，是业务语义 |
| **版本打标+归因** | 请求上带 `version_tag` | **Gateway** | 成本/延迟/模型/命中都在 Gateway 汇聚，版本标这里才能关联 |

所以本实现把 prompt 逻辑放在**应用层 SDK**，Gateway 只接收一个**不透明字符串** tag
用于归因——它不知道 `qa@v1` 背后是什么 prompt，只知道「这次请求属于这个版本」，
好把版本与该请求的 cost/latency/model 关联起来。

> 注：Portkey / Helicone 这类产品确实把 prompt 管理做进 Gateway，图的是「单点可观测」。
> 那是一种取舍（换来的是耦合）。本项目选**分层干净**这条路：Gateway 保持 prompt-agnostic。

## 1. 分层架构

```
应用层
  PromptClient（SDK，复用模块02 Registry）
    resolve(id, version|alias|ab) → PromptSpec
    spec.build(**variables) → messages          ← 业务变量在此渲染
    version_tag = "qa@v1"（不透明字符串）
        │  gateway.chat(messages, version_tag=tag, strategy=…)
        ▼
─────────────────────────────────────────────── 层边界（Gateway 只见 messages + tag）
基础设施层（Gateway）
  CachedProvider → ModelRouter → Provider
    各组件 stamp usage["version_tag"] = tag       ← 与 cost/latency/routing 同处，可归因
```

职责边界（代码里的体现）：

- **SDK 侧**：`resp["prompt_meta"]` 存完整版本信息（template_id/version/fingerprint/resolved_by）。
- **Gateway 侧**：`usage["version_tag"]` 只存一个不透明字符串。Router/Cache 用
  `kwargs.pop("version_tag")` 取出、stamp 进 usage——**它们的代码里没有任何 prompt 概念**。

## 2. 复用模块 02，不是复制

`PromptClient` 直接 import 模块 02 的 `PromptRegistry`（`experiments/prompt-sdk`），一行没重写：

```python
_SDK = _REPO / "experiments" / "prompt-sdk"
sys.path.insert(0, str(_SDK))
from prompt_registry import PromptRegistry, PromptSpec, Template, RegistryError
```

复用到的能力：id@version 不可变 / alias 发布回滚 / `ab_route` 稳定分桶 / `resolve` 钉扎 /
`Template.render` 缺变量早失败 / `content_fingerprint` 审计。SDK 只加「渲染后传 tag 给
gateway + 记 prompt_meta」这层薄集成。

## 3. 四个能力怎么落（验收对应段）

- **版本钉扎（第10段）**：`version="v1"` 精确解析，v1/v2 指纹不同 → 可复现。
- **alias 发布/回滚（第11段）**：`prod: v1→灰度v2→回滚v1`，调用方始终只写 `alias="prod"`，
  切版本/回滚**不改调用代码**——版本决策收敛到 `set_alias` 一处。
- **A/B 稳定分桶（第12段）**：`sha256(experiment_id:user_key)` 分桶，u42 五次恒 v1，
  30 个不同用户覆盖 v1+v2 → 同用户体验一致、实验可归因。
- **版本不可变（第13段）**：重复注册 `qa@v1` 被 `RegistryError` 拒 → 同号不同内容不可能发生。
- **全链路（第14段）**：`PromptClient(CachedProvider(ModelRouter(...)))`，SDK 出 prompt_meta、
  Gateway 出 version_tag + cache + routing——**版本治理与选型/缓存正交解耦，各记各的**。

## 4. 为什么这些决策

- **业务只传 prompt_id 不传文本**：改 prompt 不改业务代码、可灰度、可归因。
- **发布回滚走 alias**：版本决策收敛一处，回滚调用方零改动。
- **A/B 按 user_key 稳定分桶**：同用户落同版本，否则体验漂移 + 实验数据脏。
- **版本不可变**：同号不同内容会让复现与审计失效，改则发新号。
- **Gateway 只收不透明 tag**：基础设施不耦合业务语义，还能把版本与成本/延迟关联做归因。

## 5. 踩过的坑 / 易混淆点

- **把 Prompt 渲染放进 Gateway**：基础设施耦合业务变量。渲染是应用层的事，Gateway 只收 messages。
- **Gateway 存 prompt_id/模板**：越权。Gateway 只该拿到不透明 version_tag 做归因。
- **调用方写死 version**：回滚要改所有调用点。用 alias 收敛。
- **A/B 随机分桶**：同用户漂移。必须按 user_key 稳定哈希。
- **prompt_meta 和 version_tag 混为一谈**：前者是 SDK 侧完整记录，后者是 Gateway 侧不透明标签，
  分离才对——一个服务业务审计，一个服务基础设施归因。

## 6. 面试问答（自测）

- **Q: Prompt 版本管理该放 Gateway 还是应用层？** 渲染放应用层（要业务变量、是业务语义）；
  Gateway 只做版本归因（收不透明 tag）。把渲染放 Gateway 是基础设施耦合业务。
- **Q: 为什么 Gateway 还要碰 version_tag？** 成本/延迟/模型/命中都在 Gateway 汇聚，
  版本标在这里才能回答「哪个 prompt 版本导致了这次贵/慢」。但只收不透明 tag，不解析内容。
- **Q: 发布回滚为什么用 alias？** 版本决策收敛一处，调用方零改动。
- **Q: A/B 为什么按 user_key 稳定分桶？** 同用户体验一致 + 实验可归因。
- **Q: 版本为什么不可变？** 同号不同内容会让复现/审计失效。

## 参考资料

- 复用源：`experiments/prompt-sdk/prompt_registry.py`（模块 02 · Registry/版本/别名/AB）
- 模块 02 笔记：`docs/02-prompt-engineering/prompt-registry.md`
- 集成代码：`p2gateway/prompt_client.py`、验收 `app.py`（10–14 段）
