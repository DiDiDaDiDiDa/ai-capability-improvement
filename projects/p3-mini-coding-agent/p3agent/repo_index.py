"""
M4 · Repository Understanding —— 大仓库理解的两条路（纯标准库）。

不引向量库：教学项目要证明的是「索引 + 检索」的本质，不是特定库。
  A) repo map (Aider 风格) —— ast 提取函数/类符号摘要，压 token 给 LLM 冷启动
  B) 轻量检索 (Cursor 预索引的 stdlib 版) —— 按块建 TF-IDF 索引，按 query 排序命中

关键区别（面试点）：
  agentic search（M1 的 search_code）= 无索引、按需 grep，靠强模型多轮拉取
  预索引检索（本文件）              = 一次建索引、多次快速召回，适合大仓库冷启动
"""
from __future__ import annotations

import ast
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ------------------------------------------------------------
# A) repo map：ast 抽符号（函数 / 类 / 方法）
# ------------------------------------------------------------
@dataclass
class Symbol:
    kind: str      # "func" | "class" | "method"
    name: str
    lineno: int
    signature: str
    doc: str = ""


def extract_symbols(source: str) -> list[Symbol]:
    """从单文件源码抽取顶层函数/类及类内方法。语法错误则返回空。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    syms: list[Symbol] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            syms.append(_fn_symbol(node, kind="func"))
        elif isinstance(node, ast.ClassDef):
            doc = (ast.get_docstring(node) or "").split("\n")[0]
            syms.append(Symbol("class", node.name, node.lineno, f"class {node.name}", doc))
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    syms.append(_fn_symbol(sub, kind="method", owner=node.name))
    return syms


def _fn_symbol(node: ast.FunctionDef | ast.AsyncFunctionDef, kind: str, owner: str = "") -> Symbol:
    args = [a.arg for a in node.args.args]
    name = f"{owner}.{node.name}" if owner else node.name
    sig = f"def {node.name}({', '.join(args)})"
    doc = (ast.get_docstring(node) or "").split("\n")[0]
    return Symbol(kind, name, node.lineno, sig, doc)


def build_repo_map(root: Path, glob: str = "*.py") -> dict[str, list[Symbol]]:
    """扫描仓库 → {相对路径: [符号,...]}。跳过隐藏目录与 __pycache__。"""
    out: dict[str, list[Symbol]] = {}
    for p in sorted(root.rglob(glob)):
        if not p.is_file():
            continue
        if any(part.startswith(".") or part == "__pycache__" for part in p.parts):
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        syms = extract_symbols(src)
        if syms:
            out[str(p.relative_to(root))] = syms
    return out


def render_repo_map(repo_map: dict[str, list[Symbol]]) -> str:
    """把 repo map 渲染成紧凑文本（喂 LLM 的低 token 仓库概览）。"""
    lines: list[str] = []
    for path, syms in repo_map.items():
        lines.append(f"{path}:")
        for s in syms:
            tag = {"func": "fn", "class": "cls", "method": "  ·"}[s.kind]
            suffix = f"  # {s.doc}" if s.doc else ""
            lines.append(f"  {tag} {s.signature}{suffix}")
    return "\n".join(lines)


# ------------------------------------------------------------
# B) 轻量检索：符号级 chunk + TF-IDF 余弦（Cursor 预索引的 stdlib 版）
# ------------------------------------------------------------
_TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")


def _tokenize(text: str) -> list[str]:
    """标识符切词 + 驼峰/下划线拆分，让 circleArea/circle_area 都能命中 'area'。"""
    toks: list[str] = []
    for w in _TOKEN_RE.findall(text.lower()):
        toks.append(w)
        toks.extend(part for part in w.split("_") if part)
        # 驼峰拆分（原词已 lower，这里对原始大小写不敏感，靠下划线为主）
    return toks


@dataclass
class Chunk:
    path: str
    lineno: int
    name: str
    text: str
    tf: Counter = field(default_factory=Counter)


@dataclass
class RepoRetriever:
    """一次建索引，多次检索。IDF 全局统计，query 与 chunk 做 TF-IDF 余弦。"""

    chunks: list[Chunk] = field(default_factory=list)
    idf: dict[str, float] = field(default_factory=dict)

    @classmethod
    def build(cls, root: Path, glob: str = "*.py") -> "RepoRetriever":
        repo_map = build_repo_map(root, glob)
        chunks: list[Chunk] = []
        for path, syms in repo_map.items():
            for s in syms:
                blob = f"{s.name} {s.signature} {s.doc}"
                chunks.append(Chunk(path, s.lineno, s.name, blob, Counter(_tokenize(blob))))
        # IDF: log(N / df)
        n = len(chunks) or 1
        df: Counter = Counter()
        for c in chunks:
            df.update(set(c.tf))
        idf = {t: math.log(n / (1 + d)) + 1.0 for t, d in df.items()}
        return cls(chunks=chunks, idf=idf)

    def _vec(self, tf: Counter) -> dict[str, float]:
        return {t: f * self.idf.get(t, 1.0) for t, f in tf.items()}

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        qv = self._vec(Counter(_tokenize(query)))
        qnorm = math.sqrt(sum(v * v for v in qv.values())) or 1e-9
        scored: list[tuple[float, Chunk]] = []
        for c in self.chunks:
            cv = self._vec(c.tf)
            dot = sum(qv.get(t, 0.0) * cv.get(t, 0.0) for t in qv)
            cnorm = math.sqrt(sum(v * v for v in cv.values())) or 1e-9
            score = dot / (qnorm * cnorm)
            if score > 0:
                scored.append((score, c))
        scored.sort(key=lambda x: (-x[0], x[1].path, x[1].lineno))
        return [
            {"path": c.path, "line": c.lineno, "name": c.name,
             "score": round(sc, 4), "preview": c.text[:120]}
            for sc, c in scored[:top_k]
        ]
