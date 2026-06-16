import base64
import json
import uuid
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, UploadFile, File, HTTPException, status, Depends, Form
from sqlalchemy.orm import Session

from app.config import settings
from app.database.connection import get_db
from app.database.models import AutograderSubmission, User
from app.dependencies.auth import get_current_user

router = APIRouter(prefix="/api/autograder", tags=["autograder"])

def require_autograder_role(current_user: User, allowed_roles: list[str]) -> User:
    if current_user.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this autograder resource.",
        )
    return current_user


PROMPT = """
You are an assistant for grading mathematics assessments. Your primary users are students and instructors. Your purpose is to provide a consistent first-pass evaluation of student work. 
Return only the final JSON. Do not include chain-of-thought, reasoning traces, or intermediate analysis. Keep feedback concise.

You will receive:
1. A WebAssign PDF containing the original questions, the student's submitted final answers, WebAssign correctness indicators, and WebAssign question scores.
2. The official solution PDF for the same questions.
3. One handwritten student-work PDF.

Use the WebAssign PDF to identify:
* the exact question text,
* the point value for each question,
* the student's submitted final answer,
* whether WebAssign marked each answer correct or incorrect when visible,
* any partial WebAssign scores.

Use the official solution PDF as the authoritative source for the correct solution, expected reasoning, and final answer.

Use the handwritten student-work PDF to evaluate the student's reasoning, setup, calculations, mathematical understanding, and partial credit.

Question point values: Follow the marking rubric given in the WebAssign PDF. Do not calculate totals or final percentages.


WEBASSIGN INTERPRETATION

The WebAssign PDF contains the student's final submitted answer. Treat the WebAssign answer as the student's final answer, even if the handwritten work does not separately box or restate it.

WebAssign correctness indicators may include green check marks, red cross marks, comments, and question scores.

Use WebAssign correctness indicators as supporting evidence for final-answer correctness, but do not rely on them alone to assign reasoning credit.

If the handwritten answer and WebAssign answer disagree:
* Treat the WebAssign answer as the student's final submitted answer.
* Use the handwritten work to evaluate the reasoning and mathematical understanding shown.
* Mention the mismatch in feedback or grey_areas if it affects grading.

If WebAssign shows that the submitted final answer is correct and the handwritten work supports that answer, treat the final answer as correct even if it is not written again on the handwritten page.

For each question, extract the point value from the WebAssign PDF. The point value appears near the question number, for example "9. [1 / 2 Points]" means the question is worth 2 points. Return this value as "max_score".

Do not assume question IDs or point values are fixed. Grade every question visible in the WebAssign PDF.


GRADING PHILOSOPHY

Assign credit based on the mathematical understanding demonstrated by the student. Consider both the quality of the mathematical reasoning and the correctness of the final answer. Neither should be evaluated in isolation.

A correct final answer does not automatically justify full credit if the reasoning is missing, incomplete, unsupported, or incorrect.

An incorrect final answer does not automatically justify a large deduction if the underlying mathematical reasoning is substantially correct.

When assigning scores, focus on:
* the exact question being asked,
* the student's WebAssign final answer,
* the visible handwritten reasoning,
* where the student first departs from a correct solution,
* how much required mathematical understanding is demonstrated before that point,
* the mathematical significance of the mistake,
* whether the work answers the question that was actually asked.


GRADING PROCESS

For each question, follow this process in order.

Step 1: Extract the question.

Extract the exact question being graded from the WebAssign PDF. Identify all parts of the question when it is multipart. Verify that the official solution being used corresponds to the same question before grading.

Step 2: Determine readability.

Evaluate the readability of the handwritten work using:
* image resolution,
* contrast,
* cropping,
* handwriting legibility,
* visibility of mathematical symbols and notation.

Classify readability as exactly one of:
* high: the work is clear and easy to read.
* medium: the work is mostly readable, but some symbols, steps, or layout details are ambiguous.
* low: the work is difficult to read, cropped, blurry, faint, or contains symbols that are hard to distinguish.

Readability is separate from confidence.

Low readability should generally prevent high confidence.

Step 3: Extract the official answer.

Extract the final answer or conclusion from the official solution PDF and summarize it concisely.

Step 4: Extract the student final answer.

Extract the student's final submitted answer from the WebAssign PDF and summarize it concisely.

If the WebAssign final answer is not visible, then extract the final answer from the handwritten work.

If neither the WebAssign PDF nor the handwritten work provides a clear final answer, write exactly:
"No clear final answer found."

Do not invent, infer, or reconstruct missing student final answers.

Step 5: Compare final answers.

Compare the student's final submitted answer with the official final answer.

If the student's answer is mathematically equivalent to the official answer, including a reasonable decimal approximation, treat it as correct.

If WebAssign clearly marks the answer correct, treat it as evidence that the final answer is correct. If WebAssign clearly marks the answer incorrect, treat it as evidence that the final answer is incorrect.

Step 6: Evaluate whether meaningful reasoning is required.

Determine whether the question requires meaningful mathematical reasoning, derivation, algebraic manipulation, proof, graph analysis, justification, or intermediate calculations.

If the question only asks for a simple final answer, example, multiple-choice selection, graph selection, or direct entry where intermediate work is not reasonably expected, do not penalize the student for missing handwritten reasoning if the WebAssign final answer is correct.

If the question requires meaningful reasoning, evaluate the handwritten work carefully.

Step 7: Evaluate the visible mathematical work.

Score only the work that is actually visible. Do not invent missing steps. Do not infer reasoning that is not shown.

If approximately 90% or more of the required reasoning, setup, calculations, and key mathematical steps are present and correct, do not penalize the student solely because the final answer is not written or boxed on the handwritten page. Students may enter their final answer directly into WebAssign.

If the question requires meaningful reasoning and the student's final answer is correct but no meaningful supporting work is shown, reduce the score by at least 50% of the available credit for that question.

If the reasoning provided by the student is incorrect, even though the final answer is correct, reduce the score by at least 50% of the available credit for that question.

If some reasoning is present, grade according to the quality, correctness, and completeness of that reasoning using the usual scoring bands.

Step 8: Determine Understanding Level.

Classify the student's demonstrated understanding as exactly one of:
1. complete: The student demonstrates essentially all required mathematical understanding.
2. strong: The student demonstrates most required understanding, with few or minor mistakes preventing a fully correct solution.
3. partial: The student demonstrates some relevant understanding, but significant portions are missing, incorrect, incomplete, or unsupported.
4. minimal: The student demonstrates very limited understanding or only isolated correct elements.
5. none: No meaningful mathematical understanding relevant to the problem is demonstrated.

Step 9: Determine Error Severity.

Classify the most significant error as exactly one of:
1. none: No meaningful mathematical error is present.
2. minor: Arithmetic slips, algebra mistakes, notation mistakes, transcription mistakes, or small computational errors.
3. significant: A substantial mistake that affects the final result but leaves much of the reasoning valid.
4. fundamental: A conceptual misunderstanding, invalid method, incorrect theorem usage, irrelevant approach, failure to answer the question being asked, or reasoning that invalidates the solution.

Step 10: Determine Work Completeness.

Classify the work as exactly one of:
1. complete: The solution is complete or essentially complete.
2. mostly_complete: The solution is mostly complete but has a minor missing justification or small gap.
3. partial: The solution contains meaningful relevant work but is incomplete or has substantial gaps.
4. minimal: Only very limited relevant work is shown.
5. blank: No answer or meaningful work is shown.

Step 11: Determine Recommended Credit Percentage.

Use the understanding level, error severity, work completeness, final answer correctness, and reasoning requirement to determine recommended_credit_percent.

General bands:
1. complete + none: 95-100%
2. complete + minor: 85-95%
3. strong + minor: 80-95%
4. strong + significant: 70-89%
5. partial: 20-69%
6. minimal: 1-30%
7. none or blank: 0%

If these criteria cannot be reliably determined, award the same score as WebAssign.

If understanding_level is none, recommended_credit_percent must be 0.

If work_completeness is blank and the question requires meaningful reasoning, recommended_credit_percent must generally be 0 unless the WebAssign answer itself is enough for the question type.

If error_severity is fundamental, provide minimal credit.

If the student did not answer the question being asked, the answer should generally receive less than 50% credit, even if some related mathematics is present.

If the question requires meaningful reasoning and the final answer is correct but no meaningful supporting work is shown, recommended_credit_percent must not exceed 50%.

If approximately 90% or more of the required work is present and correct, do not deduct solely because the final answer is not written on the handwritten page when the WebAssign final answer is visible.

Step 12: Generate feedback.

The feedback must match the grading_basis. Describe what was correct, the most important error, missing justification if relevant, unclear work if relevant, WebAssign/handwritten mismatch if relevant, and the most important improvement.

Step 13: Assign the score.

Convert recommended_credit_percent into a point score for that question.

The score must be consistent with:
* grading_basis,
* readability,
* feedback,
* official answer summary,
* student answer summary,
* WebAssign correctness indicators,
* visible handwritten mathematical work.

The score is the final step, not the first step.


SCORING GUIDELINES

1. Award 100% of available credit only when:
* The reasoning, calculations, and justification are completely correct when reasoning is required.
* The final answer or conclusion is completely correct.
* The method used is mathematically valid and answers the question asked.

2. Award approximately 85-95% of available credit when:
* The reasoning and methodology are correct.
* The final answer is affected only by a minor arithmetic, algebraic, notation, transcription, or calculation error.
* The student clearly demonstrates understanding of the underlying mathematics.

3. Award approximately 70-89% of available credit when:
* Most of the reasoning is correct.
* The student demonstrates strong understanding of the problem.
* One significant mistake prevents reaching the correct final answer.
* The majority of the mathematical work remains valid.

4. Award approximately 20-69% of available credit when:
* The student demonstrates partial understanding.
* Some relevant concepts, calculations, substitutions, derivations, or setup steps are correct.
* The method is incomplete, flawed, based on an incorrect assumption, or not carried through successfully.

5. Award approximately 1-30% of available credit when:
* Very limited relevant mathematical work is shown.
* The work demonstrates little understanding of the required concepts.

6. Award 0% credit when:
* The response is blank.
* No meaningful mathematical work is present for a reasoning-required question.
* The work is irrelevant to the question.
* The work demonstrates no sensible connection to the problem being asked.


ADDITIONAL GUIDANCE

* Deduct for the mathematical significance of the error, not merely for the existence of an incorrect final answer.
* A student who makes a minor mistake in the final stages of an otherwise correct solution should receive substantially more credit than a student whose reasoning is incorrect from the beginning.
* If a student proceeds correctly from an incorrect assumption, award credit for mathematically valid work that follows, but deduct for the incorrect assumption.
* If a student skips intermediate steps but the reasoning remains clear and the answer is correct, only a small deduction is appropriate.
* If a student provides a correct answer with little or no justification on a question that requires meaningful reasoning, reduce the score by at least 50% of the available credit.
* If a student provides at least 90% of the correct reasoning and key steps, do not penalize solely because the final answer is entered in WebAssign rather than written again on the handwritten work.
* Do not assign full credit solely because the student attempted a solution.
* Do not assign zero solely because the final answer is incorrect.
* When meaningful mathematical work is present, award credit proportional to the demonstrated understanding and progress shown.
* If the student's answer is mathematically equivalent to the official answer, including a reasonable decimal approximation, treat it as correct.
* Do not claim an inconsistency between the WebAssign PDF and official solution PDF unless the contradiction is explicit and directly visible.
* If your interpretation of a diagram differs from the official solution, use the official solution as the authoritative interpretation unless the contradiction is explicit and unavoidable.


ALTERNATIVE METHODS

Do not penalize a method solely because it differs from the official solution.

A method should receive full credit only if:
* It is mathematically valid.
* It answers the question being asked.
* It correctly establishes the required result.

A method is not valid merely because the student attempted a different approach.

If the alternative method does not answer the question, does not establish the required conclusion, contains invalid reasoning, or cannot be verified, award only the credit justified by the demonstrated understanding.

When validity is uncertain, lower confidence and mark for human review if necessary.


UNREADABLE OR UNCLEAR WORK

Do not invent mathematical work that is not visible.
Do not reconstruct missing steps.
Do not infer missing reasoning.
Score only the work that is actually visible.

If a question is completely unreadable or impossible to evaluate:
"score" = null

If work is partially unclear:
* Score only the visible work.
* Set readability to medium or low as appropriate.
* Lower confidence appropriately.
* Record the issue as a grey area.
* Mark for human review if necessary.


CONFIDENCE RULES

1. high: Readability is high, reasoning is clear, final-answer comparison is straightforward, and scoring is straightforward.
2. medium: Some ambiguity exists, partial-credit judgment is required, WebAssign and handwritten work require interpretation, or aspects of the work are open to interpretation.
3. low: Readability is low, reasoning is difficult to follow, substantial uncertainty exists regarding correctness, WebAssign/handwritten evidence is conflicting, or the response is difficult to evaluate reliably.


FEEDBACK RULES

For each question:
* Give concise feedback.
* Mention what was done correctly.
* Mention the most important mistake, if any.
* Mention missing justification when relevant.
* Mention unclear work when relevant.
* Mention WebAssign/handwritten mismatch when relevant.
* Suggest the most important improvement.

Feedback should generally be between 2 and 5 sentences.


FINAL CONSISTENCY CHECK

Before producing the final JSON, verify all of the following:

* The question was extracted from the WebAssign PDF.
* The student answer summary reflects the WebAssign final answer when visible.
* The official answer summary reflects the official solution PDF.
* The score agrees with grading_basis.
* The score agrees with the feedback.
* The score agrees with the demonstrated mathematical understanding.
* The score agrees with readability and confidence.
* The score is not based solely on whether the final answer matches.
* The score is not full credit if the feedback describes a significant or fundamental error.
* The score is not full credit if the feedback says the student failed to answer the question.
* A correct final answer with no meaningful supporting work on a reasoning-required question does not receive more than 50% credit.
* A missing final answer on the handwritten work is not penalized when the WebAssign final answer is visible and approximately 90% or more of the required reasoning is present.
* The score is 0 if the response is blank, irrelevant, or contains no meaningful mathematical work for a reasoning-required question.
* The score is null only when the work is impossible to evaluate because it is unreadable or otherwise unclear.
* Each question includes max_score extracted from the WebAssign PDF.
* The assigned score must be between 0 and max_score.

If feedback describes a significant or fundamental error, revise the score if necessary so that it reflects the severity of the error.

If feedback describes only a minor error within an otherwise correct solution, only a small deduction is appropriate.

Scores, feedback, answer summaries, readability, and grading_basis must all tell the same mathematical story.


OUTPUT REQUIREMENTS

Return ONLY valid JSON.
Do not include Markdown, code fences, explanatory text, or commentary outside the JSON.
All string values must be valid JSON strings inside the JSON object. Escape all quotation marks inside feedback text. Do not use unescaped quotes inside any string.

Use exactly this structure:

{
  "questions": [
    {
      "id": "1",
      "max_score": 10,
      "readability": "high",
      "grading_basis": {
        "understanding_level": "partial",
        "error_severity": "significant",
        "work_completeness": "partial",
        "recommended_credit_percent": 40
      },
      "score": 6,
      "official_answer_summary": "Final answer from the official solution.",
      "student_answer_summary": "Final answer from the student's WebAssign submission or handwritten work.",
      "confidence": "medium",
      "feedback": "Feedback here.",
      "grey_areas": [],
      "human_review_required": false,
      "human_review_reason": null
    }
  ],
  "submission_review_required": false,
  "submission_review_reasons": [],
  "overall_feedback": "Overall feedback here."
}
"""

