#!/usr/bin/env python3
"""
ProfSidekick Backend Setup Script
Helps with initial setup and configuration checks
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path


def check_python_version():
    """Check if Python version is 3.11+"""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 11):
        print("❌ Python 3.11+ is required")
        print(f"   Current version: {version.major}.{version.minor}.{version.micro}")
        return False
    print(f"✅ Python {version.major}.{version.minor}.{version.micro}")
    return True


def check_command(command, name):
    """Check if a command is available"""
    if shutil.which(command):
        try:
            result = subprocess.run([command, "--version"], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                version = result.stdout.split('\n')[0]
                print(f"✅ {name}: {version}")
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    
    print(f"❌ {name} not found or not working")
    return False


def check_docker():
    """Check Docker and Docker Compose"""
    docker_ok = check_command("docker", "Docker")
    compose_ok = check_command("docker-compose", "Docker Compose")
    return docker_ok and compose_ok


def check_postgresql():
    """Check PostgreSQL availability"""
    return check_command("psql", "PostgreSQL Client")


def check_redis():
    """Check Redis availability"""
    return check_command("redis-cli", "Redis CLI")


def create_env_file():
    """Create .env file from template"""
    env_example = Path("env.example")
    env_file = Path(".env")
    
    if not env_example.exists():
        print("❌ env.example file not found")
        return False
    
    if env_file.exists():
        response = input("📝 .env file already exists. Overwrite? (y/N): ")
        if response.lower() != 'y':
            print("   Keeping existing .env file")
            return True
    
    try:
        # Copy template
        shutil.copy(env_example, env_file)
        print("✅ Created .env file from template")
        
        # Prompt for essential variables
        print("\n📋 Please configure these essential environment variables:")
        print("   Edit .env file and set:")
        print("   - OPENAI_API_KEY: Your OpenAI API key")
        print("   - DATABASE_URL: PostgreSQL connection string")
        print("   - REDIS_URL: Redis connection string")
        print("   - SECRET_KEY: A secure secret key")
        
        return True
    except Exception as e:
        print(f"❌ Error creating .env file: {e}")
        return False


def create_directories():
    """Create necessary directories"""
    directories = ["uploads", "static", "static/slides"]
    
    for directory in directories:
        try:
            Path(directory).mkdir(parents=True, exist_ok=True)
            print(f"✅ Created directory: {directory}")
        except Exception as e:
            print(f"❌ Error creating directory {directory}: {e}")
            return False
    
    return True


def install_dependencies():
    """Install Python dependencies"""
    if not Path("requirements.txt").exists():
        print("❌ requirements.txt not found")
        return False
    
    try:
        print("📦 Installing Python dependencies...")
        result = subprocess.run([
            sys.executable, "-m", "pip", "install", "-r", "requirements.txt"
        ], check=True, capture_output=True, text=True)
        
        print("✅ Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Error installing dependencies: {e}")
        print(f"   Error output: {e.stderr}")
        return False


def test_openai_connection():
    """Test OpenAI API connection"""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or api_key == "your_openai_api_key_here":
            print("⚠️  OpenAI API key not configured")
            return False
        
        # Test connection
        import openai
        client = openai.OpenAI(api_key=api_key)
        models = client.models.list()
        print("✅ OpenAI API connection successful")
        return True
        
    except ImportError:
        print("⚠️  OpenAI package not installed, skipping connection test")
        return False
    except Exception as e:
        print(f"❌ OpenAI API connection failed: {e}")
        return False


def main():
    """Main setup function"""
    print("🚀 ProfSidekick Backend Setup")
    print("=" * 40)
    
    # Check Python version
    if not check_python_version():
        print("\n💡 Please install Python 3.11 or later")
        sys.exit(1)
    
    # Check dependencies
    print("\n🔍 Checking system dependencies:")
    docker_available = check_docker()
    postgres_available = check_postgresql()
    redis_available = check_redis()
    
    # Deployment recommendation
    print("\n📋 Deployment Options:")
    if docker_available:
        print("✅ Docker deployment available (recommended)")
        print("   Run: docker-compose up -d")
    else:
        print("❌ Docker not available")
    
    if postgres_available and redis_available:
        print("✅ Local development setup possible")
    else:
        print("⚠️  Local development requires PostgreSQL and Redis")
    
    # Setup configuration
    print("\n⚙️  Setting up configuration:")
    if not create_env_file():
        sys.exit(1)
    
    if not create_directories():
        sys.exit(1)
    
    # Install dependencies
    response = input("\n📦 Install Python dependencies? (Y/n): ")
    if response.lower() != 'n':
        if not install_dependencies():
            print("⚠️  You can install dependencies later with: pip install -r requirements.txt")
    
    # Test connections
    print("\n🔌 Testing connections:")
    test_openai_connection()
    
    # Final instructions
    print("\n✅ Setup complete!")
    print("\n📚 Next steps:")
    print("1. Configure .env file with your API keys and connection strings")
    print("2. Choose deployment method:")
    print("   - Docker: docker-compose up -d")
    print("   - Local: python -m uvicorn app.main:app --reload")
    print("3. Access API documentation: http://localhost:8000/docs")
    print("4. Health check: http://localhost:8000/health")
    
    print("\n🔗 Useful commands:")
    print("   - Run tests: pytest tests/")
    print("   - View logs: docker-compose logs -f backend")
    print("   - Stop services: docker-compose down")


if __name__ == "__main__":
    main() 