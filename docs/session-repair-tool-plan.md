# OpenCode Session Repair Tool

## References
- [Error: Invalid signature in thinking block #6418](https://github.com/anomalyco/opencode/issues/6418) on OpenCode
- [Workaround to similar issue on Claude Code](https://github.com/anthropics/claude-code/issues/10199#issuecomment-3600387852)

---

## Problem Description

### Error Message
```
messages.{N}.content.{M}: Invalid `signature` in `thinking` block
```

Example from actual corrupted session:
```json
{
  "error": {
    "name": "APIError",
    "data": {
      "message": "messages.1.content.0: Invalid `signature` in `thinking` block",
      "statusCode": 400,
      "isRetryable": false
    }
  }
}
```

### Symptoms
- Session becomes completely unresponsive
- Every subsequent user input triggers the same 400 error
- The error persists because the corrupted state remains in conversation history
- Session cannot be resumed with certain models

### Root Cause

The corruption occurs due to **model switching mid-session**:

1. A session contains assistant responses with `thinking` blocks that have cryptographic signatures
2. These signatures are model-specific (each model/provider signs thinking blocks differently)
3. When switching to a different model (e.g., from GLM 4.7 to Claude Opus 4.5), the new model cannot validate signatures created by the previous model
4. The Anthropic API correctly rejects requests containing thinking blocks with invalid signatures
5. Since the corrupted history is persisted, the error repeats on every subsequent request

**Trigger Scenarios:**
- Switching between model providers mid-session (e.g., MinMax -> Anthropic)
- Switching between model versions that use different signature schemes
- Resuming an old session with a newer model version

---

## OpenCode Storage Structure

Sessions are stored in `~/.local/share/opencode/storage/`:

```
~/.local/share/opencode/storage/
├── session/
│   └── {projectID}/
│       └── ses_{sessionID}.json       # Session metadata
├── message/
│   └── ses_{sessionID}/
│       └── msg_{messageID}.json       # Individual messages
├── part/
│   └── msg_{messageID}/
│       └── prt_{partID}.json          # Content blocks (text, tool, thinking)
└── session_diff/
    └── ses_{sessionID}/               # File diffs for session
```

### Session Metadata (`session/*.json`)
```json
{
  "id": "ses_471a726a1ffe1hQ6hYnZZZ6btG",
  "projectID": "361ca7d6e3f68f4ed6095ec597a2c566f317ad21",
  "directory": "/home/luigi/dm-next",
  "title": "Reviewing SHM TTS migration plan",
  "time": { "created": 1767619746142, "updated": 1767677710014 }
}
```

### Message Files (`message/ses_*/*.json`)
```json
{
  "id": "msg_b91219779002aY62CeVyK7PxBy",
  "sessionID": "ses_471a726a1ffe1hQ6hYnZZZ6btG",
  "role": "assistant",
  "modelID": "claude-opus-4-5",
  "providerID": "anthropic",
  "error": {
    "name": "APIError",
    "data": {
      "message": "messages.1.content.0: Invalid `signature` in `thinking` block"
    }
  }
}
```

### Part Files (`part/msg_*/*.json`)
Content blocks including thinking blocks with signatures are stored here.

---

## Detection Method

### Find Corrupted Sessions
```bash
# Search for error messages containing signature errors
grep -r "Invalid.*signature.*thinking" ~/.local/share/opencode/storage/message/

# Find all messages with this specific error
find ~/.local/share/opencode/storage/message -name "*.json" \
  -exec grep -l "Invalid.*signature.*thinking" {} \;
```

### Identify Affected Session
```bash
# Get session ID from corrupted message file
cat /path/to/corrupted/msg_*.json | jq '.sessionID'

# List all messages in that session
ls ~/.local/share/opencode/storage/message/ses_{sessionID}/
```

---

## Example: Corrupted Session Found

**Session:** "Reviewing SHM TTS migration plan"  
**Session ID:** `ses_471a726a1ffe1hQ6hYnZZZ6btG`

**Corrupted Messages (3 instances of same error):**
| Message ID | Timestamp | Error Position |
|------------|-----------|----------------|
| `msg_b91219779002aY62CeVyK7PxBy` | Jan 6 02:27:38 UTC | messages.1.content.0 |
| `msg_b91745c1c001WF2DeQRM9Raf3d` | Jan 6 03:58:01 UTC | messages.1.content.0 |
| `msg_b91cd4f14002T7iD6rZ3TbqUIY` | Jan 6 05:35:11 UTC | messages.1.content.0 |

**Context:** Session was using `claude-opus-4-5` via Anthropic provider. The `messages.1.content.0` position indicates the corruption is in the 2nd message (index 1), first content block - likely a thinking block from an earlier model's response.

---

## Repair Strategies

### Option 1: Delete Corrupted Messages (Quick Fix)
Remove the error messages to allow session to continue:
```bash
# Backup first
cp -r ~/.local/share/opencode/storage/message/ses_{ID} ~/backup/

# Remove corrupted message files
rm ~/.local/share/opencode/storage/message/ses_{ID}/msg_{corrupted_id}.json
```

### Option 2: Truncate Session History
Truncate the session to before the first thinking block with invalid signature:
1. Identify the first message containing a thinking block from a different model
2. Delete all messages after that point
3. Delete corresponding parts

### Option 3: Remove Thinking Blocks from History
Strip thinking blocks from the conversation history:
1. Find all part files with `"type": "thinking"`
2. Delete those part files
3. Update message files to reflect removed content

### Option 4: Start Fresh Session with Context
1. Export useful context from the corrupted session
2. Create a new session
3. Paste the context as the first user message

---

## Prevention

1. **Avoid switching models mid-session** when using models with thinking/reasoning blocks
2. **Start a new session** when switching between model providers
3. **Be cautious with extended thinking** features when model flexibility is needed

---

## Session Repair Tool

A session repair tool has been implemented at `tools/session-repair.py`.

### Installation

```bash
git clone https://github.com/vieenrose/opencode-toolkit.git
cd opencode-toolkit
```

No dependencies required - uses Python 3 standard library only.

### Commands

| Command | Description |
|---------|-------------|
| `list` | Scan and display all corrupted sessions |
| `fix <target>` | Fix a specific session or message |
| `fix --all` | Fix all corrupted sessions |
| `help` | Show help message |

### Options

| Option | Description |
|--------|-------------|
| `--dry-run` | Preview changes without modifying any files |

### Usage Examples

```bash
# List all corrupted sessions
python3 tools/session-repair.py list

# Preview fix without making changes (dry-run)
python3 tools/session-repair.py fix --all --dry-run

# Fix a specific session by full ID
python3 tools/session-repair.py fix ses_471a726a1ffe1hQ6hYnZZZ6btG

# Fix a specific session by partial ID match
python3 tools/session-repair.py fix ses_471a726

# Fix a specific message by message ID
python3 tools/session-repair.py fix msg_b91219779002aY62CeVyK7PxBy

# Fix all corrupted sessions at once
python3 tools/session-repair.py fix --all
```

### What Gets Removed

When fixing a corrupted session, the tool removes:

1. **Source message** - The first assistant message containing the invalid thinking block signature
2. **Error messages** - All messages that recorded the "Invalid signature in thinking block" API errors
3. **Associated parts** - All part files (`prt_*.json`) linked to removed messages

### Backup Location

Before any modifications, backups are created at:
```
~/.local/share/opencode/repair-backups/session_{sessionID}_{timestamp}/
```

The backup preserves the original directory structure:
```
repair-backups/
└── session_ses_471a726a1ffe1hQ6_20260106_141623/
    ├── message/
    │   └── ses_471a726a1ffe1hQ6hYnZZZ6btG/
    │       ├── msg_b8e5ec4b7002m4e3wzClqFHkIG.json
    │       ├── msg_b91219779002aY62CeVyK7PxBy.json
    │       └── ...
    └── part/
        └── msg_b8e5ec4b7002m4e3wzClqFHkIG/
            ├── prt_xxx.json
            └── ...
```

### Example: List Command

```
$ python3 tools/session-repair.py list

Scanning for corrupted sessions...

Found 6 corrupted message(s):

----------------------------------------------------------------------------------------------------

[1] Session: Reviewing SHM TTS migration plan
    Session ID: ses_471a726a1ffe1hQ6hYnZZZ6btG
    Corrupted Messages: 3

    - Message: msg_b91cd4f14002T7iD6rZ3TbqUIY
      Time: 2026-01-06 13:35:10
      Model: anthropic/claude-opus-4-5
      Error: messages.1.content.0: Invalid `signature` in `thinking` block

    - Message: msg_b91745c1c001WF2DeQRM9Raf3d
      Time: 2026-01-06 11:58:00
      Model: anthropic/claude-opus-4-5
      Error: messages.1.content.0: Invalid `signature` in `thinking` block

    - Message: msg_b91219779002aY62CeVyK7PxBy
      Time: 2026-01-06 10:27:36
      Model: anthropic/claude-opus-4-5
      Error: messages.1.content.0: Invalid `signature` in `thinking` block

    Fix: Remove 4 message(s) and 5 part(s)

----------------------------------------------------------------------------------------------------

To fix a specific session, run:
  python session-repair.py fix <session_id>

To fix all corrupted sessions, run:
  python session-repair.py fix --all

Add --dry-run to see what would be done without making changes.
```

### Example: Fix Command with Dry-Run

```
$ python3 tools/session-repair.py fix ses_471a726a1ffe1hQ6hYnZZZ6btG --dry-run

[DRY RUN] No changes will be made.

Processing session: Reviewing SHM TTS migration plan
  Session ID: ses_471a726a1ffe1hQ6hYnZZZ6btG
  Status: WOULD SUCCEED
  Messages removed: 4
    - msg_b8e5ec4b7002m4e3wzClqFHkIG
    - msg_b91219779002aY62CeVyK7PxBy
    - msg_b91745c1c001WF2DeQRM9Raf3d
    - msg_b91cd4f14002T7iD6rZ3TbqUIY
  Parts removed: 5
```

### Example: Fix Command (Actual Fix)

```
$ python3 tools/session-repair.py fix ses_471a726a1ffe1hQ6hYnZZZ6btG

Processing session: Reviewing SHM TTS migration plan
  Session ID: ses_471a726a1ffe1hQ6hYnZZZ6btG
  Status: SUCCESS
  Messages removed: 4
    - msg_b8e5ec4b7002m4e3wzClqFHkIG
    - msg_b91219779002aY62CeVyK7PxBy
    - msg_b91745c1c001WF2DeQRM9Raf3d
    - msg_b91cd4f14002T7iD6rZ3TbqUIY
  Parts removed: 5
  Backup saved to: /home/luigi/.local/share/opencode/repair-backups/session_ses_471a726a1ffe1hQ6_20260106_141623

============================================================
Repair complete!
Please restart OpenCode to see the changes.
============================================================
```

### How It Works

1. **Scan** - Searches `~/.local/share/opencode/storage/message/` for messages containing the error "Invalid signature in thinking block"
2. **Parse** - Extracts the error position (e.g., `messages.1.content.0`) to identify which message has the corrupted thinking block
3. **Identify** - Finds the source assistant message containing the invalid signature, plus all error messages
4. **Backup** - Creates a timestamped backup preserving directory structure
5. **Remove** - Deletes the identified message files and their associated parts from `storage/part/`

### After Repair

After running the fix:
1. **Restart OpenCode** to reload session data
2. The repaired session will have lost the first assistant response (the one with the invalid thinking block)
3. You can continue using the session normally
4. If needed, restore from backup at `~/.local/share/opencode/repair-backups/`
