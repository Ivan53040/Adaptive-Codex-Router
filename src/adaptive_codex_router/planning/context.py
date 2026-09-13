"""Small, dependency-free repository snapshot for the local planner."""

from __future__ import annotations

import re
from pathlib import Path

_IGNORED_PARTS = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
    "vendor",
}
_TEXT_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
_PRIORITY_NAMES = {
    "agents.md",
    "architecture.md",
    "cargo.toml",
    "go.mod",
    "package.json",
    "pyproject.toml",
    "readme.md",
    "requirements.txt",
}


def build_workspace_context(
    workspace: str | Path,
    prompt: str,
    *,
    max_chars: int,
    max_files: int = 400,
) -> str:
    root = Path(workspace).resolve()
    if not root.is_dir() or max_chars <= 0:
        return ""

    files: list[Path] = []
    for candidate in root.rglob("*"):
        if len(files) >= max_files:
            break
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_symlink() or not candidate.is_file():
            continue
        if any(part.lower() in _IGNORED_PARTS for part in relative.parts):
            continue
        files.append(candidate)

    relative_names = [path.relative_to(root).as_posix() for path in files]
    listing = "FILES\n" + "\n".join(relative_names)
    remaining = max_chars - len(listing)
    if remaining <= 0:
        return listing[:max_chars]

    prompt_terms = {
        term.lower()
        for term in re.findall(r"[A-Za-z0-9_.-]{3,}", prompt)
        if term.lower() not in {"the", "and", "for", "with", "from", "this", "that"}
    }

    def score(path: Path) -> tuple[int, int, str]:
        relative = path.relative_to(root).as_posix().lower()
        name = path.name.lower()
        explicit = sum(5 for term in prompt_terms if term in relative)
        priority = 4 if name in _PRIORITY_NAMES else 0
        source = 1 if path.suffix.lower() in _TEXT_SUFFIXES else 0
        return (-(explicit + priority + source), len(relative), relative)

    sections = [listing]
    for path in sorted(files, key=score):
        if path.suffix.lower() not in _TEXT_SUFFIXES and path.name.lower() not in _PRIORITY_NAMES:
            continue
        try:
            if path.stat().st_size > 256_000:
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        relative = path.relative_to(root).as_posix()
        block = f"\n\nFILE {relative}\n{content}"
        if len(block) > remaining:
            if remaining > 200:
                sections.append(block[:remaining])
            break
        sections.append(block)
        remaining -= len(block)
    return "".join(sections)
