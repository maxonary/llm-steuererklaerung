from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class SourceType(str, Enum):
    GMAIL_ATTACHMENT = "gmail_attachment"
    GMAIL_LINK = "gmail_link"
    LOCAL_DROP = "local_drop"


class InvoiceStatus(str, Enum):
    NEW = "new"
    PROCESSED = "processed"
    NEEDS_REVIEW = "needs_review"
    EXPORTED = "exported"
    DUPLICATE = "duplicate"


@dataclass
class InvoiceRecord:
    invoice_id: str
    source_type: str
    source_message_id: Optional[str]
    gmail_thread_id: Optional[str]
    gmail_link: Optional[str]
    vendor: str
    subject: str
    invoice_date: Optional[str]
    ingest_date: str
    amount: Optional[float]
    currency: str
    category: str
    file_path: Optional[str]
    sha256: Optional[str]
    status: str
    review_reason: Optional[str]
    tax_year: Optional[int]
    tax_month: Optional[int]
    notes: Optional[str]

    @classmethod
    def now_iso(cls) -> str:
        return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
