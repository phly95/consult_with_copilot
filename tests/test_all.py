#!/usr/bin/env python3
"""Tests for consult_with_copilot file handling, sessions, security, and CLI."""

import sys
import json
import tempfile
import shutil
import subprocess
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.files import (
    repo_to_text, bundle_files, should_ignore, read_file_safe,
    file_with_txt_extension, load_gitignore,
)
from lib.session import SessionManager
from lib.security import is_binary, is_image, is_sensitive, SENSITIVE_DIRS

CONSULT_PY = str(Path(__file__).parent.parent / "consult.py")


# ---------------------------------------------------------------------------
# repo_to_text
# ---------------------------------------------------------------------------

def test_repo_to_text():
    """Test repo-to-text conversion."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "main.py").write_text("print('hello')")
        (Path(tmpdir) / "utils.js").write_text("function add(a, b) { return a + b; }")
        (Path(tmpdir) / "README.md").write_text("# Test")
        (Path(tmpdir) / "binary.exe").write_bytes(b"\x00\x01\x02\x03")
        (Path(tmpdir) / "node_modules").mkdir()
        (Path(tmpdir) / "node_modules" / "dep.js").write_text("module.exports = {};")

        text, images = repo_to_text(tmpdir)

        # New format uses <file path="..."> tags
        assert '<file path="main.py">' in text
        assert '<file path="utils.js">' in text
        assert '<file path="README.md">' in text
        assert "print('hello')" in text
        # node_modules should be excluded
        assert "dep.js" not in text
        # Directory structure should be present
        assert "<directory_structure>" in text
        assert "</directory_structure>" in text
        # Summary should be present
        assert "<file_summary>" in text
        assert "</file_summary>" in text
        assert len(images) == 0
        print("  ✓ repo_to_text")


def test_repo_to_text_include():
    """Test include patterns."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "main.py").write_text("print('hello')")
        (Path(tmpdir) / "utils.js").write_text("console.log('hi')")
        (Path(tmpdir) / "README.md").write_text("# Test")

        text, _ = repo_to_text(tmpdir, include_patterns=["*.py"])
        assert '<file path="main.py">' in text
        assert "utils.js" not in text
        assert "README.md" not in text
        print("  ✓ repo_to_text include patterns")


def test_repo_to_text_exclude():
    """Test exclude patterns."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "main.py").write_text("code")
        (Path(tmpdir) / "test_main.py").write_text("test code")

        text, _ = repo_to_text(tmpdir, exclude_patterns=["test_*"])
        assert '<file path="main.py">' in text
        assert "test_main.py" not in text
        print("  ✓ repo_to_text exclude patterns")


def test_repo_to_text_skips_symlinks():
    """Test that symlinks are skipped during traversal."""
    with tempfile.TemporaryDirectory() as tmpdir:
        real = Path(tmpdir) / "real.py"
        real.write_text("print('real')")
        link = Path(tmpdir) / "link.py"
        link.symlink_to(real)

        text, _ = repo_to_text(tmpdir)
        assert '<file path="real.py">' in text
        assert "link.py" not in text
        print("  ✓ repo_to_text skips symlinks")


def test_repo_to_text_skips_symlink_dirs():
    """Test that symlinked directories are skipped."""
    with tempfile.TemporaryDirectory() as tmpdir:
        real_dir = Path(tmpdir) / "real_dir"
        real_dir.mkdir()
        (real_dir / "code.py").write_text("print('inside')")
        link_dir = Path(tmpdir) / "link_dir"
        link_dir.symlink_to(real_dir)

        text, _ = repo_to_text(tmpdir)
        assert '<file path="real_dir/code.py">' in text  # from real_dir
        assert "link_dir" not in text
        print("  ✓ repo_to_text skips symlinked directories")


# ---------------------------------------------------------------------------
# bundle_files
# ---------------------------------------------------------------------------

def test_bundle_files():
    """Test file bundling."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f1 = Path(tmpdir) / "a.py"
        f2 = Path(tmpdir) / "b.py"
        f1.write_text("def a(): pass")
        f2.write_text("def b(): pass")

        text, images = bundle_files([str(f1), str(f2)])
        assert "a.py" in text
        assert "b.py" in text
        assert "def a()" in text
        assert "def b()" in text
        print("  ✓ bundle_files")


