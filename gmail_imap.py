# gmail_imap.py - DATABASE-BASED TRACKING
import asyncio
import imaplib
import email
import hashlib
import time
from email.header import decode_header
from datetime import datetime
import re
import logging

logger = logging.getLogger(__name__)

class GmailIMAPWatcher:
    """Gmail watcher with database tracking"""
    
    def __init__(self, email_address: str, app_password: str, db, user_id: str):
        self.email = email_address
        self.password = app_password
        self.db = db
        self.user_id = user_id
        self.running = False
        self.imap = None
        
    def generate_email_id(self, email_data: dict) -> str:
        """Generate unique ID for email based on content"""
        # Create a hash of sender + subject + date to identify unique emails
        content = f"{email_data.get('sender_email', '')}:{email_data.get('subject', '')}:{email_data.get('date', '')}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def connect(self) -> bool:
        """Connect to Gmail IMAP server"""
        try:
            logger.info(f"🔗 Connecting to Gmail: {self.email}")
            self.imap = imaplib.IMAP4_SSL('imap.gmail.com', 993, timeout=15)
            self.imap.login(self.email, self.password)
            self.imap.select('INBOX')
            logger.info("✅ Gmail connected successfully")
            return True
        except Exception as e:
            logger.error(f"❌ Gmail connection failed: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from Gmail"""
        self.running = False
        if self.imap:
            try:
                self.imap.logout()
                logger.info("✅ Gmail disconnected")
            except Exception:
                pass
            self.imap = None
    
    def parse_email_data(self, email_bytes: bytes) -> dict:
        """Parse email data from raw bytes"""
        try:
            msg = email.message_from_bytes(email_bytes)
            
            # Get sender
            from_header = msg.get("From", "Unknown")
            sender_email = from_header
            
            # Extract email address
            if '<' in from_header and '>' in from_header:
                match = re.search(r'<([^>]+)>', from_header)
                if match:
                    sender_email = match.group(1)
            
            # Get subject
            subject_header = msg.get("Subject", "No Subject")
            subject, encoding = decode_header(subject_header)[0]
            if isinstance(subject, bytes):
                subject = subject.decode(encoding if encoding else "utf-8")
            
            # Get date
            date_header = msg.get("Date", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            
            # Get body preview
            body_preview = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        try:
                            body = part.get_payload(decode=True)
                            if body:
                                body_preview = body.decode('utf-8', errors='ignore')[:150]
                            break
                        except:
                            continue
            else:
                try:
                    body = msg.get_payload(decode=True)
                    if body:
                        body_preview = body.decode('utf-8', errors='ignore')[:150]
                except:
                    body_preview = ""
            
            # Check for attachments
            has_attachments = False
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_disposition() == 'attachment':
                        has_attachments = True
                        break
            
            email_data = {
                'from': from_header,
                'sender_email': sender_email,
                'subject': subject,
                'preview': body_preview,
                'date': date_header,
                'has_attachments': has_attachments
            }
            
            # Generate unique ID for this email
            email_data['email_id'] = self.generate_email_id(email_data)
            
            return email_data
            
        except Exception as e:
            logger.error(f"Error parsing email: {e}")
            return None
    
    def get_recent_emails(self, max_results: int = 10):
        """Get recent emails (read or unread)"""
        try:
            if not self.imap:
                return []
            
            # Search for ALL recent emails (not just unread)
            result, data = self.imap.search(None, 'ALL')
            if result != 'OK' or not data[0]:
                return []
            
            # Get the most recent emails
            all_uids = data[0].split()
            recent_uids = all_uids[-max_results:] if len(all_uids) > max_results else all_uids
            
            emails = []
            for uid in recent_uids:
                try:
                    result, msg_data = self.imap.fetch(uid, '(RFC822)')
                    if result == 'OK' and msg_data and isinstance(msg_data[0], tuple):
                        email_bytes = msg_data[0][1]
                        email_data = self.parse_email_data(email_bytes)
                        if email_data:
                            emails.append(email_data)
                except Exception as e:
                    logger.error(f"Error fetching email: {e}")
                    continue
            
            return emails
            
        except Exception as e:
            logger.error(f"Error getting recent emails: {e}")
            return []
    
    def get_new_emails_since_last_check(self):
        """Get emails that haven't been sent to user yet"""
        if not self.imap:
            return []
        
        try:
            # Get recent emails
            recent_emails = self.get_recent_emails(max_results=20)
            
            # Filter out emails already sent to this user
            new_emails = []
            for email_data in recent_emails:
                email_id = email_data.get('email_id')
                
                # Check database if this email was already sent to user
                if email_id and not self.db.is_email_already_sent(email_id, self.user_id):
                    new_emails.append(email_data)
            
            return new_emails
            
        except Exception as e:
            logger.error(f"Error checking new emails: {e}")
            return []
    
    async def monitor_with_database(self, callback_func, check_interval: int = 20):
        """Monitor using database for tracking"""
        self.running = True
        
        # Connect to Gmail
        if not self.connect():
            return False
        
        logger.info(f"🚀 Starting database-tracked monitoring for user {self.user_id}")
        logger.info(f"📧 Will check every {check_interval}s for NEW emails")
        
        # Don't notify about existing emails on first run
        logger.info("🔄 Skipping existing emails, only NEW ones will be notified")
        
        consecutive_errors = 0
        max_errors = 5
        
        while self.running and consecutive_errors < max_errors:
            try:
                # Get emails that haven't been sent yet
                new_emails = self.get_new_emails_since_last_check()
                
                if new_emails:
                    logger.info(f"📨 Found {len(new_emails)} new email(s) for user {self.user_id}")
                    
                    # Process each new email
                    for email_data in new_emails:
                        email_id = email_data.get('email_id')
                        sender = email_data.get('sender_email', 'Unknown')
                        subject = email_data.get('subject', 'No Subject')[:50]
                        
                        logger.info(f"  • New email from {sender}: {subject}...")
                        
                        try:
                            # Send notification
                            await callback_func(email_data)
                            
                            # Mark as sent in database (AFTER successful notification)
                            self.db.mark_email_as_sent(
                                email_id=email_id,
                                sender_email=sender,
                                subject=subject,
                                user_id=self.user_id
                            )
                            logger.info(f"  ✅ Marked email {email_id[:8]}... as sent")
                            
                        except Exception as e:
                            logger.error(f"Callback error: {e}")
                else:
                    # No new emails - normal case
                    pass
                
                # Keep connection alive
                if self.imap:
                    self.imap.noop()
                
                # Reset error counter
                consecutive_errors = 0
                
                # Wait for next check
                await asyncio.sleep(check_interval)
                
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Monitoring error #{consecutive_errors}: {e}")
                
                if consecutive_errors < max_errors:
                    # Wait before retry
                    wait_time = min(30, 5 * consecutive_errors)
                    logger.warning(f"Waiting {wait_time}s before retry...")
                    await asyncio.sleep(wait_time)
                    
                    # Try to reconnect
                    self.disconnect()
                    if not self.connect():
                        break
        
        self.disconnect()
        return True