#!/usr/bin/env python3
"""Tests for consult_with_copilot file handling, sessions, and CLI."""

import sys
import json
import tempfile
import shutil
import subprocess
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.files import repo_to_text, bundle_files, should_ignore, is_binary, is_image, file_with_txt_extension
from lib.session import SessionManager


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

        assert "main.py" in text
        assert "utils.js" in text
        assert "README.md" in text
        assert "print('hello')" in text
        assert "node_modules" not in text  # skipped by default
        assert len(images) == 0
        print("  ✓ repo_to_text")


def test_repo_to_text_include():
    """Test include patterns."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "main.py").write_text("print('hello')")
        (Path(tmpdir) / "utils.js").write_text("console.log('hi')")
        (Path(tmpdir) / "README.md").write_text("# Test")

        text, _ = repo_to_text(tmpdir, include_patterns=["*.py"])
        assert "main.py" in text
        assert "utils.js" not in text
        assert "README.md" not in text
        print("  ✓ repo_to_text include patterns")


def test_repo_to_text_exclude():
    """Test exclude patterns."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "main.py").write_text("code")
        (Path(tmpdir) / "test_main.py").write_text("test code")

        text, _ = repo_to_text(tmpdir, exclude_patterns=["test_*"])
        assert "main.py" in text
        assert "test_main.py" not in text
        print("  ✓ repo_to_text exclude patterns")


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


def test_should_ignore():
    """Test ignore patterns."""
    # *.pyc matches any .pyc file
    assert should_ignore(Path("file.pyc"), {"*.pyc"})
    # vendor/* matches files inside vendor directory
    assert should_ignore(Path("vendor/lib.py"), {"vendor/*"})
    # .env matches .env files
    assert should_ignore(Path(".env"), {".env"})
    # node_modules as filename matches node_modules file
    assert should_ignore(Path("node_modules"), {"node_modules"})
    # But node_modules/dep.js doesn't match "node_modules" pattern
    assert not should_ignore(Path("node_modules/dep.js"), {"node_modules"})
    print("  ✓ should_ignore")


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


def test_file_with_txt_extension():
    """Test .txt extension wrapping."""
    # Just test the name generation (file doesn't need to exist for the name part)
    # The function reads the file, so we create a temp file
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


def test_sensitive_file_detection():
    """Test that sensitive files are identified."""
    sensitive = [".env", ".env.local", "credentials.json", "id_rsa", "key.pem"]
    safe = ["main.py", "README.md", "package.json"]

    sensitive_patterns = {".env", ".env.local", "credentials.json", "*.pem", "*.key", "id_rsa"}

    for name in sensitive:
        p = Path(name)
        matched = False
        for pattern in sensitive_patterns:
            if pattern.startswith("*"):
                if p.name.endswith(pattern[1:]):
                    matched = True
            elif p.name == pattern:
                matched = True
        assert matched, f"Should be sensitive: {name}"

    for name in safe:
        p = Path(name)
        matched = False
        for pattern in sensitive_patterns:
            if pattern.startswith("*"):
                if p.name.endswith(pattern[1:]):
                    matched = True
            elif p.name == pattern:
                matched = True
        assert not matched, f"Should NOT be sensitive: {name}"

    print("  ✓ sensitive_file_detection")


def test_cli_help():
    """Test that CLI help works."""
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent.parent / "consult.py"), "--help"],
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
        [sys.executable, str(Path(__file__).parent.parent / "consult.py"), "send", "--help"],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0
    assert "--attach" in result.stdout
    assert "--session" in result.stdout
    print("  ✓ cli_send_help")


def test_repo_dry_run():
    """Test repo dry-run doesn't send anything."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "test.py").write_text("print('hello')")
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent.parent / "consult.py"),
             "repo", tmpdir, "--dry-run"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0
        assert "test.py" in result.stdout
        print("  ✓ repo_dry_run")


def test_exit_codes():
    """Test that exit codes are correct."""
    # File not found
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent.parent / "consult.py"),
         "send", "test", "--attach", "/nonexistent/file.py"],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 3, f"Expected exit code 3, got {result.returncode}"
    print("  ✓ exit_codes")


if __name__ == "__main__":
    print("=== Running tests ===\n")

    tests = [
        test_repo_to_text,
        test_repo_to_text_include,
        test_repo_to_text_exclude,
        test_bundle_files,
        test_should_ignore,
        test_is_binary,
        test_is_image,
        test_file_with_txt_extension,
        test_session_manager,
        test_session_nonexistent,
        test_sensitive_file_detection,
        test_cli_help,
        test_cli_send_help,
        test_repo_dry_run,
        test_exit_codes,
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