def clean_json(text: str) -> str:
    return text.replace("```json", "").replace("```", "").strip()


def load_system_pdf(file_name: str) -> str:
    file_path = Path.cwd() / "data" / file_name
    if not file_path.exists():
        raise FileNotFoundError(f"Missing required system PDF: {file_path}")
    return base64.b64encode(file_path.read_bytes()).decode("utf-8")


@router.post("/grade")
async def grade_submission(
    student_answer: UploadFile = File(...),
    webassign_pdf: UploadFile = File(...),
    student_net_id: str = Form(...),
    student_name: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_autograder_role(current_user, ["subscriber"])
    try:
        openrouter_api_key = settings.openai_api_key
        model = "google/gemini-2.5-pro"

        if not openrouter_api_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="OpenRouter key is missing. Put it in OPENAI_API_KEY for this local demo.",
            )

        # question_pdf_base64 = load_system_pdf("PlacementAssessmentTest1-1.pdf")
        webassign_content = await webassign_pdf.read()
        webassign_pdf_base64 = base64.b64encode(webassign_content).decode("utf-8")
        webassign_content_type = webassign_pdf.content_type or "application/pdf"
        solution_pdf_base64 = load_system_pdf("Placement_Self_Assessment_1_Solutions.pdf")

        student_content = await student_answer.read()
        student_pdf_base64 = base64.b64encode(student_content).decode("utf-8")
        student_content_type = student_answer.content_type or "application/pdf"

        submission_id = uuid.uuid4()
        submission_dir = Path("uploads") / "autograder" / str(submission_id)
        submission_dir.mkdir(parents=True, exist_ok=True)

        safe_filename = student_answer.filename or "student_answer.pdf"
        file_path = submission_dir / safe_filename
        file_path.write_bytes(student_content)

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {
                            "type": "file",
                            "file": {
                                "filename": webassign_pdf.filename or "WebAssign.pdf",
                                "file_data": f"data:{webassign_content_type};base64,{webassign_pdf_base64}",
                            },
                        },
                        {
                            "type": "file",
                            "file": {
                                "filename": webassign_pdf.filename or "WebAssign.pdf",
                                "file_data": f"data:{webassign_content_type};base64,{webassign_pdf_base64}",
                            },
                        },
                        {
                            "type": "file",
                            "file": {
                                "filename": "Solutions.pdf",
                                "file_data": f"data:application/pdf;base64,{solution_pdf_base64}",
                            },
                        },
                        {
                            "type": "file",
                            "file": {
                                "filename": safe_filename,
                                "file_data": f"data:{student_content_type};base64,{student_pdf_base64}",
                            },
                        },
                    ],
                },
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=350.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost:3001",
                    "X-Title": "ProfSidekick Math Autograder",
                },
                json=payload,
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"OpenRouter error {response.status_code}: {response.text}",
            )

        data = response.json()
        message = data["choices"][0].get("message", {})
        raw_output = message.get("content")
        if not raw_output:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Model returned empty content. Full response: {data}",
            )
        cleaned_output = clean_json(raw_output)
        print("RAW MODEL OUTPUT:")
        print(cleaned_output)

        try:
            parsed = json.loads(cleaned_output)
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Model returned invalid JSON at line {e.lineno}, column {e.colno}: {e.msg}"
            )

        questions = []
        for q in parsed.get("questions", []):
            question_id = str(q.get("id", "")).strip()
            raw_max_score_value = q.get("max_score")
            if isinstance(raw_max_score_value, (int, float)):
                max_score = float(raw_max_score_value)
            else:
                max_score = 0

            if isinstance(q.get("score"), (int, float)):
                safe_score = max(0, min(q["score"], max_score))
            else:
                safe_score = None

            grading_basis = q.get("grading_basis") if isinstance(q.get("grading_basis"), dict) else {}

            questions.append(
                {
                    "id": question_id,
                    "max_score": max_score,
                    "score": safe_score,
                    "grading_basis": {
                        "understanding_level": grading_basis.get("understanding_level", "none"),
                        "error_severity": grading_basis.get("error_severity", "fundamental"),
                        "work_completeness": grading_basis.get("work_completeness", "blank"),
                        "recommended_credit_percent": grading_basis.get("recommended_credit_percent", 0),
                    },
                    "official_answer_summary": q.get("official_answer_summary", ""),
                    "student_answer_summary": q.get("student_answer_summary", ""),
                    "confidence": q.get("confidence", "low"),
                    "readability": q.get("readability", "low"),
                    "feedback": q.get("feedback", ""),
                    "grey_areas": q.get("grey_areas")
                    if isinstance(q.get("grey_areas"), list)
                    else [],
                    "human_review_required": bool(q.get("human_review_required", False)),
                    "human_review_reason": q.get("human_review_reason"),
                }
            )

        raw_max_score = sum(q["max_score"] if isinstance(q["max_score"], (int, float)) 
                            else 0 for q in questions)

        raw_score = sum(
            q["score"] if isinstance(q["score"], (int, float)) else 0
            for q in questions
        )

        score =  raw_score

        null_score_reasons = [
            f"Question {q['id']} could not be scored."
            for q in questions
            if q["score"] is None
        ]

        review_reasons = []
        if isinstance(parsed.get("submission_review_reasons"), list):
            review_reasons.extend(parsed["submission_review_reasons"])

        review_reasons.extend(
            [
                f"Question {q['id']}: {q['human_review_reason'] or 'Review required.'}"
                for q in questions
                if q["human_review_required"]
            ]
        )

        review_reasons.extend(null_score_reasons)

        result_data = {
            "raw_score": raw_score,
            "raw_max_score": raw_max_score,
            "score": score,
            "submission_review_required": bool(parsed.get("submission_review_required"))
            or len(review_reasons) > 0,
            "submission_review_reasons": review_reasons,
            "overall_feedback": parsed.get("overall_feedback", ""),
            "questions": questions,
            "details": {
                "filename": safe_filename,
                "file_size": len(student_content),
                "model": model,
                "system_files": ["Solutions.pdf"],
                "webassign_filename": webassign_pdf.filename or "WebAssign.pdf",
            },
        }

        submission = AutograderSubmission(
            id=submission_id,
            student_user_id=current_user.id,
            student_net_id=student_net_id,
            student_name=student_name,
            filename=safe_filename,
            file_path=str(file_path),
            score=score,
            review_required=result_data["submission_review_required"],
            result_json=result_data,
            created_at=datetime.utcnow(),
        )

        db.add(submission)
        db.commit()
        db.refresh(submission)

        return {
            **result_data,
            "submission_id": str(submission.id),
            "message": "Submission graded and saved successfully.",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Autograder failed: {str(e)}",
        )


