import argparse
import base64
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv


def encode_pdf(pdf_path: Path) -> str:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    return base64.b64encode(pdf_path.read_bytes()).decode("utf-8")


def main():
    parser = argparse.ArgumentParser(description="Test Mistral OCR on a PDF.")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--out", default="data/mistral_ocr_tests")
    parser.add_argument("--model", default="mistral-ocr-4-0")
    args = parser.parse_args()

    load_dotenv()

    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key or api_key == "replace_later":
        print("MISTRAL_API_KEY is missing or still set to replace_later.")
        return

    pdf_path = Path(args.pdf)
    output_dir = Path(args.out) / pdf_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    base64_pdf = encode_pdf(pdf_path)

    payload = {
        "model": args.model,
        "document": {
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{base64_pdf}",
        },
        "include_image_base64": False,
    }

    print(f"Calling Mistral OCR for: {pdf_path}")

    response = httpx.post(
        "https://api.mistral.ai/v1/ocr",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )

    print("Status:", response.status_code)

    try:
        data = response.json()
    except Exception:
        print(response.text)
        return

    raw_path = output_dir / "raw_response.json"
    raw_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    markdown_parts = []
    for page in data.get("pages", []):
        index = page.get("index", "?")
        markdown = page.get("markdown", "")
        markdown_parts.append(f"# Page {index}\n\n{markdown}")

    md_path = output_dir / "ocr_markdown.md"
    md_path.write_text("\n\n".join(markdown_parts), encoding="utf-8")

    print(f"Saved raw response: {raw_path}")
    print(f"Saved markdown: {md_path}")

    if response.status_code != 200:
        print("API returned an error. Check raw_response.json for details.")


if __name__ == "__main__":
    main()