# ---------------------------------------------------------------------------
# should_ignore
# ---------------------------------------------------------------------------

def test_should_ignore():
    """Test ignore patterns with the updated API."""
    default, gitignore = load_gitignore("/nonexistent")

    # *.pyc matches any .pyc file
    assert should_ignore(Path("file.pyc"), default)
    # .env matches .env files
    assert should_ignore(Path(".env"), default)
    # node_modules as filename matches node_modules file
    assert should_ignore(Path("node_modules"), default)
    # node_modules/dep.js — basename is dep.js, which doesn't match any default
    assert not should_ignore(Path("node_modules/dep.js"), default)
    # node_modules IS in DEFAULT_IGNORE as a bare name, so it's skipped at dir level
    print("  ✓ should_ignore")


def test_gitignore_negation():
    """Test that gitignore negation (!) un-ignores files."""
    default = set()
    gitignore = ["*.log", "!important.log"]

    # *.log is ignored
    assert should_ignore(Path("debug.log"), default, gitignore)
    # important.log is un-ignored by the negation
    assert not should_ignore(Path("important.log"), default, gitignore)
    print("  ✓ gitignore negation")


def test_gitignore_anchored_pattern():
    """Test that /build anchors to repo root only."""
    default = set()
    # /build should match a file named "build" at repo root but not "vendor/build"
    gitignore = ["/build"]
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        build_file = root / "build"
        build_file.write_text("data")
        vendor_build = root / "vendor" / "build"
        vendor_build.parent.mkdir()
        vendor_build.write_text("data")
        assert should_ignore(build_file, default, gitignore, repo_root=root)
        assert not should_ignore(vendor_build, default, gitignore, repo_root=root)
    print("  ✓ gitignore anchored pattern")


# ---------------------------------------------------------------------------
# is_binary / is_image
# ---------------------------------------------------------------------------

def test_is_binary():
    """Test binary detection."""
    assert is_binary(Path("image.png"))
    assert is_binary(Path("archive.zip"))
    assert is_binary(Path("script.py")) is False
    assert is_binary(Path("readme.md")) is False
    print("  ✓ is_binary")


def test_is_image():
    """Test image detection."""
    assert is_image(Path("photo.jpg"))
    assert is_image(Path("icon.png"))
    assert is_image(Path("script.py")) is False
    print("  ✓ is_image")


# ---------------------------------------------------------------------------
# file_with_txt_extension
# ---------------------------------------------------------------------------

def test_file_with_txt_extension():
    """Test .txt extension wrapping."""
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
        f.write("print('test')")
        f.flush()
        try:
            name, content = file_with_txt_extension(Path(f.name))
            assert name.endswith(".py.txt")
            assert "print" in content
        finally:
            Path(f.name).unlink()
    print("  ✓ file_with_txt_extension")


def test_file_with_txt_extension_already_txt():
    """Test that .txt files are not double-extended."""
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
        f.write("hello world")
        f.flush()
        try:
            name, content = file_with_txt_extension(Path(f.name))
            assert name.endswith(".txt")
            assert not name.endswith(".txt.txt")
            assert "hello world" in content
        finally:
            Path(f.name).unlink()
    print("  ✓ file_with_txt_extension already .txt")


# ---------------------------------------------------------------------------
# is_sensitive
# ---------------------------------------------------------------------------

def test_is_sensitive_basename():
    """Test sensitive file detection by basename."""
    assert is_sensitive(Path(".env"))
    assert is_sensitive(Path(".env.local"))
    assert is_sensitive(Path(".env.production"))
    assert is_sensitive(Path(".env.staging"))
    assert is_sensitive(Path(".env.test"))
    assert is_sensitive(Path("credentials.json"))
    assert is_sensitive(Path("id_rsa"))
    assert is_sensitive(Path("key.pem"))
    assert not is_sensitive(Path("main.py"))
    assert not is_sensitive(Path("README.md"))
    print("  ✓ is_sensitive basename")