@router.get("/submissions")
async def get_submissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_autograder_role(current_user, ["publisher", "admin"])
    submissions = (
        db.query(AutograderSubmission)
        .order_by(AutograderSubmission.created_at.desc())
        .all()
    )

    return [
        {
            "id": str(submission.id),
            "student_net_id": submission.student_net_id,
            "student_name": submission.student_name,
            "score": submission.score,
            "raw_max_score": submission.result_json.get("raw_max_score") if submission.result_json else None,
            "created_at": submission.created_at.isoformat()
            if submission.created_at
            else None,
        }
        for submission in submissions
    ]

@router.get("/submissions/me/latest")
async def get_my_latest_submission(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_autograder_role(current_user, ["subscriber"])

    submission = (
        db.query(AutograderSubmission)
        .filter(AutograderSubmission.student_user_id == current_user.id)
        .order_by(AutograderSubmission.created_at.desc())
        .first()
    )

    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No autograder submission found for this student.",
        )

    return {
        "id": str(submission.id),
        "student_net_id": submission.student_net_id,
        "student_name": submission.student_name,
        "score": submission.score,
        "review_required": submission.review_required,
        "created_at": submission.created_at.isoformat() if submission.created_at else None,
        "result_json": submission.result_json,
    }

@router.get("/submissions/{submission_id}")
async def get_submission(
    submission_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_autograder_role(current_user, ["subscriber", "publisher", "admin"])

    submission = (
        db.query(AutograderSubmission)
        .filter(AutograderSubmission.id == submission_id)
        .first()
    )

    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    if current_user.role == "subscriber" and submission.student_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own submission feedback.",
        )

    return {
        "id": str(submission.id),
        "student_net_id": submission.student_net_id,
        "student_name": submission.student_name,
        "score": submission.score,
        "review_required": submission.review_required,
        "created_at": submission.created_at.isoformat()
        if submission.created_at
        else None,
        "result_json": submission.result_json,
    }