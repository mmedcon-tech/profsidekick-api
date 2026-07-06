import argparse
import base64
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types


def main():
    parser = argparse.ArgumentParser(description="Test Gemini OCR on a PDF.")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--out", default="data/gemini_ocr_tests")
    parser.add_argument("--model", default="gemini-2.5-pro")
    args = parser.parse_args()

    load_dotenv()

    api_key = ( os.getenv("GEMINI_API_KEY")  )

    if not api_key:
        print("No Gemini API key found in .env.")
        return

    pdf_path = Path(args.pdf)
    output_dir = Path(args.out) / pdf_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")

    client = genai.Client(api_key=api_key)

    prompt = r"""
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

    response = client.models.generate_content(
        model=args.model,
        contents=[
            types.Part.from_bytes(
                data=pdf_path.read_bytes(),
                mime_type="application/pdf",
            ),
            prompt,
        ],
    )

    md_path = output_dir / "ocr_markdown.md"
    md_path.write_text(response.text or "", encoding="utf-8")

    print(f"Saved Gemini OCR markdown: {md_path}")
    print("\nPreview:\n")
    print((response.text or "")[:2000])


if __name__ == "__main__":
    main()