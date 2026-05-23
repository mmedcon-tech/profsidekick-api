#!/bin/bash

# ProfSidekick Backend - Fly.io Setup Script

echo "🚀 Setting up ProfSidekick Backend for Fly.io deployment..."

# Check if Fly CLI is installed
if ! command -v fly &> /dev/null; then
    echo "📥 Installing Fly CLI..."
    curl -L https://fly.io/install.sh | sh
    export PATH="$HOME/.fly/bin:$PATH"
    echo "✅ Fly CLI installed"
else
    echo "✅ Fly CLI already installed"
fi

# Login to Fly.io
echo "🔐 Please login to Fly.io..."
fly auth login

# List organizations to choose from
echo "📋 Available organizations:"
fly orgs list

echo ""
echo "🏢 Which organization would you like to deploy under?"
read -p "Enter organization name (or press Enter for personal): " ORG_NAME

# Initialize the app
if [ -n "$ORG_NAME" ]; then
    echo "🎯 Initializing app under organization: $ORG_NAME"
    fly launch --no-deploy --org "$ORG_NAME"
else
    echo "🎯 Initializing app under personal account"
    fly launch --no-deploy
fi

echo "✅ Fly.io setup complete!"
echo ""
echo "📝 Next steps:"
echo "1. Create a PostgreSQL database: fly postgres create"
echo "2. Set environment variables: fly secrets set SECRET_KEY=your-secret-key"
echo "3. Deploy: fly deploy" 