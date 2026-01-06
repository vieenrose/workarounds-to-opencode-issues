#!/usr/bin/env python3
"""
OpenCode Session Repair Tool

Scans for and repairs corrupted sessions caused by invalid thinking block signatures.
This typically occurs when switching models mid-session.

Usage:
    python session-repair.py list              # List all corrupted sessions
    python session-repair.py fix <session_id>  # Fix a specific session
    python session-repair.py fix --all         # Fix all corrupted sessions
    
Options:
    --dry-run    Show what would be done without making changes

The fix removes the first assistant message in a corrupted session, which typically
contains the thinking block with an invalid signature from a previous model.
"""

import json
import os
import re
import sys
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

# OpenCode storage path
STORAGE_PATH = Path.home() / ".local" / "share" / "opencode" / "storage"
MESSAGE_PATH = STORAGE_PATH / "message"
SESSION_PATH = STORAGE_PATH / "session"
PART_PATH = STORAGE_PATH / "part"
BACKUP_PATH = Path.home() / ".local" / "share" / "opencode" / "repair-backups"


def get_session_title(session_id: str) -> str:
    """Get the title of a session from its metadata."""
    for project_dir in SESSION_PATH.iterdir():
        if not project_dir.is_dir():
            continue
        session_file = project_dir / f"{session_id}.json"
        if session_file.exists():
            try:
                with open(session_file) as f:
                    data = json.load(f)
                    return data.get("title", "Untitled")
            except (json.JSONDecodeError, IOError):
                pass
    return "Unknown"


def find_corrupted_messages() -> list[dict]:
    """
    Scan all message files for thinking block signature errors.
    Returns a list of corrupted message info sorted by time (newest first).
    """
    corrupted = []
    
    if not MESSAGE_PATH.exists():
        print(f"Error: Message path not found: {MESSAGE_PATH}")
        return corrupted
    
    # Iterate through all session directories
    for session_dir in MESSAGE_PATH.iterdir():
        if not session_dir.is_dir():
            continue
        
        session_id = session_dir.name
        
        # Check each message file in the session
        for msg_file in session_dir.glob("msg_*.json"):
            try:
                with open(msg_file) as f:
                    data = json.load(f)
                
                # Check if message has the signature error
                error = data.get("error", {})
                error_data = error.get("data", {})
                error_msg = error_data.get("message", "")
                
                if "Invalid" in error_msg and "signature" in error_msg and "thinking" in error_msg:
                    # Extract the message position from error (e.g., "messages.1.content.0")
                    position_match = re.search(r'messages\.(\d+)\.content\.(\d+)', error_msg)
                    msg_index = int(position_match.group(1)) if position_match else None
                    content_index = int(position_match.group(2)) if position_match else None
                    
                    # Extract timestamp
                    time_info = data.get("time", {})
                    created = time_info.get("created", 0)
                    
                    # Get session title
                    title = get_session_title(session_id)
                    
                    corrupted.append({
                        "message_id": data.get("id", msg_file.stem),
                        "session_id": session_id,
                        "session_title": title,
                        "error_message": error_msg,
                        "error_msg_index": msg_index,
                        "error_content_index": content_index,
                        "timestamp": created,
                        "timestamp_str": datetime.fromtimestamp(created / 1000).strftime("%Y-%m-%d %H:%M:%S") if created else "Unknown",
                        "model_id": data.get("modelID", "Unknown"),
                        "provider_id": data.get("providerID", "Unknown"),
                        "file_path": str(msg_file),
                    })
            except (json.JSONDecodeError, IOError) as e:
                # Skip files that can't be read
                continue
    
    # Sort by timestamp, newest first
    corrupted.sort(key=lambda x: x["timestamp"], reverse=True)
    return corrupted


def get_session_messages(session_id: str) -> list[dict]:
    """Get all messages for a session, sorted by creation time."""
    messages = []
    session_msg_dir = MESSAGE_PATH / session_id
    
    if not session_msg_dir.exists():
        return messages
    
    for msg_file in session_msg_dir.glob("msg_*.json"):
        try:
            with open(msg_file) as f:
                data = json.load(f)
                data["_file_path"] = msg_file
                messages.append(data)
        except (json.JSONDecodeError, IOError):
            continue
    
    # Sort by creation time
    messages.sort(key=lambda x: x.get("time", {}).get("created", 0))
    return messages


