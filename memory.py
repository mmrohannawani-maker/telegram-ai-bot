# memory.py
import logging
from typing import List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class PersistentHybridMemory:
    """Hybrid memory with database persistence"""
    
    def __init__(self, user_id: str, db, buffer_size: int = 3):
        """Initialize memory with database connection"""
        if db is None:
            raise ValueError("Database connection required")
        
        self.user_id = user_id
        self.db = db
        self.buffer_size = buffer_size
        
        # Load from database
        self.recent_messages, self.summary = self.db.load_user_memory(user_id)
        logger.info(f"Memory loaded for {user_id}: {len(self.recent_messages)} recent, summary: {bool(self.summary)}")
    
    def add_conversation(self, user_input: str, ai_response: str):
        """Add conversation and auto-save to DB"""
        # Add to recent buffer
        self.recent_messages.append({
            "user": user_input,
            "ai": ai_response,
            "timestamp": self._get_timestamp()
        })
        
        # Keep buffer size
        if len(self.recent_messages) > self.buffer_size:
            removed = self.recent_messages.pop(0)
            self._update_summary(removed)
        
        # Save to history table
        self.db.add_message_to_history(self.user_id, "user", user_input)
        self.db.add_message_to_history(self.user_id, "assistant", ai_response)
        
        # Save to memory table
        self._save_to_db()
    
    def _update_summary(self, old_message: Dict):
        """Update summary with old message"""
        if not self.summary:
            self.summary = f"Previously: {old_message['user'][:50]}..."
        elif len(self.summary) < 500:  # Limit summary length
            self.summary = f"{self.summary}; Also: {old_message['user'][:30]}..."
    
    def _save_to_db(self):
        """Save current state to database"""
        self.db.save_user_memory(self.user_id, self.recent_messages, self.summary)
    
    def _get_timestamp(self):
        """Get current timestamp"""
        return datetime.now().isoformat()
    
    def get_context(self) -> str:
        """Get memory context for prompt"""
        if not self.recent_messages:
            return "No previous conversation."
        
        recent_context = ""
        for msg in self.recent_messages[-self.buffer_size:]:
            recent_context += f"Human: {msg['user']}\nAI: {msg['ai']}\n"
        
        if self.summary:
            return f"Previous conversation summary: {self.summary}\n\nRecent conversation:\n{recent_context}"
        else:
            return f"Recent conversation:\n{recent_context}"
    
    def clear(self):
        """Clear memory and delete from DB"""
        self.recent_messages = []
        self.summary = ""
        self.db.delete_user_memory(self.user_id)
        logger.info(f"Memory cleared for {self.user_id}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics"""
        db_stats = self.db.get_user_stats(self.user_id)
        
        return {
            "buffer_entries": len(self.recent_messages),
            "buffer_size": self.buffer_size,
            "summary_length": len(self.summary),
            "has_summary": bool(self.summary),
            **db_stats
        }