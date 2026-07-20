"""Sandbox workspace: all file/tool paths must resolve under root."""

from __future__ import annotations

from pathlib import Path


class WorkspaceError(ValueError):
    pass


class Workspace:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise WorkspaceError(f"workspace root not a directory: {self.root}")

    def resolve(self, rel: str) -> Path:
        """Map relative path → absolute under root; reject escape."""
        rel = (rel or "").strip().lstrip("/")
        if not rel:
            raise WorkspaceError("empty path")
        if rel.startswith("..") or "/../" in f"/{rel}/":
            # still allow resolve check below
            pass
        candidate = (self.root / rel).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as e:
            raise WorkspaceError(f"path escapes workspace: {rel}") from e
        return candidate

    def relpath(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.root))
