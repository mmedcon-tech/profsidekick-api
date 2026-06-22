import base64
import json
import time

import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel, Part

from app.llm.errors import FatalError, RetryableError
from app.llm.provider import GradingResult, LLMProvider, StudentFiles
from app.services.gemini_file_cache import autograder_cache


_VERTEX_INITIALIZED = False


def _ensure_vertex_init(project: str, location: str) -> None:
    global _VERTEX_INITIALIZED
    if not _VERTEX_INITIALIZED:
        vertexai.init(project=project, location=location)
        _VERTEX_INITIALIZED = True


class VertexAIProvider(LLMProvider):
    """
    Grading provider using Gemini via Vertex AI + Application Default Credentials.

    Static PDFs are sent via GCS URIs when GCS_STATIC_BUCKET is configured
    (uploaded once at startup by load_autograder_cache).  If GCS is not set or
    the GCS URIs are unavailable, all PDFs are sent inline as base64 — this is
    the safe default that always works.

    Student PDFs are always inline (never cached).

    Auth: requires ADC to be configured before the process starts.
      Local dev:  gcloud auth application-default login
      CI/prod:    GOOGLE_APPLICATION_CREDENTIALS pointing at a service-account
                  JSON, or Workload Identity on GKE/Cloud Run.
    """

    def __init__(self, project: str, location: str, model: str):
        self._project = project
        self._location = location
        self._model_name = model
        _ensure_vertex_init(project, location)
        self._model = GenerativeModel(model)

    @property
    def name(self) -> str:
        return f"vertex/{self._model_name}"

    @property
    def max_attempts(self) -> int:
        return 1

    async def grade(self, student_files: StudentFiles) -> GradingResult:
        contents = self._build_parts(student_files)
        using_gcs = bool(autograder_cache.vertex_gcs_uris)

        gen_config = GenerationConfig(
            temperature=0.0,
            response_mime_type="application/json",
        )

        t0 = time.monotonic()
        print(
            f"[TRACE] vertex_request_start model={self._model_name} "
            f"parts={len(contents)} using_gcs={using_gcs}"
        )

        try:
            response = await self._model.generate_content_async(
                contents,
                generation_config=gen_config,
            )
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            print(
                f"[TRACE] vertex_response_ok elapsed_ms={elapsed_ms} "
                f"model={self._model_name}"
            )
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            msg = str(exc)
            print(
                f"[TRACE] vertex_error elapsed_ms={elapsed_ms} "
                f"model={self._model_name} error={msg[:200]}"
            )
            lower = msg.lower()
            if any(k in lower for k in (
                "quota", "rate", "503", "502", "429", "unavailable",
                "resource exhausted", "deadline exceeded",
            )):
                raise RetryableError(f"{self.name}: {msg[:300]}")
            # GCS URI access failure — retry with inline fallback if we were using GCS.
            if using_gcs and any(k in lower for k in (
                "permission denied", "not found", "invalid", "access"
            )):
                print(
                    f"[TRACE] vertex_gcs_failure_fallback "
                    f"retrying inline model={self._model_name}"
                )
                contents = self._build_inline_parts(student_files)
                try:
                    response = await self._model.generate_content_async(
                        contents, generation_config=gen_config,
                    )
                    elapsed_ms = int((time.monotonic() - t0) * 1000)
                    print(
                        f"[TRACE] vertex_inline_fallback_ok elapsed_ms={elapsed_ms}"
                    )
                except Exception as exc2:
                    raise FatalError(f"{self.name} (inline fallback): {str(exc2)[:300]}")
            else:
                raise FatalError(f"{self.name}: {msg[:300]}")

        return self._parse_response(response)

    # ------------------------------------------------------------------
    # Part construction
    # ------------------------------------------------------------------

    def _build_parts(self, student_files: StudentFiles) -> list:
        """Use GCS URIs for static files when available; fall back to inline."""
        gcs = autograder_cache.vertex_gcs_uris
        if gcs.get("rubric"):
            static_parts = [
                Part.from_uri(gcs["rubric"], mime_type="application/pdf"),
                Part.from_uri(gcs["webassign_solution"], mime_type="application/pdf"),
                Part.from_uri(gcs["solution"], mime_type="application/pdf"),
            ]
        else:
            static_parts = self._inline_static_parts()

        return [
            *static_parts,
            self._pdf_inline(student_files.webassign_b64),
            self._pdf_inline(student_files.handwritten_b64),
            Part.from_text(autograder_cache.grading_prompt),
        ]

    def _build_inline_parts(self, student_files: StudentFiles) -> list:
        """Always-inline version used as GCS fallback."""
        return [
            *self._inline_static_parts(),
            self._pdf_inline(student_files.webassign_b64),
            self._pdf_inline(student_files.handwritten_b64),
            Part.from_text(autograder_cache.grading_prompt),
        ]

    def _inline_static_parts(self) -> list:
        return [
            self._pdf_inline(autograder_cache.rubric_b64),
            self._pdf_inline(autograder_cache.webassign_solution_b64),
            self._pdf_inline(autograder_cache.solution_b64),
        ]

    @staticmethod
    def _pdf_inline(b64: str) -> Part:
        return Part.from_data(data=base64.b64decode(b64), mime_type="application/pdf")

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, response) -> GradingResult:
        try:
            raw_output = response.text
        except Exception as exc:
            raise FatalError(
                f"{self.name}: Could not extract text from Vertex AI response: {exc}"
            )

        if not raw_output:
            raise FatalError(f"{self.name}: Model returned empty content.")

        cleaned = raw_output.replace("```json", "").replace("```", "").strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise FatalError(
                f"{self.name}: Invalid JSON at line {exc.lineno}, col {exc.colno}: {exc.msg}"
            )

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
                q.get("grading_basis") if isinstance(q.get("grading_basis"), dict) else {}
            )
            questions.append(
                {
                    "id": question_id,
                    "max_score": max_score,
                    "score": safe_score,
                    "grading_basis": {
                        "understanding_level": grading_basis.get("understanding_level", "none"),
                        "error_severity": grading_basis.get("error_severity", "fundamental"),
                        "work_completeness": grading_basis.get("work_completeness", "blank"),
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
                        q.get("grey_areas") if isinstance(q.get("grey_areas"), list) else []
                    ),
                    "human_review_required": bool(q.get("human_review_required", False)),
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
            model_used=self._model_name,
            source="vertex_ai",
        )
