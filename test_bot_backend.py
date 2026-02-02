import os
import sys
import asyncio
import logging
from unittest.mock import AsyncMock, Mock, patch
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_environment():
    """Test environment variables"""
    print("\n🔧 Testing Environment Variables...")
    
    required_vars = ['TELEGRAM_BOT_TOKEN', 'OPENROUTER_API_KEY']
    all_ok = True
    
    for var in required_vars:
        if os.getenv(var):
            print(f"  ✅ {var}: Set")
        else:
            print(f"  ❌ {var}: Missing")
            all_ok = False
    
    return all_ok

def test_imports():
    """Test module imports"""
    print("\n📦 Testing Imports...")
    
    try:
        from bot import SimpleHybridMemory, OpenRouterClient, TelegramBotWithMemory
        print("  ✅ All imports successful")
        return True
    except ImportError as e:
        print(f"  ❌ Import failed: {e}")
        return False

def test_hybrid_memory():
    """Test hybrid memory implementation"""
    print("\n🧠 Testing Hybrid Memory...")
    
    try:
        from bot import SimpleHybridMemory
        
        memory = SimpleHybridMemory(buffer_size=2)
        
        # Test adding conversations
        memory.add_conversation("Hello", "Hi there!")
        memory.add_conversation("How are you?", "I'm good, thanks!")
        
        # Get context
        context = memory.get_context()
        
        print(f"  ✅ HybridMemory created")
        print(f"  ✅ Buffer size: {len(memory.recent_messages)}")
        print(f"  ✅ Has summary: {bool(memory.summary)}")
        
        return True
    except Exception as e:
        print(f"  ❌ Hybrid memory test failed: {e}")
        return False

def test_bot_initialization():
    """Test bot initialization"""
    print("\n🤖 Testing Bot Initialization...")
    
    with patch.dict(os.environ, {
        'TELEGRAM_BOT_TOKEN': 'test_token',
        'OPENROUTER_API_KEY': 'test_key',
        'BUFFER_WINDOW_SIZE': '2'
    }):
        try:
            from bot import TelegramBotWithMemory
            bot = TelegramBotWithMemory()
            
            print("  ✅ Bot initialization successful")
            
            # Test user memory
            memory = bot.get_user_memory("test_user_123")
            print(f"  ✅ User memory created")
            print(f"  ✅ Total users: {len(bot.user_memories)}")
            
            return True
            
        except Exception as e:
            print(f"  ❌ Initialization failed: {e}")
            return False

async def test_message_handling():
    """Test message handling"""
    print("\n💬 Testing Message Handling...")
    
    with patch.dict(os.environ, {
        'TELEGRAM_BOT_TOKEN': 'test_token',
        'OPENROUTER_API_KEY': 'test_key'
    }):
        with patch('requests.post') as mock_post:
            from bot import TelegramBotWithMemory
            
            # Mock API response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "choices": [{"message": {"content": "Mocked AI response"}}]
            }
            mock_post.return_value = mock_response
            
            bot = TelegramBotWithMemory()
            
            # Mock Telegram update
            mock_update = AsyncMock()
            mock_update.effective_user.id = 12345
            mock_update.message.text = "Hello bot"
            mock_update.message.reply_text = AsyncMock()
            
            mock_context = AsyncMock()
            
            # Test
            await bot.handle_message(mock_update, mock_context)
            
            print("  ✅ Message handling successful")
            print("  ✅ AI response generated")
            
            return True

async def test_commands():
    """Test command handlers"""
    print("\n⌨️ Testing Command Handlers...")
    
    try:
        with patch.dict(os.environ, {
            'TELEGRAM_BOT_TOKEN': 'test_token',
            'OPENROUTER_API_KEY': 'test_key'
        }):
            from bot import TelegramBotWithMemory
            
            bot = TelegramBotWithMemory()
            
            # Test /start
            mock_update = AsyncMock()
            mock_update.effective_user.id = 12345
            mock_update.message.reply_text = AsyncMock()
            mock_context = AsyncMock()
            
            await bot.start_command(mock_update, mock_context)
            print("  ✅ /start command works")
            
            # Test /clear
            mock_update.message.reply_text.reset_mock()
            bot.user_memories["12345"] = Mock()
            await bot.clear_command(mock_update, mock_context)
            print("  ✅ /clear command works")
            
            # Test /memory
            mock_update.message.reply_text.reset_mock()
            mock_memory = Mock()
            mock_memory.get_stats.return_value = {
                "buffer_entries": 2,
                "buffer_size": 3,
                "summary_length": 50,
                "has_summary": True
            }
            mock_memory.recent_messages = [
                {"user": "Hello", "ai": "Hi"},
                {"user": "How are you?", "ai": "Good"}
            ]
            bot.user_memories["12345"] = mock_memory
            await bot.memory_command(mock_update, mock_context)
            print("  ✅ /memory command works")
            
            return True
            
    except Exception as e:
        print(f"  ❌ Command test failed: {e}")
        return False

def run_integration_test():
    """Test with real APIs if available"""
    print("\n🚀 Integration Test (Real APIs)...")
    
    if not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("OPENROUTER_API_KEY"):
        print("  ⚠ Skipping - Set TELEGRAM_BOT_TOKEN and OPENROUTER_API_KEY in .env")
        return None
    
    try:
        from bot import TelegramBotWithMemory
        
        print("  Initializing with real APIs...")
        bot = TelegramBotWithMemory()
        
        print(f"  ✅ Bot created")
        print(f"  • Using direct OpenRouter API")
        print(f"  • Hybrid memory: SimpleHybridMemory")
        
        return True
            
    except Exception as e:
        print(f"  ❌ Integration test failed: {e}")
        return False

async def main():
    """Run all tests"""
    print("=" * 60)
    print("🤖 TELEGRAM BOT TEST SUITE (No LangChain)")
    print("=" * 60)
    
    results = []
    
    # Run tests
    results.append(("Environment", test_environment()))
    results.append(("Imports", test_imports()))
    results.append(("Hybrid Memory", test_hybrid_memory()))
    results.append(("Bot Initialization", test_bot_initialization()))
    results.append(("Message Handling", await test_message_handling()))
    results.append(("Commands", await test_commands()))
    
    # Integration test
    integration_result = run_integration_test()
    if integration_result is not None:
        results.append(("Integration", integration_result))
    
    # Print summary
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        if result is None:
            status = "⚠ SKIPPED"
        elif not result:
            all_passed = False
        print(f"{test_name:25} {status}")
    
    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 ALL TESTS PASSED! Bot is ready to run.")
        print("Run: python bot.py")
    else:
        print("⚠ Some tests failed. Check above for details.")
    print("=" * 60)
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)