def find_message_to_remove(session_id: str, error_msg_index: int) -> Optional[dict]:
    """
    Find the message that needs to be removed based on the error position.
    
    The error "messages.N.content.M" refers to the Nth message in the API request.
    In OpenCode's storage, we need to find the corresponding assistant message
    that contains the thinking block.
    
    The error typically occurs at position 1 (second message, which is usually
    the first assistant response containing a thinking block).
    """
    messages = get_session_messages(session_id)
    
    if not messages:
        return None
    
    # Filter to only assistant messages (user messages don't have thinking blocks)
    assistant_messages = [m for m in messages if m.get("role") == "assistant"]
    
    # The error index is 0-based in the API request
    # messages.1 means the second message (index 1)
    # For thinking block issues, this is typically the first assistant response
    
    # Find the first assistant message (index 0 in assistant_messages)
    # which corresponds to messages.1 in the full conversation
    if error_msg_index is not None and error_msg_index > 0:
        # Map API index to assistant message index
        # API index 1 = first assistant message (index 0)
        # API index 3 = second assistant message (index 1), etc.
        assistant_index = (error_msg_index - 1) // 2
        if assistant_index < len(assistant_messages):
            return assistant_messages[assistant_index]
    
    # Fallback: return the first assistant message
    if assistant_messages:
        return assistant_messages[0]
    
    return None


def backup_files(files: list[Path], backup_name: str) -> Path:
    """Create a backup of files before modification."""
    BACKUP_PATH.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = BACKUP_PATH / f"{backup_name}_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    for file_path in files:
        if file_path.exists():
            # Preserve directory structure in backup
            rel_path = file_path.relative_to(STORAGE_PATH)
            dest = backup_dir / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, dest)
    
    return backup_dir


def get_message_parts(message_id: str) -> list[Path]:
    """Get all part files for a message."""
    parts_dir = PART_PATH / message_id
    if not parts_dir.exists():
        return []
    return list(parts_dir.glob("prt_*.json"))


def find_error_messages(session_id: str) -> list[dict]:
    """Find all messages with thinking block signature errors in a session."""
    error_messages = []
    session_msg_dir = MESSAGE_PATH / session_id
    
    if not session_msg_dir.exists():
        return error_messages
    
    for msg_file in session_msg_dir.glob("msg_*.json"):
        try:
            with open(msg_file) as f:
                data = json.load(f)
            
            error = data.get("error", {})
            error_data = error.get("data", {})
            error_msg = error_data.get("message", "")
            
            if "Invalid" in error_msg and "signature" in error_msg and "thinking" in error_msg:
                data["_file_path"] = msg_file
                error_messages.append(data)
        except (json.JSONDecodeError, IOError):
            continue
    
    return error_messages


def update_session_after_repair(session_id: str, removed_message_ids: set) -> bool:
    """
    Update the session file to remove references to deleted messages.
    This ensures Claude can resume the session without encountering
    references to non-existent messages.
    """
    for project_dir in SESSION_PATH.iterdir():
        if not project_dir.is_dir():
            continue
        session_file = project_dir / f"{session_id}.json"
        if session_file.exists():
            try:
                with open(session_file) as f:
                    data = json.load(f)
                
                modified = False
                
                # Remove references from messageOrder list
                if "messageOrder" in data and isinstance(data["messageOrder"], list):
                    data["messageOrder"] = [
                        msg_id for msg_id in data["messageOrder"]
                        if msg_id not in removed_message_ids
                    ]
                    modified = True
                
                # Remove references from messages dict
                if "messages" in data and isinstance(data["messages"], dict):
                    for msg_id in removed_message_ids:
                        if msg_id in data["messages"]:
                            del data["messages"][msg_id]
                            modified = True
                
                # Remove references from conversation.history
                if "conversation" in data and isinstance(data["conversation"], dict):
                    history = data["conversation"].get("history", [])
                    if isinstance(history, list):
                        # Rebuild history without removed messages
                        new_history = []
                        for entry in history:
                            if isinstance(entry, dict) and entry.get("messageId") not in removed_message_ids:
                                new_history.append(entry)
                            elif not isinstance(entry, dict):
                                new_history.append(entry)
                        if len(new_history) != len(history):
                            data["conversation"]["history"] = new_history
                            modified = True
                
                if modified:
                    with open(session_file, "w") as f:
                        json.dump(data, f, indent=2)
                    return True
                    
            except (json.JSONDecodeError, IOError, KeyError) as e:
                pass
    return False


