# AWS S3 Cloud Storage Setup Guide

This guide will help you set up AWS S3 cloud storage for your ProfSidekick backend.

## 🚀 Quick Setup

### 1. AWS Account Setup

1. **Create AWS Account** (if you don't have one):
   - Go to [AWS Console](https://aws.amazon.com/console/)
   - Sign up for an account
   - Complete verification process

2. **Create S3 Bucket**:
   ```bash
   # Via AWS CLI (recommended)
   aws s3 mb s3://your-profsidekick-bucket --region us-east-1
   
   # Or via AWS Console:
   # 1. Go to S3 service
   # 2. Click "Create bucket"
   # 3. Choose unique name (e.g., profsidekick-files-2024)
   # 4. Select region (us-east-1 recommended)
   # 5. Uncheck "Block all public access" for public file access
   ```

3. **Configure Bucket Policy** (for public access):
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Sid": "PublicReadGetObject",
         "Effect": "Allow",
         "Principal": "*",
         "Action": "s3:GetObject",
         "Resource": "arn:aws:s3:::your-profsidekick-bucket/*"
       }
     ]
   }
   ```

### 2. AWS Credentials Setup

1. **Create IAM User**:
   - Go to IAM service in AWS Console
   - Click "Users" → "Create user"
   - Username: `profsidekick-s3-user`
   - Attach policy: `AmazonS3FullAccess` (for development)
   - Or create custom policy with minimal permissions:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "s3:GetObject",
           "s3:PutObject",
           "s3:DeleteObject",
           "s3:PutObjectAcl"
         ],
         "Resource": "arn:aws:s3:::your-profsidekick-bucket/*"
       },
       {
         "Effect": "Allow",
         "Action": "s3:ListBucket",
         "Resource": "arn:aws:s3:::your-profsidekick-bucket"
       }
     ]
   }
   ```

2. **Generate Access Keys**:
   - Go to your user → "Security credentials" tab
   - Click "Create access key"
   - Choose "Application running outside AWS"
   - Save the Access Key ID and Secret Access Key

### 3. Environment Configuration

1. **Update your `.env` file**:
   ```bash
   # Enable cloud storage
   USE_CLOUD_STORAGE=true
   
   # AWS Credentials
   AWS_ACCESS_KEY_ID=your_access_key_id_here
   AWS_SECRET_ACCESS_KEY=your_secret_access_key_here
   AWS_REGION=us-east-1
   
   # S3 Configuration
   S3_BUCKET_NAME=your-profsidekick-bucket
   S3_BUCKET_REGION=us-east-1
   
   # Optional: CloudFront CDN (for better performance)
   CLOUDFRONT_DOMAIN=your-cloudfront-domain.cloudfront.net
   ```

2. **Install Dependencies**:
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

### 4. Test the Setup

1. **Start your backend**:
   ```bash
   python -m uvicorn app.main:app --reload
   ```

2. **Test file upload**:
   - Go to `/docs` endpoint
   - Try uploading a file through the course materials API
   - Check your S3 bucket to see if files appear

## 🔧 Advanced Configuration

### CloudFront CDN (Optional but Recommended)

For better performance and global distribution:

1. **Create CloudFront Distribution**:
   - Go to CloudFront service
   - Click "Create distribution"
   - Origin domain: Select your S3 bucket
   - Default cache behavior: Allow GET, HEAD, OPTIONS
   - Price class: Choose based on your needs

2. **Update Environment**:
   ```bash
   CLOUDFRONT_DOMAIN=d1234567890.cloudfront.net
   ```

### Security Best Practices

1. **Use IAM Roles** (for production):
   ```bash
   # Instead of access keys, use IAM roles
   # This is automatically handled by AWS services
   ```

2. **Bucket Versioning**:
   ```bash
   # Enable versioning for data protection
   aws s3api put-bucket-versioning \
     --bucket your-profsidekick-bucket \
     --versioning-configuration Status=Enabled
   ```

