from __future__ import annotations

import base64
import os
import pickle
import re
from datetime import datetime
from typing import Iterator, Optional

import requests
from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
KEYWORDS = ["RECHNUNG", "INVOICE", "BELEG"]
LABEL_PROCESSED = "Invoices/Processed"
LABEL_REVIEW = "Invoices/NeedsReview"
LABEL_DUPLICATE = "Invoices/Duplicate"


def gmail_authenticate() -> object:
    creds = None
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
        creds = flow.run_local_server(port=0)
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)
    return build("gmail", "v1", credentials=creds)


def build_search_query(
    *,
    since: Optional[str] = None,
    window_months: int = 18,
    keywords: Optional[list[str]] = None,
) -> str:
    kw = keywords or KEYWORDS
    keyword_part = " OR ".join(kw)
    if since:
        return f"({keyword_part}) after:{since}"
    # Gmail query language supports m for months.
    return f"({keyword_part}) newer_than:{window_months}m"


def search_messages(service: object, query: str) -> list[dict]:
    messages: list[dict] = []
    next_page_token = None
    while True:
        response = (
            service.users()
            .messages()
            .list(userId="me", q=query, pageToken=next_page_token)
            .execute()
        )
        messages.extend(response.get("messages", []))
        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break
    return messages


def _parse_headers(payload: dict) -> tuple[str, str]:
    subject = "No Subject"
    sender = ""
    for header in payload.get("headers", []):
        name = header.get("name", "").lower()
        if name == "subject":
            subject = header.get("value", "No Subject")
        if name == "from":
            sender = header.get("value", "")
    return subject, sender


def load_message(service: object, message_id: str) -> dict:
    return (
        service.users().messages().get(userId="me", id=message_id, format="full").execute()
    )


def message_summary(full_message: dict) -> dict:
    payload = full_message.get("payload", {})
    subject, sender = _parse_headers(payload)
    internal_ts = full_message.get("internalDate")
    message_dt = datetime.utcnow()
    if internal_ts:
        message_dt = datetime.utcfromtimestamp(int(internal_ts) / 1000)
    return {
        "subject": subject,
        "sender": sender,
        "thread_id": full_message.get("threadId"),
        "message_date": message_dt.strftime("%Y-%m-%d"),
    }


def download_pdf_attachments(
    service: object, message_id: str, save_dir: str
) -> Iterator[str]:
    os.makedirs(save_dir, exist_ok=True)
    message = load_message(service, message_id)
    for part in message.get("payload", {}).get("parts", []):
        filename = part.get("filename", "")
        body = part.get("body", {})
        if filename.lower().endswith(".pdf") and "attachmentId" in body:
            attachment_id = body["attachmentId"]
            attachment = (
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=message_id, id=attachment_id)
                .execute()
            )
            raw_data = attachment.get("data", "")
            if not raw_data:
                continue
            data = base64.urlsafe_b64decode(raw_data.encode("utf-8"))
            dest = _unique_file_path(os.path.join(save_dir, filename))
            with open(dest, "wb") as f:
                f.write(data)
            yield dest


def _extract_anchor_context(body_fragments: list[str], max_chars: int = 4000) -> str:
    soup = BeautifulSoup("\n".join(body_fragments), "html.parser")
    lines: list[str] = []
    total = 0
    for i, anchor in enumerate(soup.find_all("a"), 1):
        href = (anchor.get("href") or "").strip()
        if not href:
            continue
        text = (anchor.get_text(strip=True) or "")[:80]
        parent_text = ""
        if anchor.parent:
            parent_text = (anchor.parent.get_text(strip=True) or "")[:50]
        line = f"{i}. [{text}]({href}) -- context: \"{parent_text}\""
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


def extract_pdf_links(full_message: dict, *, use_llm_fallback: bool = False) -> list[str]:
    body_fragments: list[str] = []
    for part in full_message.get("payload", {}).get("parts", []):
        mime = part.get("mimeType")
        raw_data = part.get("body", {}).get("data")
        if mime in {"text/plain", "text/html"} and raw_data:
            body_fragments.append(base64.urlsafe_b64decode(raw_data).decode("utf-8", errors="ignore"))
    soup = BeautifulSoup("\n".join(body_fragments), "html.parser")
    urls: list[str] = []
    for anchor in soup.find_all("a"):
        href = (anchor.get("href") or "").strip()
        label = (anchor.text or "").lower()
        if not href:
            continue
        if href.lower().endswith(".pdf") or re.search(
            r"(rechnung|invoice|beleg|receipt|download|pdf)", label
        ):
            cleaned = href.strip(">)].,;\"'")
            if cleaned not in urls:
                urls.append(cleaned)

    if not urls and use_llm_fallback:
        context = _extract_anchor_context(body_fragments)
        if context:
            from invoice_app.classifier import extract_links_with_llm

            subject = ""
            sender = ""
            for h in full_message.get("payload", {}).get("headers", []):
                if h["name"].lower() == "subject":
                    subject = h["value"]
                if h["name"].lower() == "from":
                    sender = h["value"]
            llm_urls = extract_links_with_llm(subject, sender, context)
            if llm_urls:
                print(f"[i] LLM found {len(llm_urls)} link(s) for message")
            urls.extend(llm_urls)

    return urls


def download_pdf_from_url(url: str, save_dir: str) -> Optional[str]:
    try:
        response = requests.get(url, timeout=8)
    except Exception:
        return None
    if response.status_code >= 400:
        return None
    content_type = response.headers.get("content-type", "").lower()
    if "pdf" not in content_type and not url.lower().endswith(".pdf"):
        return None
    if not response.content:
        return None
    filename = os.path.basename(url.split("?")[0]) or "download.pdf"
    if not filename.lower().endswith(".pdf"):
        filename = f"{filename}.pdf"
    dest = _unique_file_path(os.path.join(save_dir, filename))
    with open(dest, "wb") as f:
        f.write(response.content)
    return dest


def ensure_label(service: object, name: str) -> str:
    response = service.users().labels().list(userId="me").execute()
    for label in response.get("labels", []):
        if label.get("name") == name:
            return label.get("id")
    created = (
        service.users()
        .labels()
        .create(
            userId="me",
            body={
                "name": name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        )
        .execute()
    )
    return created["id"]


def apply_label(service: object, message_id: str, label_name: str) -> None:
    label_id = ensure_label(service, label_name)
    service.users().messages().modify(
        userId="me", id=message_id, body={"addLabelIds": [label_id]}
    ).execute()


def _unique_file_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while True:
        candidate = f"{base}_{i}{ext}"
        if not os.path.exists(candidate):
            return candidate
        i += 1

