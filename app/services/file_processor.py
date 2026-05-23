import os
import uuid
from typing import List, Tuple, Dict, Any
from pathlib import Path
from PIL import Image
import io

# PowerPoint processing
from pptx import Presentation as PPTXPresentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

# PDF processing
import PyPDF2
from pdf2image import convert_from_path

from app.config import settings
from app.services.cloud_storage_service import cloud_storage


class FileProcessor:
    """Handles processing of presentation files (PowerPoint and PDF)"""
    
    def __init__(self):
        self.upload_dir = Path(settings.upload_dir)
        self.static_dir = Path(settings.static_dir)

    async def convert_presentation_to_images(self, file_path: str, session_id: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Convert presentation to images
        """
        # if file_path.endswith('.pptx') or file_path.endswith('.ppt'):
            # return await self._convert_pptx_to_images(file_path, session_id)
        if file_path.endswith('.pdf'):
            return await self._convert_pdf_to_images(file_path, session_id)
        else:
            raise ValueError(f"Unsupported file type: {file_path}")

    async def _convert_pdf_to_images(self, file_path: str, session_id: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        # Convert PDF pages to images
        try:
            # Create session-specific directories
            session_slides_dir = self.upload_dir / session_id / "slides"
            session_slides_dir.mkdir(parents=True, exist_ok=True)

            # Check if file_path is a cloud storage URL
            if file_path.startswith('https://') and settings.use_cloud_storage:
                # Download file from S3 to local temp directory
                print(f"Downloading PDF from cloud storage: {file_path}")
                import requests
                import tempfile
                
                try:
                    response = requests.get(file_path, timeout=30)
                    response.raise_for_status()
                    
                    # Create temporary file
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                        temp_file.write(response.content)
                        temp_file_path = temp_file.name
                    
                    print(f"Downloaded PDF to temporary file: {temp_file_path}")
                    pdf_images = convert_from_path(
                        temp_file_path, 
                        dpi=150,  # Good quality for display
                        first_page=1,
                        fmt='PNG'
                    )
                    
                    # Clean up temporary file
                    os.unlink(temp_file_path)
                    
                except requests.RequestException as e:
                    print(f"Failed to download PDF from cloud storage: {e}")
                    raise Exception(f"Failed to download PDF from cloud storage: {e}")
                except Exception as e:
                    print(f"Error processing downloaded PDF: {e}")
                    # Clean up temporary file if it exists
                    if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
                        os.unlink(temp_file_path)
                    raise Exception(f"Error processing downloaded PDF: {e}")
            else:
                # Use local file path
                print(f"Converting PDF to images: {file_path}")
                pdf_images = convert_from_path(
                    file_path, 
                    dpi=150,  # Good quality for display
                    first_page=1,
                    fmt='PNG'
                )
            print(f"Successfully converted {len(pdf_images)} pages to images")

            pdf_images_paths = []

            for page_num, pdf_image in enumerate(pdf_images):
                image_filename = f"slide_{page_num}.png"
                thumbnail_filename = f"thumb_{page_num}.png"

                # Save full-size image
                full_image_path = session_slides_dir / image_filename
                pdf_image.save(full_image_path, 'PNG')
                print(f"Saved slide image: {full_image_path}")

                # Create and save thumbnail (256x192)
                thumbnail_image = pdf_image.copy()
                thumbnail_image.thumbnail((256, 192), Image.Resampling.LANCZOS)
                thumbnail_path = session_slides_dir / thumbnail_filename
                thumbnail_image.save(thumbnail_path, 'PNG')
                print(f"Saved thumbnail: {thumbnail_path}")

                # Determine image paths based on storage method
                if settings.use_cloud_storage:
                    # Upload images to cloud storage
                    try:
                        # Convert PIL images to bytes properly
                        import io
                        
                        # Convert full-size image to bytes
                        full_image_buffer = io.BytesIO()
                        pdf_image.save(full_image_buffer, format='PNG')
                        full_image_bytes = full_image_buffer.getvalue()
                        
                        # Convert thumbnail to bytes
                        thumbnail_buffer = io.BytesIO()
                        thumbnail_image.save(thumbnail_buffer, format='PNG')
                        thumbnail_bytes = thumbnail_buffer.getvalue()
                        
                        # Upload full-size image
                        full_s3_key, full_public_url = await cloud_storage.upload_image(
                            image_data=full_image_bytes,
                            file_path=str(full_image_path),
                            content_type='image/png',
                            metadata={
                                'session_id': session_id,
                                'slide_number': str(page_num + 1),
                                'image_type': 'full_size'
                            }
                        )
                        
                        # Upload thumbnail
                        thumbnail_s3_key, thumbnail_public_url = await cloud_storage.upload_image(
                            image_data=thumbnail_bytes,
                            file_path=str(thumbnail_path),
                            content_type='image/png',
                            metadata={
                                'session_id': session_id,
                                'slide_number': str(page_num + 1),
                                'image_type': 'thumbnail'
                            }
                        )
                        
                        pdf_images_paths.append({
                            "imagePath": full_public_url,
                            "thumbnailPath": thumbnail_public_url,
                            "slideNumber": page_num + 1
                        })
                        
                        # Clean up local files if cloud upload successful
                        if full_image_path.exists():
                            full_image_path.unlink()
                        if thumbnail_path.exists():
                            thumbnail_path.unlink()
                            
                    except Exception as e:
                        print(f"Failed to upload images to cloud storage: {e}")
                        # Fallback to local paths
                        pdf_images_paths.append({
                            "imagePath": f"/uploads/{session_id}/slides/{image_filename}",
                            "thumbnailPath": f"/uploads/{session_id}/slides/{thumbnail_filename}",
                            "slideNumber": page_num + 1
                        })
                else:
                    # Use local file paths
                    pdf_images_paths.append({
                        "imagePath": f"/uploads/{session_id}/slides/{image_filename}",
                        "thumbnailPath": f"/uploads/{session_id}/slides/{thumbnail_filename}",
                        "slideNumber": page_num + 1
                    })

        except Exception as e:
            print(f"Error converting PDF to images: {str(e)}")
            raise Exception(f"Error converting PDF to images: {str(e)}")
        
        return pdf_images, pdf_images_paths
 
    def validate_file(self, file_content: bytes, filename: str) -> Tuple[bool, str]:
        # Check file size
        # if len(file_content) > settings.max_file_size:
        #     return False, f"File size exceeds maximum allowed size of {settings.max_file_size / 1024 / 1024:.1f}MB"
        
        # Check file extension
        file_ext = Path(filename).suffix.lower()
        if file_ext not in settings.allowed_file_types:
            return False, f"File type {file_ext} not allowed. Supported types: {', '.join(settings.allowed_file_types)}"
        
        # Basic file validation (magic number checking could be added here)
        if len(file_content) == 0:
            return False, "File is empty"
        
        return True, ""
    
    async def save_uploaded_file(self, file_content: bytes, filename: str, session_id: str) -> str:
        """
        Save uploaded file to disk or cloud storage
        
        Returns:
            Path to saved file (local path or cloud URL)
        """
        # Generate unique filename
        file_ext = Path(filename).suffix.lower()
        unique_filename = f"{uuid.uuid4()}_{filename}{file_ext}"
        session_dir = self.upload_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        file_path = session_dir / unique_filename
        
        if settings.use_cloud_storage:
            # Upload to cloud storage
            try:
                s3_key, public_url = await cloud_storage.upload_file(
                    file_content=file_content,
                    file_path=str(file_path),
                    content_type=None,  # Let boto3 determine content type
                    metadata={
                        'session_id': session_id,
                        'original_filename': filename,
                        'file_type': 'presentation'
                    }
                )
                return public_url
            except Exception as e:
                print(f"Failed to upload to cloud storage, falling back to local: {e}")
                # Fallback to local storage
                pass
        
        # Save file locally
        with open(file_path, 'wb') as f:
            f.write(file_content)

        return str(file_path)