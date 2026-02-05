import os
import logging
from typing import Dict
from dotenv import load_dotenv
from tavily import TavilyClient
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime


# Load environment variables
load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
tavily_client = TavilyClient(api_key=TAVILY_API_KEY)


# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Import Telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Import our modules
from database import MemoryDatabase
from memory import PersistentHybridMemory

# Import OpenRouter client
import requests
import json


def tavily_search(query: str, max_results: int = 5) -> str:
    """Fetch web context using Tavily for RAG"""
    if not TAVILY_API_KEY:
        return ""

    try:
        response = tavily_client.search(
            query=query,
            max_results=max_results,
            search_depth="basic"
        )

        if not response.get("results"):
            return ""

        context = "Web search results:\n"
        for i, r in enumerate(response["results"], 1):
            context += f"{i}. {r['title']}\n{r['content']}\n"

        return context

    except Exception as e:
        logger.error(f"Tavily search failed: {e}")
        return ""



# ========== OPENROUTER CLIENT ==========
class OpenRouterClient:
    """Simple OpenRouter client without LangChain"""
    
    def __init__(self, api_key: str, model: str = "mistralai/mistral-small-3.2-24b-instruct"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://openrouter.ai/api/v1"
    
    def generate_response(self, prompt: str, memory_context: str = "", temperature: float = 0.7) -> str:
        """Generate response from OpenRouter"""
        # Combine memory context with prompt
        if memory_context:
            full_prompt = f"""{memory_context}

Current conversation:
Human: {prompt}
AI:"""
        else:
            full_prompt = f"Human: {prompt}\nAI:"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://telegram-bot.com",
            "X-Title": "Telegram AI Assistant"
        }
        
        data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a helpful AI assistant."},
                {"role": "user", "content": full_prompt}
            ],
            "temperature": temperature,
            "max_tokens": 500
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=data,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                return result["choices"][0]["message"]["content"]
            else:
                logger.error(f"OpenRouter API error: {response.status_code} - {response.text}")
                return f"Sorry, I encountered an API error (Status: {response.status_code})"
                
        except Exception as e:
            logger.error(f"OpenRouter request failed: {e}")
            return "Sorry, I'm having trouble connecting to the AI service."

