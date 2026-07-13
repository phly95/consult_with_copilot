"""Shared security and file classification policies.

Single source of truth for:
- Image and binary file type classification
- Sensitive file detection (never upload these)
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# File-type classification
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
}

BINARY_EXTENSIONS = IMAGE_EXTENSIONS | {
    ".pdf", ".zip", ".tar", ".gz", ".mp3", ".mp4", ".wav",
    ".woff", ".woff2", ".ttf", ".otf", ".exe", ".dll", ".so",
    ".bin", ".dat",
    ".pyc", ".pyo", ".class", ".o", ".obj",
}


def is_image(path):
    """Check if a file is an image by extension."""
    return Path(path).suffix.lower() in IMAGE_EXTENSIONS


def is_binary(path):
    """Check if a file is binary by extension."""
    return Path(path).suffix.lower() in BINARY_EXTENSIONS


# ---------------------------------------------------------------------------
# Sensitive-file detection
# ---------------------------------------------------------------------------

# Patterns matched against individual path components (basename or dir name).
# Paths containing a sensitive *directory* component are also flagged.
SENSITIVE_PATTERNS = {
    ".env", ".env.local", ".env.production", ".env.development",
    "credentials.json", "service-account.json", "keyfile.json",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks",
    "id_rsa", "id_ed25519", "id_ecdsa",
    ".netrc", ".npmrc", ".pypirc",
    "kubeconfig",
}

# Directory names that make any file inside them sensitive.
SENSITIVE_DIRS = {
    ".kube",
    "browser_profile", "browser_data",
}


def is_sensitive(path):
    """Check whether *path* should be blocked from upload.

    Matches against:
    1. The basename of the file (case-insensitive).
    2. Every directory component in the path (case-insensitive).
    3. Symlink targets — resolved path is also checked.

    Handles patterns like ``.kube/config`` by splitting on ``/`` and
    matching each component independently.
    """
    path = Path(path)

    # Resolve symlinks so a symlink named ``my_link`` pointing to
    # ``~/.ssh`` is correctly flagged.
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path

    # Check every component of both the original and resolved paths.
    parts_lower = [p.lower() for p in path.parts]
    resolved_parts_lower = [p.lower() for p in resolved.parts]
    all_parts = set(parts_lower + resolved_parts_lower)

    # 1. Sensitive directory components — any file inside is sensitive.
    for part in all_parts:
        if part in SENSITIVE_DIRS:
            return True

    # 2. Basename match against patterns.
    basename = path.name.lower()
    if _matches_pattern(basename, SENSITIVE_PATTERNS):
        return True

    # 3. Also check resolved basename (symlink target).
    resolved_basename = resolved.name.lower()
    if resolved_basename != basename:
        if _matches_pattern(resolved_basename, SENSITIVE_PATTERNS):
            return True

    return False


def _matches_pattern(name, patterns):
    """Check if *name* matches any pattern (supports ``*`` prefix globs)."""
    for pattern in patterns:
        if pattern.startswith("*"):
            if name.endswith(pattern[1:]):
                return True
        elif name == pattern.lower():
            return True
    return False
