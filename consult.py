#!/usr/bin/env python3
"""
consult_with_copilot - CLI tool for consulting M365 Copilot from coding agents.

Commands:
    send "message"                     Send a message to Copilot
    repo /path "question"              Convert repo to text and ask
    bundle file1 file2 "question"      Bundle files and ask
    doctor                             Check installation and login status
    login                              Open browser to authenticate
    logout                             Delete browser profile
    session --create --list --delete   Manage conversation sessions
"""

import sys
import os
import json
import time
import shutil
import argparse
import tempfile
import subprocess
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from lib.browser import CopilotSession, PERSISTENT_DIR
from lib.session import SessionManager
from lib.files import repo_to_text, bundle_files, file_with_txt_extension
from lib.security import is_image, is_sensitive

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NOT_LOGGED_IN = 2
EXIT_FILE_NOT_FOUND = 3
EXIT_SENSITIVE_FILE = 4

def eprint(msg):
    """Print to stderr."""
    print(msg, file=sys.stderr)


def _make_json_output(error=None, **overrides):
    """Build a standard JSON response envelope, merging in per-command fields."""
    base = {
        "session_id": None,
        "model": None,
        "response": None,
        "downloaded": [],
        "elapsed_seconds": None,
        "conversation_url": None,
        "error": error,
    }
    base.update(overrides)
    return base


def cmd_doctor(args):
    """Check installation and login status."""
    results = []
    all_ok = True

    def check(name, ok, detail=""):
        status = "✓" if ok else "✗"
        results.append({"name": name, "ok": ok, "detail": detail})
        print(f"  {status} {name}" + (f" — {detail}" if detail else ""))
        if not ok:
            nonlocal all_ok
            all_ok = False

    print("=== consult_with_copilot doctor ===\n")

    # 1. Python version
    v = sys.version_info
    check("Python", v >= (3, 10), f"{v.major}.{v.minor}.{v.micro}")

    # 2. Playwright installed
    try:
        import playwright
        try:
            pw_ver = playwright.__version__
        except AttributeError:
            pw_ver = "installed"
        check("Playwright", True, pw_ver)
    except ImportError:
        check("Playwright", False, "run: pip install playwright")

    # 3. Chromium installed
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
            capture_output=True, text=True, timeout=10
        )
        chromium_path = Path.home() / ".cache" / "ms-playwright"
        has_chromium = any(chromium_path.glob("chromium-*")) if chromium_path.exists() else False
        check("Chromium browser", has_chromium, "installed" if has_chromium else "run: playwright install chromium")
    except Exception:
        chromium_path = Path.home() / ".cache" / "ms-playwright"
        has_chromium = any(chromium_path.glob("chromium-*")) if chromium_path.exists() else False
        check("Chromium browser", has_chromium, "installed" if has_chromium else "run: playwright install chromium")

    # 4. Browser profile exists
    profile_exists = PERSISTENT_DIR.exists()
    check("Browser profile", profile_exists, str(PERSISTENT_DIR))

    # 5. Login state (try to load page)
    if profile_exists:
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(PERSISTENT_DIR),
                headless=True,
                viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://m365.cloud.microsoft/chat", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(5000)
            url = page.url
            logged_in = "login" not in url.lower() and "sign" not in url.lower()
            check("M365 login", logged_in, "logged in" if logged_in else "run: python consult.py login")
            ctx.close()
            pw.stop()
        except Exception as e:
            check("M365 login", False, f"error: {e}")
    else:
        check("M365 login", False, "run: python consult.py login")

    # 6. Downloads directory
    downloads_dir = Path(__file__).parent / "downloads"
    check("Downloads directory", True, str(downloads_dir))

    # 7. Sessions directory
    sessions_dir = Path(__file__).parent / "sessions"
    check("Sessions directory", True, str(sessions_dir))

    print(f"\n{'All checks passed' if all_ok else 'Some checks failed — see above'}")
    return EXIT_OK if all_ok else EXIT_ERROR