# ========== MAIN BOT CLASS ==========
class TelegramBotWithDatabaseMemory:
    """Bot with database-backed memory"""
    
    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        
        if not self.bot_token:
            raise ValueError("Set TELEGRAM_BOT_TOKEN in .env")
        if not self.openrouter_api_key:
            raise ValueError("Set OPENROUTER_API_KEY in .env")
        
        # Initialize database
        self.db = MemoryDatabase()
        
        # Initialize OpenRouter client
        self.llm = OpenRouterClient(
            api_key=self.openrouter_api_key,
            model=os.getenv("OPENROUTER_MODEL", "mistralai/mistral-small-3.2-24b-instruct")
        )
        
        

        # User memory storage
        self.user_memories: Dict[str, PersistentHybridMemory] = {}

        self.scheduler = AsyncIOScheduler()
        self.notification_jobs: Dict[str, str] = {}  # user_id -> job_id
        self.active_notifications = False
        
        logger.info("Bot initialized with database memory")
    
    def get_user_memory(self, user_id: str) -> PersistentHybridMemory:
        """Get or create memory for user"""
        if user_id not in self.user_memories:
            buffer_size = int(os.getenv("BUFFER_WINDOW_SIZE", "3"))
            self.user_memories[user_id] = PersistentHybridMemory(
                user_id=user_id,
                db=self.db,
                buffer_size=buffer_size
            )
        return self.user_memories[user_id]
    
    # ========== NOTIFICATION METHODS ==========
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start"""
        user_id = str(update.effective_user.id)
        username = update.effective_user.username
        first_name = update.effective_user.first_name

        # Save user for notifications
        self.db.save_user_for_notifications(user_id, username, first_name)
        
        welcome = (
    "🤖 Hello! I'm your AI assistant with memory!\n"
    "I remember our conversations and can send you notifications.\n\n"
    "📋 Commands:\n"
    "/start - Register for notifications\n"
    "/start_notifications - Start receiving notifications every minute\n"
    "/stop_notifications - Stop notifications\n"
    "/notification_status - Check notification status\n"
    "/test_notify - Test notification\n"
    "/notify [message] - Send one-time notification\n"
    "/clear - Clear memory\n"
    "/memory - Show memory stats\n"
    "/stats - Show notification stats\n"
    "/dbstats - Show database stats\n"
    "/migrate - Migrate existing users"
)
        await update.message.reply_text(welcome)
    
    async def test_notify_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send test notification to yourself"""
        chat_id = update.effective_chat.id
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="🔔 Test notification successful!\nThis proves proactive messaging works."
            )
            logger.info(f"Test notification sent to {chat_id}")
        except Exception as e:
            logger.error(f"Failed to send test: {e}")
            await update.message.reply_text("❌ Failed to send test notification")
    
    async def broadcast_notification(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Broadcast notification to all users"""
        if not context.args:
            await update.message.reply_text("Usage: /notify [message]")
            return
        
        message = " ".join(context.args)
        user_ids = self.db.get_all_users_for_notifications()
        
        if not user_ids:
            await update.message.reply_text("No users registered for notifications.")
            return
        
        await update.message.reply_text(f"📢 Sending notification to {len(user_ids)} users...")
        
        success_count = 0
        fail_count = 0
        
        for user_id in user_ids:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"📢 Announcement: {message}"
                )
                success_count += 1
                await asyncio.sleep(0.1)  # Rate limiting
            except Exception as e:
                logger.error(f"Failed to send to {user_id}: {e}")
                fail_count += 1
        
        await update.message.reply_text(
            f"✅ Notification sent!\n"
            f"Successful: {success_count}\n"
            f"Failed: {fail_count}"
        )
    
    async def migrate_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Migrate existing users to notifications table"""
        await update.message.reply_text("🔄 Migrating existing users...")
        migrated = self.db.migrate_existing_users()
        await update.message.reply_text(f"✅ Migrated {migrated} users to notifications system.")
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show notification stats"""
        stats = self.db.get_database_stats()
        
        response = (
            f"📊 Notification Stats:\n"
            f"• Database: {stats.get('database_type', 'Unknown')}\n"
            f"• Total users: {stats.get('total_users', 0)}\n"
            f"• Notification users: {stats.get('notification_users', 0)}\n"
            f"• Total messages: {stats.get('total_messages', 0)}\n"
            f"• Your User ID: {update.effective_user.id}"
        )
        await update.message.reply_text(response)

         # ✅ ADD SCHEDULED NOTIFICATION METHODS RIGHT HERE (BEFORE handle_message):

    async def send_scheduled_notification(self, user_id: str, message: str = None):
        """Send scheduled notification to a specific user"""
        try:
            if not message:
                # Default notification message
                message = "⏰ Scheduled reminder from your AI assistant!"
            
            await self.application.bot.send_message(
                chat_id=user_id,
                text=f"🔔 {message}\n\nTime: {datetime.now().strftime('%H:%M:%S')}"
            )
            logger.info(f"Scheduled notification sent to {user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to send scheduled notification to {user_id}: {e}")
            return False
        
    async def start_notifications_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start sending notifications every minute"""
        user_id = str(update.effective_user.id)
        
        # Check if already running for this user
        if user_id in self.notification_jobs:
            await update.message.reply_text("⏰ Notifications are already running for you!")
            return
        
        # Get custom message if provided
        message = " ".join(context.args) if context.args else None
        
        # Create job for this user
        job_id = f"user_{user_id}_notifications"
        
        # Add job to scheduler (every 60 seconds)
        job = self.scheduler.add_job(
            self.send_scheduled_notification,
            IntervalTrigger(seconds=60),
            args=[user_id, message],
            id=job_id,
            replace_existing=True
        )
        
        # Store job reference
        self.notification_jobs[user_id] = job_id
        self.active_notifications = True
        
        # Start scheduler if not already running
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Notification scheduler started")
        
        await update.message.reply_text(
            f"✅ Notifications started!\n"
            f"• Will send every minute\n"
            f"• Use /stop_notifications to stop\n"
            f"• First notification in 60 seconds..."
        )
        
        # Send first notification immediately
        await self.send_scheduled_notification(user_id, message)
        logger.info(f"Started scheduled notifications for user {user_id}")



    async def stop_notifications_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Stop scheduled notifications for this user"""
        user_id = str(update.effective_user.id)
        
        if user_id not in self.notification_jobs:
            await update.message.reply_text("❌ You don't have any active notifications to stop.")
            return
        
        # Remove the job
        job_id = self.notification_jobs[user_id]
        self.scheduler.remove_job(job_id)
        
        # Remove from tracking
        del self.notification_jobs[user_id]
        
        # Stop scheduler if no more jobs
        if not self.notification_jobs and self.scheduler.running:
            self.scheduler.shutdown()
            self.active_notifications = False
            logger.info("Notification scheduler stopped (no more jobs)")
        
        await update.message.reply_text(
            "🛑 Notifications stopped!\n"
            "You will no longer receive scheduled notifications."
        )
        logger.info(f"Stopped scheduled notifications for user {user_id}")


    async def notification_status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check notification status"""
        user_id = str(update.effective_user.id)
        
        if user_id in self.notification_jobs:
            status = "✅ ACTIVE - You're receiving notifications every minute"
        else:
            status = "❌ INACTIVE - Use /start_notifications to begin"
        
        response = (
            f"📊 Your Notification Status:\n"
            f"{status}\n\n"
            f"🔧 Commands:\n"
            f"/start_notifications [message] - Start (optional custom message)\n"
            f"/stop_notifications - Stop\n"
            f"/notification_status - Check status\n\n"
            f"Total users with active notifications: {len(self.notification_jobs)}"
        )
        
        await update.message.reply_text(response)
    
    async def broadcast_scheduled_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start scheduled notifications for ALL users (admin)"""
        # Optional admin check (uncomment if needed)
        # user_id = str(update.effective_user.id)
        # if user_id != "YOUR_ADMIN_ID":
        #     await update.message.reply_text("❌ Admin only.")
        #     return
        
        if not context.args:
            await update.message.reply_text("Usage: /broadcast_scheduled [message]")
            return
        
        message = " ".join(context.args)
        user_ids = self.db.get_all_users_for_notifications()
        
        if not user_ids:
            await update.message.reply_text("No users registered for notifications.")
            return
        
        await update.message.reply_text(f"⏰ Starting scheduled notifications for {len(user_ids)} users...")
        
        started_count = 0
        for user_id in user_ids:
            # Start notifications for each user
            if user_id not in self.notification_jobs:
                job_id = f"user_{user_id}_scheduled"
                self.scheduler.add_job(
                    self.send_scheduled_notification,
                    IntervalTrigger(seconds=60),
                    args=[user_id, message],
                    id=job_id,
                    replace_existing=True
                )
                self.notification_jobs[user_id] = job_id
                started_count += 1
        
        # Start scheduler if not already running
        if not self.scheduler.running:
            self.scheduler.start()
            self.active_notifications = True
        
        await update.message.reply_text(
            f"✅ Started scheduled notifications!\n"
            f"• Users: {started_count}\n"
            f"• Interval: Every minute\n"
            f"• Message: {message[:50]}..."
        )

    # ========== EXISTING METHODS ==========
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming messages"""
        try:
            user_id = str(update.effective_user.id)
            user_message = update.message.text
            
            logger.info(f"Message from {user_id}: {user_message}")

            # Update user interaction time
            self.db.update_user_interaction(user_id)
            
            # Get user memory (auto-loads from DB)
            memory = self.get_user_memory(user_id)
            
            # Get memory context
            memory_context = memory.get_context()

            # 🔍 RAG: Web search context
            rag_context = tavily_search(user_message)

            # Combine RAG + memory
            combined_context = ""
            if rag_context:
                combined_context += rag_context + "\n\n"
                combined_context += memory_context

            # Verbose logging
            print(f"\n{'='*60}")
            print("🤖 CONVERSATION CHAIN (verbose=True)")
            print(f"{'='*60}")

            print("🧠 MEMORY CONTEXT:")
            print(memory_context if memory_context else "No memory available")

            print(f"\n🌐 RAG (Web Search) CONTEXT:")
            print(rag_context if rag_context else "No web search used")

            print(f"\n👤 HUMAN INPUT:")
            print(user_message)

            print(f"{'='*60}")
            
            # Get response from OpenRouter
            response = self.llm.generate_response(
                prompt=user_message,
                memory_context=combined_context,
                temperature=float(os.getenv("LLM_TEMPERATURE", "0.7"))
            )
            
            # Add to memory (auto-saves to DB)
            memory.add_conversation(user_message, response)
            
            # Send response
            await update.message.reply_text(response)
            logger.info(f"Response sent to {user_id}")
            
        except Exception as e:
            logger.error(f"Error: {e}")
            await update.message.reply_text("Sorry, I encountered an error. Please try again.")
    
    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /clear"""
        user_id = str(update.effective_user.id)
        memory = self.get_user_memory(user_id)
        memory.clear()
        await update.message.reply_text("✅ Memory cleared from database!")
    
    async def memory_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /memory"""
        user_id = str(update.effective_user.id)
        memory = self.get_user_memory(user_id)
        stats = memory.get_stats()
        
        response = (
            f"🧠 Memory Stats:\n"
            f"• Buffer: {stats['buffer_entries']}/{stats['buffer_size']}\n"
            f"• Total messages: {stats.get('total_messages', 0)}\n"
            f"• Last active: {stats.get('last_active', 'Never')}\n"
            f"• Has summary: {'Yes' if stats['has_summary'] else 'No'}"
        )
        await update.message.reply_text(response)
    
    async def dbstats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show database statistics"""
        db_stats = self.db.get_database_stats()
        
        response = (
            f"📊 Database Stats:\n"
            f"• Total users: {db_stats.get('total_users', 0)}\n"
            f"• Total messages: {db_stats.get('total_messages', 0)}\n"
            f"• Notification users: {db_stats.get('notification_users', 0)}\n"
            f"• Database type: {db_stats.get('database_type', 'Unknown')}"
        )
        await update.message.reply_text(response)
    
    def run(self):
        """Start the bot"""
        try:
            application = Application.builder().token(self.bot_token).build()

            self.application = application
            
            # Add command handlers
            application.add_handler(CommandHandler("start", self.start_command))
            application.add_handler(CommandHandler("clear", self.clear_command))
            application.add_handler(CommandHandler("memory", self.memory_command))
            application.add_handler(CommandHandler("dbstats", self.dbstats_command))
            application.add_handler(CommandHandler("stats", self.stats_command))
            application.add_handler(CommandHandler("test_notify", self.test_notify_command))
            application.add_handler(CommandHandler("notify", self.broadcast_notification))
            application.add_handler(CommandHandler("migrate", self.migrate_command))

            # ✅ ADD NEW NOTIFICATION COMMANDS:
            application.add_handler(CommandHandler("start_notifications", self.start_notifications_command))
            application.add_handler(CommandHandler("stop_notifications", self.stop_notifications_command))
            application.add_handler(CommandHandler("notification_status", self.notification_status_command))
            application.add_handler(CommandHandler("broadcast_scheduled", self.broadcast_scheduled_command))
            
            # Add message handler
            application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
            
            # Start
            logger.info("Starting bot...")
            print("\n" + "="*60)
            print("🤖 Telegram Bot with Database Memory & Notifications")
            print("="*60)
            print("Database: Auto (SQLite local / PostgreSQL Railway)")
            print("Notification system: ✅ ACTIVE")
            print("Commands: /start, /stats, /test_notify, /notify, /migrate")
            print("Press Ctrl+C to stop")
            print("="*60)
            print("✅ Commands available:")
            print("   /start_notifications - Start per-user notifications")
            print("   /stop_notifications - Stop your notifications")
            print("   /notification_status - Check status")
            print("   /broadcast_scheduled - Admin: Start for all users")
            print("="*60)
            
            application.run_polling()
            
        except Exception as e:
            logger.error(f"Bot error: {e}")
        finally:
            # Cleanup
            # Cleanup scheduler
            if self.scheduler.running:
                self.scheduler.shutdown()
            # Cleanup database
            self.db.close()

def main():
    bot = TelegramBotWithDatabaseMemory()
    bot.run()

if __name__ == "__main__":
    main()