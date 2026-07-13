import json

import openai

from app.llm.errors import FatalError, RetryableError
from app.llm.provider import GradingResult, LLMProvider, StudentFiles
from app.services.gemini_file_cache import autograder_cache


class OpenAIProvider(LLMProvider):
    """
    Grading provider using the OpenAI Responses API (vision-capable).

    All five PDFs are sent inline as base64 on every request — OpenAI has no
    equivalent to Gemini's Files API, so there is no file-URI caching here.

    Static PDFs (rubric + graded solutions) are read from autograder_cache.{key}_b64,
    which is pre-encoded at startup.  Student PDFs arrive pre-encoded from the API
    layer.  No disk I/O occurs during a live request.
    """

    def __init__(self, api_key: str):
        self._api_key = api_key
        from app.config import settings
        self._model = settings.openai_model
        self._client = openai.AsyncOpenAI(api_key=api_key)

        sdk_version = getattr(openai, "VERSION", getattr(openai, "version", "unknown"))
        has_responses = hasattr(self._client, "responses")
        print(
            f"[TRACE] openai_sdk_init "
            f"sdk_version={sdk_version} "
            f"model={self._model} "
            f"has_responses_api={has_responses} "
            f"client_type={type(self._client).__name__}"
        )
        if not has_responses:
            print(
                f"[TRACE] openai_sdk_WARNING: 'responses' attribute is MISSING on "
                f"AsyncOpenAI (sdk={sdk_version}). The Responses API requires "
                f"openai>=1.66.0. Current provider will raise FatalError on every "
                f"call. Fix: update requirements.txt to openai>=1.66.0"
            )

    @property
    def name(self) -> str:
        return f"openai/{self._model}"

    @property
    def max_attempts(self) -> int:
        return 1

    async def grade(self, student_files: StudentFiles) -> GradingResult:
        sdk_version = getattr(openai, "VERSION", getattr(openai, "version", "unknown"))
        has_responses = hasattr(self._client, "responses")
        available_attrs = [a for a in dir(self._client) if not a.startswith("_")]

        print(
            f"[TRACE] openai_grade_start "
            f"model={self._model} "
            f"sdk_version={sdk_version} "
            f"has_responses_api={has_responses} "
            f"openai_method_used={'responses.create' if has_responses else 'UNAVAILABLE'}"
        )
        if not has_responses:
            print(
                f"[TRACE] openai_attribute_check "
                f"available_top_level_attrs={available_attrs}"
            )
            raise FatalError(
                f"{self.name}: 'responses' API not available in openai=={sdk_version}. "
                f"Upgrade requirements.txt to openai>=1.66.0 to enable the Responses API."
            )

        try:
            response = await self._client.responses.create(
                model=self._model,
                input=self._build_input(student_files),
                text={"format": {"type": "json_object"}},
            )
        except openai.RateLimitError as exc:
            print(f"[TRACE] openai_exception type=RateLimitError msg={str(exc)[:200]}")
            raise RetryableError(f"{self.name}: rate limited — {exc}")
        except openai.APIConnectionError as exc:
            print(f"[TRACE] openai_exception type=APIConnectionError msg={str(exc)[:200]}")
            raise RetryableError(f"{self.name}: connection error — {exc}")
        except openai.APITimeoutError as exc:
            print(f"[TRACE] openai_exception type=APITimeoutError msg={str(exc)[:200]}")
            raise RetryableError(f"{self.name}: timeout — {exc}")
        except openai.InternalServerError as exc:
            print(f"[TRACE] openai_exception type=InternalServerError msg={str(exc)[:200]}")
            raise RetryableError(f"{self.name}: server error — {exc}")
        except openai.BadRequestError as exc:
            print(f"[TRACE] openai_exception type=BadRequestError msg={str(exc)[:200]}")
            raise FatalError(f"{self.name}: bad request — {exc}")
        except openai.AuthenticationError as exc:
            print(f"[TRACE] openai_exception type=AuthenticationError msg={str(exc)[:200]}")
            raise FatalError(f"{self.name}: authentication failed — {exc}")
        except Exception as exc:
            # Unknown exceptions are not safe to retry — they may be programming
            # errors (TypeError, AttributeError) that would fail identically on
            # every attempt.  Treat as fatal so the bug surfaces immediately.
            print(
                f"[TRACE] openai_exception type={type(exc).__name__} "
                f"msg={str(exc)[:300]}"
            )
            raise FatalError(f"{self.name}: unexpected error — {type(exc).__name__}: {exc}")

        return self._parse_response(response)

    # ------------------------------------------------------------------
    # Request construction
    # ------------------------------------------------------------------

    def _build_input(self, student_files: StudentFiles) -> list:
        """
        Constructs the Responses API input list.

        Order mirrors the Gemini payload convention:
          rubric → graded_webassign → graded_handwritten →
          student_webassign → student_handwritten → prompt
        """
        content = [
            # --- Static reference PDFs (pre-encoded at startup, no disk I/O) ---
            _pdf_part("rubric.pdf", autograder_cache.rubric_b64),
            _pdf_part("graded_webassign.pdf", autograder_cache.webassign_solution_b64),
            _pdf_part("graded_handwritten.pdf", autograder_cache.solution_b64),
            # --- Student submission (inline per-request, never reused) ---
            _pdf_part("student_webassign.pdf", student_files.webassign_b64),
            _pdf_part("student_handwritten.pdf", student_files.handwritten_b64),

            {
                "type": "input_text",
                "text": f"""
            Additional OCR transcript of the student's handwritten work:

            {student_files.handwritten_transcript or "[No handwritten transcript provided]"}

            Use this transcript only as a readability aid alongside the original handwritten PDF.
            If the transcript appears inconsistent with the handwritten PDF in a way that may affect grading, flag human review.
            """,
            },
            # --- Grading instruction (last, after all documents are presented) ---
            {"type": "input_text", "text": autograder_cache.grading_prompt},
        ]
        return [{"role": "user", "content": content}]

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, response) -> GradingResult:
        raw_text = getattr(response, "output_text", None)
        if not raw_text:
            raise FatalError(
                f"{self.name}: response contained no output text. "
                f"Full response: {response}"
            )

        cleaned = raw_text.replace("```json", "").replace("```", "").strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise FatalError(
                f"{self.name}: invalid JSON at line {exc.lineno}, "
                f"col {exc.colno}: {exc.msg}"
            )

        # Full schema — model followed the grading prompt's JSON spec.
        if "questions" in parsed:
            return self._parse_full_schema(parsed)

        # Simplified schema — model returned {"grade": N, "feedback": "..."}.
        if "grade" in parsed:
            return self._parse_simple_schema(parsed)

        raise FatalError(
            f"{self.name}: unrecognised response schema. "
            f"Keys received: {list(parsed.keys())}"
        )

    def _parse_full_schema(self, parsed: dict) -> GradingResult:
        """Parse the same JSON schema the grading prompt specifies for Gemini."""
        questions: list[dict] = []
        for q in parsed.get("questions", []):
            question_id = str(q.get("id", "")).strip()

            raw_max = q.get("max_score")
            max_score = float(raw_max) if isinstance(raw_max, (int, float)) else 0.0

            raw_score_val = q.get("score")
            safe_score: float | None = (
                max(0.0, min(float(raw_score_val), max_score))
                if isinstance(raw_score_val, (int, float))
                else None
            )

            grading_basis = (
                q.get("grading_basis")
                if isinstance(q.get("grading_basis"), dict)
                else {}
            )

            questions.append(
                {
                    "id": question_id,
                    "max_score": max_score,
                    "score": safe_score,
                    "grading_basis": {
                        "understanding_level": grading_basis.get(
                            "understanding_level", "none"
                        ),
                        "error_severity": grading_basis.get(
                            "error_severity", "fundamental"
                        ),
                        "work_completeness": grading_basis.get(
                            "work_completeness", "blank"
                        ),
                        "recommended_credit_percent": grading_basis.get(
                            "recommended_credit_percent", 0
                        ),
                    },
                    "official_answer_summary": q.get("official_answer_summary", ""),
                    "student_answer_summary": q.get("student_answer_summary", ""),
                    "confidence": q.get("confidence", "low"),
                    "readability": q.get("readability", "low"),
                    "feedback": q.get("feedback", ""),
                    "grey_areas": (
                        q.get("grey_areas")
                        if isinstance(q.get("grey_areas"), list)
                        else []
                    ),
                    "human_review_required": bool(
                        q.get("human_review_required", False)
                    ),
                    "human_review_reason": q.get("human_review_reason"),
                }
            )

        raw_max_score = sum(q["max_score"] for q in questions)
        raw_score = sum(
            q["score"] for q in questions if isinstance(q["score"], (int, float))
        )

        null_score_reasons = [
            f"Question {q['id']} could not be scored."
            for q in questions
            if q["score"] is None
        ]

        review_reasons: list[str] = []
        if isinstance(parsed.get("submission_review_reasons"), list):
            review_reasons.extend(parsed["submission_review_reasons"])
        review_reasons.extend(
            f"Question {q['id']}: {q['human_review_reason'] or 'Review required.'}"
            for q in questions
            if q["human_review_required"]
        )
        review_reasons.extend(null_score_reasons)

        return GradingResult(
            raw_score=raw_score,
            raw_max_score=raw_max_score,
            score=raw_score,
            submission_review_required=(
                bool(parsed.get("submission_review_required")) or bool(review_reasons)
            ),
            submission_review_reasons=review_reasons,
            overall_feedback=parsed.get("overall_feedback", ""),
            questions=questions,
            model_used=self._model,
            source="openai",
        )

    def _parse_simple_schema(self, parsed: dict) -> GradingResult:
        """
        Handles {"grade": N, "feedback": "..."} when the model did not follow
        the full schema.  Produces a valid GradingResult with no per-question
        breakdown — the reviewer flag is set so a human can inspect the result.
        """
        score = float(parsed.get("grade", 0))
        feedback = str(parsed.get("feedback", ""))
        return GradingResult(
            raw_score=score,
            raw_max_score=0.0,   # max unknown — model skipped per-question breakdown
            score=score,
            submission_review_required=True,
            submission_review_reasons=[
                "OpenAI returned a simplified grade only — per-question "
                "breakdown unavailable. Human review recommended."
            ],
            overall_feedback=feedback,
            questions=[],
            model_used=self._model,
            source="openai",
        )


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def _pdf_part(filename: str, b64: str) -> dict:
    """Build a single Responses API input_file content block for a PDF."""
    return {
        "type": "input_file",
        "filename": filename,
        "file_data": f"data:application/pdf;base64,{b64}",
    }