def cmd_send(args):
    """Send a message to Copilot."""
    sm = SessionManager()

    # Create or reuse session
    session_id = args.session
    session_data = None
    if session_id:
        session_data = sm.get(session_id)
        if session_data is None:
            eprint(f"Creating new session: {session_id}")
            sm.create(session_id)
    else:
        import uuid
        session_id = str(uuid.uuid4())[:8]
        sm.create(session_id)

    # Collect files to attach
    attach_files = list(args.attach) if args.attach else []

    # Check for sensitive files
    for fp in attach_files:
        p = Path(fp)
        if not p.exists():
            return _exit_with_error(EXIT_FILE_NOT_FOUND, f"file not found: {fp}")
        if is_sensitive(p):
            return _exit_with_error(
                EXIT_SENSITIVE_FILE,
                f"refusing to attach sensitive file: {fp}",
            )

    # Determine download directory
    download_dir = None
    if not args.no_download:
        download_dir = Path(args.download_dir) if args.download_dir else Path(__file__).parent / "downloads"

    # JSON output mode
    json_mode = getattr(args, 'json', False)

    if not json_mode:
        eprint(f"Sending to Copilot...")

    conv_url = session_data.get("conversation_url") if session_data else None
    with CopilotSession(headless=args.headless, conversation_url=conv_url) as cs:
        cs.set_model("GPT 5.6 Think deeper")
        model = cs.verify_model()

        if not json_mode:
            eprint(f"Model: {model}")

        # Prepare temp files with .txt extension for code files
        temp_files = []
        for fp in attach_files:
            p = Path(fp)
            if p.exists() and not is_image(fp):
                txt_name, content = file_with_txt_extension(fp)
                tmp = Path(tempfile.gettempdir()) / txt_name
                tmp.write_text(content)
                temp_files.append(str(tmp))
            elif p.exists():
                temp_files.append(str(p.resolve()))

        t_start = time.time()
        response, downloaded = cs.send_message(args.message, temp_files or None, download_dir=download_dir)
        elapsed = time.time() - t_start

        # Clean up temp files
        for tf in temp_files:
            Path(tf).unlink(missing_ok=True)

        if json_mode:
            output = _make_json_output(
                session_id=session_id,
                model=model,
                response=response,
                downloaded=downloaded,
                elapsed_seconds=round(elapsed, 1),
                conversation_url=cs.page.url,
            )
            print(json.dumps(output, indent=2))
        else:
            if response:
                print(f"\n{response}")
                if downloaded:
                    eprint(f"\nDownloaded {len(downloaded)} file(s):")
                    for f in downloaded:
                        eprint(f"  {f}")
            else:
                eprint("No response received")

        sm.add_message(session_id, "user", args.message)
        if response:
            sm.add_message(session_id, "assistant", response)
        sm.update(session_id, conversation_url=cs.page.url)

    if not json_mode:
        eprint(f"\nSession: {session_id}")

    return EXIT_OK


