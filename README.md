# consult_with_copilot

CLI tool that lets coding agents (Qwen Code, Claude Code, opencode, etc.) consult Microsoft 365 Copilot with **GPT 5.6 Think deeper**.

**How it works:** This tool automates the M365 Copilot web interface using Playwright (headless Chromium). It logs into your Microsoft 365 account via a persistent browser profile, sends messages through the chat UI, and captures responses. This is browser automation, not an API — it depends on the current Copilot web UI and may break if Microsoft changes the interface.

## Prerequisites

- **Python 3.10+**
- **Microsoft 365 account** with Copilot access (Copilot Chat Basic or higher)
- **Linux, macOS, or Windows (WSL)** — tested on Linux (Ubuntu/Debian)

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/phly95/consult_with_copilot.git
cd consult_with_copilot

# 2. Run setup (installs dependencies + Chromium)
bash setup.sh

# 3. Log in (opens a browser window — one time only)
.venv/bin/python consult.py login
# Log in to your Microsoft account, then close the browser window.

# 4. Verify everything works
.venv/bin/python consult.py doctor

# 5. Send a test message
.venv/bin/python consult.py send "What is 2+2?"
```

**Expected output:**
```
4
```

## Usage

### Send a message

```bash
.venv/bin/python consult.py send "your question here"
```

### Attach files

```bash
.venv/bin/python consult.py send "review this code" --attach src/main.py src/utils.py
```

### Follow-up messages (sessions)

```bash
.venv/bin/python consult.py send "first question" -s my-session
.venv/bin/python consult.py send "follow-up" -s my-session
```

### Ask about a repository

```bash
.venv/bin/python consult.py repo ./src "explain the architecture"
```

### Generate files

```bash
.venv/bin/python consult.py send "write a Python script that fetches weather data"
# → downloads/fetch_weather.py saved automatically
```

### All commands

| Command | Description |
|---------|-------------|
| `send "msg"` | Send a message to Copilot |
| `repo ./path "q"` | Convert repo to text and ask |
| `bundle f1 f2 "q"` | Bundle files and ask |
| `doctor` | Check installation and login status |
| `login` | Open browser to authenticate |
| `logout` | Delete browser profile (use `--all` to also clear sessions and downloads) |
| `session --create --list --delete` | Manage conversation sessions |

### All options

| Flag | Description |
|------|-------------|
| `--attach FILE` | Attach files to message |
| `-s, --session ID` | Session ID for follow-ups |
| `--download-dir DIR` | Where to save generated files |
| `--no-download` | Disable auto-download |
| `--no-headless` | Show browser window |
| `--json` | Output as JSON (for agent parsing) |
| `--include PATTERN` | Glob patterns for repo command |
| `--exclude PATTERN` | Patterns to skip in repo |
| `--dry-run` | Show what repo would send without sending |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Not logged in |
| 3 | File not found |
| 4 | Refused to attach sensitive file |

Status messages go to stderr; responses go to stdout. This lets coding agents parse output cleanly.

## Authentication

### Login

```bash
.venv/bin/python consult.py login
```

Opens a visible Chromium window. Log in with your Microsoft 365 account, then close the window. The session is saved to `~/.cache/consult_with_copilot/browser_profile/`.

### Login succeeds when

After running `login`, run `doctor` — the "M365 login" check should show ✓. Or run `send "hello"` — if you get a response, you're logged in.

### Session persistence

- The browser profile stores cookies and session tokens
- Sessions persist across tool runs until you close the browser or they expire
- Microsoft tokens typically expire after 1–24 hours depending on your org's policy
- If you see "Not logged in", run `login` again

### MFA / SSO

If your organization requires MFA or SSO, the login browser window will prompt you for it. Complete the MFA flow in the browser before closing it.

### Re-login

```bash
.venv/bin/python consult.py login
```

### Reset / Logout

```bash
# Delete browser profile only (clears authentication)
.venv/bin/python consult.py logout

# Delete everything: browser profile, sessions, and downloads
.venv/bin/python consult.py logout --all
```

## Browser Profile Location

The browser profile is stored at:

```
~/.cache/consult_with_copilot/browser_profile/
```

Override with environment variable:
```bash
export CONSULT_COPILOT_PROFILE=/custom/path
```

**Never commit, share, or copy this directory.** It contains your authentication cookies.

## Integration with Coding Agents

Add to your agent's instruction file (QWEN.md, CLAUDE.md, AGENTS.md, etc.):

```markdown
## Copilot Consultation

You can consult M365 Copilot for code review, debugging, and architecture questions:

\```bash
python /absolute/path/to/consult_with_copilot/consult.py send "your question"
python /absolute/path/to/consult_with_copilot/consult.py send "review" --attach file.py
python /absolute/path/to/consult_with_copilot/consult.py repo ./src "explain this"
\```

Files Copilot generates are auto-downloaded to ./consult_with_copilot/downloads/.
Use -s session-id for follow-up questions in the same conversation.
Run doctor to verify the tool is working.
```

**Important:** Use the absolute path to `consult.py` or ensure it's on your PATH.

