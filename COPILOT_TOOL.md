# Copilot Tool — Agent Instructions

This project provides a CLI tool for consulting Microsoft 365 Copilot (GPT 5.6 Think deeper).

## Setup (one-time)

```bash
cd consult_with_copilot && bash setup.sh
.venv/bin/python consult.py login     # opens browser, log in, close it
.venv/bin/python consult.py doctor    # verify everything works
```

## Usage

All commands use `consult_with_copilot/consult.py`. Use the venv Python.

### Ask a question

```bash
.venv/bin/python consult_with_copilot/consult.py send "your question"
```

### Attach files

```bash
.venv/bin/python consult_with_copilot/consult.py send "review this" --attach file.py
```

### Follow-up (same conversation)

```bash
.venv/bin/python consult_with_copilot/consult.py send "first question" -s my-session
.venv/bin/python consult_with_copilot/consult.py send "follow-up" -s my-session
```

### Ask about a codebase

```bash
.venv/bin/python consult_with_copilot/consult.py repo ./src "explain the architecture"
```

### Bundle specific files

```bash
.venv/bin/python consult_with_copilot/consult.py bundle file1.py file2.py --context "review these files"
```

### Manage sessions

```bash
.venv/bin/python consult_with_copilot/consult.py session --list          # list all sessions
.venv/bin/python consult_with_copilot/consult.py session --create --id my-session  # create
.venv/bin/python consult_with_copilot/consult.py session --delete my-session       # delete
```

### Generate files (auto-downloaded)

```bash
.venv/bin/python consult_with_copilot/consult.py send "create a script that does X"
# → downloads/X.py
```

### Check tool health

```bash
.venv/bin/python consult_with_copilot/consult.py doctor
```

### JSON output (for parsing)

```bash
.venv/bin/python consult_with_copilot/consult.py --json send "question"
```

## Quick Reference

| What | Command |
|------|---------|
| Ask Copilot | `send "question"` |
| With files | `send "review" --attach file.py` |
| Follow-up | `send "more?" -s session-id` |
| About repo | `repo ./path "question"` |
| Bundle files | `bundle file1.py file2.py --context "review"` |
| Generate file | `send "create X"` (auto-downloads to ./downloads/) |
| No downloads | `send "question" --no-download` |
| Sessions | `session --list`, `session --create --id X`, `session --delete X` |
| Health check | `doctor` |
| Login | `login` |
| Reset | `logout` (profile only) or `logout --all` (everything) |

## Important Notes

- Profile stored at `~/.cache/consult_with_copilot/browser_profile/`
- If doctor shows M365 login ✗, run `login` again
- Sensitive files (.env, keys, credentials) are blocked from attachment
- Model: GPT 5.6 Think deeper (set via UI; will error if unavailable)
- Exit codes: 0=success, 1=error, 2=not logged in, 3=file not found, 4=sensitive file
- Status messages go to stderr; responses go to stdout
