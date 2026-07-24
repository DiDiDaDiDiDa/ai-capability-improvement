#!/usr/bin/env python3
"""
P2 AI Gateway · Model Router 验收入口。

M2 Model Router：按成本 / 延迟 / 能力动态选模型。
  - 四策略：cost / latency / quality / balanced
  - 能力硬过滤：need_caps 不满足直接淘汰
  - 无候选 → RouteError（绝不静默乱选）
  - Router 自身实现 LLMProvider.chat 契约（对 P1 就是普通 Provider，可组合热插）

运行:
  cd projects/p2-ai-gateway && python3 app.py
"""
from __future__ import annotations

import sys

from p2gateway.providers import ModelProfile, ScriptedProvider
from p2gateway.router import ModelRouter, RouteError, RouteRequest
from p2gateway.semantic_cache import CachedProvider, SemanticCache
from p2gateway.prompt_client import (
    PromptClient,
    PromptRegistry,
    PromptRequest,
    PromptSpec,
    RegistryError,
    Template,
)


def section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def assert_true(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def build_fleet() -> list[ScriptedProvider]:
    """三档模型：便宜快但弱 / 均衡 / 贵慢但强+多能力。可复现的教学画像。"""
    return [
        ScriptedProvider(ModelProfile(
            name="cheap-fast", cost_per_1k=0.10, latency_ms=200, quality=0.60,
            capabilities=frozenset({"zh", "chat"}), max_context=8192)),
        ScriptedProvider(ModelProfile(
            name="balanced-mid", cost_per_1k=0.50, latency_ms=500, quality=0.80,
            capabilities=frozenset({"zh", "chat", "code"}), max_context=32768)),
        ScriptedProvider(ModelProfile(
            name="premium-strong", cost_per_1k=3.00, latency_ms=1200, quality=0.97,
            capabilities=frozenset({"zh", "chat", "code", "vision"}), max_context=128000)),
    ]


MSG = [{"role": "user", "content": "帮我写一个快速排序并解释复杂度"}]


def demo_strategies() -> None:
    section("1) 四策略选型：cost / latency / quality / balanced")
    router = ModelRouter(build_fleet())
    expect = {
        "cost": "cheap-fast",
        "latency": "cheap-fast",
        "quality": "premium-strong",
    }
    for strat, want in expect.items():
        _, d = router.route(RouteRequest(messages=MSG, strategy=strat))
        print(f"  strategy={strat:8s} → {d.chosen:15s} score={d.score} order={d.candidates}")
        assert_true(d.chosen == want, f"{strat} should pick {want}, got {d.chosen}")
    # balanced：不是最便宜也不是最强，成本权重略高 → 落在便宜/均衡之间
    _, db = router.route(RouteRequest(messages=MSG, strategy="balanced"))
    print(f"  strategy=balanced → {db.chosen:15s} score={db.score} order={db.candidates}")
    assert_true(db.chosen in {"cheap-fast", "balanced-mid"}, f"balanced unexpected: {db.chosen}")
    print("  strategies: PASS")


def demo_capability_filter() -> None:
    section("2) 能力硬过滤：need vision → 只有 premium 幸存")
    router = ModelRouter(build_fleet())
    _, d = router.route(RouteRequest(messages=MSG, strategy="cost", need_caps={"vision"}))
    print(f"  need=vision, strategy=cost → {d.chosen}")
    print(f"  rejected={d.rejected}")
    # 即便策略是 cost，能力不满足的 cheap/mid 被淘汰，只能选 premium
    assert_true(d.chosen == "premium-strong", f"vision must route to premium, got {d.chosen}")
    assert_true("cheap-fast" in d.rejected and "vision" in d.rejected["cheap-fast"], "cheap must be rejected for caps")
    print("  capability filter: PASS")


def demo_budget_filter() -> None:
    section("3) 成本/延迟上限：约束淘汰候选")
    router = ModelRouter(build_fleet())
    # 成本上限 0.2 → 只有 cheap-fast 活着
    _, d = router.route(RouteRequest(messages=MSG, strategy="quality", max_cost_per_1k=0.2))
    print(f"  max_cost=0.2, strategy=quality → {d.chosen} (质量优先也被预算摁住)")
    assert_true(d.chosen == "cheap-fast", f"budget cap should force cheap-fast, got {d.chosen}")
    # 延迟上限 600ms → premium(1200) 出局
    _, d2 = router.route(RouteRequest(messages=MSG, strategy="quality", max_latency_ms=600))
    print(f"  max_latency=600, strategy=quality → {d2.chosen}")
    assert_true(d2.chosen == "balanced-mid", f"latency cap should pick balanced-mid, got {d2.chosen}")
    assert_true("premium-strong" in d2.rejected, "premium must be rejected for latency")
    print("  budget/latency filter: PASS")


def demo_no_candidate() -> None:
    section("4) 无候选满足 → RouteError（不静默乱选）")
    router = ModelRouter(build_fleet())
    raised = False
    try:
        router.route(RouteRequest(messages=MSG, need_caps={"audio"}))  # 无人支持 audio
    except RouteError as e:
        raised = True
        print(f"  RouteError raised: {str(e)[:70]}…")
    assert_true(raised, "must raise RouteError when no candidate")
    print("  no-candidate guard: PASS")


def demo_chat_contract() -> None:
    section("5) Router 实现 LLMProvider.chat 契约（对 P1 可热插）")
    router = ModelRouter(build_fleet())
    resp = router.chat(MSG, strategy="balanced", need_caps={"code"})
    print(f"  content={resp['content'][:40]}…")
    print(f"  provider={resp['provider']} router={resp.get('router')}")
    print(f"  usage.cost_usd={resp['usage'].get('cost_usd')} routing.chosen={resp['usage']['routing']['chosen']}")
    # 契约字段齐全
    assert_true(set(resp) >= {"content", "usage", "provider"}, "must satisfy P1 chat contract")
    assert_true("routing" in resp["usage"], "routing decision must be observable in usage")
    assert_true(resp["usage"]["routing"]["chosen"] == resp["provider"], "chosen must match executing provider")
    # need code → cheap-fast(无code)出局，只会在 mid/premium 里选
    assert_true(resp["provider"] in {"balanced-mid", "premium-strong"}, f"code cap wrong: {resp['provider']}")
    print("  chat contract: PASS")


class CountingProvider:
    """计数 Provider：记录底层被真实调用几次，用于证明缓存省了调用。"""

    name = "counting"

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        return {"content": f"answer:{user}", "usage": {"prompt_tokens": 10}, "provider": self.name}


def _q(text: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": text}]


def demo_cache_hit_and_save() -> None:
    section("6) Semantic Cache: 近似问法命中，省底层调用")
    backend = CountingProvider()
    cached = CachedProvider(inner=backend, cache=SemanticCache(threshold=0.85))

    # char-ngram embedding 命中的是「字面高度重合」的变体：加标点、加前缀词、语气词
    r1 = cached.chat(_q("如何重置公司邮箱密码"))          # miss → 真调
    r2 = cached.chat(_q("请问如何重置公司邮箱密码"))      # 加前缀 sim≈0.90 → 命中
    r3 = cached.chat(_q("如何重置公司邮箱密码？"))        # 加标点 sim≈0.95 → 命中
    print(f"  q1 cache={r1['usage']['cache']['status']}")
    print(f"  q2 cache={r2['usage']['cache']['status']} sim={r2['usage']['cache']['similarity']}")
    print(f"  q3 cache={r3['usage']['cache']['status']} sim={r3['usage']['cache']['similarity']}")
    print(f"  底层真实调用次数={backend.calls}（3 次请求只调 1 次）")
    print(f"  stats={cached.cache.stats()}")
    assert_true(r1["usage"]["cache"]["status"] == "miss", "first must miss")
    assert_true(r2["usage"]["cache"]["status"] == "hit", "prefix variant must hit")
    assert_true(r3["usage"]["cache"]["status"] == "hit", "punct variant must hit")
    assert_true(backend.calls == 1, f"backend should be called once, got {backend.calls}")
    assert_true(r2["content"] == r1["content"], "hit must return cached answer")
    print("  cache hit + save: PASS")


def demo_cache_no_false_hit() -> None:
    section("7) Semantic Cache: 阈值防误命中（不同意图不复用）")
    backend = CountingProvider()
    cached = CachedProvider(inner=backend, cache=SemanticCache(threshold=0.9))
    cached.chat(_q("北京今天天气怎么样"))               # miss → 真调
    r2 = cached.chat(_q("上海今天天气怎么样"))           # 意图不同 → 不应命中
    print(f"  q2 cache={r2['usage']['cache']['status']} sim={r2['usage']['cache']['similarity']}")
    print(f"  底层调用次数={backend.calls}（两个不同城市，必须各调一次）")
    assert_true(r2["usage"]["cache"]["status"] == "miss", "different intent must NOT hit")
    assert_true(backend.calls == 2, f"both must call backend, got {backend.calls}")
    print("  no-false-hit: PASS（语义相似≠答案相同，阈值是安全阀）")


def demo_cache_ttl() -> None:
    section("8) Semantic Cache: TTL 过期失效")
    import time
    backend = CountingProvider()
    cached = CachedProvider(inner=backend, cache=SemanticCache(threshold=0.85, ttl_s=0.3))
    cached.chat(_q("查询本月报销额度"))                  # miss → 写缓存
    hit = cached.chat(_q("查询本月报销额度"))            # 立刻查 → 命中
    time.sleep(0.4)                                      # 等过期
    after = cached.chat(_q("查询本月报销额度"))          # 过期 → 重新真调
    print(f"  即时={hit['usage']['cache']['status']} 过期后={after['usage']['cache']['status']}")
    print(f"  底层调用次数={backend.calls}（首次 + 过期后 = 2）")
    assert_true(hit["usage"]["cache"]["status"] == "hit", "immediate re-query must hit")
    assert_true(after["usage"]["cache"]["status"] == "miss", "expired must miss")
    assert_true(backend.calls == 2, f"expired should re-call, got {backend.calls}")
    print("  ttl expiry: PASS")


def demo_cache_over_router() -> None:
    section("9) 组合: Cache 套在 Router 外层（命中连选型都省）")
    router = ModelRouter(build_fleet())
    cached = CachedProvider(inner=router, cache=SemanticCache(threshold=0.85))
    r1 = cached.chat(_q("写个冒泡排序函数"), strategy="cost")   # miss → 走 Router 选型
    r2 = cached.chat(_q("请写个冒泡排序函数"), strategy="cost")  # 加前缀 sim≈0.94 → 命中
    print(f"  q1 cache=miss provider={r1['provider']} routing.chosen={r1['usage'].get('routing',{}).get('chosen')}")
    print(f"  q2 cache={r2['usage']['cache']['status']}（命中则连 Router 都不触发）")
    assert_true(r2["usage"]["cache"]["status"] == "hit", "similar must hit over router")
    assert_true(r2["provider"] == r1["provider"], "cached provider preserved")
    print("  cache-over-router: PASS")


def build_registry() -> PromptRegistry:
    """注册同一 prompt 的两个版本 + prod 别名（模拟迭代发布）。"""
    reg = PromptRegistry()
    reg.register(PromptSpec(
        template_id="qa", version="v1", system="你是客服助手，简洁回答。",
        user_template=Template("问题：{q}", name="qa", version="v1")))
    reg.register(PromptSpec(
        template_id="qa", version="v2", system="你是资深客服，先复述问题再分点回答。",
        user_template=Template("用户问题：{q}\n请分点回答。", name="qa", version="v2")))
    reg.set_alias("prod", "qa", "v1")            # 先发 v1 上线
    return reg


def demo_prompt_versions() -> None:
    section("10) Prompt Version：版本钉扎复现 + 缺变量早失败（复用模块02）")
    reg = build_registry()
    sdk = PromptClient(registry=reg, gateway=CountingProvider())
    r1 = sdk.run(PromptRequest(prompt_id="qa", version="v1", variables={"q": "怎么退货"}))
    r2 = sdk.run(PromptRequest(prompt_id="qa", version="v2", variables={"q": "怎么退货"}))
    print(f"  v1 messages[0]={r1['messages'][0]['content'][:20]}… prompt_meta.version={r1['prompt_meta']['version']}")
    print(f"  v2 messages[0]={r2['messages'][0]['content'][:20]}… prompt_meta.version={r2['prompt_meta']['version']}")
    print(f"  gateway 侧归因 usage.version_tag={r1['usage']['version_tag']}")
    # SDK 侧完整版本记录
    assert_true(r1["prompt_meta"]["version"] == "v1", "must pin v1")
    assert_true(r2["prompt_meta"]["version"] == "v2", "must pin v2")
    assert_true(r1["prompt_meta"]["fingerprint"] != r2["prompt_meta"]["fingerprint"], "版本指纹应不同")
    # gateway 侧只见不透明 tag（归因），不见 prompt_id/变量
    assert_true(r1["usage"]["version_tag"] == "qa@v1", "gateway must stamp opaque version_tag")
    # 缺变量早失败（模块 02 契约）
    raised = False
    try:
        sdk.run(PromptRequest(prompt_id="qa", version="v1", variables={}))
    except Exception as e:
        raised = "缺少变量" in str(e) or "q" in str(e)
    assert_true(raised, "missing var must fail early")
    print("  version pin + missing-var + gateway 归因: PASS")


def demo_prompt_alias_rollback() -> None:
    section("11) Prompt Version：alias 发布/回滚（改指向不改代码）")
    reg = build_registry()
    sdk = PromptClient(registry=reg, gateway=CountingProvider())
    before = sdk.run(PromptRequest(prompt_id="qa", alias="prod", variables={"q": "x"}))
    reg.set_alias("prod", "qa", "v2")            # 灰度：prod 指向 v2（无需改调用方）
    after = sdk.run(PromptRequest(prompt_id="qa", alias="prod", variables={"q": "x"}))
    reg.set_alias("prod", "qa", "v1")            # 回滚：出问题一键切回 v1
    rolled = sdk.run(PromptRequest(prompt_id="qa", alias="prod", variables={"q": "x"}))
    print(f"  prod: {before['prompt_meta']['version']} → 灰度 {after['prompt_meta']['version']} → 回滚 {rolled['prompt_meta']['version']}")
    assert_true(before["prompt_meta"]["version"] == "v1", "prod initially v1")
    assert_true(after["prompt_meta"]["version"] == "v2", "alias switch to v2")
    assert_true(rolled["prompt_meta"]["version"] == "v1", "rollback to v1")
    print("  alias publish/rollback: PASS（调用方始终只写 alias=prod）")


def demo_prompt_ab() -> None:
    section("12) Prompt Version：A/B 稳定分桶（同用户落同版本）")
    reg = build_registry()
    sdk = PromptClient(registry=reg, gateway=CountingProvider())
    arms = [("v1", 50), ("v2", 50)]
    # 同一 user_key 多次调用必落同版本（可复现）
    picks = {sdk.run(PromptRequest(prompt_id="qa", ab=arms, user_key="u42", variables={"q": "x"}))["prompt_meta"]["version"] for _ in range(5)}
    print(f"  user=u42 五次落桶版本集合={picks}（应恒为 1 个）")
    assert_true(len(picks) == 1, f"same user must be stable, got {picks}")
    # 不同用户应能分散到两个臂
    seen = {sdk.run(PromptRequest(prompt_id="qa", ab=arms, user_key=f"u{i}", variables={"q": "x"}))["prompt_meta"]["version"] for i in range(30)}
    print(f"  30 个不同用户覆盖版本={sorted(seen)}")
    assert_true(seen == {"v1", "v2"}, f"AB should split across arms, got {seen}")
    print("  A/B stable bucketing: PASS")


def demo_prompt_immutable() -> None:
    section("13) Prompt Version：版本不可变（防覆盖事故）")
    reg = build_registry()
    raised = False
    try:
        reg.register(PromptSpec(template_id="qa", version="v1", system="改坏了",
                                user_template=Template("x", name="qa", version="v1")))
    except RegistryError:
        raised = True
    print(f"  重复注册 qa@v1 被拒={raised}")
    assert_true(raised, "duplicate version must be rejected (immutable)")
    print("  immutability: PASS")


def demo_prompt_full_chain() -> None:
    section("14) 端到端：Prompt→Cache→Router 全链路")
    reg = build_registry()
    # 分层：应用层 SDK（Prompt）→ Gateway（Cache→Router→Provider）
    gateway = CachedProvider(inner=ModelRouter(build_fleet()), cache=SemanticCache(threshold=0.85))
    sdk = PromptClient(registry=reg, gateway=gateway)
    resp = sdk.run(PromptRequest(prompt_id="qa", alias="prod", variables={"q": "怎么退货"}),
                   strategy="cost")
    p = resp["prompt_meta"]
    u = resp["usage"]
    print(f"  [SDK] prompt_meta={p['template_id']}@{p['version']} (resolved_by={p['resolved_by']})")
    print(f"  [Gateway] version_tag={u['version_tag']} provider={resp['provider']} cache={u['cache']['status']} routing.chosen={u.get('routing',{}).get('chosen')}")
    # SDK 侧完整版本记录
    assert_true(p["version"] == "v1", "prod resolves v1")
    # Gateway 侧：version_tag 与 cost/routing/cache 同处 usage → 可关联归因，但 gateway 不碰 prompt 内容
    assert_true(u["version_tag"] == "qa@v1", "gateway stamps opaque version_tag")
    assert_true(resp["provider"] == "cheap-fast", "cost strategy picks cheap-fast")
    assert_true({"cache", "routing", "version_tag"} <= set(u), "归因元数据齐全")
    print("  full chain: PASS（应用层版本治理 + Gateway 侧版本归因，正交解耦）")


def main() -> int:
    print("P2 AI Gateway · Router + Semantic Cache + Prompt Version acceptance")
    demo_strategies()
    demo_capability_filter()
    demo_budget_filter()
    demo_no_candidate()
    demo_chat_contract()
    demo_cache_hit_and_save()
    demo_cache_no_false_hit()
    demo_cache_ttl()
    demo_cache_over_router()
    demo_prompt_versions()
    demo_prompt_alias_rollback()
    demo_prompt_ab()
    demo_prompt_immutable()
    demo_prompt_full_chain()
    section("DONE · P2 Router + Semantic Cache + Prompt Version green")
    print("  Router: cost/latency/quality/balanced + 硬过滤 + 报错 + chat 契约")
    print("  Cache: 近似命中省调用 + 阈值防误命中 + TTL 失效 + 可套 Router 外层")
    print("  Prompt: 应用层版本治理(SDK 复用模块02) + Gateway 侧不透明 version_tag 归因")
    print("EXIT:0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print(f"ASSERT FAIL: {e}", file=sys.stderr)
        raise SystemExit(1)