3. **Lifecycle Policies**:
   ```bash
   # Set up automatic cleanup of old files
   # Go to S3 bucket → Management → Lifecycle rules
   ```

## 📁 File Structure in S3

Your files will be organized as follows:

```
your-profsidekick-bucket/
├── sessions/
│   └── sess_[session_id]/
│       ├── files/
│       │   └── [uuid]_presentation.pdf
│       └── images/
│           ├── slide_0.png
│           ├── thumb_0.png
│           └── ...
└── course-materials/
    └── [material_id]/
        └── [uuid]_material.pdf
```

## 🔄 Migration from Local Storage

If you have existing local files:

1. **Backup existing files**:
   ```bash
   cp -r uploads/ uploads_backup/
   ```

2. **Upload to S3** (optional script):
   ```python
   # Create a migration script to upload existing files
   import boto3
   import os
   from pathlib import Path
   
   def migrate_files():
       s3 = boto3.client('s3')
       bucket = 'your-profsidekick-bucket'
       
       for file_path in Path('uploads').rglob('*'):
           if file_path.is_file():
               s3_key = f"migrated/{file_path.relative_to('uploads')}"
               s3.upload_file(str(file_path), bucket, s3_key)
               print(f"Uploaded: {s3_key}")
   ```

## 🐛 Troubleshooting

### Common Issues

1. **Access Denied Error**:
   - Check IAM user permissions
   - Verify bucket policy
   - Ensure access keys are correct

2. **Bucket Not Found**:
   - Verify bucket name in environment
   - Check AWS region setting
   - Ensure bucket exists in the specified region

3. **Connection Timeout**:
   - Check AWS region configuration
   - Verify network connectivity
   - Check AWS service status

### Debug Mode

Enable debug logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Health Check

Test your S3 connection:
```python
# Add this endpoint to test S3 connection
@app.get("/health/s3")
async def health_check_s3():
    try:
        cloud_storage._test_connection()
        return {"status": "healthy", "storage": "s3"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
```

## 💰 Cost Optimization

### S3 Pricing Tips

1. **Storage Classes**:
   - Standard: For frequently accessed files
   - IA (Infrequent Access): For older files
   - Glacier: For long-term archival

2. **Lifecycle Rules**:
   ```json
   {
     "Rules": [
       {
         "ID": "MoveOldFiles",
         "Status": "Enabled",
         "Transitions": [
           {
             "Days": 30,
             "StorageClass": "STANDARD_IA"
           },
           {
             "Days": 90,
             "StorageClass": "GLACIER"
           }
         ]
       }
     ]
   }
   ```

3. **Monitor Usage**:
   - Set up billing alerts
   - Use AWS Cost Explorer
   - Monitor S3 metrics

## 🚀 Production Deployment

### Railway Deployment

1. **Set Environment Variables**:
   ```bash
   # In Railway dashboard
   USE_CLOUD_STORAGE=true
   AWS_ACCESS_KEY_ID=your_key
   AWS_SECRET_ACCESS_KEY=your_secret
   S3_BUCKET_NAME=your-bucket
   ```

2. **Update CORS Origins**:
   ```bash
   CORS_ORIGINS=https://your-frontend-domain.com
   ```

### Security Checklist

- [ ] Use IAM roles instead of access keys
- [ ] Enable bucket versioning
- [ ] Set up lifecycle policies
- [ ] Configure CloudFront for HTTPS
- [ ] Set up monitoring and alerts
- [ ] Regular backup verification

## 📞 Support

If you encounter issues:

1. Check AWS CloudTrail for API errors
2. Review S3 access logs
3. Test with AWS CLI: `aws s3 ls s3://your-bucket`
4. Check IAM permissions: `aws iam simulate-principal-policy`

---

**Note**: This setup provides a robust, scalable file storage solution. The system automatically falls back to local storage if cloud storage fails, ensuring reliability.
