import asyncio
import json
import time

import httpx

from app.llm.errors import FatalError, RetryableError
from app.llm.provider import GradingResult, LLMProvider, StudentFiles
from app.services.gemini_file_cache import autograder_cache, refresh_static_uris_for_tier


class GeminiProvider(LLMProvider):
    """
    Calls the Gemini generateContent REST API.

    Each tier (pro / flash / free) uploads static reference PDFs under its own
    API key at startup and stores the resulting Files API URIs in
    autograder_cache.gemini_uris[tier].  At request time _build_parts() reads
    those URIs — if the tier has no URIs (key not configured) it falls back to
    inline base64 automatically.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        tier: str,
    ):
        self._api_key = api_key
        self._model = model
        self._tier = tier

    @property
    def name(self) -> str:
        return f"gemini/{self._model}/{self._tier}"

    @property
    def max_attempts(self) -> int:
        return 2 if self._tier == "pro" else 1

    async def grade(self, student_files: StudentFiles) -> GradingResult:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:generateContent?key={self._api_key}"
        )
        headers = {"Content-Type": "application/json"}
        payload = self._make_payload(student_files)
        parts = payload["contents"][0]["parts"]

        has_uris = bool(autograder_cache.gemini_uris.get(self._tier))
        print(
            f"[TRACE] gemini_request_start "
            f"model={self._model} tier={self._tier} "
            f"using_file_uris={has_uris} "
            f"parts_count={len(parts)} "
            f"part_types={[list(p.keys())[0] for p in parts]}"
        )

        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=350.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            elapsed_ms = int((time.monotonic() - t0) * 1000)

            print(
                f"[TRACE] gemini_response_status={resp.status_code} "
                f"elapsed_ms={elapsed_ms} "
                f"model={self._model} tier={self._tier}"
            )

            # Recovery path: expired/deleted file URI → re-upload once and retry.
            # Triggers on 400/403/404 when this tier has Files API URIs configured.
            if (
                resp.status_code in (400, 403, 404)
                and bool(autograder_cache.gemini_uris.get(self._tier))
                and self._is_file_not_found(resp.json() if resp.content else {})
            ):
                error_body = resp.json() if resp.content else {}
                print(
                    f"[TRACE] gemini_file_not_found_recovery "
                    f"tier={self._tier} "
                    f"status={resp.status_code} "
                    f"error_status={error_body.get('error', {}).get('status')} "
                    f"refreshing_uris=True"
                )
                await asyncio.to_thread(refresh_static_uris_for_tier, self._api_key, self._tier)
                t1 = time.monotonic()
                resp = await client.post(url, json=self._make_payload(student_files), headers=headers)
                elapsed_ms = int((time.monotonic() - t1) * 1000)
                print(
                    f"[TRACE] gemini_response_status={resp.status_code} "
                    f"elapsed_ms={elapsed_ms} "
                    f"after_uri_refresh=True tier={self._tier}"
                )

        if resp.status_code != 200:
            try:
                error_body = resp.json()
            except Exception:
                error_body = {"raw": resp.text[:500]}
            print(
                f"[TRACE] gemini_error_raw "
                f"status={resp.status_code} "
                f"error_code={error_body.get('error', {}).get('code')} "
                f"error_status={error_body.get('error', {}).get('status')} "
                f"error_message={str(error_body.get('error', {}).get('message', ''))[:200]}"
            )

        self._raise_for_status(resp)
        return self._parse_response(resp.json())

    # ------------------------------------------------------------------
    # Payload construction
    # ------------------------------------------------------------------

    def _make_payload(self, student_files: StudentFiles) -> dict:
        return {
            "contents": [{"role": "user", "parts": self._build_parts(student_files)}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }

    def _build_parts(self, student_files: StudentFiles) -> list:
        tier_uris = autograder_cache.gemini_uris.get(self._tier, {})

        if tier_uris.get("rubric"):
            # Use Gemini Files API URIs uploaded at startup for this tier.
            static_parts = [
                {"file_data": {"mime_type": "application/pdf", "file_uri": tier_uris["rubric"]}},
                {"file_data": {"mime_type": "application/pdf", "file_uri": tier_uris["webassign_solution"]}},
                {"file_data": {"mime_type": "application/pdf", "file_uri": tier_uris["solution"]}},
            ]
        else:
            # No URIs for this tier (key not configured) — send inline base64.
            static_parts = [
                {"inline_data": {"mime_type": "application/pdf", "data": autograder_cache.rubric_b64}},
                {"inline_data": {"mime_type": "application/pdf", "data": autograder_cache.webassign_solution_b64}},
                {"inline_data": {"mime_type": "application/pdf", "data": autograder_cache.solution_b64}},
            ]

        return [
            *static_parts,

            {"inline_data": {"mime_type": "application/pdf", "data": student_files.webassign_b64}},
            {"inline_data": {"mime_type": "application/pdf", "data": student_files.handwritten_b64}},

            {
                "text": f"""
        Additional OCR transcript of the student's handwritten work:

        {student_files.handwritten_transcript or "[No handwritten transcript provided]"}

        Use this transcript only as a readability aid alongside the original handwritten PDF.
        If the transcript appears inconsistent with the handwritten PDF in a way that may affect grading, flag human review.
        """
            },

            {"text": autograder_cache.grading_prompt},
        ]

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code == 200:
            return
        # 429 = rate limited; 500/502/503/504 = transient server/proxy failures.
        if resp.status_code in (429, 500, 502, 503, 504):
            raise RetryableError(
                f"{self.name}: HTTP {resp.status_code} — {resp.text[:200]}"
            )
        raise FatalError(
            f"{self.name}: HTTP {resp.status_code} — {resp.text[:200]}"
        )

    @staticmethod
    def _is_file_not_found(error_data: dict) -> bool:
        error = error_data.get("error", {})
        status = error.get("status", "")
        message = error.get("message", "").lower()
        return (
            status == "NOT_FOUND"
            or status == "PERMISSION_DENIED"  # cross-project stale URI
            or (status == "INVALID_ARGUMENT" and "not found" in message)
        )

    # ------------------------------------------------------------------
    # Response parsing — all Gemini-specific JSON extraction lives here
    # ------------------------------------------------------------------

    def _parse_response(self, data: dict) -> GradingResult:
        raw_output = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text")
        )
        if not raw_output:
            raise FatalError(
                f"{self.name}: Model returned empty content. Full response: {data}"
            )

        cleaned = self._clean_json(raw_output)
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
            source=f"gemini_{self._tier}",
        )

    @staticmethod
    def _clean_json(text: str) -> str:
        return text.replace("```json", "").replace("```", "").strip()
