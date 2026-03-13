from __future__ import annotations

import os

import fitz
import ollama
import openai

MODEL = os.getenv("OLLAMA_MODEL", "mistral")
USE_OPENAI = str(os.getenv("USE_OPENAI", "")).lower() in {"1", "true", "yes"}
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


def extract_text_from_pdf(pdf_path: str, limit: int = 3000) -> str:
    doc = fitz.open(pdf_path)
    text = "\n".join(page.get_text() for page in doc)
    return text[:limit]


def infer_vendor(subject: str, text: str) -> str:
    # Subject is generally the best available source for an initial vendor name.
    if subject:
        parts = subject.split("-")
        if parts:
            return parts[0].strip()[:80]
    first_line = (text or "").splitlines()[0] if text else ""
    return first_line[:80] or "Unknown Vendor"


def categorize_invoice(text: str) -> str:
    prompt = f"""
You are an invoice assistant. Categorize this invoice into one of these categories:
- Work Equipment
- Insurance
- Travel
- Food
- Lifestyle
- Other
Only return one category name.

Invoice:
{text}
"""
    if USE_OPENAI and OPENAI_API_KEY:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
        )
        result = response.choices[0].message.content.strip()
    else:
        response = ollama.chat(model=MODEL, messages=[{"role": "user", "content": prompt}])
        result = response["message"]["content"].strip()

    allowed = {"Work Equipment", "Insurance", "Travel", "Food", "Lifestyle", "Other"}
    return result if result in allowed else "Other"

