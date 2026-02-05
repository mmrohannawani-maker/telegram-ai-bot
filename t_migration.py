from database import MemoryDatabase

db = MemoryDatabase()

# Test 1: Check connection
print("✅ Database connection established")

# Test 2: Run migration
print("🔄 Running migration...")
migrated = db.migrate_existing_users()
print(f"✅ Migrated {migrated} users")

# Test 3: Check notifications table
users = db.get_all_users_for_notifications()
print(f"📱 Users in notifications table: {len(users)}")
print(f"👤 User IDs: {users[:5]}")  # First 5 users

# Test 4: Get stats
count = db.get_user_count()
print(f"📊 Total active users: {count}")

db.close()