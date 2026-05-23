#!/usr/bin/env python3
"""
Railway startup script for ProfSidekick Backend
This Python script handles the PORT environment variable and database migrations
"""

import os
import sys
import subprocess
import time

def setup_database():
    """Set up database tables for fresh deployment"""
    
    # Get DATABASE_URL
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        print("⚠️  No DATABASE_URL found, skipping database setup (likely local development)")
        return True
    
    if "sqlite" in database_url.lower():
        print("⚠️  SQLite database detected, skipping database setup (likely local development)")
        return True
    
    print("🔄 Setting up fresh database...")
    
    try:
        # Create all tables from SQLAlchemy models
        print("📋 Creating tables from models...")
        result = subprocess.run(
            ["python", "-c", """
from app.database.connection import engine, Base
from app.database.models import User, Session, Course, SessionRun, SavedPrompt  # Import all models
print('Creating all tables...')
Base.metadata.create_all(bind=engine)
print('All tables created successfully')
"""],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            print(f"❌ Table creation failed")
            print(f"STDOUT: {result.stdout}")
            print(f"STDERR: {result.stderr}")
            return False
        
        print("✅ All tables created successfully")
        
        # Mark migrations as current (so future migrations work)
        print("🏷️  Marking database as up-to-date...")
        stamp_result = subprocess.run(
            ["python", "-m", "alembic", "stamp", "head"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if stamp_result.returncode == 0:
            print("✅ Database marked as up-to-date")
        else:
            print("⚠️  Could not mark database as up-to-date, but tables exist")
            print(f"STDOUT: {stamp_result.stdout}")
            print(f"STDERR: {stamp_result.stderr}")
        
        return True
            
    except subprocess.TimeoutExpired:
        print("❌ Database setup timed out")
        return False
    except Exception as e:
        print(f"❌ Database setup error: {e}")
        return False

def wait_for_database():
    """Wait for database to be available (useful for Railway startup)"""
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url or "sqlite" in database_url.lower():
        return True
    
    print("🔄 Waiting for database to be ready...")
    
    for attempt in range(30):  # Wait up to 30 seconds
        try:
            # Try to connect to database using a simple Python check
            result = subprocess.run(
                ["python", "-c", "from app.database.connection import engine; engine.connect()"],
                capture_output=True,
                timeout=5
            )
            
            if result.returncode == 0:
                print("✅ Database is ready")
                return True
                
        except Exception:
            pass
        
        if attempt < 29:  # Don't sleep on the last attempt
            print(f"⏳ Database not ready yet, waiting... (attempt {attempt + 1}/30)")
            time.sleep(1)
    
    print("⚠️  Database connection timeout, proceeding anyway...")
    return True



def main():
    print("🚀 Starting ProfSidekick Backend...")
    
    # Get PORT from environment, default to 8000
    port = os.getenv("PORT", "8000")
    
    # Validate port is a number
    try:
        port_int = int(port)
        if port_int <= 0 or port_int > 65535:
            raise ValueError("Port must be between 1 and 65535")
    except ValueError as e:
        print(f"❌ Error: Invalid port '{port}': {e}")
        sys.exit(1)
    
    # Wait for database to be ready (important for Railway)
    if not wait_for_database():
        print("❌ Database not available, exiting...")
        sys.exit(1)
    
    # Set up database (clean approach for fresh deployment)
    if not setup_database():
        print("❌ Database setup failed, exiting...")
        sys.exit(1)
    
    print(f"🌟 Starting ProfSidekick API on port {port}...")
    
    # Build uvicorn command
    cmd = [
        "python", "-m", "uvicorn", 
        "app.main:app",
        "--host", "0.0.0.0",
        "--port", str(port)
    ]
    
    # Add debug logging if DEBUG env var is set
    if os.getenv("DEBUG", "").lower() in ("true", "1", "yes"):
        cmd.extend(["--log-level", "debug", "--reload"])
    else:
        cmd.extend(["--log-level", "info"])
    
    # Execute uvicorn
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error starting server: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n👋 Shutting down server...")
        sys.exit(0)

if __name__ == "__main__":
    main()
