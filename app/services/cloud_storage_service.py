import os
import uuid
import mimetypes
from typing import Optional, Tuple, Dict, Any
from pathlib import Path
from io import BytesIO

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from fastapi import HTTPException

from app.config import settings
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class CloudStorageService:
    """Handles cloud storage operations using AWS S3"""
    
    def __init__(self):
        self.use_cloud_storage = settings.use_cloud_storage
        if not self.use_cloud_storage:
            return
            
        try:
            # Initialize S3 client
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                region_name=settings.aws_region
            )
            self.bucket_name = settings.s3_bucket_name
            self.cloudfront_domain = settings.cloudfront_domain
            
            # Test connection
            self._test_connection()
            
        except NoCredentialsError:
            raise HTTPException(
                status_code=500, 
                detail="AWS credentials not configured properly"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to initialize cloud storage: {str(e)}"
            )
    
    def _test_connection(self):
        """Test S3 connection by listing bucket contents"""
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
        except ClientError as e:
            error_code = int(e.response['Error']['Code'])
            if error_code == 404:
                raise HTTPException(
                    status_code=500, 
                    detail=f"S3 bucket '{self.bucket_name}' not found"
                )
            elif error_code == 403:
                raise HTTPException(
                    status_code=500, 
                    detail=f"Access denied to S3 bucket '{self.bucket_name}'"
                )
            else:
                raise HTTPException(
                    status_code=500, 
                    detail=f"S3 connection error: {str(e)}"
                )
    
    def _generate_s3_key(self, file_path: str, file_type: str = "file") -> str:
        """
        Generate S3 key (path) for file storage
        Maintains folder structure similar to local storage
        """
        # Extract session_id from path if it's a session file
        if "/sess_" in file_path:
            parts = Path(file_path).parts
            session_part = None
            for part in parts:
                if part.startswith("sess_"):
                    session_part = part
                    break
            
            if session_part:
                # For session files: sessions/{session_id}/files/...
                return f"sessions/{session_part}/{file_type}s/{Path(file_path).name}"
        
        # For course materials: course-materials/{material_id}/...
        if "course_materials" in file_path:
            parts = Path(file_path).parts
            material_part = None
            for part in parts:
                if part != "course_materials" and "course_materials" in str(Path(file_path).parent):
                    material_part = part
                    break
            
            if material_part:
                return f"course-materials/{material_part}/{Path(file_path).name}"
        
        # Default structure
        return f"uploads/{file_type}s/{Path(file_path).name}"
    
    def _get_public_url(self, s3_key: str) -> str:
        """
        Generate public URL for S3 object
        Uses CloudFront if configured, otherwise direct S3 URL
        """
        if self.cloudfront_domain:
            return f"https://{self.cloudfront_domain}/{s3_key}"
        else:
            return f"https://{self.bucket_name}.s3.{settings.aws_region}.amazonaws.com/{s3_key}"
    
    async def upload_file(
        self, 
        file_content: bytes, 
        file_path: str, 
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None
    ) -> Tuple[str, str]:
        """
        Upload file to S3
        
        Returns:
            Tuple of (s3_key, public_url)
        """
        if not self.use_cloud_storage:
            raise HTTPException(
                status_code=500, 
                detail="Cloud storage is not enabled"
            )
        
        try:
            # Generate S3 key
            s3_key = self._generate_s3_key(file_path, "file")
            
            # Determine content type
            if not content_type:
                content_type, _ = mimetypes.guess_type(file_path)
                if not content_type:
                    content_type = 'application/octet-stream'
            
            # Upload to S3
            extra_args = {
                'ContentType': content_type,
                'ACL': 'public-read'  # Make files publicly accessible
            }
            
            if metadata:
                # Ensure all metadata values are strings (boto3 requirement)
                string_metadata = {}
                for key, value in metadata.items():
                    string_metadata[key] = str(value) if value is not None else ''
                extra_args['Metadata'] = string_metadata
            
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=file_content,
                **extra_args
            )
            
            # Generate public URL
            public_url = self._get_public_url(s3_key)
            
            return s3_key, public_url
            
        except ClientError as e:
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to upload file to S3: {str(e)}"
            )
    
    async def upload_image(
        self, 
        image_data: bytes, 
        file_path: str, 
        content_type: str = "image/png",
        metadata: Optional[Dict[str, str]] = None
    ) -> Tuple[str, str]:
        """
        Upload image to S3 with image-specific settings
        
        Returns:
            Tuple of (s3_key, public_url)
        """
        if not self.use_cloud_storage:
            logger.info("Cloud storage is not enabled")
            raise HTTPException(
                status_code=500, 
                detail="Cloud storage is not enabled"
            )
        
        try:
            # Generate S3 key
            logger.info("Generating S3 key")
            s3_key = self._generate_s3_key(file_path, "image")
            
            # Upload to S3 with image-specific settings
            logger.info("Uploading to S3")
            extra_args = {
                'ContentType': content_type,
                'ACL': 'public-read',
                'CacheControl': 'max-age=31536000'  # 1 year cache for images
            }
            
            if metadata:
                # Ensure all metadata values are strings (boto3 requirement)
                string_metadata = {}
                for key, value in metadata.items():
                    string_metadata[key] = str(value) if value is not None else ''
                extra_args['Metadata'] = string_metadata
            
            logger.info("Putting object")
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=image_data,
                **extra_args
            )
            
            # Generate public URL
            logger.info("Generating public URL")
            public_url = self._get_public_url(s3_key)
            
            logger.info(f"Uploaded image to S3: {s3_key}")
            return s3_key, public_url
            
        except ClientError as e:
            logger.error(f"Failed to upload image to S3: {str(e)}")
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to upload image to S3: {str(e)}"
            )
    
    async def delete_file(self, s3_key: str) -> bool:
        """
        Delete file from S3
        
        Returns:
            True if successful, False otherwise
        """
        if not self.use_cloud_storage:
            return False
        
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            return True
        except ClientError as e:
            print(f"Failed to delete file from S3: {str(e)}")
            return False
    
    async def file_exists(self, s3_key: str) -> bool:
        """
        Check if file exists in S3
        
        Returns:
            True if file exists, False otherwise
        """
        if not self.use_cloud_storage:
            return False
        
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=s3_key)
            return True
        except ClientError:
            return False
    
    def get_file_url(self, s3_key: str) -> str:
        """
        Get public URL for S3 object
        
        Returns:
            Public URL for the file
        """
        if not self.use_cloud_storage:
            return ""
        
        return self._get_public_url(s3_key)
    
    async def generate_presigned_url(
        self, 
        s3_key: str, 
        expiration: int = 3600,
        http_method: str = 'GET'
    ) -> str:
        """
        Generate presigned URL for S3 object
        
        Args:
            s3_key: S3 object key
            expiration: URL expiration time in seconds (default: 1 hour)
            http_method: HTTP method (GET, PUT, etc.)
        
        Returns:
            Presigned URL
        """
        if not self.use_cloud_storage:
            return ""
        
        try:
            response = self.s3_client.generate_presigned_url(
                http_method,
                Params={'Bucket': self.bucket_name, 'Key': s3_key},
                ExpiresIn=expiration
            )
            return response
        except ClientError as e:
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to generate presigned URL: {str(e)}"
            )


# Global instance
cloud_storage = CloudStorageService()
