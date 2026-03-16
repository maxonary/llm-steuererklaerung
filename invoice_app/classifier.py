from __future__ import annotations

import os

import fitz

MODEL = os.getenv("OLLAMA_MODEL", "mistral")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

# Backend priority: anthropic > openai > ollama
USE_ANTHROPIC = str(os.getenv("USE_ANTHROPIC", "")).lower() in {"1", "true", "yes"} or bool(ANTHROPIC_API_KEY)
USE_OPENAI = str(os.getenv("USE_OPENAI", "")).lower() in {"1", "true", "yes"}


def _llm_complete(prompt: str, max_tokens: int = 30) -> str:
    """Route a single-turn prompt to the best available LLM backend."""
    if USE_ANTHROPIC and ANTHROPIC_API_KEY:
        import anthropic

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    if USE_OPENAI and OPENAI_API_KEY:
        import openai

        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()

    import ollama

    response = ollama.chat(model=MODEL, messages=[{"role": "user", "content": prompt}])
    return response["message"]["content"].strip()


def extract_text_from_pdf(pdf_path: str, limit: int = 3000) -> str:
    doc = fitz.open(os.path.realpath(pdf_path))
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
    prompt = f"""You are a German tax assistant for a Freiberufler (freelance IT/software consultant).
Categorize this invoice into one of the following EÜR-aligned categories (Anlage EÜR):

- Fremdleistungen (Line 27: subcontractor invoices, freelancers paid for project work)
- Arbeitsmittel (Line 28/29: computers, monitors, keyboards, software licenses, office supplies)
- Reisekosten (Line 31: Deutsche Bahn, SBB, flights, Uber/Bolt, hotels, transport for business travel)
- Bewirtung (Line 32: business meals with clients/partners, restaurant receipts)
- Raumkosten (Line 34: rent, home office costs, coworking spaces)
- Versicherungen (Line 35: Berufshaftpflicht, business insurance, professional liability)
- Telekommunikation (Line 37: phone bills, internet, mobile contracts)
- Übrige Betriebsausgaben (Line 38: SaaS, cloud hosting, domains, Google Ads, memberships, other deductible)
- Nicht abzugsfähig (personal purchases, clothing, sneakers, entertainment, non-deductible items)

Key distinctions:
- SaaS tools, cloud hosting, domains, ads = Übrige Betriebsausgaben (NOT Arbeitsmittel)
- Phone/internet bills = Telekommunikation
- Hardware (computers, monitors) = Arbeitsmittel
- Deutsche Bahn, SBB, flights, Uber, Bolt, taxi, ride-hailing, hotels = Reisekosten (NOT Fremdleistungen)
- Uber Eats, Lieferando, food delivery = Nicht abzugsfähig (personal, NOT Bewirtung)
- Restaurant/meal receipts with business context = Bewirtung
- Fremdleistungen is ONLY for subcontractors/agencies you hired for project work (e.g. developer, designer, consultant invoices)

Only return the category name, nothing else.

Invoice:
{text}
"""
    result = _llm_complete(prompt, max_tokens=10)
    allowed = {
        "Fremdleistungen", "Arbeitsmittel", "Reisekosten", "Bewirtung",
        "Raumkosten", "Versicherungen", "Telekommunikation",
        "Übrige Betriebsausgaben", "Nicht abzugsfähig",
    }
    return result if result in allowed else "Übrige Betriebsausgaben"


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
        result = _llm_complete(prompt, max_tokens=10).lower()
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
        result = _llm_complete(prompt, max_tokens=300)
        if result.upper() == "NONE":
            return []
        return [line.strip() for line in result.splitlines() if line.strip().startswith("http")]
    except Exception:
        return []
