"""
Shared SAE handwritten transcription service.

The handwritten PDF is transcribed.
The WebAssign PDF is provided only as question and notation context.
"""

import asyncio
import os

from google import genai
from google.genai import types


SAE_TRANSCRIPTION_MODEL = "gemini-2.5-pro"

SAE_TRANSCRIPTION_PROMPT = r"""
You are transcribing a student's handwritten mathematics exam submission.

You will receive two PDFs:

1. The student's handwritten work. This is the document you must transcribe.
2. The student's WebAssign question and final-answer PDF. This is provided only
   as context to help identify question numbers, question wording, variables,
   symbols, mathematical notation, and the student's submitted final answers.

Use the WebAssign PDF only to improve the accuracy of reading the handwritten work.

Do not:
- copy reasoning or intermediate steps from the WebAssign PDF
- correct the student's handwritten work
- complete missing handwritten steps
- replace the handwritten answer with the WebAssign answer
- solve or grade any question
- add work that is not visible in the handwritten PDF

If the handwritten PDF and WebAssign PDF conflict, preserve what is visible in
the handwritten PDF. If the handwriting remains ambiguous, write `[unreadable]`
instead of guessing.

Transcribe:
- question numbers and subparts
- the student's written mathematical work
- final answers visible in the handwritten work
- relevant graph or plot descriptions
- the student's mistakes, spelling, notation, and solution structure

Ignore:
- scanner watermarks or application names
- page borders, timestamps, file labels, crop marks, and stamps
- crossed-out or clearly discarded work

Formatting rules:

Markdown:
- Use Markdown headings for questions and subparts.
- Use normal Markdown paragraphs for written explanations.
- Use Markdown tables for tabular work.
- Use bullet points or numbered lists where appropriate.
- Describe graphs, plots, tables, geometric figures, and diagrams in plain text.

LaTeX mathematics:
- Use `$...$` for inline mathematical expressions.
- Use `$$...$$` for displayed mathematical expressions.
- Use standard LaTeX notation inside math delimiters.
- Do not use `\documentclass`, `\begin{document}`, or `\end{document}`.
- Do not use raw environments such as `tabular`, `array`, `align`,
  `enumerate`, or `itemize`.
- For multi-step work, use separate display equations or Markdown steps.

Return only the transcript. Do not include explanations, comments,
introductions, or code fences.
"""


def _transcribe_sync(
    handwritten_bytes: bytes,
    webassign_bytes: bytes,
) -> dict:
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured.")

    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=SAE_TRANSCRIPTION_MODEL,
        contents=[
            "DOCUMENT 1: Student handwritten work to transcribe.",
            types.Part.from_bytes(
                data=handwritten_bytes,
                mime_type="application/pdf",
            ),
            (
                "DOCUMENT 2: The same student's WebAssign question and "
                "final-answer PDF. Use this only as transcription context."
            ),
            types.Part.from_bytes(
                data=webassign_bytes,
                mime_type="application/pdf",
            ),
            SAE_TRANSCRIPTION_PROMPT,
        ],
    )

    transcript_text = (response.text or "").strip()

    if not transcript_text:
        raise RuntimeError("Gemini returned an empty handwritten transcript.")

    return {
        "model": SAE_TRANSCRIPTION_MODEL,
        "latex": transcript_text,
    }


async def transcribe_sae_handwritten(
    handwritten_bytes: bytes,
    webassign_bytes: bytes,
) -> dict:
    """
    Generate a Markdown transcript with LaTeX math from handwritten work.

    WebAssign is supplied only as supporting question context.
    """
    return await asyncio.to_thread(
        _transcribe_sync,
        handwritten_bytes,
        webassign_bytes,
    )