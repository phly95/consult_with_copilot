"""File processing: repo-to-text conversion, bundling, and image handling."""

import os
import fnmatch
from pathlib import Path

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
BINARY_EXTENSIONS = IMAGE_EXTENSIONS | {
    ".pdf", ".zip", ".tar", ".gz", ".mp3", ".mp4", ".wav",
    ".woff", ".woff2", ".ttf", ".otf", ".exe", ".dll", ".so",
    ".pyc", ".pyo", ".class", ".o", ".obj",
}

# Default patterns to always ignore
DEFAULT_IGNORE = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv",
    ".env", ".DS_Store", "Thumbs.db", "*.pyc", "*.pyo", "*.class",
    "*.o", "*.obj", "*.so", "*.dll", "*.exe", "*.bin",
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.bmp",
    "*.pdf", "*.zip", "*.tar", "*.gz", "*.mp3", "*.mp4",
    "*.woff", "*.woff2", "*.ttf", "*.otf",
}


def load_gitignore(repo_path):
    """Load .gitignore patterns from a repo."""
    patterns = set(DEFAULT_IGNORE)
    gitignore = Path(repo_path) / ".gitignore"
    if gitignore.exists():
        for line in gitignore.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.add(line)
    return patterns


def should_ignore(path, patterns):
    """Check if a path matches any ignore pattern."""
    name = path.name
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
        if fnmatch.fnmatch(str(path), pattern):
            return True
    return False


def is_binary(path):
    """Check if a file is binary based on extension."""
    return Path(path).suffix.lower() in BINARY_EXTENSIONS


def is_image(path):
    """Check if a file is an image."""
    return Path(path).suffix.lower() in IMAGE_EXTENSIONS


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
    """Convert a repository directory into a unified text file.

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

    gitignore_patterns = load_gitignore(repo_path)
    if exclude_patterns:
        gitignore_patterns.update(exclude_patterns)

    sections = []
    image_paths = []

    for root, dirs, files in os.walk(repo_path):
        root_path = Path(root)

        # Filter out ignored directories
        dirs[:] = [
            d for d in dirs
            if not should_ignore(root_path / d, gitignore_patterns)
        ]

        for fname in sorted(files):
            fpath = root_path / fname
            rel = fpath.relative_to(repo_path)

            if should_ignore(fpath, gitignore_patterns):
                continue

            # Apply include patterns if specified
            if include_patterns:
                matched = any(fnmatch.fnmatch(fname, p) for p in include_patterns)
                if not matched:
                    continue

            if is_image(fpath):
                image_paths.append(str(fpath))
                sections.append(f"--- {rel} [IMAGE - attached separately] ---\n")
                continue

            if is_binary(fpath):
                sections.append(f"--- {rel} [BINARY - skipped] ---\n")
                continue

            content = read_file_safe(fpath)
            sections.append(f"--- {rel} ---\n{content}\n")

    unified = "\n".join(sections)
    header = f"# Repository: {repo_path.name}\n# Files: {len(sections)}\n\n"
    return header + unified, image_paths


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
    This lets Copilot understand code files while keeping them as attachments.
    """
    p = Path(file_path)
    content = read_file_safe(p)
    txt_name = p.name + ".txt"
    return txt_name, content
