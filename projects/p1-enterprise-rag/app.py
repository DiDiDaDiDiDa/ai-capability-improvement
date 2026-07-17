#!/usr/bin/env python3
"""
P1 企业级 RAG · M4 工程化可运行入口。

默认 Mock Gateway（离线全绿）；接真 Gateway：
  P1_PROVIDER=http P1_GATEWAY_URL=http://host:port/v1/chat/completions \\
  P1_GATEWAY_KEY=... python3 app.py

运行: python3 app.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from p1rag.gateway import make_provider
from p1rag.pipeline import RAGPipeline


def section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def main() -> None:
    data_dir = ROOT / "data"
    provider = make_provider()  # mock by default
    print(f"P1 Enterprise RAG  |  provider={getattr(provider, 'name', provider)}")
    print(f"data_dir={data_dir}")

    pipe = RAGPipeline.from_data_dir(data_dir, provider=provider)
    section("1) 多格式导入")
    for doc_id, text in pipe.corpus.items():
        print(f"  {doc_id:<22} chars={len(text)}  head={text.splitlines()[0][:40]!r}")
    assert any(d.endswith(".md") for d in pipe.corpus), "应导入 markdown"
    assert any(d.endswith(".txt") for d in pipe.corpus), "应导入 txt"
    print(f"  chunks indexed: {len(pipe.index.chunks)}")
    assert len(pipe.index.chunks) >= 4, "索引块过少"

    cases = [
        ("一线城市住宿报销上限多少", "policy-travel.md", "500"),
        ("工龄满二十年年假多少天", "hr-leave.md", "15"),
        ("公共 Wi-Fi 要开 VPN 吗", "it-security.md", "VPN"),
        ("X-KEY-99 谁能轮换", "it-security.md", "安全组"),
    ]

    section("2) Hybrid 检索 + Grounded Prompt + Gateway")
    hit_n = 0
    cite_n = 0
    for q, gold, must in cases:
        r = pipe.ask(q, top_k=3, gold_doc=gold)
        ok = bool(r.gold_hit)
        hit_n += ok
        has_cite = bool(r.citations) and any(
            c["sid"] in r.answer or c["source"].split("#")[0] in r.answer for c in r.citations
        )
        # Mock 答案必含 [S#]；Http 侧至少 citations 结构在
        if "[S" in r.answer or has_cite:
            cite_n += 1
        print(f"\nQ: {q}")
        print(f"  gold={gold} hit@k={'YES' if ok else 'NO'}  provider={r.provider}")
        print(f"  hits: {[h['source'] for h in r.hits]}")
        print(f"  citations: {r.citations}")
        print(f"  grounded_ok={r.grounded_ok}  template={r.prompt_meta}")
        print(f"  answer: {r.answer[:200]}")
        assert r.grounded_ok, f"grounded 校验失败: {r.prompt_meta}"
        assert r.citations, "必须带来源 citations"
        if r.provider == "mock-gateway":
            assert "[S" in r.answer, "Mock 答案必须含 [S#] 引用"
            assert must in r.answer or any(must in h["preview"] for h in r.hits), (
                f"证据或答案应含关键信号 {must!r}"
            )

    print(f"\n  hit@3 gold_doc: {hit_n}/{len(cases)}  answers_with_cite_signal: {cite_n}/{len(cases)}")
    assert hit_n == len(cases), "四道题 gold 均应进入 Top-K（Hybrid）"
    assert cite_n == len(cases), "答案侧应有引用信号"

    section("3) Provider 抽象可热替换")
    mock = make_provider("mock")
    assert mock.name == "mock-gateway"
    # Http 构造不连网，只验证配置接口
    from p1rag.gateway import HttpGatewayProvider

    http = HttpGatewayProvider(base_url="http://example.invalid/v1/chat/completions")
    assert http.name == "http-gateway"
    print(f"  mock={mock.name}  http={http.name} url={http.base_url}")
    print("  → 接 P2：P1_PROVIDER=http P1_GATEWAY_URL=<gateway>/v1/chat/completions")

    section("4) 结构化输出样例（便于对接）")
    sample = pipe.ask(cases[0][0], top_k=2, gold_doc=cases[0][1])
    out = {
        "question": sample.question,
        "answer": sample.answer,
        "citations": sample.citations,
        "provider": sample.provider,
        "usage": sample.usage,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))

    section("DONE · P1 M4 green")
    print("pipeline: load md/txt → hybrid → rag-grounded.v1 → gateway(provider) → answer+[S#]")


if __name__ == "__main__":
    main()
