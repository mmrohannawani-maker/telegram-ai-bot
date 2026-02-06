# gmail_imap.py - 20-SECOND POLLING (NEW EMAILS ONLY)
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
    """Gmail watcher with 20-second polling for new emails only"""
    
    def __init__(self, email_address: str, app_password: str):
        self.email = email_address
        self.password = app_password
        self.running = False
        self.imap = None
        self.last_uid = None
        self.state_file = "gmail_state.json"
        
    def _get_last_uid(self):
        """Get the last processed UID from file"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    return data.get('last_uid')
        except Exception as e:
            logger.debug(f"Could not read state file: {e}")
        return None
    
    def _save_last_uid(self, uid):
        """Save last processed UID to file"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump({'last_uid': uid}, f)
        except Exception as e:
            logger.error(f"Error saving state file: {e}")
    
    def connect(self) -> bool:
        """Connect to Gmail IMAP server"""
        try:
            logger.info(f"🔗 Connecting to Gmail: {self.email}")
            self.imap = imaplib.IMAP4_SSL('imap.gmail.com', 993, timeout=15)
            self.imap.login(self.email, self.password)
            self.imap.select('INBOX')
            
            # Get current highest UID to establish baseline
            try:
                result, data = self.imap.uid('search', None, 'ALL')
                if result == 'OK' and data[0]:
                    uids = data[0].split()
                    if uids:
                        self.last_uid = int(uids[-1])
                        logger.info(f"📧 Starting UID: {self.last_uid}")
                        self._save_last_uid(self.last_uid)
            except Exception as e:
                logger.warning(f"Could not get baseline UID: {e}")
                self.last_uid = 0
            
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
    
    def check_for_new_emails(self):
        """Check for NEW emails since last UID"""
        if not self.imap or self.last_uid is None:
            return []
        
        try:
            # Search for emails with UID greater than last_uid
            # This ensures we only get NEW emails, not old unread ones
            search_criteria = f"UID {self.last_uid + 1}:*"
            result, data = self.imap.uid('search', None, search_criteria)
            
            if result != 'OK' or not data[0]:
                return []
            
            new_uids = data[0].split()
            if not new_uids:
                return []
            
            new_emails = []
            
            # Process from oldest to newest
            for uid_bytes in new_uids:
                try:
                    uid = uid_bytes.decode()
                    
                    # Fetch the email
                    result, msg_data = self.imap.uid('fetch', uid, '(RFC822)')
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
            
            # Update last_uid to the newest one
            if new_emails and new_uids:
                try:
                    latest_uid = max(int(uid.decode()) for uid in new_uids)
                    self.last_uid = latest_uid
                    self._save_last_uid(self.last_uid)
                    logger.info(f"📬 Updated last UID to: {self.last_uid} ({len(new_emails)} new emails)")
                except Exception as e:
                    logger.error(f"Error updating UID: {e}")
            
            return new_emails
            
        except Exception as e:
            logger.error(f"Error checking new emails: {e}")
            return []
    
    def get_unread_emails(self, max_results: int = 5):
        """Get recent unread emails for manual check"""
        try:
            if not self.imap:
                return []
            
            # Search for unread emails
            result, data = self.imap.search(None, 'UNSEEN')
            if result != 'OK' or not data[0]:
                return []
            
            uids = data[0].split()[-max_results:]  # Get last N emails
            
            emails = []
            for uid in uids:
                try:
                    result, msg_data = self.imap.fetch(uid, '(RFC822)')
                    if result == 'OK' and msg_data and isinstance(msg_data[0], tuple):
                        email_bytes = msg_data[0][1]
                        email_data = self.parse_email_data(email_bytes)
                        if email_data:
                            emails.append(email_data)
                except Exception as e:
                    logger.error(f"Error fetching email: {e}")
            
            return emails
            
        except Exception as e:
            logger.error(f"Error getting unread emails: {e}")
            return []
    
    async def monitor_loop(self, callback_func, check_interval: int = 20):
        """20-second polling loop for NEW emails only"""
        self.running = True
        
        # Load last UID from previous session
        saved_uid = self._get_last_uid()
        if saved_uid:
            try:
                self.last_uid = int(saved_uid)
                logger.info(f"📧 Resuming from UID: {self.last_uid}")
            except:
                self.last_uid = 0
        else:
            self.last_uid = 0
        
        # Connect to Gmail
        if not self.connect():
            return False
        
        logger.info(f"🚀 Starting 20-second polling for NEW emails")
        logger.info(f"📧 Will only notify about emails arriving AFTER this point")
        
        consecutive_errors = 0
        max_errors = 5
        
        while self.running and consecutive_errors < max_errors:
            try:
                # Check for NEW emails (since last UID)
                new_emails = self.check_for_new_emails()
                
                if new_emails:
                    logger.info(f"📨 Found {len(new_emails)} new email(s)")
                    
                    # Process each new email
                    for email_data in new_emails:
                        logger.info(f"  • {email_data['sender_email']}: {email_data['subject'][:50]}...")
                        try:
                            await callback_func(email_data)
                        except Exception as e:
                            logger.error(f"Callback error: {e}")
                else:
                    # No new emails - this is normal, don't log every time
                    pass
                
                # Send NOOP to keep connection alive
                if self.imap:
                    self.imap.noop()
                
                # Reset error counter
                consecutive_errors = 0
                
                # Wait for next check (20 seconds)
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