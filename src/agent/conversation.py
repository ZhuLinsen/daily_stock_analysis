# -*- coding: utf-8 -*-
"""
Conversation Manager for Agent multi-turn chat.

Manages conversation sessions with TTL, storing message history and context.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.storage import get_db

logger = logging.getLogger(__name__)

@dataclass
class ConversationSession:
    """A single multi-turn conversation session."""
    session_id: str
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)

    def add_message(self, role: str, content: str):
        """Add a message to the session history."""
        get_db().save_conversation_message(self.session_id, role, content)
        self.last_active = datetime.now()

    def update_context(self, key: str, value: Any):
        """Update session context."""
        self.context[key] = value
        self.last_active = datetime.now()

    def get_history(self) -> List[Dict[str, Any]]:
        """Get message history."""
        messages = get_db().get_conversation_history(self.session_id)
        return messages

class ConversationManager:
    """Manages multiple conversation sessions with TTL."""
    
    def __init__(self, ttl_minutes: int = 30):
        self._sessions: Dict[str, ConversationSession] = {}
        self.ttl = timedelta(minutes=ttl_minutes)

    def get_or_create(self, session_id: str) -> ConversationSession:
        """Get an existing session or create a new one."""
        self._cleanup_expired()
        
        if session_id not in self._sessions:
            self._sessions[session_id] = ConversationSession(session_id=session_id)
            logger.info(f"Created new conversation session: {session_id}")
        else:
            # Update last active time
            self._sessions[session_id].last_active = datetime.now()
            
        return self._sessions[session_id]

    def add_message(self, session_id: str, role: str, content: str):
        """Add a message to a session."""
        session = self.get_or_create(session_id)
        session.add_message(role, content)

    def get_history(self, session_id: str) -> List[Dict[str, Any]]:
        """Get message history for a session."""
        session = self.get_or_create(session_id)
        return session.get_history()

    def clear(self, session_id: str):
        """Clear a session."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"Cleared conversation session: {session_id}")
        # We don't delete from DB here to keep history, or we could add a delete method.
        # For now, just clear from memory.

    def _cleanup_expired(self):
        """Remove expired sessions."""
        now = datetime.now()
        expired = [
            sid for sid, session in self._sessions.items()
            if now - session.last_active > self.ttl
        ]
        for sid in expired:
            del self._sessions[sid]
            logger.info(f"Cleaned up expired conversation session: {sid}")

# Global instance
conversation_manager = ConversationManager()
