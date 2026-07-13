from dataclasses import dataclass, field

@dataclass
class StudentFiles:
    webassign_b64: str
    handwritten_b64: str = ""
    handwritten_transcript: str | None = None


@dataclass
class GradingResult:
    """Structured output returned by any provider after a successful grading call."""
    raw_score: float
    raw_max_score: float
    score: float
    submission_review_required: bool
    submission_review_reasons: list[str]
    overall_feedback: str
    questions: list[dict]
    model_used: str
    source: str = ""  # "gemini_pro" | "gemini_free" | "openai"


class LLMProvider:
    """Abstract base for all grading providers."""

    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def max_attempts(self) -> int:
        """Maximum number of attempts FallbackProvider will make for this provider."""
        raise NotImplementedError

    async def grade(self, student_files: StudentFiles) -> GradingResult:
        raise NotImplementedError
