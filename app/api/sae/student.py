"""
Student-facing SAE routes.

All endpoints require the caller to be an activated SAE student
(verified by the require_sae_subscriber dependency below).

GET  /api/sae/student/me          → own SAE student profile
GET  /api/sae/student/submission  → own submission (404 if not yet submitted)
POST /api/sae/student/submit      → one-time file upload + grading
"""

import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import SAEStudent, User
from app.dependencies.auth import require_subscriber
from app.schemas.sae import SAEStudentMe, SAESubmissionResult
from app.services import sae_service
from app.services.gemini_file_cache import autograder_cache
from app.services.r2_service import r2

import json
from google import genai
from google.genai import types

router = APIRouter(prefix="/api/sae/student", tags=["sae-student"])

SAE_TRANSCRIPTION_MODEL = "gemini-2.5-pro"

SAE_TRANSCRIPTION_PROMPT = r"""
You are transcribing a student's mathematics exam submission using LaTeX.

Transcribe the academic content needed for grading precisely:
- question numbers and subparts
- the student's written mathematical work with answers
- relevant graph/diagram descriptions

Ignore non-answer content:
- scanner watermarks or app names such as CamScanner
- page borders, stamps, timestamps, file labels, crop marks
- circled page/order markers that are not question numbers
- random annotations unrelated to the solution
- crossed-out or scribbled-out work

Rules:
- Do not solve, correct, simplify, complete, or grade the work.
- Preserve the student's mistakes, spelling, and document structure.
- Output LaTeX body content only.
- Do not include \documentclass, \begin{document}, or \end{document}.
- Do not use Unicode characters.
- Use standard LaTeX math notation for all mathematical expressions.
- If handwriting is unreadable or ambiguous, write [unreadable].
- If a graph, plot, table, geometric figure, or diagram is part of a student answer, describe it clearly in text, including labels, axes, coordinates, curves, shading, and annotations relevant to grading.
- Return only the transcription, with no explanations, introductions, comments, or code fences.
"""


async def transcribe_sae_pdf(pdf_bytes: bytes) -> dict:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured.")

    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=SAE_TRANSCRIPTION_MODEL,
        contents=[
            types.Part.from_bytes(
                data=pdf_bytes,
                mime_type="application/pdf",
            ),
            SAE_TRANSCRIPTION_PROMPT,
        ],
    )

    return {
        "model": SAE_TRANSCRIPTION_MODEL,
        "latex": (response.text or "").strip(),
    }


def build_sae_draft_dir(student_code: str) -> Path:
    path = Path("uploads") / "sae_drafts" / student_code
    path.mkdir(parents=True, exist_ok=True)
    return path

# ── SAE-specific auth dependency ───────────────────────────────────────────────

async def require_sae_subscriber(
    current_user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
) -> SAEStudent:
    """
    Resolve the calling user as an activated SAE student.
    Raises 403 if the user exists but is not in sae_students —
    this prevents regular subscribers from accessing SAE-only routes.
    """
    sae_student = (
        db.query(SAEStudent)
        .filter(SAEStudent.user_id == current_user.id)
        .first()
    )
    if not sae_student:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not registered for the Self Assessment Exam.",
        )
    return sae_student


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/me", response_model=SAEStudentMe)
def get_my_profile(
    sae_student: SAEStudent = Depends(require_sae_subscriber),
):
    """Return the SAE student profile for the currently authenticated user."""
    return SAEStudentMe(
        id=sae_student.id,
        student_number=sae_student.student_number,
        student_code=sae_student.student_code,
        display_name=sae_student.display_name,
        is_activated=sae_student.is_activated,
        has_submitted=sae_student.has_submitted,
    )


@router.get("/submission", response_model=SAESubmissionResult)
def get_my_submission(
    sae_student: SAEStudent = Depends(require_sae_subscriber),
):
    """Return the student's submission. 404 if they haven't submitted yet."""
    sub = sae_student.submission
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You have not submitted yet.",
        )
    return SAESubmissionResult(
        id=sub.id,
        score=sub.score,
        overall_confidence=sub.overall_confidence,
        review_required=sub.review_required,
        result_json=sae_service.get_effective_result_json(sub),
        submitted_by_publisher=sub.submitted_by_publisher,
        created_at=sub.created_at,
        handwritten_filename=sub.handwritten_filename,
        webassign_filename=sub.webassign_filename,
    )

