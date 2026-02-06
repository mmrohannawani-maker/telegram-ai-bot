# gmail_imap.py - PURE EVENT-BASED VERSION (NO POLLING)
import asyncio
import aioimaplib
import email
from email.header import decode_header
from datetime import datetime
import logging
import re

logger = logging.getLogger(__name__)

class GmailIMAPWatcher:
    """Pure event-based Gmail watcher using IMAP IDLE (NO POLLING)"""
    
    def __init__(self, email_address: str, app_password: str):
        self.email = email_address
        self.password = app_password
        self.host = 'imap.gmail.com'
        self.port = 993
        self.client = None
        self.running = False
        self.processed_uids = set()  # Track processed emails in memory
        self.idle_task = None
        
    async def connect(self) -> bool:
        """Connect to Gmail IMAP server"""
        try:
            logger.info(f"🔗 Connecting to Gmail: {self.email}")
            self.client = aioimaplib.IMAP4_SSL(host=self.host, port=self.port)
            await self.client.wait_hello_from_server()
            
            await self.client.login(self.email, self.password)
            await self.client.select('INBOX')
            
            logger.info("✅ Gmail IMAP connected successfully")
            return True
        except Exception as e:
            logger.error(f"❌ Gmail connection failed: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from Gmail"""
        self.running = False
        
        if self.idle_task and not self.idle_task.done():
            self.idle_task.cancel()
            
        if self.client:
            try:
                await self.client.logout()
                logger.info("✅ Gmail disconnected")
            except:
                pass
            self.client = None
    
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
                                body_preview = body.decode('utf-8', errors='ignore')[:200]
                            break
                        except:
                            continue
            else:
                try:
                    body = msg.get_payload(decode=True)
                    if body:
                        body_preview = body.decode('utf-8', errors='ignore')[:200]
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
    
    async def get_latest_email(self) -> dict:
        """Get the latest email from inbox"""
        try:
            # Search for all emails and get the latest one
            await self.client.noop()  # Refresh connection
            
            # Get UIDs of all emails
            result, data = await self.client.uid('search', None, 'ALL')
            if result != 'OK' or not data[0]:
                return None
            
            uids = data[0].split()
            if not uids:
                return None
            
            # Get the latest UID
            latest_uid = uids[-1].decode()
            
            # Fetch this email
            result, msg_data = await self.client.uid('fetch', latest_uid, '(RFC822)')
            if result != 'OK' or not msg_data:
                return None
            
            # Parse the email
            email_bytes = msg_data[0]
            if isinstance(email_bytes, tuple) and len(email_bytes) > 1:
                email_bytes = email_bytes[1]
            
            email_data = self.parse_email_data(email_bytes)
            if email_data:
                email_data['uid'] = latest_uid
            
            return email_data
            
        except Exception as e:
            logger.error(f"Error getting latest email: {e}")
            return None
    
    async def wait_for_new_email_idle(self):
        """Wait for new email using IMAP IDLE command"""
        try:
            # Send IDLE command
            await self.client.idle()
            
            # Wait for IDLE response (new email notification)
            while self.running:
                try:
                    # Wait for server response (this blocks until email arrives)
                    response = await self.client.wait_server_push()
                    
                    # Check if it's an EXISTS response (new email)
                    if isinstance(response, tuple) and len(response) > 1:
                        if b'EXISTS' in response[1] or b'FETCH' in response[1]:
                            logger.info("📨 IMAP IDLE notification: New email detected!")
                            return True
                    
                except asyncio.TimeoutError:
                    # Send DONE to keep connection alive (required every 29 mins)
                    await self.client.idle_done()
                    await asyncio.sleep(1)
                    await self.client.idle()
                    continue
                    
        except Exception as e:
            logger.error(f"IDLE error: {e}")
            return False
        finally:
            # Exit IDLE mode
            try:
                await self.client.idle_done()
            except:
                pass
    
    async def monitor_idle(self, callback_func):
        """Pure event-based monitoring using IMAP IDLE (NO POLLING)"""
        self.running = True
        
        # Connect to Gmail
        if not await self.connect():
            return False
        
        logger.info("🚀 Starting PURE EVENT-BASED Gmail monitoring")
        logger.info("📧 Using IMAP IDLE - Will notify INSTANTLY when emails arrive")
        logger.info("⏰ No polling intervals - True event-based notifications")
        
        # Get baseline - don't notify about existing emails
        logger.info("🔄 Ignoring existing emails, only new arrivals will be notified")
        
        connection_errors = 0
        max_errors = 3
        
        while self.running and connection_errors < max_errors:
            try:
                # Wait for new email using IDLE (BLOCKS until email arrives)
                logger.info("⏳ Waiting for new email (IMAP IDLE mode)...")
                
                idle_result = await self.wait_for_new_email_idle()
                
                if idle_result and self.running:
                    # Brief pause to ensure email is fully delivered
                    await asyncio.sleep(3)
                    
                    # Get the new email
                    email_data = await self.get_latest_email()
                    
                    if email_data:
                        uid = email_data.get('uid')
                        
                        # Check if we've already processed this UID
                        if uid and uid in self.processed_uids:
                            logger.info(f"Email {uid} already processed, skipping")
                            continue
                        
                        # Add to processed set
                        if uid:
                            self.processed_uids.add(uid)
                        
                        logger.info(f"📨 New email received: {email_data['subject'][:50]}...")
                        
                        # Call callback with email data
                        try:
                            await callback_func(email_data)
                        except Exception as e:
                            logger.error(f"Callback error: {e}")
                        
                        # Reset error counter on success
                        connection_errors = 0
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                connection_errors += 1
                logger.error(f"Monitoring error: {e}")
                
                if connection_errors < max_errors:
                    logger.warning(f"Reconnecting... ({connection_errors}/{max_errors})")
                    await asyncio.sleep(5)
                    
                    # Reconnect
                    await self.disconnect()
                    if not await self.connect():
                        break
                else:
                    logger.error("❌ Too many connection errors")
                    break
        
        await self.disconnect()
        return True
    
    async def monitor_loop(self, callback_func, check_interval: int = 60):
        """LEGACY METHOD - Only kept for compatibility"""
        logger.warning("⚠️ Using polling mode (not event-based)")
        logger.info(f"Will check every {check_interval} seconds")
        
        # Call the pure event-based monitor instead
        return await self.monitor_idle(callback_func)