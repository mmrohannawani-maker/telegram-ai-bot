import sys
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_database():
    print("🧪 Testing Database...")
    
    try:
        from database import MemoryDatabase
        
        # Test 1: Create database
        print("1. Creating database...")
        db = MemoryDatabase("test_memory.db")
        print("   ✅ Database created")
        
        # Test 2: Save memory
        print("2. Saving memory...")
        test_messages = [
            {"user": "Hello", "ai": "Hi!", "timestamp": "2024-01-01"},
            {"user": "How are you?", "ai": "Good!", "timestamp": "2024-01-01"}
        ]
        
        success = db.save_user_memory("test_user", test_messages, "Test summary")
        if not success:
            print("   ❌ Failed to save memory")
            return False
        print("   ✅ Memory saved")
        
        # Test 3: Load memory
        print("3. Loading memory...")
        messages, summary = db.load_user_memory("test_user")
        print(f"   ✅ Loaded: {len(messages)} messages")
        
        # Test 4: Message history
        print("4. Testing message history...")
        db.add_message_to_history("test_user", "user", "Hello")
        db.add_message_to_history("test_user", "assistant", "Hi!")
        print("   ✅ Message history added")
        
        # Test 5: Get recent messages
        print("5. Getting recent messages...")
        recent = db.get_recent_messages("test_user", limit=5)
        print(f"   ✅ Got {len(recent)} recent messages")
        
        # Test 6: Get stats
        print("6. Getting statistics...")
        stats = db.get_user_stats("test_user")
        print(f"   ✅ User stats: {stats}")
        
        # Test 7: Database stats
        print("7. Getting database stats...")
        db_stats = db.get_database_stats()
        print(f"   ✅ Database stats: {db_stats}")
        
        # Test 8: Cleanup
        print("8. Cleaning up...")
        db.delete_user_memory("test_user")
        print("   ✅ Cleaned up")
        
        db.close()
        print("\n🎉 ALL DATABASE TESTS PASSED!")
        return True
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        print("Check your SQL syntax in database.py")
        return False

if __name__ == "__main__":
    success = test_database()
    if success:
        try:
            os.remove("test_memory.db")
            print("🧹 Cleaned up test database file")
        except:
            pass
    sys.exit(0 if success else 1)