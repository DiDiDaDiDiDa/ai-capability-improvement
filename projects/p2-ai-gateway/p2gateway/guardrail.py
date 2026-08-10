"""
Guardrail（P2 M7）—— 输入输出安全 / 敏感信息 Masking。

套在链路**最外层**的安全阀：进模型前检查输入（拦注入/违规/输入侧 PII），返回调用方前
检查输出（拦不安全内容 + 对敏感信息脱敏）。三种处置：block（拒绝）/ mask（脱敏放行）/
flag（放行但打标告警）。

为什么最外层：安全检查必须在**任何昂贵操作之前**——输入 Guardrail 在 Cache/Router 之前，
被拦请求根本不该进缓存、更不该调模型（省钱又安全）。输出 Guardrail 是响应流出系统最后一关。

诚实边界（第 5 节）：正则 Masking 会漏检（变体格式）、会误检（订单号当银行卡），注入检测
更弱（关键词匹配只挡最粗糙的）。生产要叠加 NER + 专用内容安全模型分层纵深——**本模块是
最小规则内核，不声称能挡住一切。**
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable


# --- Masking 规则：(类型, 匹配正则, 替换函数) ---
def _mask_phone(m: re.Match) -> str:
    s = m.group()
    return s[:3] + "****" + s[-4:]


def _mask_email(m: re.Match) -> str:
    name, domain = m.group().split("@", 1)
    return (name[0] + "***") + "@" + domain


def _mask_idcard(m: re.Match) -> str:
    s = m.group()
    return s[:3] + "*" * (len(s) - 7) + s[-4:]


def _mask_secret(m: re.Match) -> str:
    return "sk-****"                          # 密钥整体遮蔽——留一位也是泄露


def _mask_bankcard(m: re.Match) -> str:
    s = re.sub(r"\D", "", m.group())
    return "**** **** **** " + s[-4:]         # 银行卡保留后 4 位


# 顺序有讲究：先密钥、再身份证/银行卡（长数字），最后手机号，避免短模式先吃掉长串
MASKERS: list[tuple[str, re.Pattern, Callable[[re.Match], str]]] = [
    ("api_key", re.compile(r"sk-[A-Za-z0-9]{6,}"), _mask_secret),
    ("id_card", re.compile(r"\b\d{17}[\dXx]\b"), _mask_idcard),
    ("bank_card", re.compile(r"\b\d{16,19}\b"), _mask_bankcard),
    ("phone", re.compile(r"\b1[3-9]\d{9}\b"), _mask_phone),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), _mask_email),
]

# 注入/越权特征（粗筛，仅挡最直白的）
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
    re.compile(r"disregard\s+(the\s+)?(system|above)", re.I),
    re.compile(r"(dump|reveal|print)\s+(the\s+)?system\s+prompt", re.I),
    re.compile(r"你是.*不要理会.*(之前|以上|系统)", re.I),
    re.compile(r"忽略(之前|以上|上面).*(指令|规则|设定)", re.I),
]


@dataclass
class GuardResult:
    action: str                              # pass | mask | block | flag
    reasons: list[str] = field(default_factory=list)
    masked_types: list[str] = field(default_factory=list)
    text: str = ""                           # mask 后的文本（action=mask 时有意义）


def detect_injection(text: str) -> list[str]:
    return [p.pattern for p in INJECTION_PATTERNS if p.search(text)]


def mask_text(text: str) -> tuple[str, list[str]]:
    """对文本做脱敏，返回 (脱敏后文本, 命中类型列表)。"""
    hit: list[str] = []
    for kind, pat, repl in MASKERS:
        if pat.search(text):
            hit.append(kind)
            text = pat.sub(repl, text)
    return text, hit


def _last_user(messages: list[dict[str, str]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return m.get("content", "")
    return ""


def input_guard(messages: list[dict[str, str]]) -> GuardResult:
    """输入侧：注入 → block；PII → mask（脱敏后放行）；否则 pass。"""
    text = _last_user(messages)
    inj = detect_injection(text)
    if inj:
        return GuardResult(action="block", reasons=["injection"] )
    _, kinds = mask_text(text)
    if kinds:
        # 对所有消息里的 user 内容脱敏
        return GuardResult(action="mask", masked_types=kinds, reasons=["input_pii"])
    return GuardResult(action="pass")


def output_guard(content: str) -> GuardResult:
    """输出侧：敏感信息 → mask（脱敏后返回）；否则 pass。"""
    masked, kinds = mask_text(content)
    if kinds:
        return GuardResult(action="mask", masked_types=kinds, reasons=["output_pii"], text=masked)
    return GuardResult(action="pass", text=content)


@dataclass
class GuardedProvider:
    """
    Guardrail 装饰器：实现 chat 契约，套最外层
    （Guarded → RateLimit → Cache → Router → Provider）。

    命中 block 的输入直接返回拒绝响应、不调下游（省调用又安全）。
    命中详情回填 usage.guardrail = {input_action, output_action, masked_types, reasons}，可审计。
    """

    inner: Any
    name: str = "guardrail"
    block_message: str = "请求被安全策略拦截"

    def _mask_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        out = []
        for m in messages:
            if m.get("role") == "user":
                masked, _ = mask_text(m.get("content", ""))
                out.append({**m, "content": masked})
            else:
                out.append(m)
        return out

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        ig = input_guard(messages)
        reasons = list(ig.reasons)
        masked_types = list(ig.masked_types)

        if ig.action == "block":
            return {
                "content": self.block_message,
                "provider": self.name,
                "usage": {"guardrail": {
                    "input_action": "block", "output_action": "n/a",
                    "masked_types": [], "reasons": reasons}},
            }

        safe_messages = self._mask_messages(messages) if ig.action == "mask" else messages
        resp = self.inner.chat(safe_messages, **kwargs)

        og = output_guard(resp.get("content", ""))
        if og.action == "mask":
            resp["content"] = og.text
            masked_types = masked_types + [t for t in og.masked_types if t not in masked_types]
            reasons = reasons + og.reasons

        usage = dict(resp.get("usage") or {})
        usage["guardrail"] = {
            "input_action": ig.action,
            "output_action": og.action,
            "masked_types": masked_types,
            "reasons": reasons,
        }
        resp["usage"] = usage
        return resp
