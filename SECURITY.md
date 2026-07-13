# Security Policy

## Authentication Data

This tool stores browser authentication data (cookies, session tokens) at:

```
~/.cache/consult_with_copilot/browser_profile/
```

**Never commit, share, copy, or back up this directory.** It contains your Microsoft 365 session cookies.

## What Is Stored Locally

| Data | Location | Purpose |
|------|----------|---------|
| Browser profile | `~/.cache/consult_with_copilot/browser_profile/` | Authentication cookies |
| Session history | `./sessions/*.json` | Conversation IDs and message text |
| Generated files | `./downloads/` | Files created by Copilot |

## What Is Sent to Microsoft

- Messages you type in the chat
- Files you attach (including repository contents via `repo` command)
- All data is sent through the M365 Copilot web interface, subject to Microsoft's privacy policy

## Sensitive File Protection

The tool refuses to attach files matching:
- `.env`, `.env.local`, `.env.production`, `.env.development`, `.env.staging`, `.env.test`, `.env.ci`
- `credentials.json`, `service-account.json`, `keyfile.json`
- `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.jks`
- `id_rsa`, `id_ed25519`, `id_ecdsa`
- `.netrc`, `.npmrc`, `.pypirc`
- `kubeconfig` (or anything inside a `.kube/` directory)
- Anything inside `browser_profile/` or `browser_data/`

Symlinks pointing to sensitive targets are also blocked (the tool resolves symlinks before checking).

## Cleanup

```bash
# Delete browser profile only (clears authentication)
python consult.py logout

# Delete everything: browser profile, sessions, and downloads
python consult.py logout --all
```

## Reporting Vulnerabilities

If you discover a security issue, please open a GitHub issue or contact the maintainers directly.
