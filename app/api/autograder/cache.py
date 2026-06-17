import base64
from pathlib import Path


class AutograderCache:
    grading_prompt: str = ""
    solution_b64: str = ""             # base64-encoded graded handwritten solution PDF
    webassign_solution_b64: str = ""   # base64-encoded graded WebAssign solution PDF
    rubric_b64: str = ""               # base64-encoded rubric PDF
    loaded: bool = False


autograder_cache = AutograderCache()


def load_autograder_cache() -> None:
    """Called once at application startup. Raises RuntimeError if any required file is missing or empty."""
    # cache.py lives at: profsidekick-api/app/api/autograder/cache.py
    # 4 .parent calls resolve to:  profsidekick-api/
    data_dir = Path(__file__).resolve().parent.parent.parent.parent / "data"

    required_files = ["grading_prompt.txt", "solution.pdf", "webassign_solution.pdf", "rubric.pdf"]
    missing = [f for f in required_files if not (data_dir / f).exists()]
    if missing:
        raise RuntimeError(
            f"FATAL: Autograder cannot start. Missing required static files "
            f"in {data_dir}: {', '.join(missing)}"
        )

    autograder_cache.grading_prompt = (data_dir / "grading_prompt.txt").read_text(encoding="utf-8")

    if not autograder_cache.grading_prompt.strip():
        raise RuntimeError("FATAL: grading_prompt.txt is empty.")

    autograder_cache.solution_b64 = base64.b64encode(
        (data_dir / "solution.pdf").read_bytes()
    ).decode()

    autograder_cache.webassign_solution_b64 = base64.b64encode(
        (data_dir / "webassign_solution.pdf").read_bytes()
    ).decode()

    autograder_cache.rubric_b64 = base64.b64encode(
        (data_dir / "rubric.pdf").read_bytes()
    ).decode()

    autograder_cache.loaded = True
    print(f"[STARTUP] Autograder static files loaded from {data_dir}")
