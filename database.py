import sqlite3
import json
import logging
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)

class MemoryDatabase:
    """Simple database for storing conversation memory"""
    
    def __init__(self, db_path: str = "bot_memory.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._create_tables()
        logger.info(f"Database initialized: {self.db_path}")
    
    def _create_tables(self):
        """Create database tables"""
        cursor = self.conn.cursor()
        
        # User memory table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_conversations (
            user_id TEXT PRIMARY KEY,
            recent_messages TEXT DEFAULT '[]',
            summary TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Message history table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS message_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            role TEXT,
            content TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        self.conn.commit()
        logger.info("Database tables created/verified")
    
    def save_user_memory(self, user_id: str, recent_messages: List[Dict], summary: str) -> bool:
        """Save user memory to database"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO user_conversations 
                (user_id, recent_messages, summary, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ''', (user_id, json.dumps(recent_messages), summary))
            self.conn.commit()
            logger.info(f"Saved memory for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error saving memory: {e}")
            return False
    
    def load_user_memory(self, user_id: str) -> Tuple[List[Dict], str]:
        """Load user memory from database"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT recent_messages, summary 
                FROM user_conversations 
                WHERE user_id = ?
            ''', (user_id,))
            
            row = cursor.fetchone()
            if row:
                recent_messages = json.loads(row[0]) if row[0] else []
                summary = row[1] if row[1] else ""
                logger.debug(f"Loaded memory for user {user_id}")
                return recent_messages, summary
            return [], ""
        except Exception as e:
            logger.error(f"Error loading memory: {e}")
            return [], ""
    
    def add_message_to_history(self, user_id: str, role: str, content: str) -> bool:
        """Add single message to history"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO message_history (user_id, role, content)
                VALUES (?, ?, ?)
            ''', (user_id, role, content))
            self.conn.commit()
            logger.debug(f"Added message to history for {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error saving message: {e}")
            return False
    
    def get_recent_messages(self, user_id: str, limit: int = 10) -> List[Dict]:
        """Get recent messages"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT role, content 
                FROM message_history 
                WHERE user_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (user_id, limit))
            
            messages = []
            for row in cursor.fetchall():
                messages.append({"role": row[0], "content": row[1]})
            
            return messages[::-1]
        except Exception as e:
            logger.error(f"Error getting messages: {e}")
            return []
    
    def delete_user_memory(self, user_id: str) -> bool:
        """Delete all memory for user"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('DELETE FROM user_conversations WHERE user_id = ?', (user_id,))
            cursor.execute('DELETE FROM message_history WHERE user_id = ?', (user_id,))
            self.conn.commit()
            logger.info(f"Deleted memory for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting memory: {e}")
            return False
    
    def get_user_stats(self, user_id: str) -> Dict[str, Any]:
        """Get user statistics"""
        try:
            cursor = self.conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM message_history WHERE user_id = ?', (user_id,))
            total_messages = cursor.fetchone()[0]
            
            cursor.execute('SELECT MAX(timestamp) FROM message_history WHERE user_id = ?', (user_id,))
            last_active = cursor.fetchone()[0]
            
            return {
                "total_messages": total_messages,
                "last_active": last_active or "Never",
                "has_memory": self.load_user_memory(user_id)[0] != []
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}
    
    def get_all_users(self) -> List[str]:
        """Get all user IDs in database"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT DISTINCT user_id FROM message_history')
            return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting users: {e}")
            return []
    
    def get_database_stats(self) -> Dict[str, Any]:
        """Get overall database statistics"""
        try:
            cursor = self.conn.cursor()
            
            cursor.execute('SELECT COUNT(DISTINCT user_id) FROM message_history')
            total_users = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM message_history')
            total_messages = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM user_conversations')
            total_memories = cursor.fetchone()[0]
            
            return {
                "total_users": total_users,
                "total_messages": total_messages,
                "total_memories": total_memories,
                "database_file": self.db_path
            }
        except Exception as e:
            logger.error(f"Error getting database stats: {e}")
            return {}
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
    
    def __del__(self):
        """Destructor to ensure connection is closed"""
        self.close()