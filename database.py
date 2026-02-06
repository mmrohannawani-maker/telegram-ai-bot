import os
import logging
import json
import sqlite3
from typing import List, Dict, Any, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

class MemoryDatabase:
    """SQLite database for everything (chats + Gmail)"""
    
    def __init__(self, db_path: str = "bot_memory.db"):
        # Always use SQLite
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.db_type = "sqlite"
        
        self._create_tables()
        logger.info(f"✅ SQLite database initialized: {db_path}")
    
    def _create_tables(self):
        """Create all tables for chats + Gmail"""
        
        # Table 1: Users for notifications
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
        ''')
        
        # Table 2: Message history
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS message_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                role TEXT,
                content TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Table 3: User conversations/memory
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_conversations (
                user_id TEXT PRIMARY KEY,
                recent_messages TEXT DEFAULT '[]',
                summary TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Table 4: Gmail tracking (NEW - for email notifications)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS gmail_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id TEXT NOT NULL,
                sender_email TEXT NOT NULL,
                subject TEXT NOT NULL,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id TEXT NOT NULL,
                UNIQUE(email_id, user_id)
            )
        ''')
        
        # Create indexes for better performance
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_gmail_user ON gmail_tracking(user_id)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_gmail_email ON gmail_tracking(email_id)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_history_user ON message_history(user_id)')
        
        self.conn.commit()
        logger.info("✅ All tables created (chats + Gmail)")
    
    # ========== EXISTING CHAT METHODS ==========
    
    def save_user_memory(self, user_id: str, recent_messages: List[Dict], summary: str) -> bool:
        try:
            self.cursor.execute('''
                INSERT OR REPLACE INTO user_conversations 
                (user_id, recent_messages, summary, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ''', (user_id, json.dumps(recent_messages), summary))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error saving memory: {e}")
            return False
    
    def load_user_memory(self, user_id: str) -> Tuple[List[Dict], str]:
        try:
            self.cursor.execute('''
                SELECT recent_messages, summary 
                FROM user_conversations 
                WHERE user_id = ?
            ''', (user_id,))
            
            row = self.cursor.fetchone()
            if row:
                recent_messages = json.loads(row['recent_messages'])
                summary = row['summary']
                return recent_messages, summary
            return [], ""
        except Exception as e:
            logger.error(f"Error loading memory: {e}")
            return [], ""
    
    def save_user_for_notifications(self, user_id: str, username: str = None, first_name: str = None) -> bool:
        """Save user for notifications"""
        try:
            self.cursor.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, username, first_name, last_interaction, is_active)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, 1)
            ''', (user_id, username, first_name))
            self.conn.commit()
            logger.info(f"✅ Saved user {user_id} for notifications")
            return True
        except Exception as e:
            logger.error(f"❌ Error saving user: {e}")
            return False
    
    def get_all_users_for_notifications(self) -> List[str]:
        """Get all active user IDs"""
        try:
            self.cursor.execute('SELECT user_id FROM users WHERE is_active = 1')
            return [row['user_id'] for row in self.cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting users: {e}")
            return []
    
    def update_user_interaction(self, user_id: str) -> bool:
        try:
            self.cursor.execute('''
                UPDATE users 
                SET last_interaction = CURRENT_TIMESTAMP 
                WHERE user_id = ?
            ''', (user_id,))
            self.conn.commit()
            return self.cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating interaction: {e}")
            return False
    
    def add_message_to_history(self, user_id: str, role: str, content: str) -> bool:
        try:
            self.cursor.execute('''
                INSERT INTO message_history (user_id, role, content)
                VALUES (?, ?, ?)
            ''', (user_id, role, content))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error saving message: {e}")
            return False
    
    def get_recent_messages(self, user_id: str, limit: int = 10) -> List[Dict]:
        try:
            self.cursor.execute('''
                SELECT role, content 
                FROM message_history 
                WHERE user_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (user_id, limit))
            
            messages = []
            for row in self.cursor.fetchall():
                messages.append({"role": row['role'], "content": row['content']})
            
            return messages[::-1]
        except Exception as e:
            logger.error(f"Error getting messages: {e}")
            return []
    
    def delete_user_memory(self, user_id: str) -> bool:
        try:
            self.cursor.execute('DELETE FROM user_conversations WHERE user_id = ?', (user_id,))
            self.cursor.execute('DELETE FROM message_history WHERE user_id = ?', (user_id,))
            self.cursor.execute('UPDATE users SET is_active = 0 WHERE user_id = ?', (user_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error deleting memory: {e}")
            return False
    
    def get_database_stats(self) -> Dict[str, Any]:
        try:
            stats = {}
            
            # Total users from history
            self.cursor.execute('SELECT COUNT(DISTINCT user_id) as count FROM message_history')
            stats["total_users"] = self.cursor.fetchone()['count']
            
            # Total messages
            self.cursor.execute('SELECT COUNT(*) as count FROM message_history')
            stats["total_messages"] = self.cursor.fetchone()['count']
            
            # Notification users
            self.cursor.execute('SELECT COUNT(*) as count FROM users WHERE is_active = 1')
            stats["notification_users"] = self.cursor.fetchone()['count']
            
            # Gmail tracking stats
            self.cursor.execute('SELECT COUNT(DISTINCT user_id) as count FROM gmail_tracking')
            stats["gmail_users"] = self.cursor.fetchone()['count']
            
            self.cursor.execute('SELECT COUNT(*) as count FROM gmail_tracking')
            stats["total_emails_tracked"] = self.cursor.fetchone()['count']
            
            stats["database_type"] = "SQLite"
            stats["database_file"] = self.db_path
            
            return stats
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}
    
    # ========== GMAIL TRACKING METHODS ==========
    
    def is_email_already_sent(self, email_id: str, user_id: str) -> bool:
        """Check if email has already been sent to user"""
        try:
            self.cursor.execute(
                "SELECT 1 FROM gmail_tracking WHERE email_id = ? AND user_id = ?",
                (email_id, user_id)
            )
            return self.cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking email: {e}")
            return False
    
    def mark_email_as_sent(self, email_id: str, sender_email: str, subject: str, user_id: str) -> bool:
        """Mark email as sent to user"""
        try:
            self.cursor.execute('''
                INSERT OR IGNORE INTO gmail_tracking 
                (email_id, sender_email, subject, user_id, notified_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (email_id, sender_email, subject, user_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error marking email as sent: {e}")
            return False
    
    def get_last_email_time(self, user_id: str):
        """Get time of last email sent to user"""
        try:
            self.cursor.execute(
                "SELECT MAX(notified_at) FROM gmail_tracking WHERE user_id = ?",
                (user_id,)
            )
            result = self.cursor.fetchone()
            return result[0] if result and result[0] else None
        except Exception as e:
            logger.error(f"Error getting last email time: {e}")
            return None
    
    def get_email_count_for_user(self, user_id: str) -> int:
        """Get count of emails sent to user"""
        try:
            self.cursor.execute(
                "SELECT COUNT(*) FROM gmail_tracking WHERE user_id = ?",
                (user_id,)
            )
            result = self.cursor.fetchone()
            return result[0] if result else 0
        except Exception as e:
            logger.error(f"Error getting email count: {e}")
            return 0
    
    def cleanup_old_email_records(self, days: int = 30) -> int:
        """Cleanup old email records"""
        try:
            self.cursor.execute(
                "DELETE FROM gmail_tracking WHERE notified_at < datetime('now', ?)",
                (f'-{days} days',)
            )
            self.conn.commit()
            deleted = self.cursor.rowcount
            logger.info(f"🧹 Cleaned up {deleted} old email records")
            return deleted
        except Exception as e:
            logger.error(f"Error cleaning up email records: {e}")
            return 0
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
    
    def __del__(self):
        """Destructor to ensure connection is closed"""
        self.close()