"""File processing: repo-to-text conversion, bundling, and image handling."""

import os
import fnmatch
from pathlib import Path

from lib.security import is_binary, is_image, BINARY_EXTENSIONS, IMAGE_EXTENSIONS

# Default patterns to always ignore
DEFAULT_IGNORE = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv",
    ".env", ".DS_Store", "Thumbs.db",
    "*.pyc", "*.pyo", "*.class",
    "*.o", "*.obj", "*.so", "*.dll", "*.exe", "*.bin",
}


def load_gitignore(repo_path):
    """Load .gitignore patterns from a repo.

    Supports basic Git-ignore semantics:
    - Comments (``#``) and blank lines are skipped.
    - Leading ``!`` (negation) is recognized and kept with the ``!`` prefix.
    - Trailing ``/`` on a pattern means directory-only matching.
    - Patterns anchored with ``/`` are anchored to the repo root.
    """
    patterns = []
    gitignore = Path(repo_path) / ".gitignore"
    if gitignore.exists():
        for line in gitignore.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            patterns.append(line)
    # Wrap in a list so caller can inspect/order later if needed.
    return DEFAULT_IGNORE, patterns


def should_ignore(path, default_patterns, gitignore_patterns=None, repo_root=None):
    """Check if a path matches any ignore pattern.

    *default_patterns* is a set of built-in patterns (always active).
    *gitignore_patterns* is a list from ``.gitignore`` (order matters for
    negation).
    *repo_root* is the repo root path (used to anchor ``/`` patterns).
    """
    name = path.name
    str_path = str(path)

    # Compute the repo-relative path for anchored pattern matching.
    if repo_root is not None:
        try:
            rel_path = str(Path(path).relative_to(repo_root))
        except ValueError:
            rel_path = str_path
    else:
        rel_path = str_path

    # Built-in patterns — fast set lookup for common cases.
    for pattern in default_patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
        if fnmatch.fnmatch(str_path, pattern):
            return True

    if not gitignore_patterns:
        return False

    # Gitignore patterns are applied in order so that ``!`` can un-ignore.
    ignored = False
    for pattern in gitignore_patterns:
        is_negation = pattern.startswith("!")
        if is_negation:
            pattern = pattern[1:]

        dir_only = pattern.endswith("/")
        if dir_only:
            pattern = pattern.rstrip("/")

        # Rooted patterns (starting with /) are anchored to repo root.
        anchored = pattern.startswith("/")
        if anchored:
            pattern = pattern.lstrip("/")

        if dir_only:
            # Only match directory names — skip if this is a file.
            if not path.is_dir():
                continue

        if anchored:
            # Match the repo-relative path, not the basename.
            matched = fnmatch.fnmatch(rel_path, pattern)
        else:
            matched = (
                fnmatch.fnmatch(name, pattern)
                or fnmatch.fnmatch(str_path, pattern)
            )

        if matched:
            ignored = not is_negation

    return ignored


def read_file_safe(path, max_size=100_000):
    """Read a file safely, handling encoding errors and size limits."""
    path = Path(path)
    if path.stat().st_size > max_size:
        return f"[File too large: {path.stat().st_size} bytes]"
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"[Error reading file: {e}]"