def fix_session(session_id: str, error_msg_index: int = 1, dry_run: bool = False) -> dict:
    """
    Fix a corrupted session by removing:
    1. The message containing the invalid thinking block (first assistant message)
    2. All error messages that recorded the API failures
    
    Returns a dict with:
        - success: bool
        - messages_removed: list of message IDs
        - parts_removed: int
        - backup_path: str (if not dry_run)
        - error: str (if failed)
    """
    result = {
        "success": False,
        "messages_removed": [],
        "parts_removed": 0,
        "backup_path": None,
        "error": None,
    }
    
    # Find the message containing the thinking block to remove
    msg_to_remove = find_message_to_remove(session_id, error_msg_index)
    
    # Find all error messages to remove
    error_messages = find_error_messages(session_id)
    
    if not msg_to_remove and not error_messages:
        result["error"] = "Could not identify any messages to remove"
        return result
    
    # Collect all messages to remove
    messages_to_remove = []
    
    if msg_to_remove:
        messages_to_remove.append(msg_to_remove)
    
    for err_msg in error_messages:
        # Avoid duplicates
        if err_msg.get("id") not in [m.get("id") for m in messages_to_remove]:
            messages_to_remove.append(err_msg)
    
    # Collect all files to backup and remove
    files_to_backup = []
    all_parts = []
    
    for msg in messages_to_remove:
        message_id = msg.get("id")
        msg_file = msg.get("_file_path")
        
        if message_id and msg_file:
            result["messages_removed"].append(message_id)
            files_to_backup.append(msg_file)
            
            # Get associated parts
            parts = get_message_parts(message_id)
            all_parts.extend(parts)
            files_to_backup.extend(parts)
    
    result["parts_removed"] = len(all_parts)
    
    if dry_run:
        result["success"] = True
        return result
    
    # Backup before modification
    backup_dir = backup_files(files_to_backup, f"session_{session_id[:20]}")
    result["backup_path"] = str(backup_dir)
    
    # Remove message files
    for msg in messages_to_remove:
        msg_file = msg.get("_file_path")
        if msg_file and msg_file.exists():
            try:
                msg_file.unlink()
            except IOError as e:
                # Continue even if some fail
                pass
    
    # Remove part files
    for part_file in all_parts:
        try:
            part_file.unlink()
        except IOError as e:
            # Continue even if some parts fail
            pass
    
    # Remove empty parts directories
    for msg in messages_to_remove:
        message_id = msg.get("id")
        if message_id:
            parts_dir = PART_PATH / message_id
            if parts_dir.exists():
                try:
                    parts_dir.rmdir()
                except OSError:
                    pass
    
    # Update session file to remove references to deleted messages
    removed_message_ids = set(result["messages_removed"])
    if removed_message_ids:
        update_session_after_repair(session_id, removed_message_ids)
    
    result["success"] = True
    return result


