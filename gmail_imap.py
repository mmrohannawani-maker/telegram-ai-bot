# gmail_imap.py
import imaplib
import email
import time
from email.header import decode_header
import asyncio
from datetime import datetime

class GmailIMAPWatcher:
    """Simple Gmail watcher using IMAP (no OAuth needed)"""
    
    def __init__(self, email_address: str, app_password: str):
        self.email = email_address
        self.password = app_password
        self.imap = None
        self.running = False
        self.last_uid = None  # Track last processed email UID
        
    def connect(self) -> bool:
        """Connect to Gmail IMAP server"""
        try:
            print(f"🔗 Connecting to Gmail: {self.email}")
            self.imap = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            self.imap.login(self.email, self.password)
            self.imap.select("INBOX")
            print("✅ Gmail IMAP connected successfully")
            
            # Get the current highest UID to ignore old emails
            if self.last_uid is None:
                self._get_latest_uid()
                
            return True
        except Exception as e:
            print(f"❌ Gmail connection failed: {e}")
            return False
    
    def _get_latest_uid(self):
        """Get the latest email UID to establish a baseline"""
        try:
            # Search for ALL emails and get the latest UID
            status, messages = self.imap.uid('search', None, 'ALL')
            if status == 'OK' and messages[0]:
                uids = messages[0].split()
                if uids:
                    self.last_uid = int(uids[-1])
                    print(f"📧 Baseline UID set to: {self.last_uid}")
        except Exception as e:
            print(f"Error getting latest UID: {e}")
            self.last_uid = 0
    
    def get_new_emails(self):
        """Get ONLY NEW emails since last check"""
        if not self.imap:
            return []
        
        try:
            # If we don't have a last_uid yet, get current latest
            if self.last_uid is None:
                self._get_latest_uid()
                return []  # Return empty on first run to avoid old emails
            
            # Search for emails with UID greater than last_uid
            # UID SEARCH uses: UID <start>:* to get emails after start UID
            search_criteria = f"UID {self.last_uid + 1}:*"
            status, messages = self.imap.uid('search', None, search_criteria)
            
            if status != "OK" or not messages[0]:
                return []
            
            email_uids = messages[0].split()
            
            if not email_uids:
                return []
            
            emails = []
            
            for email_uid in email_uids:
                try:
                    # Fetch the email using UID
                    status, msg_data = self.imap.uid('fetch', email_uid, "(RFC822)")
                    
                    if status != "OK":
                        continue
                    
                    # Parse email
                    msg = email.message_from_bytes(msg_data[0][1])
                    
                    # Get sender
                    from_header = msg.get("From", "Unknown")
                    
                    # Extract email from "Name <email@example.com>" format
                    sender_email = from_header
                    if "<" in from_header and ">" in from_header:
                        sender_email = from_header.split("<")[1].split(">")[0]
                    
                    # Get subject
                    subject_header = msg.get("Subject", "No Subject")
                    subject, encoding = decode_header(subject_header)[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding if encoding else "utf-8")
                    
                    # Get body preview
                    body_preview = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                try:
                                    body_preview = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                                    break
                                except:
                                    continue
                    else:
                        try:
                            body_preview = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
                        except:
                            body_preview = "Could not decode body"
                    
                    # Get date
                    date_header = msg.get("Date", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                    
                    emails.append({
                        'uid': int(email_uid),
                        'from': from_header,
                        'sender_email': sender_email,
                        'subject': subject,
                        'preview': body_preview[:200] + "..." if len(body_preview) > 200 else body_preview,
                        'date': date_header,
                        'full_body': body_preview[:500]
                    })
                    
                except Exception as e:
                    print(f"Error parsing email {email_uid}: {e}")
                    continue
            
            # Update last_uid to the newest email UID
            if emails:
                latest_uid = max(email['uid'] for email in emails)
                self.last_uid = latest_uid
                print(f"📬 Updated last UID to: {self.last_uid}")
            
            return emails
            
        except Exception as e:
            print(f"Error fetching new emails: {e}")
            return []
    
    def disconnect(self):
        """Disconnect from Gmail"""
        if self.imap:
            try:
                self.imap.logout()
                print("✅ Gmail disconnected")
            except:
                pass
            self.imap = None
        self.running = False
    
    async def monitor_loop(self, callback_func, check_interval: int = 60):
        """Monitor for NEW emails and call callback function"""
        if not self.connect():
            return False
        
        self.running = True
        print(f"👀 Starting Gmail monitor (checking every {check_interval}s)")
        print("📧 Will only notify about NEW emails arriving AFTER this point")
        
        while self.running:
            try:
                # Get NEW emails since last check
                new_emails = self.get_new_emails()
                
                # Process each new email
                for email_data in new_emails:
                    print(f"📨 New email detected: {email_data['subject']}")
                    await callback_func(email_data)
                
                # Wait before next check
                await asyncio.sleep(check_interval)
                
            except Exception as e:
                print(f"Monitor error: {e}")
                # Try to reconnect
                self.disconnect()
                await asyncio.sleep(5)
                if not self.connect():
                    print("❌ Could not reconnect to Gmail")
                    break
        
        
        self.disconnect()
        return True