def repo_to_text(repo_path, include_patterns=None, exclude_patterns=None):
    """Convert a repository directory into a repomix-style unified text file.

    Produces output structured as:
    1. File summary (purpose, format, guidelines)
    2. Directory structure
    3. File contents wrapped in ``<file path="...">`` tags

    Args:
        repo_path: Path to the repository root
        include_patterns: Glob patterns to include (e.g., ["*.py", "*.js"])
        exclude_patterns: Additional glob patterns to exclude

    Returns:
        tuple: (unified_text, list_of_image_paths)
    """
    repo_path = Path(repo_path).resolve()
    if not repo_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {repo_path}")

    default_patterns, gitignore_raw = load_gitignore(repo_path)
    if exclude_patterns:
        gitignore_raw.extend(exclude_patterns)

    # First pass: discover all files and classify them.
    all_files = []       # (relative_path, status)  status: "ok" | "binary" | "image" | "skipped"
    file_contents = []   # (relative_path, content_string)
    image_paths = []

    for root, dirs, files in os.walk(repo_path, followlinks=False):
        root_path = Path(root)

        # Filter out ignored / symlinked directories.
        filtered_dirs = []
        for d in dirs:
            dpath = root_path / d
            if dpath.is_symlink():
                continue
            if should_ignore(dpath, default_patterns, gitignore_raw, repo_root=repo_path):
                continue
            filtered_dirs.append(d)
        dirs[:] = filtered_dirs

        for fname in sorted(files):
            fpath = root_path / fname

            if fpath.is_symlink():
                continue

            rel = str(fpath.relative_to(repo_path))

            if should_ignore(fpath, default_patterns, gitignore_raw, repo_root=repo_path):
                continue

            if include_patterns:
                if not any(fnmatch.fnmatch(fname, p) for p in include_patterns):
                    continue

            if is_image(fpath):
                image_paths.append(str(fpath))
                all_files.append((rel, "image"))
                continue

            if is_binary(fpath):
                all_files.append((rel, "binary"))
                continue

            content = read_file_safe(fpath)
            all_files.append((rel, "ok"))
            file_contents.append((rel, content))

    # --- Build output ---
    repo_name = repo_path.name
    file_count = len(all_files)
    content_count = len(file_contents)

    # 1. Summary section
    summary = f"""This file is a merged representation of the entire codebase, combined into
a single document by consult_with_copilot.

<file_summary>
This section contains a summary of this file.

<purpose>
This file contains a packed representation of the entire repository's contents.
It is designed to be easily consumable by AI systems for analysis, code review,
or other automated processes.
</purpose>

<file_format>
The content is organized as follows:
1. This summary section
2. Directory structure
3. Repository files, each wrapped in <file path="..."> tags
</file_format>

<usage_guidelines>
- This file should be treated as read-only. Any changes should be made to the
  original repository files, not this packed version.
- When processing this file, use the file path to distinguish between different
  files in the repository.
</usage_guidelines>

<notes>
- Files matching patterns in .gitignore are excluded
- Symlinked files and directories are excluded
- Binary files are listed in the directory structure but their contents are not included
- Image files are listed in the directory structure; originals are attached separately
</notes>

</file_summary>
"""

    # 2. Directory structure — build an indented tree.
    dir_tree = _build_dir_tree([rel for rel, _ in all_files])
    dir_section = f"<directory_structure>\n{dir_tree}</directory_structure>\n"

    # 3. File contents
    file_sections = []
    for rel, content in file_contents:
        file_sections.append(f'<file path="{rel}">\n{content}\n</file>\n')
    files_section = "<files>\n" + "\n".join(file_sections) + "</files>\n"

    unified = summary + "\n" + dir_section + "\n" + files_section
    return unified, image_paths


def _build_dir_tree(rel_paths):
    """Build an indented directory tree string from a list of relative paths."""
    tree = {}
    for p in rel_paths:
        parts = Path(p).parts
        node = tree
        for part in parts:
            node = node.setdefault(part, {})

    lines = []
    _render_tree(tree, lines, indent=0)
    return "\n".join(lines) + "\n"


def _render_tree(node, lines, indent):
    for name in sorted(node.keys()):
        lines.append("  " * indent + name)
        if node[name]:
            _render_tree(node[name], lines, indent + 1)


def bundle_files(file_paths, base_dir=None):
    """Bundle a list of files into a unified text file.

    Args:
        file_paths: List of file paths to include
        base_dir: Base directory for relative path calculation

    Returns:
        tuple: (unified_text, list_of_image_paths)
    """
    base = Path(base_dir) if base_dir else None
    sections = []
    image_paths = []

    for fp in sorted(file_paths):
        p = Path(fp).resolve()
        if not p.exists():
            sections.append(f"--- {fp} [NOT FOUND] ---\n")
            continue

        if base:
            try:
                rel = p.relative_to(base)
            except ValueError:
                rel = p.name
        else:
            rel = p.name

        if is_image(p):
            image_paths.append(str(p))
            sections.append(f"--- {rel} [IMAGE - attached separately] ---\n")
            continue

        if is_binary(p):
            sections.append(f"--- {rel} [BINARY - skipped] ---\n")
            continue

        content = read_file_safe(p)
        sections.append(f"--- {rel} ---\n{content}\n")

    unified = "\n".join(sections)
    header = f"# Bundled Files: {len(sections)} files\n\n"
    return header + unified, image_paths


def file_with_txt_extension(file_path):
    """Read a file and return content with .txt appended to the filename.

    If the file already has a ``.txt`` extension it is not double-extended.
    """
    p = Path(file_path)
    content = read_file_safe(p)
    if p.suffix.lower() == ".txt":
        txt_name = p.name
    else:
        txt_name = p.name + ".txt"
    return txt_name, content
