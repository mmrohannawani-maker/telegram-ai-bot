# gmail_imap.py - FIXED UID TRACKING
import asyncio
import imaplib
import email
import json
import os
import time
from email.header import decode_header
from datetime import datetime
import re
import logging

logger = logging.getLogger(__name__)

class GmailIMAPWatcher:
    """Gmail watcher with proper UID tracking"""
    
    def __init__(self, email_address: str, app_password: str):
        self.email = email_address
        self.password = app_password
        self.running = False
        self.imap = None
        self.start_uid = None  # UID when monitoring started
        self.last_notified_uid = None  # Last UID we notified about
        self.state_file = "gmail_state.json"
        
    def _get_state(self):
        """Get state from file"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    return json.load(f)
        except:
            pass
        return {}
    
    def _save_state(self, start_uid=None, last_notified_uid=None):
        """Save state to file"""
        try:
            state = self._get_state()
            if start_uid is not None:
                state['start_uid'] = start_uid
            if last_notified_uid is not None:
                state['last_notified_uid'] = last_notified_uid
            
            with open(self.state_file, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            logger.error(f"Error saving state: {e}")
    
    def connect(self) -> bool:
        """Connect to Gmail IMAP server"""
        try:
            logger.info(f"🔗 Connecting to Gmail: {self.email}")
            self.imap = imaplib.IMAP4_SSL('imap.gmail.com', 993, timeout=15)
            self.imap.login(self.email, self.password)
            self.imap.select('INBOX')
            
            # Get current highest UID to establish baseline
            result, data = self.imap.uid('search', None, 'ALL')
            if result == 'OK' and data[0]:
                uids = data[0].split()
                if uids:
                    current_max_uid = int(uids[-1])
                    
                    # If we haven't set start_uid yet (first run), set it to current max
                    if self.start_uid is None:
                        self.start_uid = current_max_uid
                        self._save_state(start_uid=self.start_uid)
                        logger.info(f"📧 Monitoring STARTED at UID: {self.start_uid}")
                    
                    # Load last notified UID from state
                    state = self._get_state()
                    self.last_notified_uid = state.get('last_notified_uid', self.start_uid)
                    
                    logger.info(f"📊 UID Status: Start={self.start_uid}, Last Notified={self.last_notified_uid}, Current={current_max_uid}")
            
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
            
            return {
                'from': from_header,
                'sender_email': sender_email,
                'subject': subject,
                'preview': body_preview,
                'date': date_header,
                'has_attachments': has_attachments
            }
            
        except Exception as e:
            logger.error(f"Error parsing email: {e}")
            return None
    
    def get_new_emails_since_last_notified(self):
        """Get emails with UID > last_notified_uid"""
        if not self.imap or self.last_notified_uid is None:
            return []
        
        try:
            # Search for emails with UID greater than last_notified_uid
            search_criteria = f"UID {self.last_notified_uid + 1}:*"
            result, data = self.imap.uid('search', None, search_criteria)
            
            if result != 'OK' or not data[0]:
                return []
            
            new_uids = data[0].split()
            if not new_uids:
                return []
            
            new_emails = []
            
            # Process all new emails
            for uid_bytes in new_uids:
                try:
                    uid = int(uid_bytes.decode())
                    
                    # Skip emails that arrived before monitoring started
                    if uid <= self.start_uid:
                        continue
                    
                    # Fetch the email
                    result, msg_data = self.imap.uid('fetch', uid_bytes, '(RFC822)')
                    if result != 'OK' or not msg_data:
                        continue
                    
                    # Parse the email
                    if isinstance(msg_data[0], tuple) and len(msg_data[0]) > 1:
                        email_bytes = msg_data[0][1]
                    else:
                        continue
                    
                    email_data = self.parse_email_data(email_bytes)
                    if email_data:
                        email_data['uid'] = uid
                        new_emails.append(email_data)
                        
                except Exception as e:
                    logger.error(f"Error processing email: {e}")
                    continue
            
            # Update last_notified_uid if we found new emails
            if new_emails:
                latest_uid = max(email['uid'] for email in new_emails)
                self.last_notified_uid = latest_uid
                self._save_state(last_notified_uid=self.last_notified_uid)
                logger.info(f"📬 Updated last notified UID to: {self.last_notified_uid}")
            
            return new_emails
            
        except Exception as e:
            logger.error(f"Error checking new emails: {e}")
            return []
    
    def get_recent_unread_emails(self, max_results: int = 5):
        """Get recent unread emails for manual check"""
        try:
            if not self.imap:
                return []
            
            # Search for unread emails
            result, data = self.imap.search(None, 'UNSEEN')
            if result != 'OK' or not data[0]:
                return []
            
            uids = data[0].split()[-max_results:]
            
            emails = []
            for uid in uids:
                try:
                    result, msg_data = self.imap.fetch(uid, '(RFC822)')
                    if result == 'OK' and msg_data and isinstance(msg_data[0], tuple):
                        email_bytes = msg_data[0][1]
                        email_data = self.parse_email_data(email_bytes)
                        if email_data:
                            # Get UID for this email
                            result, uid_data = self.imap.fetch(uid, '(UID)')
                            if result == 'OK' and uid_data:
                                # Extract UID from response
                                uid_response = uid_data[0].decode()
                                if 'UID' in uid_response:
                                    email_uid = int(uid_response.split()[-1].strip(')'))
                                    email_data['uid'] = email_uid
                            emails.append(email_data)
                except Exception as e:
                    logger.error(f"Error fetching email: {e}")
            
            return emails
            
        except Exception as e:
            logger.error(f"Error getting unread emails: {e}")
            return []
    
    async def monitor_loop(self, callback_func, check_interval: int = 20):
        """Monitor loop with proper UID tracking"""
        self.running = True
        
        # Load state
        state = self._get_state()
        self.start_uid = state.get('start_uid')
        self.last_notified_uid = state.get('last_notified_uid')
        
        # Connect to Gmail
        if not self.connect():
            return False
        
        logger.info(f"🚀 Starting monitoring with UID tracking")
        logger.info(f"📧 Start UID: {self.start_uid}, Last Notified: {self.last_notified_uid}")
        
        consecutive_errors = 0
        max_errors = 5
        
        while self.running and consecutive_errors < max_errors:
            try:
                # Get emails since last notified UID
                new_emails = self.get_new_emails_since_last_notified()
                
                if new_emails:
                    logger.info(f"📨 Found {len(new_emails)} new email(s) to notify")
                    
                    # Process each new email
                    for email_data in new_emails:
                        logger.info(f"  • UID {email_data['uid']}: {email_data['subject'][:50]}...")
                        try:
                            await callback_func(email_data)
                        except Exception as e:
                            logger.error(f"Callback error: {e}")
                else:
                    # No new emails - normal case
                    pass
                
                # Send NOOP to keep connection alive
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
                    # Wait longer between retries
                    wait_time = min(30, 5 * consecutive_errors)
                    logger.warning(f"Waiting {wait_time}s before retry...")
                    await asyncio.sleep(wait_time)
                    
                    # Try to reconnect
                    self.disconnect()
                    if not self.connect():
                        break
        
        self.disconnect()
        return True
    
    def reset_monitoring(self):
        """Reset monitoring to start from current UID"""
        try:
            if self.connect():
                result, data = self.imap.uid('search', None, 'ALL')
                if result == 'OK' and data[0]:
                    uids = data[0].split()
                    if uids:
                        current_max_uid = int(uids[-1])
                        self.start_uid = current_max_uid
                        self.last_notified_uid = current_max_uid
                        self._save_state(
                            start_uid=self.start_uid,
                            last_notified_uid=self.last_notified_uid
                        )
                        logger.info(f"🔄 Reset monitoring to UID: {current_max_uid}")
                        return True
        except Exception as e:
            logger.error(f"Error resetting monitoring: {e}")
        
        return False