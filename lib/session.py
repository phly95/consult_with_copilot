"""Session management for persistent Copilot conversations."""

import json
import time
from pathlib import Path

SESSIONS_DIR = Path(__file__).parent.parent / "sessions"


class SessionManager:
    """Manages persistent session metadata for follow-up conversations."""

    def __init__(self, sessions_dir=None):
        self.sessions_dir = Path(sessions_dir) if sessions_dir else SESSIONS_DIR
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id):
        return self.sessions_dir / f"{session_id}.json"

    def create(self, session_id, conversation_url=None, model=None):
        """Create a new session record."""
        data = {
            "id": session_id,
            "created": time.time(),
            "conversation_url": conversation_url,
            "model": model or "GPT 5.6 Think deeper",
            "messages": [],
        }
        self._session_path(session_id).write_text(json.dumps(data, indent=2))
        return data

    def get(self, session_id):
        """Load a session record."""
        path = self._session_path(session_id)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def update(self, session_id, **kwargs):
        """Update a session record."""
        data = self.get(session_id)
        if data is None:
            raise FileNotFoundError(f"Session {session_id} not found")
        data.update(kwargs)
        self._session_path(session_id).write_text(json.dumps(data, indent=2))
        return data

    def add_message(self, session_id, role, text):
        """Append a message to the session history."""
        data = self.get(session_id)
        if data is None:
            raise FileNotFoundError(f"Session {session_id} not found")
        data["messages"].append({
            "role": role,
            "text": text,
            "timestamp": time.time(),
        })
        self._session_path(session_id).write_text(json.dumps(data, indent=2))

    def list_sessions(self):
        """List all session IDs with metadata."""
        sessions = []
        for path in sorted(self.sessions_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            data = json.loads(path.read_text())
            sessions.append({
                "id": data["id"],
                "created": data.get("created"),
                "model": data.get("model"),
                "messages": len(data.get("messages", [])),
            })
        return sessions

    def delete(self, session_id):
        """Delete a session."""
        path = self._session_path(session_id)
        if path.exists():
            path.unlink()
