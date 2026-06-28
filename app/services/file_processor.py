import os
import subprocess
import sys
import tempfile
import uuid
from typing import List, Tuple, Dict, Any, Optional
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import io

# PowerPoint processing
from pptx import Presentation as PPTXPresentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

# Word document processing
try:
    from docx import Document as DocxDocument
    _DOCX_AVAILABLE = True
except ImportError:
    _DOCX_AVAILABLE = False

# PDF processing
import PyPDF2
from pdf2image import convert_from_path

from app.config import settings
from app.services.cloud_storage_service import cloud_storage

# All formats now go through Vision API via LibreOffice conversion.
# Text-extraction methods are retained for knowledge-base chunking only.
_TEXT_EXTRACTION_EXTS: set = set()


class FileProcessor:
    """Handles processing of presentation files (PowerPoint and PDF)"""
    
    def __init__(self):
        self.upload_dir = Path(settings.upload_dir)
        self.static_dir = Path(settings.static_dir)

    def is_text_extraction_format(self, filename: str) -> bool:
        """Return True for formats handled by text extraction (not the Vision pipeline)."""
        return Path(filename).suffix.lower() in _TEXT_EXTRACTION_EXTS

    def extract_text_content(self, file_path: str, source: str = "student") -> List[Dict[str, Any]]:
        """
        Extract text from PPTX, PPT, or DOCX and return a list of slide-compatible dicts.

        Each dict matches the shape that Vision-processed slides produce:
          { slideNumber, title, content, imagePath, thumbnailPath, source }

        This allows the rest of the pipeline (slides_details storage, context injection)
        to work identically for PDF and text-based formats.
        """
        ext = Path(file_path).suffix.lower()
        if ext == ".pptx":
            return self._extract_pptx_content(file_path, source)
        if ext == ".docx":
            return self._extract_docx_content(file_path, source)
        if ext == ".ppt":
            raise ValueError(
                ".ppt (legacy binary format) cannot be text-extracted. "
                "Install LibreOffice to process .ppt files."
            )
        raise ValueError(f"extract_text_content does not handle {ext}")

    def _extract_pptx_content(self, file_path: str, source: str) -> List[Dict[str, Any]]:
        """Extract per-slide text from a PPTX file using python-pptx."""
        try:
            prs = PPTXPresentation(file_path)
        except Exception as e:
            raise ValueError(f"Failed to open PPTX file: {e}")

        slides_out: List[Dict[str, Any]] = []
        for idx, slide in enumerate(prs.slides, start=1):
            title_text = ""
            body_parts: List[str] = []

            for shape in slide.shapes:
                if not shape.has_text_frame:
                    continue
                text = shape.text_frame.text.strip()
                if not text:
                    continue
                # Heuristic: placeholder index 0 or title shape → treat as title
                if (hasattr(shape, "placeholder_format") and
                        shape.placeholder_format is not None and
                        shape.placeholder_format.idx == 0):
                    title_text = text
                else:
                    body_parts.append(text)

            # Speaker notes
            if slide.has_notes_slide:
                notes = slide.notes_slide.notes_text_frame.text.strip()
                if notes:
                    body_parts.append(f"[Speaker notes] {notes}")

            content = "\n\n".join(body_parts) if body_parts else "(No text content)"
            slides_out.append({
                "id": idx,
                "slideNumber": idx,
                "title": title_text or f"Slide {idx}",
                "content": content,
                "imagePath": None,
                "thumbnailPath": None,
                "source": source,
            })

        return slides_out

    def _extract_docx_content(self, file_path: str, source: str) -> List[Dict[str, Any]]:
        """
        Extract text from a DOCX file and split into logical sections.

        Strategy: group paragraphs by heading boundaries. Each Heading 1/2 starts
        a new 'slide'. Non-heading content is appended to the current section body.
        Minimum section size is 1 paragraph; long headingless docs are split every
        DOCX_CHUNK_PARAGRAPHS paragraphs.
        """
        CHUNK_SIZE = 25  # paragraphs per section for headingless docs

        if not _DOCX_AVAILABLE:
            raise ValueError(
                "python-docx is not installed. Run: pip install python-docx"
            )
        try:
            doc = DocxDocument(file_path)
        except Exception as e:
            raise ValueError(f"Failed to open DOCX file: {e}")

        HEADING_STYLES = {"heading 1", "heading 2", "heading 3", "title"}

        sections: List[Dict[str, Any]] = []
        current_title = "Document Start"
        current_body: List[str] = []
        slide_num = 1

        def _flush(title: str, body: List[str], num: int) -> Optional[Dict[str, Any]]:
            content = "\n".join(body).strip()
            if not content and not title:
                return None
            return {
                "id": num,
                "slideNumber": num,
                "title": title or f"Section {num}",
                "content": content or "(No text content)",
                "imagePath": None,
                "thumbnailPath": None,
                "source": source,
            }

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            style_name = (para.style.name or "").lower()
            is_heading = any(style_name.startswith(h) for h in HEADING_STYLES)

            if is_heading:
                # Flush previous section
                if current_body:
                    section = _flush(current_title, current_body, slide_num)
                    if section:
                        sections.append(section)
                        slide_num += 1
                    current_body = []
                current_title = text
            else:
                current_body.append(text)
                # Force-flush at chunk boundary for headingless docs
                if len(current_body) >= CHUNK_SIZE:
                    section = _flush(current_title, current_body, slide_num)
                    if section:
                        sections.append(section)
                        slide_num += 1
                    current_body = []
                    current_title = ""

        # Flush remaining content
        if current_body or current_title:
            section = _flush(current_title, current_body, slide_num)
            if section:
                sections.append(section)

        # Edge-case: empty document
        if not sections:
            sections.append({
                "id": 1,
                "slideNumber": 1,
                "title": "Document",
                "content": "(Document appears to be empty)",
                "imagePath": None,
                "thumbnailPath": None,
                "source": source,
            })

        return sections

    def render_slides_as_images(self, slides: List[Dict[str, Any]], session_id: str) -> List[Dict[str, Any]]:
        """
        Render text-extracted slides as PNG images using Pillow.
        Called when LibreOffice is absent so DOCX/PPTX slides still get real imagePath values.
        Saves images to the same local path structure as the Vision pipeline.
        """
        W, H = 1280, 720

        def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
            candidates = (
                ["arialbd.ttf", "Arial Bold.ttf", "Arial_Bold.ttf"] if bold
                else ["arial.ttf", "Arial.ttf"]
            ) + (
                ["DejaVuSans-Bold.ttf", "FreeSansBold.ttf"] if bold
                else ["DejaVuSans.ttf", "FreeSans.ttf"]
            )
            for name in candidates:
                try:
                    return ImageFont.truetype(name, size)
                except Exception:
                    pass
            try:
                return ImageFont.load_default(size=size)
            except TypeError:
                return ImageFont.load_default()

        def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int) -> List[str]:
            words = text.split()
            lines: List[str] = []
            current = ""
            for word in words:
                candidate = (current + " " + word).strip()
                try:
                    w = draw.textbbox((0, 0), candidate, font=font)[2]
                except Exception:
                    w = len(candidate) * 12  # rough fallback
                if w <= max_w:
                    current = candidate
                else:
                    if current:
                        lines.append(current)
                    current = word
            if current:
                lines.append(current)
            return lines or [""]

        session_slides_dir = self.upload_dir / session_id / "slides"
        session_slides_dir.mkdir(parents=True, exist_ok=True)

        title_font = _load_font(40, bold=True)
        body_font  = _load_font(22)
        num_font   = _load_font(16)

        result: List[Dict[str, Any]] = []
        for i, slide in enumerate(slides):
            img  = Image.new("RGB", (W, H), (255, 255, 255))
            draw = ImageDraw.Draw(img)

            # Top accent bar
            draw.rectangle([(0, 0), (W, 10)], fill=(59, 130, 246))
            # Footer bar
            draw.rectangle([(0, H - 36), (W, H)], fill=(243, 244, 246))
            draw.text((W // 2, H - 18),
                      f"Slide {slide.get('slideNumber', i + 1)}",
                      fill=(156, 163, 175), font=num_font, anchor="mm")

            # Title
            title    = (slide.get('title') or f"Slide {i + 1}").strip()
            title_y  = 36
            for line in _wrap(draw, title, title_font, W - 120)[:3]:
                draw.text((60, title_y), line, fill=(17, 24, 39), font=title_font)
                title_y += 52

            # Divider
            div_y = title_y + 8
            draw.line([(60, div_y), (W - 60, div_y)], fill=(209, 213, 219), width=2)

            # Body text
            content = (slide.get('content') or '').strip()
            skip_values = {'(No text content)', '(Document appears to be empty)'}
            if content and content not in skip_values:
                body_y    = div_y + 20
                max_body  = H - 50
                for para in content.split('\n'):
                    para = para.strip()
                    if not para:
                        body_y += 10
                        continue
                    truncated = False
                    for line in _wrap(draw, para, body_font, W - 120):
                        if body_y + 28 > max_body:
                            draw.text((60, body_y), "…", fill=(107, 114, 128), font=body_font)
                            truncated = True
                            break
                        draw.text((60, body_y), line, fill=(55, 65, 81), font=body_font)
                        body_y += 30
                    if truncated:
                        break

            image_filename = f"slide_{i}.png"
            thumb_filename = f"thumb_{i}.png"
            full_path  = session_slides_dir / image_filename
            thumb_path = session_slides_dir / thumb_filename

            img.save(str(full_path), 'PNG')

            thumb = img.copy()
            thumb.thumbnail((256, 192), Image.Resampling.LANCZOS)
            thumb.save(str(thumb_path), 'PNG')

            updated = dict(slide)
            updated['imagePath']     = f"/uploads/{session_id}/slides/{image_filename}"
            updated['thumbnailPath'] = f"/uploads/{session_id}/slides/{thumb_filename}"
            result.append(updated)

        return result

    @staticmethod
    def _find_libreoffice() -> str:
        """
        Return the LibreOffice executable path.
        On Windows, winget/installer does not add soffice to PATH, so we probe
        the standard install locations when PATH lookup fails.
        """
        import shutil
        if sys.platform == "win32":
            if shutil.which("soffice"):
                return "soffice"
            candidates = [
                r"C:\Program Files\LibreOffice\program\soffice.exe",
                r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            ]
            for c in candidates:
                if os.path.exists(c):
                    return c
            raise RuntimeError(
                "LibreOffice is not installed or not found. "
                "Run: winget install TheDocumentFoundation.LibreOffice"
            )
        # Linux / macOS — must be in PATH
        cmd = shutil.which("libreoffice") or shutil.which("soffice")
        if cmd:
            return cmd
        raise RuntimeError(
            "LibreOffice is not installed or not in PATH. "
            "On Linux/Docker: apt-get install libreoffice"
        )

    def convert_to_pdf_via_libreoffice(self, input_path: str) -> str:
        """
        Convert DOCX, PPTX, or PPT to PDF using LibreOffice headless.
        Returns the path to the generated PDF.  Caller is responsible for
        deleting the returned file and its parent temp directory when done.
        Raises RuntimeError if conversion fails.
        """
        lo_cmd = self._find_libreoffice()
        # Always use an absolute path — LibreOffice on Windows does not reliably
        # resolve relative paths when launched as a subprocess.
        abs_input = str(Path(input_path).resolve())
        tmp_dir = tempfile.mkdtemp()
        try:
            result = subprocess.run(
                [
                    lo_cmd, "--headless", "--norestore", "--nofirststartwizard",
                    "--convert-to", "pdf", "--outdir", tmp_dir, abs_input,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"LibreOffice conversion failed (rc={result.returncode}): {result.stderr or result.stdout}"
                )

            basename = os.path.splitext(os.path.basename(abs_input))[0]
            pdf_path = os.path.join(tmp_dir, f"{basename}.pdf")
            if not os.path.exists(pdf_path):
                # List what LibreOffice actually produced to aid debugging
                produced = os.listdir(tmp_dir)
                raise RuntimeError(
                    f"Expected PDF '{pdf_path}' not found after LibreOffice conversion. "
                    f"Files in tmp dir: {produced}"
                )
            return pdf_path
        except Exception:
            import shutil as _shutil
            _shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    async def convert_presentation_to_images(self, file_path: str, session_id: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Convert any supported presentation file to slide images for Vision processing.
        PDF files go directly to pdf2image.
        PPTX, PPT, and DOCX are first converted to PDF via LibreOffice headless.
        """
        # Strip query string from cloud URLs to get the real extension
        clean_path = file_path.split("?")[0]
        ext = Path(clean_path).suffix.lower()

        if ext == ".pdf":
            return await self._convert_pdf_to_images(file_path, session_id)

        # Non-PDF: need a local copy for LibreOffice
        local_input = file_path
        temp_download = None
        tmp_pdf_dir = None  # tracks the temp dir produced by LibreOffice

        if file_path.startswith("https://") and settings.use_cloud_storage:
            import requests as _requests
            print(f"Downloading {ext} from cloud storage for LibreOffice conversion")
            resp = _requests.get(file_path, timeout=60)
            resp.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tf:
                tf.write(resp.content)
                temp_download = tf.name
            local_input = temp_download

        try:
            print(f"Converting {ext} to PDF via LibreOffice: {local_input}")
            pdf_path = self.convert_to_pdf_via_libreoffice(local_input)
            tmp_pdf_dir = os.path.dirname(pdf_path)
            print(f"LibreOffice produced PDF at: {pdf_path}")
        finally:
            if temp_download and os.path.exists(temp_download):
                os.unlink(temp_download)

        try:
            return await self._convert_pdf_to_images(pdf_path, session_id)
        finally:
            # Clean up the temp PDF and its directory
            if tmp_pdf_dir and os.path.isdir(tmp_pdf_dir):
                import shutil as _shutil
                _shutil.rmtree(tmp_pdf_dir, ignore_errors=True)

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
                        dpi=150,
                        first_page=1,
                        fmt='PNG',
                        poppler_path=settings.poppler_path or None
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
                    dpi=150,
                    first_page=1,
                    fmt='PNG',
                    poppler_path=settings.poppler_path or None
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
        if len(file_content) > settings.max_file_size:
            return False, f"File size exceeds maximum allowed size of {settings.max_file_size / 1024 / 1024:.0f} MB ({len(file_content) / 1024 / 1024:.1f} MB uploaded)"

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
        stem = Path(filename).stem
        unique_filename = f"{uuid.uuid4()}_{stem}{file_ext}"
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