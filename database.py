import os
import logging
import json
from typing import List, Dict, Any, Tuple
import time

logger = logging.getLogger(__name__)

class MemoryDatabase:
    """Database with SQLite for local, PostgreSQL for production"""
    
    def __init__(self, db_path: str = None):
        self.conn = None
        self.is_sqlite = True  # Default to SQLite for local
        self._init_connection(db_path)
        self._create_tables()
        logger.info("Database initialized")
    
    def _init_connection(self, db_path: str = None):
        """Initialize connection - SQLite for local, PostgreSQL for Railway"""
        database_url = os.getenv("DATABASE_URL")
        
        # If DATABASE_URL exists, try PostgreSQL (Railway production)
        if database_url and database_url.startswith("postgresql://"):
            try:
                # Try to import PostgreSQL libraries
                import psycopg2
                from psycopg2.extras import RealDictCursor
                from urllib.parse import urlparse
                
                result = urlparse(database_url)
                self.conn = psycopg2.connect(
                    database=result.path[1:],
                    user=result.username,
                    password=result.password,
                    host=result.hostname,
                    port=result.port,
                    cursor_factory=RealDictCursor,
                    connect_timeout=10
                )
                self.is_sqlite = False
                logger.info("✅ Connected to PostgreSQL (Railway)")
                return
                
            except ImportError:
                logger.warning("⚠️ psycopg2 not installed, falling back to SQLite")
            except Exception as e:
                logger.error(f"⚠️ PostgreSQL connection failed: {e}, falling back to SQLite")
        
        # Fallback to SQLite (local development)
        import sqlite3
        db_path = db_path or "bot_memory.db"
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Make it behave like psycopg2
        self.is_sqlite = True
        logger.info(f"✅ Using SQLite database: {db_path}")
    
    def _create_tables(self):
        """Create tables compatible with both SQLite and PostgreSQL"""
        cursor = self.conn.cursor()
        
        # SQL dialect differences
        if self.is_sqlite:
            # SQLite syntax
            create_users_sql = '''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
            '''
            create_history_sql = '''
            CREATE TABLE IF NOT EXISTS message_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                role TEXT,
                content TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            '''
            create_conversations_sql = '''
            CREATE TABLE IF NOT EXISTS user_conversations (
                user_id TEXT PRIMARY KEY,
                recent_messages TEXT DEFAULT '[]',
                summary TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            '''
        else:
            # PostgreSQL syntax
            create_users_sql = '''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )
            '''
            create_history_sql = '''
            CREATE TABLE IF NOT EXISTS message_history (
                id SERIAL PRIMARY KEY,
                user_id TEXT,
                role TEXT,
                content TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            '''
            create_conversations_sql = '''
            CREATE TABLE IF NOT EXISTS user_conversations (
                user_id TEXT PRIMARY KEY,
                recent_messages TEXT DEFAULT '[]',
                summary TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            '''
        
        # Execute table creation
        tables = [
            ("users", create_users_sql),
            ("message_history", create_history_sql),
            ("user_conversations", create_conversations_sql)
        ]
        
        for table_name, sql in tables:
            try:
                cursor.execute(sql)
                logger.debug(f"Table {table_name} verified/created")
            except Exception as e:
                logger.error(f"Error creating table {table_name}: {e}")
        
        self.conn.commit()
        logger.info("Database tables verified/created")
    
    def _execute(self, query: str, params: tuple = None):
        """Execute query with SQL dialect handling"""
        cursor = self.conn.cursor()
        try:
            # Handle SQL dialect differences
            if self.is_sqlite:
                # SQLite uses ? placeholders
                query = query.replace("%s", "?")
            
            cursor.execute(query, params or ())
            return cursor
        except Exception as e:
            logger.error(f"Query error: {e}")
            raise
    
    # ========== EXISTING MEMORY METHODS ==========
    
    def save_user_memory(self, user_id: str, recent_messages: List[Dict], summary: str) -> bool:
        try:
            self._execute('''
                INSERT INTO user_conversations (user_id, recent_messages, summary)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) 
                DO UPDATE SET 
                    recent_messages = EXCLUDED.recent_messages,
                    summary = EXCLUDED.summary,
                    updated_at = CURRENT_TIMESTAMP
            ''', (user_id, json.dumps(recent_messages), summary))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error saving memory: {e}")
            return False
    
    def load_user_memory(self, user_id: str) -> Tuple[List[Dict], str]:
        try:
            cursor = self._execute('''
                SELECT recent_messages, summary 
                FROM user_conversations 
                WHERE user_id = %s
            ''', (user_id,))
            
            row = cursor.fetchone()
            if row:
                # Handle both SQLite Row and PostgreSQL Dict
                recent_messages = json.loads(row[0] if self.is_sqlite else row['recent_messages'])
                summary = row[1] if self.is_sqlite else row['summary']
                return recent_messages, summary
            return [], ""
        except Exception as e:
            logger.error(f"Error loading memory: {e}")
            return [], ""
    
    # ========== PROACTIVE NOTIFICATION METHODS ==========
    
    def save_user_for_notifications(self, user_id: str, username: str = None, first_name: str = None) -> bool:
        """Save user for proactive notifications"""
        try:
            if self.is_sqlite:
                # SQLite syntax
                self._execute('''
                    INSERT OR REPLACE INTO users (user_id, username, first_name, last_interaction, is_active)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP, 1)
                ''', (user_id, username, first_name))
            else:
                # PostgreSQL syntax
                self._execute('''
                    INSERT INTO users (user_id, username, first_name, last_interaction)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id) 
                    DO UPDATE SET 
                        username = EXCLUDED.username,
                        first_name = EXCLUDED.first_name,
                        last_interaction = CURRENT_TIMESTAMP,
                        is_active = TRUE
                ''', (user_id, username, first_name))
            
            self.conn.commit()
            logger.info(f"✅ Saved user {user_id} for notifications")
            return True
        except Exception as e:
            logger.error(f"❌ Error saving user: {e}")
            return False
    
    def get_all_users_for_notifications(self) -> List[str]:
        """Get all active user IDs for notifications"""
        try:
            cursor = self._execute('''
                SELECT user_id FROM users 
                WHERE is_active = TRUE 
                ORDER BY last_interaction DESC
            ''')
            
            if self.is_sqlite:
                rows = cursor.fetchall()
                return [row[0] for row in rows]
            else:
                rows = cursor.fetchall()
                return [row['user_id'] for row in rows]
                
        except Exception as e:
            logger.error(f"Error getting users: {e}")
            return []
    
    def update_user_interaction(self, user_id: str) -> bool:
        try:
            cursor = self._execute('''
                UPDATE users 
                SET last_interaction = CURRENT_TIMESTAMP 
                WHERE user_id = %s
            ''', (user_id,))
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating interaction: {e}")
            return False
    
    def get_user_count(self) -> int:
        try:
            cursor = self._execute('SELECT COUNT(*) as count FROM users WHERE is_active = TRUE')
            row = cursor.fetchone()
            return row[0] if self.is_sqlite else row['count']
        except Exception as e:
            logger.error(f"Error counting users: {e}")
            return 0
    
    def migrate_existing_users(self) -> int:
        """Migrate existing users from message_history to users table"""
        try:
            # Get all unique users from message_history
            cursor = self._execute('SELECT DISTINCT user_id FROM message_history')
            
            if self.is_sqlite:
                existing_users = [row[0] for row in cursor.fetchall()]
            else:
                existing_users = [row['user_id'] for row in cursor.fetchall()]
            
            migrated = 0
            for user_id in existing_users:
                try:
                    if self.is_sqlite:
                        self._execute('''
                            INSERT OR IGNORE INTO users (user_id, last_interaction, is_active)
                            VALUES (?, CURRENT_TIMESTAMP, 1)
                        ''', (user_id,))
                    else:
                        self._execute('''
                            INSERT INTO users (user_id, last_interaction)
                            VALUES (%s, CURRENT_TIMESTAMP)
                            ON CONFLICT (user_id) DO NOTHING
                        ''', (user_id,))
                    migrated += 1
                except:
                    continue
            
            self.conn.commit()
            logger.info(f"✅ Migrated {migrated} existing users")
            return migrated
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            return 0
    
    # ========== EXISTING METHODS (KEEP THESE) ==========
    
    def add_message_to_history(self, user_id: str, role: str, content: str) -> bool:
        """Add single message to history"""
        try:
            self._execute('''
                INSERT INTO message_history (user_id, role, content)
                VALUES (%s, %s, %s)
            ''', (user_id, role, content))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error saving message: {e}")
            return False
    
    def get_recent_messages(self, user_id: str, limit: int = 10) -> List[Dict]:
        """Get recent messages"""
        try:
            cursor = self._execute('''
                SELECT role, content 
                FROM message_history 
                WHERE user_id = %s 
                ORDER BY timestamp DESC 
                LIMIT %s
            ''', (user_id, limit))
            
            messages = []
            rows = cursor.fetchall()
            
            for row in rows:
                if self.is_sqlite:
                    messages.append({"role": row[0], "content": row[1]})
                else:
                    messages.append({"role": row['role'], "content": row['content']})
            
            return messages[::-1]
        except Exception as e:
            logger.error(f"Error getting messages: {e}")
            return []
    
    def delete_user_memory(self, user_id: str) -> bool:
        """Delete all memory for user"""
        try:
            self._execute('DELETE FROM user_conversations WHERE user_id = %s', (user_id,))
            self._execute('DELETE FROM message_history WHERE user_id = %s', (user_id,))
            self._execute('UPDATE users SET is_active = FALSE WHERE user_id = %s', (user_id,))
            self.conn.commit()
            logger.info(f"Deleted memory for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting memory: {e}")
            return False
    
    def get_all_users(self) -> List[str]:
        """Get all user IDs in database"""
        try:
            cursor = self._execute('SELECT DISTINCT user_id FROM message_history')
            if self.is_sqlite:
                return [row[0] for row in cursor.fetchall()]
            else:
                return [row['user_id'] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting users: {e}")
            return []
    
    def get_database_stats(self) -> Dict[str, Any]:
        """Get overall database statistics"""
        try:
            stats = {}
            
            # Count distinct users from message_history
            cursor = self._execute('SELECT COUNT(DISTINCT user_id) as count FROM message_history')
            row = cursor.fetchone()
            stats["total_users"] = row[0] if self.is_sqlite else row['count']
            
            # Count total messages
            cursor = self._execute('SELECT COUNT(*) as count FROM message_history')
            row = cursor.fetchone()
            stats["total_messages"] = row[0] if self.is_sqlite else row['count']
            
            # Count users in notifications table
            cursor = self._execute('SELECT COUNT(*) as count FROM users WHERE is_active = TRUE')
            row = cursor.fetchone()
            stats["notification_users"] = row[0] if self.is_sqlite else row['count']
            
            stats["database_type"] = "SQLite" if self.is_sqlite else "PostgreSQL"
            stats["database_file"] = "bot_memory.db" if self.is_sqlite else "Railway PostgreSQL"
            
            return stats
        except Exception as e:
            logger.error(f"Error getting database stats: {e}")
            return {}
        

    
    def create_gmail_tracking_table(self):
        """Create table to track sent emails"""
        if self.db_type == "sqlite":
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS gmail_tracking (
                    email_id TEXT PRIMARY KEY,
                    sender_email TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_id TEXT NOT NULL
                )
            ''')
        else:  # PostgreSQL
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS gmail_tracking (
                    email_id TEXT PRIMARY KEY,
                    sender_email TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_id TEXT NOT NULL
                )
            ''')
        self.conn.commit()
        print("✅ Gmail tracking table created")
    
    def is_email_already_sent(self, email_id: str, user_id: str) -> bool:
        """Check if email has already been sent to user"""
        self.cursor.execute(
            "SELECT 1 FROM gmail_tracking WHERE email_id = ? AND user_id = ?",
            (email_id, user_id)
        )
        return self.cursor.fetchone() is not None
    
    def mark_email_as_sent(self, email_id: str, sender_email: str, subject: str, user_id: str):
        """Mark email as sent to user"""
        try:
            self.cursor.execute(
                '''INSERT INTO gmail_tracking 
                   (email_id, sender_email, subject, user_id) 
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT (email_id) DO NOTHING''',
                (email_id, sender_email, subject, user_id)
            )
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error marking email as sent: {e}")
            return False
    
    def get_last_email_time(self, user_id: str):
        """Get time of last email sent to user"""
        self.cursor.execute(
            "SELECT MAX(notified_at) FROM gmail_tracking WHERE user_id = ?",
            (user_id,)
        )
        result = self.cursor.fetchone()
        return result[0] if result and result[0] else None
    
    def get_email_count_for_user(self, user_id: str) -> int:
        """Get count of emails sent to user"""
        self.cursor.execute(
            "SELECT COUNT(*) FROM gmail_tracking WHERE user_id = ?",
            (user_id,)
        )
        result = self.cursor.fetchone()
        return result[0] if result else 0
    
    def cleanup_old_email_records(self, days: int = 30):
        """Cleanup old email records"""
        try:
            if self.db_type == "sqlite":
                self.cursor.execute(
                    "DELETE FROM gmail_tracking WHERE notified_at < datetime('now', ?)",
                    (f'-{days} days',)
                )
            else:  # PostgreSQL
                self.cursor.execute(
                    "DELETE FROM gmail_tracking WHERE notified_at < NOW() - INTERVAL '%s days'",
                    (days,)
                )
            self.conn.commit()
            deleted = self.cursor.rowcount
            print(f"🧹 Cleaned up {deleted} old email records")
            return deleted
        except Exception as e:
            print(f"Error cleaning up email records: {e}")
            return 0
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
    
    def __del__(self):
        """Destructor to ensure connection is closed"""
        self.close()