# 🚆 Railway Deployment Guide

This guide will help you deploy your ProfSidekick backend to Railway.

## Prerequisites

1. **Railway Account**: Sign up at [railway.app](https://railway.app)
2. **GitHub Repository**: Your code should be in a GitHub repository
3. **Environment Variables**: You'll need your OpenAI API key and other secrets

## 🚀 Deployment Steps

### 1. Connect to Railway

1. Go to [railway.app](https://railway.app)
2. Sign in with your GitHub account
3. Click "Start a New Project"
4. Select "Deploy from GitHub repo"
5. Choose your `profsidekick/backend` repository

### 2. Add PostgreSQL Database

1. In your Railway project dashboard, click "New Service"
2. Select "Database" → "PostgreSQL"
3. Railway will automatically create a PostgreSQL instance
4. The `DATABASE_URL` environment variable will be automatically injected

### 3. Configure Environment Variables

In your Railway project dashboard, go to your backend service → "Variables" tab and add:

```bash
# Required
OPENAI_API_KEY=your_openai_api_key_here
SECRET_KEY=your-super-secret-key-for-production

# Optional (Railway provides good defaults)
DEBUG=false
APP_NAME=ProfSidekick API
UPLOAD_DIR=/app/uploads
STATIC_DIR=/app/static
MAX_FILE_SIZE=52428800
ALLOWED_FILE_TYPES=.pptx,.ppt,.pdf

# CORS (add your frontend domain)
CORS_ORIGINS=https://profsidekick.vercel.app,http://localhost:3000,https://profsidekick-frontend-3il7.vercel.app
```

### 4. Deploy

1. Railway will automatically deploy when you push to your main branch
2. First deployment might take 3-5 minutes
3. Check the "Deployments" tab for build logs
4. Your app will be available at `https://your-project-name.up.railway.app`

### 5. Set Up Domain (Optional)

1. In Railway dashboard, go to "Settings" → "Domains"
2. You can use the provided `*.up.railway.app` domain
3. Or connect your custom domain

### 6. Database Migration

Railway will automatically run your database migrations if you have them set up in your startup code.

## 📊 Monitoring

- **Logs**: View real-time logs in Railway dashboard
- **Metrics**: Monitor CPU, memory, and network usage
- **Health Check**: Railway automatically monitors `/health` endpoint

## 💰 Pricing

- **Starter Plan**: $5/month credit (usually covers small apps)
- **Developer Plan**: $10/month for more resources
- **PostgreSQL**: Included in the plan
- **Bandwidth**: Generous limits

## 🔧 Post-Deployment

1. **Test API**: Visit `https://your-app.up.railway.app/docs` to test API
2. **Update Frontend**: Update your frontend to use the new Railway URL
3. **Monitor**: Check logs and metrics regularly

## 🚨 Troubleshooting

### Common Issues:

1. **Build Fails**: Check that all dependencies are in `requirements.txt`
2. **Database Connection**: Ensure PostgreSQL service is added to project
3. **Environment Variables**: Verify all required env vars are set
4. **CORS Issues**: Add your frontend domain to CORS_ORIGINS

### Useful Commands:

```bash
# View logs
railway logs

# Deploy manually
railway up

# Connect to database
railway connect
```

## 📝 Next Steps

After successful deployment:

1. ✅ Update your frontend environment variables to point to Railway URL
2. ✅ Test all API endpoints
3. ✅ Monitor application performance
4. ✅ Set up monitoring alerts (optional)

Your Railway deployment should now be live! 🎉
