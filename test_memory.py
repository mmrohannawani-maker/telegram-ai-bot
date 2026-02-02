# test_memory.py - Debug memory separately
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import MemoryDatabase
from memory import PersistentHybridMemory

def test_memory():
    print("🧠 Testing Memory System...")
    
    # Create database
    db = MemoryDatabase("test_memory.db")
    
    # Create memory
    memory = PersistentHybridMemory("test_user_2", db, buffer_size=2)
    
    # Add conversations
    memory.add_conversation("Hello", "Hi there!")
    memory.add_conversation("How are you?", "I'm good")
    memory.add_conversation("What's up?", "Not much")
    
    print(f"✅ Added 3 conversations")
    print(f"✅ Buffer size: {len(memory.recent_messages)}")
    print(f"✅ Context:\n{memory.get_context()}")
    
    # Get stats
    stats = memory.get_stats()
    print(f"✅ Stats: {stats}")
    
    # Clear
    memory.clear()
    print("✅ Memory cleared")
    
    db.close()
    print("\n🎉 Memory tests passed!")

if __name__ == "__main__":
    test_memory()