#!/usr/bin/env python3
"""
consult_with_copilot - CLI tool for consulting M365 Copilot from coding agents.

Commands:
    send "message"                     Send a message to Copilot
    repo /path "question"              Convert repo to text and ask
    bundle file1 file2 "question"      Bundle files and ask
    doctor                             Check installation and login status
    login                              Open browser to authenticate
    logout                             Delete browser profile and sessions
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
from lib.files import repo_to_text, bundle_files, file_with_txt_extension, is_image

# Sensitive file patterns that should never be uploaded
SENSITIVE_PATTERNS = {
    ".env", ".env.local", ".env.production", ".env.development",
    "credentials.json", "service-account.json", "keyfile.json",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks",
    "id_rsa", "id_ed25519", "id_ecdsa",
    ".netrc", ".npmrc", ".pypirc",
    "kubeconfig", ".kube/config",
    "browser_profile", "browser_data",
}

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NOT_LOGGED_IN = 2
EXIT_FILE_NOT_FOUND = 3
EXIT_SENSITIVE_FILE = 4


def eprint(msg):
    """Print to stderr."""
    print(msg, file=sys.stderr)


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
        # dry-run may not exist, try direct check
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
            eprint(f"Error: file not found: {fp}")
            sys.exit(EXIT_FILE_NOT_FOUND)
        if _is_sensitive(p):
            eprint(f"Error: refusing to attach sensitive file: {fp}")
            eprint("Use --force-attach to override (not recommended)")
            sys.exit(EXIT_SENSITIVE_FILE)

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
            output = {
                "session_id": session_id,
                "model": model,
                "response": response,
                "downloaded": downloaded,
                "elapsed_seconds": round(elapsed, 1),
                "conversation_url": cs.page.url,
            }
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
        eprint(f"Error: not a directory: {args.repo_path}")
        sys.exit(EXIT_FILE_NOT_FOUND)

    unified_text, image_paths = repo_to_text(
        args.repo_path,
        include_patterns=args.include,
        exclude_patterns=args.exclude,
    )

    # Dry run mode
    if getattr(args, 'dry_run', False):
        print(f"Repository: {repo_path.name}")
        print(f"Unified text: {len(unified_text)} chars")
        print(f"Images: {len(image_paths)}")
        print(f"\nFirst 500 chars of unified text:")
        print(unified_text[:500])
        if image_paths:
            print(f"\nImage files:")
            for ip in image_paths:
                print(f"  {ip}")
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

    eprint(f"Sending to Copilot (repo: {repo_path.name}, {len(unified_text)} chars)...")

    with CopilotSession(headless=args.headless) as cs:
        cs.set_model("GPT 5.6 Think deeper")
        model = cs.verify_model()
        eprint(f"Model: {model}")

        attach = [str(txt_file)] + (image_paths if image_paths else [])
        response, downloaded = cs.send_message(question, attach)

        txt_file.unlink(missing_ok=True)

        json_mode = getattr(args, 'json', False)
        if json_mode:
            output = {
                "session_id": session_id,
                "model": model,
                "repo": repo_path.name,
                "chars": len(unified_text),
                "response": response,
                "downloaded": downloaded,
            }
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

    eprint(f"\nSession: {session_id}")
    return EXIT_OK


def cmd_bundle(args):
    """Bundle specific files and send to Copilot as a file attachment."""
    # Check files exist and aren't sensitive
    for fp in args.files:
        if not Path(fp).exists():
            eprint(f"Error: file not found: {fp}")
            sys.exit(EXIT_FILE_NOT_FOUND)
        if _is_sensitive(Path(fp)):
            eprint(f"Error: refusing to include sensitive file: {fp}")
            sys.exit(EXIT_SENSITIVE_FILE)

    unified_text, image_paths = bundle_files(args.files)

    question = args.context or "Review these files. Identify issues, suggest improvements, and explain how they work together."

    sm = SessionManager()
    import uuid
    session_id = args.session or str(uuid.uuid4())[:8]
    sm.create(session_id, model="GPT 5.6 Think deeper")

    # Save as .txt file for attachment
    txt_file = Path(tempfile.gettempdir()) / "bundled_files.txt"
    txt_file.write_text(unified_text)

    eprint(f"Sending {len(args.files)} files to Copilot ({len(unified_text)} chars)...")

    with CopilotSession(headless=args.headless) as cs:
        cs.set_model("GPT 5.6 Think deeper")
        model = cs.verify_model()
        eprint(f"Model: {model}")

        attach = [str(txt_file)] + (image_paths if image_paths else [])
        response, downloaded = cs.send_message(question, attach)

        txt_file.unlink(missing_ok=True)

        json_mode = getattr(args, 'json', False)
        if json_mode:
            output = {
                "session_id": session_id,
                "model": model,
                "files": args.files,
                "response": response,
                "downloaded": downloaded,
            }
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
    with CopilotSession(headless=False, skip_login_check=True) as cs:
        eprint("Browser open — log in and close when done.")
        try:
            cs.page.wait_for_event("close", timeout=0)
        except Exception:
            pass
    eprint("Login complete. Session saved.")
    return EXIT_OK


def cmd_logout(args):
    """Delete browser profile and sessions."""
    profile = PERSISTENT_DIR
    sessions_dir = Path(__file__).parent / "sessions"
    downloads_dir = Path(__file__).parent / "downloads"

    if profile.exists():
        shutil.rmtree(profile)
        eprint(f"Deleted browser profile: {profile}")

    if sessions_dir.exists():
        for f in sessions_dir.glob("*.json"):
            f.unlink()
        eprint(f"Cleared sessions: {sessions_dir}")

    if downloads_dir.exists():
        shutil.rmtree(downloads_dir)
        eprint(f"Deleted downloads: {downloads_dir}")

    eprint("All local data cleared. Run 'login' to re-authenticate.")
    return EXIT_OK


def _is_sensitive(path):
    """Check if a file matches sensitive patterns."""
    name = path.name.lower()
    for pattern in SENSITIVE_PATTERNS:
        if pattern.startswith("*"):
            if name.endswith(pattern[1:]):
                return True
        elif name == pattern.lower():
            return True
        # Check parent dir name for browser_profile/browser_data
        if "browser_profile" in str(path) or "browser_data" in str(path):
            return True
    return False


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
    sub.add_parser("logout", help="Delete browser profile and all local data")

    args = parser.parse_args()

    if args.command == "doctor":
        sys.exit(cmd_doctor(args))
    elif args.command == "send":
        sys.exit(cmd_send(args))
    elif args.command == "repo":
        sys.exit(cmd_repo(args))
    elif args.command == "bundle":
        sys.exit(cmd_bundle(args))
    elif args.command == "session":
        sys.exit(cmd_session(args))
    elif args.command == "login":
        sys.exit(cmd_login(args))
    elif args.command == "logout":
        sys.exit(cmd_logout(args))
    else:
        parser.print_help()
        sys.exit(EXIT_OK)


if __name__ == "__main__":
    main()
