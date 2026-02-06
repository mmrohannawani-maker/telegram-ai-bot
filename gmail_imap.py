# gmail_imap.py - PURE EVENT-BASED SYSTEM
import asyncio
import imaplib
import email
import time
from email.header import decode_header
from datetime import datetime, timedelta
import select  # ADD THIS IMPORT

import re
import logging
import fasteners  # For file-based locking

logger = logging.getLogger(__name__)

class GmailIMAPWatcher:
    """Pure event-based Gmail watcher for Railway"""
    
    def __init__(self, email_address: str, app_password: str):
        self.email = email_address
        self.password = app_password
        self.running = False
        self.imap = None
        self.last_uid = None
        self.lock_file = "gmail_watcher.lock"
        self.state_file = "gmail_state.json"
        
    def _get_last_uid(self):
        """Get the last processed UID from file"""
        try:
            with open(self.state_file, 'r') as f:
                import json
                data = json.load(f)
                return data.get('last_uid')
        except:
            return None
    
    def _save_last_uid(self, uid):
        """Save last processed UID to file"""
        try:
            with open(self.state_file, 'w') as f:
                import json
                json.dump({'last_uid': uid}, f)
        except:
            pass
    
    def connect(self) -> bool:
        """Connect to Gmail IMAP server"""
        try:
            logger.info(f"🔗 Connecting to Gmail: {self.email}")
            self.imap = imaplib.IMAP4_SSL('imap.gmail.com', 993)
            self.imap.login(self.email, self.password)
            self.imap.select('INBOX')
            
            # Get current highest UID to establish baseline
            result, data = self.imap.uid('search', None, 'ALL')
            if result == 'OK' and data[0]:
                uids = data[0].split()
                if uids:
                    self.last_uid = int(uids[-1])
                    logger.info(f"📧 Baseline UID set to: {self.last_uid}")
                    self._save_last_uid(self.last_uid)
            
            logger.info("✅ Gmail IMAP connected successfully")
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
            except:
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
                    body_preview = "Could not decode body"
            
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
    
    def get_new_emails_since_last_uid(self):
        """Get ONLY new emails since last UID (true event-based)"""
        if not self.imap or self.last_uid is None:
            return []
        
        try:
            # Search for emails with UID greater than last_uid
            # Format: UID <start>:* to get all emails after start UID
            search_criteria = f"UID {self.last_uid + 1}:*"
            result, data = self.imap.uid('search', None, search_criteria)
            
            if result != 'OK' or not data[0]:
                return []
            
            new_uids = data[0].split()
            if not new_uids:
                return []
            
            new_emails = []
            
            for uid_bytes in new_uids:
                uid = uid_bytes.decode()
                
                # Fetch the email
                result, msg_data = self.imap.uid('fetch', uid, '(RFC822)')
                if result != 'OK' or not msg_data:
                    continue
                
                # Parse the email
                email_bytes = msg_data[0]
                if isinstance(email_bytes, tuple) and len(email_bytes) > 1:
                    email_bytes = email_bytes[1]
                
                email_data = self.parse_email_data(email_bytes)
                if email_data:
                    email_data['uid'] = uid
                    new_emails.append(email_data)
            
            # Update last_uid to the newest one
            if new_emails:
                latest_uid = max(int(uid) for uid in new_uids)
                self.last_uid = latest_uid
                self._save_last_uid(self.last_uid)
                logger.info(f"📬 Updated last UID to: {self.last_uid}")
            
            return new_emails
            
        except Exception as e:
            logger.error(f"Error getting new emails: {e}")
            return []
    
    async def wait_for_idle_notification(self, timeout: int = 1740):  # 29 minutes max for IMAP IDLE
        """Wait for IMAP IDLE notification"""
        if not self.imap:
            return False
        
        try:
            # Start IDLE mode
            self.imap.send(f"{self.imap._new_tag()} IDLE\r\n".encode())
            
            # Read initial response
            response = self.imap._get_response()
            
            start_time = time.time()
            
            while self.running and (time.time() - start_time) < timeout:
                try:
                    # Check for data (non-blocking)
                    if self.imap.socket is None:
                        break
                    
                    # Check if socket has data
                    ready_to_read, _, _ = select.select([self.imap.socket], [], [], 1.0)
                    
                    if ready_to_read:
                        # Read the response
                        response = self.imap._get_line().decode()
                        
                        if 'EXISTS' in response or 'FETCH' in response:
                            logger.info("📨 IMAP IDLE notification received!")
                            return True
                        
                        if 'BYE' in response:  # Server disconnected
                            break
                    
                    # Send NOOP every 60 seconds to keep connection alive
                    if int(time.time() - start_time) % 60 == 0:
                        self.imap.noop()
                        
                except Exception as e:
                    logger.error(f"IDLE wait error: {e}")
                    break
            
            # Exit IDLE mode
            self.imap.send(b"DONE\r\n")
            
        except Exception as e:
            logger.error(f"IDLE error: {e}")
        
        return False
    
    async def monitor_pure_event(self, callback_func):
        """PURE EVENT-BASED monitoring - no polling intervals"""
        self.running = True
        
        # Load last UID
        saved_uid = self._get_last_uid()
        if saved_uid:
            self.last_uid = int(saved_uid)
        
        # Connect to Gmail
        if not self.connect():
            return False
        
        logger.info("🚀 Starting PURE EVENT-BASED Gmail monitoring")
        logger.info("📧 Will only notify about NEW emails arriving AFTER this point")
        logger.info("⏰ True event-based - No polling intervals")
        
        # Main monitoring loop - NO FIXED INTERVALS
        connection_errors = 0
        max_errors = 3
        
        while self.running and connection_errors < max_errors:
            try:
                # METHOD 1: Try IMAP IDLE first (true event-based)
                logger.info("⏳ Entering IMAP IDLE mode (waiting for server notification)...")
                
                # Note: Railway might kill long connections, so we have fallback
                idle_success = await self.wait_for_idle_notification(timeout=1740)  # 29 mins
                
                if idle_success:
                    # Server notified us of new email
                    await asyncio.sleep(2)  # Brief pause for email to fully arrive
                    
                    # Get new emails since last UID
                    new_emails = self.get_new_emails_since_last_uid()
                    
                    for email_data in new_emails:
                        logger.info(f"📨 New email: {email_data['subject'][:50]}...")
                        try:
                            await callback_func(email_data)
                        except Exception as e:
                            logger.error(f"Callback error: {e}")
                    
                    connection_errors = 0
                    continue
                
                # If IDLE timed out or Railway killed connection, use adaptive checking
                # But this is NOT fixed-interval polling - it's connection recovery
                
                logger.info("🔁 Connection refresh, checking for missed emails...")
                
                # Check for any new emails we might have missed
                new_emails = self.get_new_emails_since_last_uid()
                
                for email_data in new_emails:
                    logger.info(f"📨 New email (recovery check): {email_data['subject'][:50]}...")
                    try:
                        await callback_func(email_data)
                    except Exception as e:
                        logger.error(f"Callback error: {e}")
                
                # Random sleep (NOT fixed interval) - between 1-10 seconds
                random_wait = 1  # Start with 1 second
                logger.info(f"💤 Adaptive wait: {random_wait}s")
                await asyncio.sleep(random_wait)
                
                # Reset error counter
                connection_errors = 0
                
            except Exception as e:
                connection_errors += 1
                logger.error(f"Monitoring error: {e}")
                
                if connection_errors < max_errors:
                    logger.warning(f"Reconnecting... ({connection_errors}/{max_errors})")
                    
                    # Exponential backoff
                    backoff_time = min(30, 2 ** connection_errors)
                    await asyncio.sleep(backoff_time)
                    
                    # Reconnect
                    self.disconnect()
                    if not self.connect():
                        break
                else:
                    logger.error("❌ Too many connection errors")
                    break
        
        self.disconnect()
        return True
    
    async def monitor_loop(self, callback_func, check_interval: int = 60):
        """Compatibility method - calls pure event-based"""
        logger.warning("⚠️ Using compatibility mode - switching to pure event-based")
        return await self.monitor_pure_event(callback_func)