# Contributing

## Development Setup

```bash
git clone https://github.com/phly95/consult_with_copilot.git
cd consult_with_copilot
bash setup.sh
```

## Running Tests

```bash
# Check tool health
.venv/bin/python consult.py doctor

# Send a test message
.venv/bin/python consult.py send "hello"

# Test repo conversion
.venv/bin/python consult.py repo . --dry-run
```

## Code Style

- Python 3.10+
- No external dependencies beyond Playwright
- Keep the CLI interface stable
- All output to stderr except responses (stdout)

## Submitting Changes

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test with `doctor` and a real `send` command
5. Submit a pull request

## Important Notes

- Never commit browser profiles or session data
- Test with a real M365 account before submitting
- The tool depends on the M365 Copilot web UI — UI changes may require updates