def cmd_repo(args):
    """Convert a repo to text and send to Copilot as a file attachment."""
    repo_path = Path(args.repo_path)
    if not repo_path.is_dir():
        return _exit_with_error(EXIT_FILE_NOT_FOUND, f"not a directory: {args.repo_path}")

    # When --tracked-only is set, get the list of git-tracked files
    tracked_files = None
    if getattr(args, 'tracked_only', False):
        try:
            result = subprocess.run(
                ["git", "ls-files"],
                cwd=str(repo_path),
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                tracked_files = set(result.stdout.strip().splitlines())
            else:
                eprint("Warning: --tracked-only requires git; falling back to all files")
        except Exception:
            eprint("Warning: --tracked-only requires git; falling back to all files")

    unified_text, image_paths = repo_to_text(
        args.repo_path,
        include_patterns=args.include,
        exclude_patterns=args.exclude,
        tracked_files=tracked_files,
    )

    # Dry run mode
    if getattr(args, 'dry_run', False):
        print(f"Repository: {repo_path.name}")
        print(f"Unified text: {len(unified_text)} chars")
        print(f"Images: {len(image_paths)}")
        # Show directory structure (extracted between tags)
        ds_start = unified_text.find("<directory_structure>")
        ds_end = unified_text.find("</directory_structure>")
        if ds_start != -1 and ds_end != -1:
            print(f"\nDirectory structure:")
            print(unified_text[ds_start:ds_end + len("</directory_structure>")])
        # Show first file content
        fs_start = unified_text.find("<file ")
        if fs_start != -1:
            snippet_end = unified_text.find("</file>", fs_start)
            if snippet_end != -1:
                snippet_end += len("</file>")
                # Cap at 500 chars
                if snippet_end - fs_start > 500:
                    snippet_end = fs_start + 500
            else:
                snippet_end = fs_start + 500
            print(f"\nFirst file snippet:")
            print(unified_text[fs_start:snippet_end])
        return EXIT_OK

    # Save as .txt file for attachment
    repo_name = repo_path.name
    txt_file = Path(tempfile.gettempdir()) / f"{repo_name}.txt"
    txt_file.write_text(unified_text)

    question = args.context or "Analyze this repository. Explain the architecture, identify key components, and suggest improvements."

    sm = SessionManager()
    import uuid
    session_id = args.session or str(uuid.uuid4())[:8]
    sm.create(session_id, model="GPT 5.6 Think deeper")

    if not getattr(args, 'json', False):
        eprint(f"Sending to Copilot (repo: {repo_path.name}, {len(unified_text)} chars)...")

    t_start = time.time()
    with CopilotSession(headless=args.headless) as cs:
        cs.set_model("GPT 5.6 Think deeper")
        model = cs.verify_model()
        if not getattr(args, 'json', False):
            eprint(f"Model: {model}")

        attach = [str(txt_file)] + (image_paths if image_paths else [])
        response, downloaded = cs.send_message(question, attach)
        elapsed = time.time() - t_start

        txt_file.unlink(missing_ok=True)

        json_mode = getattr(args, 'json', False)
        if json_mode:
            output = _make_json_output(
                session_id=session_id,
                model=model,
                response=response,
                downloaded=downloaded,
                elapsed_seconds=round(elapsed, 1),
                conversation_url=cs.page.url,
            )
            # Extra repo-specific fields
            output["repo"] = repo_path.name
            output["chars"] = len(unified_text)
            print(json.dumps(output, indent=2))
        else:
            if response:
                print(f"\n{response}")
            else:
                eprint("No response received")

        sm.add_message(session_id, "user", question)
        if response:
            sm.add_message(session_id, "assistant", response)
        sm.update(session_id, conversation_url=cs.page.url)

    if not getattr(args, 'json', False):
        eprint(f"\nSession: {session_id}")
    return EXIT_OK


def cmd_bundle(args):
    """Bundle specific files and send to Copilot as a file attachment."""
    # Check files exist and aren't sensitive
    for fp in args.files:
        if not Path(fp).exists():
            return _exit_with_error(EXIT_FILE_NOT_FOUND, f"file not found: {fp}")
        if is_sensitive(Path(fp)):
            return _exit_with_error(EXIT_SENSITIVE_FILE, f"refusing to include sensitive file: {fp}")

    unified_text, image_paths = bundle_files(args.files)

    question = args.context or "Review these files. Identify issues, suggest improvements, and explain how they work together."

    sm = SessionManager()
    import uuid
    session_id = args.session or str(uuid.uuid4())[:8]
    sm.create(session_id, model="GPT 5.6 Think deeper")

    # Save as .txt file for attachment
    txt_file = Path(tempfile.gettempdir()) / "bundled_files.txt"
    txt_file.write_text(unified_text)

    if not getattr(args, 'json', False):
        eprint(f"Sending {len(args.files)} files to Copilot ({len(unified_text)} chars)...")

    t_start = time.time()
    with CopilotSession(headless=args.headless) as cs:
        cs.set_model("GPT 5.6 Think deeper")
        model = cs.verify_model()
        if not getattr(args, 'json', False):
            eprint(f"Model: {model}")

        attach = [str(txt_file)] + (image_paths if image_paths else [])
        response, downloaded = cs.send_message(question, attach)
        elapsed = time.time() - t_start

        txt_file.unlink(missing_ok=True)

        json_mode = getattr(args, 'json', False)
        if json_mode:
            output = _make_json_output(
                session_id=session_id,
                model=model,
                response=response,
                downloaded=downloaded,
                elapsed_seconds=round(elapsed, 1),
                conversation_url=cs.page.url,
            )
            output["files"] = args.files
            print(json.dumps(output, indent=2))
        else:
            if response:
                print(f"\n{response}")
            else:
                eprint("No response received")

        sm.add_message(session_id, "user", question)
        if response:
            sm.add_message(session_id, "assistant", response)
        sm.update(session_id, conversation_url=cs.page.url)

    if not getattr(args, 'json', False):
        eprint(f"\nSession: {session_id}")
    return EXIT_OK


def cmd_session(args):
    """Manage sessions."""
    sm = SessionManager()

    if args.create:
        sid = args.id or None
        if not sid:
            import uuid
            sid = str(uuid.uuid4())[:8]
        sm.create(sid)
        print(f"Created session: {sid}")

    elif args.list_sessions:
        sessions = sm.list_sessions()
        if not sessions:
            print("No sessions found")
        else:
            for s in sessions:
                print(f"  {s['id']}  model={s.get('model', '?')}  messages={s['messages']}")

    elif args.delete_session:
        sm.delete(args.delete_session)
        print(f"Deleted session: {args.delete_session}")

    return EXIT_OK


def cmd_login(args):
    """Open visible browser for authentication."""
    eprint("Opening browser for M365 login...")
    eprint("Log in, then close the browser window.")
    try:
        with CopilotSession(headless=False, skip_login_check=True) as cs:
            eprint("Browser open — log in and close when done.")
            try:
                cs.page.wait_for_event("close", timeout=0)
            except Exception:
                pass
            # Verify the session landed on a non-login page
            url = cs.page.url.lower()
            if "login" in url or "sign" in url:
                eprint("Warning: browser was closed on a login page — authentication may not have completed")
                return EXIT_NOT_LOGGED_IN, "authentication may not have completed"
        eprint("Login complete. Session saved.")
        return EXIT_OK, None
    except Exception as e:
        eprint(f"Login failed: {e}")
        return EXIT_ERROR, str(e)


def cmd_logout(args):
    """Delete browser profile. With --all, also clear sessions and downloads."""
    profile = PERSISTENT_DIR
    sessions_dir = Path(__file__).parent / "sessions"
    downloads_dir = Path(__file__).parent / "downloads"

    if profile.exists():
        shutil.rmtree(profile)
        eprint(f"Deleted browser profile: {profile}")

    if getattr(args, 'all', False):
        if sessions_dir.exists():
            for f in sessions_dir.glob("*.json"):
                f.unlink()
            eprint(f"Cleared sessions: {sessions_dir}")

        if downloads_dir.exists():
            shutil.rmtree(downloads_dir)
            eprint(f"Deleted downloads: {downloads_dir}")

        eprint("All local data cleared. Run 'login' to re-authenticate.")
    else:
        eprint("Browser profile cleared. Run 'login' to re-authenticate.")
        eprint("Use --all to also delete sessions and downloads.")

    return EXIT_OK


def _exit_with_error(code, message):
    """Print error to stderr and return (exit_code, error_message) tuple."""
    eprint(f"Error: {message}")
    return code, message


def main():
    parser = argparse.ArgumentParser(
        prog="consult",
        description="Consult M365 Copilot from coding agents",
    )
    parser.add_argument("--headless", action="store_true", default=True,
                        help="Run browser headless (default)")
    parser.add_argument("--no-headless", dest="headless", action="store_false",
                        help="Show browser window")
    parser.add_argument("--json", action="store_true",
                        help="Output response as JSON")

    sub = parser.add_subparsers(dest="command")

    # doctor
    sub.add_parser("doctor", help="Check installation and login status")

    # send
    p_send = sub.add_parser("send", help="Send a message to Copilot")
    p_send.add_argument("message", help="Message to send")
    p_send.add_argument("--attach", nargs="*", metavar="FILE", help="Files to attach")
    p_send.add_argument("--session", "-s", help="Session ID for follow-up")
    p_send.add_argument("--download-dir", help="Directory for downloaded files")
    p_send.add_argument("--no-download", action="store_true", help="Disable file downloads")

    # repo
    p_repo = sub.add_parser("repo", help="Send a repo as unified text file")
    p_repo.add_argument("repo_path", help="Path to repository")
    p_repo.add_argument("context", nargs="?", help="Question about the repo")
    p_repo.add_argument("--include", nargs="*", metavar="PATTERN", help="Glob patterns to include")
    p_repo.add_argument("--exclude", nargs="*", metavar="PATTERN", help="Glob patterns to exclude")
    p_repo.add_argument("--session", "-s", help="Session ID")
    p_repo.add_argument("--dry-run", action="store_true", help="Show what would be sent without sending")
    p_repo.add_argument("--tracked-only", action="store_true",
                        help="Only include git-tracked files (requires git)")

    # bundle
    p_bundle = sub.add_parser("bundle", help="Bundle files and send")
    p_bundle.add_argument("files", nargs="+", metavar="FILE", help="Files to bundle")
    p_bundle.add_argument("context", nargs="?", help="Question about the files")
    p_bundle.add_argument("--session", "-s", help="Session ID")

    # session
    p_session = sub.add_parser("session", help="Manage conversation sessions")
    p_session.add_argument("--create", action="store_true", help="Create a session")
    p_session.add_argument("--id", help="Session ID")
    p_session.add_argument("--list", dest="list_sessions", action="store_true", help="List sessions")
    p_session.add_argument("--delete", dest="delete_session", help="Delete a session")

    # login
    sub.add_parser("login", help="Open browser to authenticate with M365")

    # logout
    p_logout = sub.add_parser("logout", help="Delete browser profile (use --all for everything)")
    p_logout.add_argument("--all", action="store_true",
                          help="Also delete sessions and downloads")

    args = parser.parse_args()

    handlers = {
        "doctor": cmd_doctor,
        "send": cmd_send,
        "repo": cmd_repo,
        "bundle": cmd_bundle,
        "session": cmd_session,
        "login": cmd_login,
        "logout": cmd_logout,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(EXIT_OK)

    result = handler(args)
    # Handlers return either an int (exit code) or a (code, error) tuple.
    if isinstance(result, tuple):
        code, error = result
    else:
        code, error = result, None

    json_mode = getattr(args, 'json', False)
    if json_mode and error:
        print(json.dumps(_make_json_output(error=error), indent=2))

    sys.exit(code)


if __name__ == "__main__":
    main()
