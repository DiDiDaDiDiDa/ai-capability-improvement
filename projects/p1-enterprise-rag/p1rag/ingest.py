"""多格式文档导入：Markdown / TXT（PDF/Word 预留接口）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_SUFFIXES = {".md", ".txt", ".markdown"}


@dataclass(frozen=True)
class Document:
    doc_id: str
    text: str
    path: str
    fmt: str


def clean_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def load_document(path: Path) -> Document:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"unsupported format: {suffix} ({path})")
    raw = path.read_text(encoding="utf-8")
    fmt = "markdown" if suffix in {".md", ".markdown"} else "txt"
    return Document(doc_id=path.name, text=clean_text(raw), path=str(path), fmt=fmt)


def load_corpus(data_dir: Path | str) -> dict[str, str]:
    """扫描目录，返回 doc_id → text。忽略隐藏文件与不支持后缀。"""
    root = Path(data_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"data_dir not found: {root}")
    corpus: dict[str, str] = {}
    for p in sorted(root.iterdir()):
        if p.name.startswith("."):
            continue
        if p.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        doc = load_document(p)
        corpus[doc.doc_id] = doc.text
    if not corpus:
        raise ValueError(f"no .md/.txt documents in {root}")
    return corpus
