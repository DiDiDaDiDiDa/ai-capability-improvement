"""
Gateway Provider 抽象（P1↔P2 接缝）。

- LLMProvider：统一 chat(messages) → {content, usage, provider}
- MockGatewayProvider：离线规则答，演示引用纪律（默认）
- HttpGatewayProvider：OpenAI 兼容 /v1/chat/completions（真 Gateway / 真模型可热替换）

P2 落地后只需把 base_url 指到 Gateway，鉴权/路由/熔断由 Gateway 侧承担。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        """返回 {content: str, usage: dict, provider: str}。"""
        ...


@dataclass
class MockGatewayProvider:
    """
    教学 Mock：从 user 消息的 <evidence> 里找与 question 最相关的 [S#] 句，
    拼一条带引用的答案。不调网络，CI 可绿。
    """

    name: str = "mock-gateway"

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        user = ""
        for m in messages:
            if m.get("role") == "user":
                user = m.get("content", "")
        evidence = _extract_tag(user, "evidence")
        question = _extract_tag(user, "question")
        blocks = _parse_evidence_blocks(evidence)
        if not blocks:
            content = "根据现有资料无法确定。\n引用：（无）"
            return {"content": content, "usage": {"prompt_tokens": 0, "completion_tokens": 0}, "provider": self.name}

        q_tokens = set(_rough_tokens(question))
        best_sid, best_src, best_text, best_score = "S1", "", blocks[0][2], -1.0
        for sid, src, text in blocks:
            overlap = len(q_tokens & set(_rough_tokens(text)))
            # 数字/专名加权
            bonus = 0.0
            for tok in re.findall(r"\d+|VPN|X-KEY-99|Wi-Fi", question, flags=re.I):
                if tok.lower() in text.lower() or tok in text:
                    bonus += 2.0
            score = overlap + bonus
            if score > best_score:
                best_sid, best_src, best_text, best_score = sid, src, text, score

        # 取证据句中含答案信号的短摘录
        snippet = best_text.strip().replace("\n", " ")
        if len(snippet) > 120:
            snippet = snippet[:120] + "…"
        content = (
            f"根据资料：{snippet} [{best_sid}]\n"
            f"引用：[{best_sid}] {best_src}"
        )
        return {
            "content": content,
            "usage": {
                "prompt_tokens": sum(len(m.get("content", "")) for m in messages) // 4,
                "completion_tokens": len(content) // 4,
            },
            "provider": self.name,
        }


@dataclass
class HttpGatewayProvider:
    """
    OpenAI 兼容 Chat Completions。
    环境变量：
      P1_GATEWAY_URL   默认 http://127.0.0.1:8080/v1/chat/completions
      P1_GATEWAY_KEY   Bearer token（可选）
      P1_GATEWAY_MODEL 默认 gpt-4o-mini
    """

    base_url: str = ""
    api_key: str = ""
    model: str = "gpt-4o-mini"
    name: str = "http-gateway"
    timeout: float = 60.0

    def __post_init__(self) -> None:
        if not self.base_url:
            self.base_url = os.environ.get(
                "P1_GATEWAY_URL", "http://127.0.0.1:8080/v1/chat/completions"
            )
        if not self.api_key:
            self.api_key = os.environ.get("P1_GATEWAY_KEY", "")
        env_model = os.environ.get("P1_GATEWAY_MODEL")
        if env_model:
            self.model = env_model

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        body = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.0),
        }
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.base_url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise RuntimeError(f"gateway unreachable: {self.base_url} ({e})") from e
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"bad gateway response: {payload!r}") from e
        usage = payload.get("usage") or {}
        return {"content": content, "usage": usage, "provider": self.name}


def make_provider(kind: str | None = None) -> LLMProvider:
    """kind: mock | http；默认读 P1_PROVIDER，缺省 mock。"""
    k = (kind or os.environ.get("P1_PROVIDER") or "mock").strip().lower()
    if k in {"http", "gateway", "openai"}:
        return HttpGatewayProvider()
    return MockGatewayProvider()


# --- helpers ---

def _extract_tag(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, flags=re.S)
    return m.group(1).strip() if m else ""


def _parse_evidence_blocks(evidence: str) -> list[tuple[str, str, str]]:
    """解析 [S1] (doc#0, score=...)\\ntext → (sid, source, text)。"""
    if not evidence or evidence.startswith("(无"):
        return []
    parts = re.split(r"(?=\[S\d+\])", evidence)
    out: list[tuple[str, str, str]] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        m = re.match(r"\[(S\d+)\]\s*\(([^,]+)", p)
        if not m:
            continue
        sid, src = m.group(1), m.group(2).strip()
        # 去掉首行 meta，剩正文
        lines = p.split("\n", 1)
        body = lines[1].strip() if len(lines) > 1 else ""
        out.append((sid, src, body))
    return out


def _rough_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*|[一-鿿]{2}", text)