def list_corrupted():
    """List all corrupted messages."""
    print("\nScanning for corrupted sessions...\n")
    
    corrupted = find_corrupted_messages()
    
    if not corrupted:
        print("No corrupted sessions found.")
        return
    
    print(f"Found {len(corrupted)} corrupted message(s):\n")
    print("-" * 100)
    
    # Group by session
    sessions = {}
    for msg in corrupted:
        sid = msg["session_id"]
        if sid not in sessions:
            sessions[sid] = {
                "title": msg["session_title"],
                "messages": [],
                "error_msg_index": msg["error_msg_index"],
            }
        sessions[sid]["messages"].append(msg)
    
    for i, (session_id, info) in enumerate(sessions.items(), 1):
        print(f"\n[{i}] Session: {info['title']}")
        print(f"    Session ID: {session_id}")
        print(f"    Corrupted Messages: {len(info['messages'])}")
        
        for msg in info["messages"]:
            print(f"\n    - Message: {msg['message_id']}")
            print(f"      Time: {msg['timestamp_str']}")
            print(f"      Model: {msg['provider_id']}/{msg['model_id']}")
            print(f"      Error: {msg['error_message']}")
        
        # Find messages that would be removed
        msg_to_remove = find_message_to_remove(session_id, info["error_msg_index"])
        error_messages = find_error_messages(session_id)
        
        total_msgs = (1 if msg_to_remove else 0) + len(error_messages)
        total_parts = 0
        if msg_to_remove:
            total_parts += len(get_message_parts(msg_to_remove.get("id", "")))
        for err_msg in error_messages:
            total_parts += len(get_message_parts(err_msg.get("id", "")))
        
        print(f"\n    Fix: Remove {total_msgs} message(s) and {total_parts} part(s)")
    
    print("\n" + "-" * 100)
    print(f"\nTo fix a specific session, run:")
    print(f"  python session-repair.py fix <session_id>")
    print(f"\nTo fix all corrupted sessions, run:")
    print(f"  python session-repair.py fix --all")
    print(f"\nAdd --dry-run to see what would be done without making changes.")


def fix_command(target: str, dry_run: bool = False):
    """Fix a specific session or all corrupted sessions."""
    
    corrupted = find_corrupted_messages()
    
    if not corrupted:
        print("No corrupted sessions found.")
        return
    
    # Group by session and get error index
    sessions_info = {}
    for msg in corrupted:
        sid = msg["session_id"]
        if sid not in sessions_info:
            sessions_info[sid] = {
                "title": msg["session_title"],
                "error_msg_index": msg["error_msg_index"],
            }
    
    # Get sessions to fix
    sessions_to_fix = []
    
    if target == "--all":
        sessions_to_fix = [(sid, info["error_msg_index"]) for sid, info in sessions_info.items()]
        print(f"\nFixing all {len(sessions_to_fix)} corrupted session(s)...")
    else:
        # Check if target is a session ID
        for sid, info in sessions_info.items():
            if sid == target or target in sid:
                sessions_to_fix.append((sid, info["error_msg_index"]))
                break
        
        if not sessions_to_fix:
            # Check if target is a message ID
            for msg in corrupted:
                if msg["message_id"] == target or target in msg["message_id"]:
                    sessions_to_fix.append((msg["session_id"], msg["error_msg_index"]))
                    break
        
        if not sessions_to_fix:
            print(f"Error: No corrupted session or message found matching '{target}'")
            print("\nAvailable corrupted sessions:")
            for sid, info in sessions_info.items():
                print(f"  - {sid} ({info['title']})")
            return
    
    if dry_run:
        print("\n[DRY RUN] No changes will be made.\n")
    
    for session_id, error_msg_index in sessions_to_fix:
        title = get_session_title(session_id)
        print(f"\nProcessing session: {title}")
        print(f"  Session ID: {session_id}")
        
        result = fix_session(session_id, error_msg_index, dry_run=dry_run)
        
        if result["success"]:
            print(f"  Status: {'WOULD SUCCEED' if dry_run else 'SUCCESS'}")
            print(f"  Messages removed: {len(result['messages_removed'])}")
            for mid in result['messages_removed']:
                print(f"    - {mid}")
            print(f"  Parts removed: {result['parts_removed']}")
            if result["backup_path"]:
                print(f"  Backup saved to: {result['backup_path']}")
        else:
            print(f"  Status: FAILED")
            print(f"  Error: {result['error']}")
    
    if not dry_run:
        print("\n" + "=" * 60)
        print("Repair complete!")
        print("Please restart OpenCode to see the changes.")
        print("=" * 60)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "list":
        list_corrupted()
    
    elif command == "fix":
        if len(sys.argv) < 3:
            print("Error: Please specify a session/message ID or --all")
            print("\nUsage:")
            print("  python session-repair.py fix <session_id>")
            print("  python session-repair.py fix <message_id>")
            print("  python session-repair.py fix --all")
            print("  python session-repair.py fix --all --dry-run")
            sys.exit(1)
        
        target = sys.argv[2]
        dry_run = "--dry-run" in sys.argv
        
        fix_command(target, dry_run=dry_run)
    
    elif command == "help" or command == "--help" or command == "-h":
        print(__doc__)
    
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