## Repo Command Details

The `repo` command walks a directory tree, concatenates text files with headers, and sends the result as a `.txt` attachment.

### What gets included

- Text files (`.py`, `.js`, `.ts`, `.md`, `.json`, etc.)
- Respects `.gitignore` patterns
- Skips binary files (images, archives, executables)
- Skips `node_modules`, `.git`, `__pycache__`, `.venv`, etc.

### What gets excluded automatically

- Binary files (images, PDFs, archives, compiled code)
- Common secret files (`.env`, `credentials.json`, `*.pem`, `id_rsa`)
- Large files (>100KB)

### Patterns

```bash
# Only include Python and JS files
.venv/bin/python consult.py repo ./src "review" --include "*.py" "*.js"

# Exclude test files
.venv/bin/python consult.py repo ./src "review" --exclude "test_*" "vendor/*"
```

### Dry run

See what would be sent without actually sending:

```bash
.venv/bin/python consult.py repo ./src --dry-run
```

## JSON Output

For machine-readable output (useful for coding agents):

```bash
.venv/bin/python consult.py --json send "what is 2+2?"
```

Output:
```json
{
  "session_id": "abc12345",
  "model": "GPT 5.6 Think deeper",
  "response": "10",
  "downloaded": [],
  "elapsed_seconds": 3.2,
  "conversation_url": "https://m365.cloud.microsoft/chat/conversation/..."
}
```

## Security and Privacy

### What is stored locally

- **Browser profile** (`~/.cache/consult_with_copilot/browser_profile/`): Authentication cookies and session tokens
- **Sessions** (`./sessions/*.json`): Conversation IDs and message history
- **Downloads** (`./downloads/`): Files generated by Copilot

### What is sent to Microsoft

- Your messages and attached files are sent to M365 Copilot via the web UI
- Repository contents (when using `repo` command) are sent as a text attachment
- Microsoft's privacy policy applies to all data sent through Copilot

### Sensitive file protection

The tool refuses to attach files matching these patterns:
- `.env`, `.env.*`, `credentials.json`, `service-account.json`
- `*.pem`, `*.key`, `*.p12`, `id_rsa`, `id_ed25519`
- `kubeconfig`, `.kube/config`
- Anything inside `browser_profile/` or `browser_data/`

### Cleanup

Delete browser profile:
```bash
.venv/bin/python consult.py logout
```

Delete everything (profile, sessions, downloads):
```bash
.venv/bin/python consult.py logout --all
```

## Reliability

### Known limitations

- **Depends on M365 Copilot web UI** — Microsoft UI changes may break the tool
- **Not an official API** — this is browser automation, not a supported integration
- **Model selection** — the tool selects GPT 5.6 Think deeper via the UI; if this model is unavailable, it falls back to whatever is available
- **File size limits** — very large repositories may exceed Copilot's input limits
- **Transient errors** — "Oops! Something happened" errors are auto-retried with page reload (up to 3 retries)

### What is tested

- Linux (Ubuntu/Debian) with Python 3.12
- Playwright 1.52.0 with bundled Chromium
- Headless and headed modes
- File attachments, repo conversion, session follow-ups

### What is NOT tested

- macOS, Windows (should work but untested)
- Python 3.10, 3.11 (should work)
- Enterprise environments with strict proxy/firewall rules

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Not logged in" | Run `login` again |
| "Oops! Something happened" | Auto-retries; if persistent, run `login` |
| Chromium won't install | Run `playwright install chromium` manually |
| Blank response | Copilot may be processing; wait and retry |
| File not downloading | Check Copilot shows "Download filename.ext" in response |
| Slow first call | First run launches Chromium (~5s) |
| MFA prompt | Complete MFA in the browser window during `login` |
| Token expired | Run `login` again |
| WSL display issues | Use `--no-headless` with an X server, or run headless |

## Architecture

```
┌─────────────┐     ┌────────────┐     ┌───────────┐     ┌──────────────────┐
│ Coding Agent │────▶│ consult.py │────▶│ Playwright │────▶│ M365 Copilot UI  │
│  (your LLM) │◀────│    CLI     │◀────│ Chromium   │◀────│ (web chat)       │
└─────────────┘     └────────────┘     └───────────┘     └──────────────────┘
     sends                sends              opens              sends to
     shell cmd            message            headless           Microsoft
                          + files            browser            servers
```

```
consult_with_copilot/
├── consult.py          # CLI entry point
├── lib/
│   ├── browser.py      # Playwright browser automation
│   ├── session.py      # Session persistence (JSON)
│   └── files.py        # Repo-to-text conversion, bundling
├── sessions/           # Conversation state (auto-created)
├── downloads/          # Generated files (auto-created)
├── setup.sh            # One-command setup
├── requirements.txt    # Pinned dependencies
├── README.md           # This file
├── COPILOT_TOOL.md     # Agent instructions
├── SECURITY.md         # Security policy
├── CONTRIBUTING.md     # Contribution guide
└── LICENSE             # MIT
```

## License

MIT
