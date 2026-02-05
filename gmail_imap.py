# gmail_imap.py
import imaplib
import email
import time
from email.header import decode_header
import asyncio

class GmailIMAPWatcher:
    """Simple Gmail watcher using IMAP (no OAuth needed)"""
    
    def __init__(self, email_address: str, app_password: str):
        self.email = email_address
        self.password = app_password
        self.imap = None
        self.running = False
        
    def connect(self) -> bool:
        """Connect to Gmail IMAP server"""
        try:
            print(f"🔗 Connecting to Gmail: {self.email}")
            self.imap = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            self.imap.login(self.email, self.password)
            self.imap.select("INBOX")
            print("✅ Gmail IMAP connected successfully")
            return True
        except Exception as e:
            print(f"❌ Gmail connection failed: {e}")
            return False
    
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
    
    def get_unread_emails(self, max_results: int = 10):
        """Get unread emails"""
        if not self.imap:
            return []
        
        try:
            # Search for unread emails
            status, messages = self.imap.search(None, 'UNSEEN')
            
            if status != "OK" or not messages[0]:
                return []
            
            email_ids = messages[0].split()
            recent_ids = email_ids[-max_results:] if len(email_ids) > max_results else email_ids
            emails = []
            
            for email_id in recent_ids:
                try:
                    # Fetch email
                    status, msg_data = self.imap.fetch(email_id, "(RFC822)")
                    
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
                    
                    emails.append({
                        'id': email_id.decode(),
                        'from': from_header,
                        'sender_email': sender_email,
                        'subject': subject,
                        'preview': body_preview[:200] + "..." if len(body_preview) > 200 else body_preview,
                        'full_body': body_preview[:500]  # First 500 chars
                    })
                    
                except Exception as e:
                    print(f"Error parsing email {email_id}: {e}")
                    continue
            
            return emails
            
        except Exception as e:
            print(f"Error fetching emails: {e}")
            return []
    
    def mark_as_read(self, email_id: str) -> bool:
        """Mark email as read"""
        try:
            self.imap.store(email_id, '+FLAGS', '\\Seen')
            return True
        except:
            return False
    
    async def monitor_loop(self, callback_func, check_interval: int = 60):
        """Monitor for new emails and call callback function"""
        if not self.connect():
            return False
        
        self.running = True
        print(f"👀 Starting Gmail monitor (checking every {check_interval}s)")
        
        # Get initial unread emails to avoid notifying old ones
        initial_emails = self.get_unread_emails()
        processed_ids = {email['id'] for email in initial_emails}
        
        while self.running:
            try:
                # Get current unread emails
                current_emails = self.get_unread_emails()
                
                # Find new emails
                for email_data in current_emails:
                    if email_data['id'] not in processed_ids:
                        # New email found - call callback
                        await callback_func(email_data)
                        processed_ids.add(email_data['id'])
                
                # Wait before next check
                await asyncio.sleep(check_interval)
                
            except Exception as e:
                print(f"Monitor error: {e}")
                # Try to reconnect
                self.disconnect()
                if not self.connect():
                    print("❌ Could not reconnect to Gmail")
                    break
                await asyncio.sleep(30)
        
        self.disconnect()
        return True