@router.post("/transcribe")
async def transcribe_submission(
    student_answer: UploadFile = File(..., description="Handwritten exam PDF"),
    webassign_pdf: UploadFile = File(..., description="WebAssign questions PDF"),
    sae_student: SAEStudent = Depends(require_sae_subscriber),
):
    """
    First SAE submit step for the demo.

    Saves both PDFs once, creates OCR transcripts for preview, but does not grade.
    The existing /submit endpoint is left unchanged as a fallback.
    """
    if sae_student.has_submitted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already submitted. Only one submission is allowed.",
        )

    handwritten_bytes = await student_answer.read()
    webassign_bytes = await webassign_pdf.read()

    draft_dir = build_sae_draft_dir(sae_student.student_code)

    handwritten_filename = student_answer.filename or "handwritten.pdf"
    webassign_filename = webassign_pdf.filename or "webassign.pdf"

    (draft_dir / "handwritten.pdf").write_bytes(handwritten_bytes)
    (draft_dir / "webassign.pdf").write_bytes(webassign_bytes)

    metadata = {
        "handwritten_filename": handwritten_filename,
        "webassign_filename": webassign_filename,
    }
    (draft_dir / "metadata.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )

    try:
        handwritten_transcript = await transcribe_sae_pdf(handwritten_bytes)
    except Exception as exc:
        handwritten_transcript = {
            "model": SAE_TRANSCRIPTION_MODEL,
            "latex": "",
            "error": str(exc),
        }

    try:
        webassign_transcript = await transcribe_sae_pdf(webassign_bytes)
    except Exception as exc:
        webassign_transcript = {
            "model": SAE_TRANSCRIPTION_MODEL,
            "latex": "",
            "error": str(exc),
        }

    transcript = {
        "handwritten": handwritten_transcript,
        "webassign": webassign_transcript,
    }

    (draft_dir / "transcript.json").write_text(
        json.dumps(transcript),
        encoding="utf-8",
    )

    return {
        "draft_id": sae_student.student_code,
        "student_code": sae_student.student_code,
        "display_name": sae_student.display_name,
        "transcript": transcript,
    }


@router.post("/grade-draft", response_model=SAESubmissionResult)
async def grade_draft_submission(
    sae_student: SAEStudent = Depends(require_sae_subscriber),
    db: Session = Depends(get_db),
):
    """
    Second SAE submit step for the demo.

    Grades the already-uploaded draft PDFs using the existing grading service.
    """
    if not autograder_cache.loaded:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Autograder not ready. Check server startup logs.",
        )

    if sae_student.has_submitted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already submitted. Only one submission is allowed.",
        )

    draft_dir = build_sae_draft_dir(sae_student.student_code)

    handwritten_path = draft_dir / "handwritten.pdf"
    webassign_path = draft_dir / "webassign.pdf"
    metadata_path = draft_dir / "metadata.json"

    if not handwritten_path.exists() or not webassign_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Draft files not found. Please upload again.",
        )

    metadata = {}
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    submission = await sae_service.grade_and_save_submission(
        db=db,
        student=sae_student,
        handwritten_bytes=handwritten_path.read_bytes(),
        handwritten_filename=metadata.get("handwritten_filename", "handwritten.pdf"),
        webassign_bytes=webassign_path.read_bytes(),
        webassign_filename=metadata.get("webassign_filename", "webassign.pdf"),
        submitted_by_publisher=False,
        publisher_user_id=None,
    )

    return SAESubmissionResult(
        id=submission.id,
        score=submission.score,
        overall_confidence=submission.overall_confidence,
        review_required=submission.review_required,
        result_json=sae_service.get_effective_result_json(submission),
        submitted_by_publisher=submission.submitted_by_publisher,
        created_at=submission.created_at,
        handwritten_filename=submission.handwritten_filename,
        webassign_filename=submission.webassign_filename,
    )


@router.get("/draft/files/{file_type}")
def get_my_draft_file(
    file_type: Literal["handwritten", "webassign"],
    sae_student: SAEStudent = Depends(require_sae_subscriber),
):
    """
    Stream the student's draft PDF before grading.
    """
    draft_dir = build_sae_draft_dir(sae_student.student_code)
    path = draft_dir / f"{file_type}.pdf"

    if not path.exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Draft file not found.",
        )

    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{file_type}.pdf"'},
    )

@router.post("/submit", response_model=SAESubmissionResult)
async def submit(
    student_answer: UploadFile = File(..., description="Handwritten exam PDF"),
    webassign_pdf: UploadFile = File(..., description="WebAssign questions PDF"),
    sae_student: SAEStudent = Depends(require_sae_subscriber),
    db: Session = Depends(get_db),
):
    """
    One-time exam submission. Returns 409 if the student has already submitted.

    Files are stored at uploads/sae/{student_code}/ and graded using the same
    LLM fallback chain as the Math Placement autograder.
    """
    if not autograder_cache.loaded:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Autograder not ready. Check server startup logs.",
        )

    if sae_student.has_submitted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already submitted. Only one submission is allowed.",
        )

    handwritten_bytes = await student_answer.read()
    webassign_bytes = await webassign_pdf.read()

    submission = await sae_service.grade_and_save_submission(
        db=db,
        student=sae_student,
        handwritten_bytes=handwritten_bytes,
        handwritten_filename=student_answer.filename or "handwritten.pdf",
        webassign_bytes=webassign_bytes,
        webassign_filename=webassign_pdf.filename or "webassign.pdf",
        submitted_by_publisher=False,
        publisher_user_id=None,
    )
    return SAESubmissionResult(
        id=submission.id,
        score=submission.score,
        overall_confidence=submission.overall_confidence,
        review_required=submission.review_required,
        result_json=sae_service.get_effective_result_json(submission),
        submitted_by_publisher=submission.submitted_by_publisher,
        created_at=submission.created_at,
        handwritten_filename=submission.handwritten_filename,
        webassign_filename=submission.webassign_filename,
    )


@router.get("/files/{file_type}")
def get_my_file(
    file_type: Literal["handwritten", "webassign"],
    sae_student: SAEStudent = Depends(require_sae_subscriber),
):
    """
    Stream the student's own submitted PDF.
    Students can only access their own submission files.
    """
    sub = sae_student.submission
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No submission found.")

    if file_type == "handwritten":
        file_path = sub.handwritten_file_path
        filename = sub.handwritten_filename or "handwritten.pdf"
    else:
        file_path = sub.webassign_file_path
        filename = sub.webassign_filename or "webassign.pdf"

    if not file_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="File path not recorded for this submission.")

    if r2.enabled and not os.path.isabs(file_path):
        data = r2.download(file_path)
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )

    disk_path = Path(file_path)
    if not disk_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="File not found on server.")

    return FileResponse(
        path=str(disk_path),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
