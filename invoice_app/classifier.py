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
    prompt = f"""You are a tax assistant for a self-employed person (Selbständiger) in Germany.
Categorize this invoice into one of these categories:

- Work Equipment (computers, software, office supplies, business tools)
- Insurance (business-related insurance, Haftpflicht, Berufshaftpflicht)
- Travel (Deutsche Bahn, flights, Uber/Bolt rides for business, hotels, transport)
- Food (business meals, Bewirtung)
- Subscriptions (SaaS, cloud services, professional memberships)
- Not Deductible (personal purchases, sneakers, entertainment, personal lifestyle)
- Other (deductible items that don't fit above categories)

The person is a Freiberufler (freelance IT/software). Consider:
- Deutsche Bahn, SBB, Bolt, Uber rides, flights, hotels = Travel
- Google Ads, cloud hosting, domains, SaaS tools = Subscriptions
- Computers, monitors, keyboards, software licenses = Work Equipment
- Business meals with clients/partners = Food (Bewirtung)
- Personal purchases (clothing, sneakers, entertainment, personal electronics) = Not Deductible

Only return the category name.

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

    allowed = {"Work Equipment", "Insurance", "Travel", "Food", "Subscriptions", "Not Deductible", "Other"}
    return result if result in allowed else "Other"


def triage_review_item(subject: str, sender: str) -> str:
    prompt = f"""You are an email triage assistant. Based on the email subject and sender, classify whether this email contains or links to an invoice/receipt.

Subject: {subject}
From: {sender}

Classify as one of:
- not_invoice — delivery notification, order confirmation without receipt, marketing, conversation thread, account alert
- likely_invoice — real invoice/receipt email where PDF might be downloadable from a portal or attached
- uncertain — can't tell from subject/sender alone

Return only one of: not_invoice, likely_invoice, uncertain"""

    try:
        if USE_OPENAI and OPENAI_API_KEY:
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
            )
            result = response.choices[0].message.content.strip().lower()
        else:
            response = ollama.chat(model=MODEL, messages=[{"role": "user", "content": prompt}])
            result = response["message"]["content"].strip().lower()

        if result in {"not_invoice", "likely_invoice", "uncertain"}:
            return result
        return "uncertain"
    except Exception:
        return "uncertain"


def extract_links_with_llm(subject: str, sender: str, links_context: str) -> list[str]:
    prompt = f"""You are an email analysis assistant. Given the following email metadata and a list of links found in the email body, identify which URLs are most likely direct invoice or receipt PDF download links.

Subject: {subject}
From: {sender}

Links found in email:
{links_context}

Return only the URLs that are most likely invoice/receipt PDF download links, one per line.
If none of the links appear to be invoice download links, return "NONE".
"""
    try:
        if USE_OPENAI and OPENAI_API_KEY:
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
            )
            result = response.choices[0].message.content.strip()
        else:
            response = ollama.chat(model=MODEL, messages=[{"role": "user", "content": prompt}])
            result = response["message"]["content"].strip()

        if result.upper() == "NONE":
            return []
        return [line.strip() for line in result.splitlines() if line.strip().startswith("http")]
    except Exception:
        return []