def test_is_sensitive_kube_config():
    """Test that .kube/config is correctly detected via directory component."""
    assert is_sensitive(Path("/home/user/.kube/config"))
    assert is_sensitive(Path("/some/project/.kube/config"))
    # Just "config" alone should NOT be sensitive
    assert not is_sensitive(Path("config"))
    print("  ✓ is_sensitive .kube/config")


def test_is_sensitive_directory_component():
    """Test that files inside sensitive directories are flagged."""
    for dirname in SENSITIVE_DIRS:
        p = Path(f"/project/{dirname}/any_file.txt")
        assert is_sensitive(p), f"Expected sensitive: {dirname}/any_file.txt"
    print("  ✓ is_sensitive directory components")


def test_is_sensitive_symlink():
    """Test that symlinks pointing to sensitive targets are flagged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        secret = Path(tmpdir) / "secret.pem"
        secret.write_text("key")
        link = Path(tmpdir) / "innocent_link"
        link.symlink_to(secret)
        assert is_sensitive(link)
        print("  ✓ is_sensitive symlink target")


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------

def test_session_manager():
    """Test session CRUD operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = SessionManager(tmpdir)

        # Create
        data = sm.create("test-123", model="GPT 5.6 Think deeper")
        assert data["id"] == "test-123"

        # Read
        loaded = sm.get("test-123")
        assert loaded is not None
        assert loaded["id"] == "test-123"

        # Add message
        sm.add_message("test-123", "user", "hello")
        sm.add_message("test-123", "assistant", "hi there")
        updated = sm.get("test-123")
        assert len(updated["messages"]) == 2
        assert updated["messages"][0]["text"] == "hello"

        # List
        sessions = sm.list_sessions()
        assert len(sessions) == 1

        # Delete
        sm.delete("test-123")
        assert sm.get("test-123") is None
        print("  ✓ session_manager")


def test_session_nonexistent():
    """Test accessing nonexistent session."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = SessionManager(tmpdir)
        assert sm.get("nonexistent") is None
        try:
            sm.add_message("nonexistent", "user", "test")
            assert False, "Should have raised"
        except FileNotFoundError:
            pass
        print("  ✓ session_nonexistent")


def test_session_id_validation():
    """Test that path-traversal session IDs are rejected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = SessionManager(tmpdir)
        for bad_id in ["../etc/passwd", "foo/../../bar", "a\\b", ""]:
            try:
                sm.create(bad_id)
                assert False, f"Should have rejected: {bad_id!r}"
            except ValueError:
                pass
        print("  ✓ session_id_validation")


