# OpenCode Toolkit

A collection of tools and workarounds for [OpenCode](https://github.com/anomalyco/opencode) - the open-source AI coding assistant.

## Tools

### Session Repair Tool

Fixes corrupted sessions caused by invalid thinking block signatures. This typically occurs when switching models mid-session.

```bash
# List all corrupted sessions
python3 tools/session-repair.py list

# Preview fix without making changes
python3 tools/session-repair.py fix --all --dry-run

# Fix a specific session
python3 tools/session-repair.py fix <session_id>

# Fix all corrupted sessions
python3 tools/session-repair.py fix --all
```

See [docs/session-repair-tool-plan.md](docs/session-repair-tool-plan.md) for detailed documentation.

## Issues Addressed

| Issue | Description | Solution |
|-------|-------------|----------|
| [#6418](https://github.com/anomalyco/opencode/issues/6418) | Invalid signature in thinking block | [Session Repair Tool](tools/session-repair.py) |

## Installation

```bash
git clone https://github.com/vieenrose/opencode-toolkit.git
cd opencode-toolkit
```

No additional dependencies required - tools use Python 3 standard library only.

## License

MIT