def test_session_atomic_write():
    """Test that session writes are atomic (file exists after write)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = SessionManager(tmpdir)
        sm.create("atomic-test")
        path = Path(tmpdir) / "atomic-test.json"
        assert path.exists()
        # Verify it's valid JSON (not a half-written file)
        data = json.loads(path.read_text())
        assert data["id"] == "atomic-test"
        # Check no temp files are left behind
        tmp_files = list(Path(tmpdir).glob("*.tmp"))
        assert len(tmp_files) == 0, "Temp files should be cleaned up"
        print("  ✓ session_atomic_write")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_help():
    """Test that CLI help works."""
    result = subprocess.run(
        [sys.executable, CONSULT_PY, "--help"],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0
    assert "send" in result.stdout
    assert "repo" in result.stdout
    assert "doctor" in result.stdout
    assert "login" in result.stdout
    assert "logout" in result.stdout
    print("  ✓ cli_help")


def test_cli_send_help():
    """Test send command help."""
    result = subprocess.run(
        [sys.executable, CONSULT_PY, "send", "--help"],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0
    assert "--attach" in result.stdout
    assert "--session" in result.stdout
    print("  ✓ cli_send_help")


def test_cli_repo_help():
    """Test repo command help shows --tracked-only."""
    result = subprocess.run(
        [sys.executable, CONSULT_PY, "repo", "--help"],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0
    assert "--tracked-only" in result.stdout
    assert "--dry-run" in result.stdout
    print("  ✓ cli_repo_help")


def test_cli_logout_help():
    """Test logout command help shows --all flag."""
    result = subprocess.run(
        [sys.executable, CONSULT_PY, "logout", "--help"],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0
    assert "--all" in result.stdout
    print("  ✓ cli_logout_help")


def test_repo_dry_run():
    """Test repo dry-run doesn't send anything."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "test.py").write_text("print('hello')")
        result = subprocess.run(
            [sys.executable, CONSULT_PY, "repo", tmpdir, "--dry-run"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0
        assert "<directory_structure>" in result.stdout
        assert "test.py" in result.stdout
        assert "<file " in result.stdout
        print("  ✓ repo_dry_run")


def test_exit_codes():
    """Test that exit codes are correct (no more sys.exit in handlers)."""
    # File not found
    result = subprocess.run(
        [sys.executable, CONSULT_PY, "send", "test", "--attach", "/nonexistent/file.py"],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 3, f"Expected exit code 3, got {result.returncode}"
    assert "file not found" in result.stderr.lower()
    print("  ✓ exit_codes")


def test_exit_codes_sensitive_file():
    """Test exit code for sensitive file rejection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sensitive = Path(tmpdir) / ".env"
        sensitive.write_text("SECRET=123")
        result = subprocess.run(
            [sys.executable, CONSULT_PY, "send", "test", "--attach", str(sensitive)],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 4, f"Expected exit code 4, got {result.returncode}"
        assert "sensitive" in result.stderr.lower()
        print("  ✓ exit_codes_sensitive_file")


def test_bundle_sensitive_file():
    """Test that bundle rejects sensitive files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        safe = Path(tmpdir) / "main.py"
        safe.write_text("print('hi')")
        sensitive = Path(tmpdir) / "id_rsa"
        sensitive.write_text("private key")

        result = subprocess.run(
            [sys.executable, CONSULT_PY, "bundle", str(safe), str(sensitive), "review"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 4
        print("  ✓ bundle_sensitive_file")


def test_exit_code_constants():
    """Test that all documented exit codes are defined."""
    source = Path(CONSULT_PY).read_text()
    assert "EXIT_OK = 0" in source
    assert "EXIT_ERROR = 1" in source
    assert "EXIT_NOT_LOGGED_IN = 2" in source
    assert "EXIT_FILE_NOT_FOUND = 3" in source
    assert "EXIT_SENSITIVE_FILE = 4" in source
    print("  ✓ exit_code_constants")


if __name__ == "__main__":
    print("=== Running tests ===\n")

    tests = [
        test_repo_to_text,
        test_repo_to_text_include,
        test_repo_to_text_exclude,
        test_repo_to_text_skips_symlinks,
        test_repo_to_text_skips_symlink_dirs,
        test_bundle_files,
        test_should_ignore,
        test_gitignore_negation,
        test_gitignore_anchored_pattern,
        test_is_binary,
        test_is_image,
        test_file_with_txt_extension,
        test_file_with_txt_extension_already_txt,
        test_is_sensitive_basename,
        test_is_sensitive_kube_config,
        test_is_sensitive_directory_component,
        test_is_sensitive_symlink,
        test_session_manager,
        test_session_nonexistent,
        test_session_id_validation,
        test_session_atomic_write,
        test_cli_help,
        test_cli_send_help,
        test_cli_repo_help,
        test_cli_logout_help,
        test_repo_dry_run,
        test_exit_codes,
        test_exit_codes_sensitive_file,
        test_bundle_sensitive_file,
        test_exit_code_constants,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  ✗ {test.__name__}: {e}")
            failed += 1

    print(f"\n=== Results: {passed} passed, {failed} failed ===")
    sys.exit(0 if failed == 0 else 1)
