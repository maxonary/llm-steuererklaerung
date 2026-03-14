from __future__ import annotations

import hashlib
import os
import re
import shutil
from datetime import datetime
from typing import Optional

CATEGORIES = [
    "Work Equipment",
    "Insurance",
    "Travel",
    "Food",
    "Lifestyle",
    "Other",
]


def ensure_dirs(*paths: str) -> None:
    for path in paths:
        os.makedirs(path, exist_ok=True)


def file_sha256(file_path: str) -> str:
    digest = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            digest.update(block)
    return digest.hexdigest()


def slugify(value: str, fallback: str = "unknown") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value or "").strip("-").lower()
    return cleaned or fallback


def first_date_from_text(text: str) -> Optional[str]:
    patterns = [
        r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})",
        r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "")
        if not match:
            continue
        groups = match.groups()
        if len(groups[0]) == 4:
            year, month, day = groups
        else:
            day, month, year = groups
            if len(year) == 2:
                year = f"20{year}"
        try:
            return datetime(int(year), int(month), int(day)).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_amount(text: str) -> Optional[float]:
    match = re.search(r"(\d{1,5}[,.]\d{2})\s?(€|EUR)", text or "", re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def unique_destination(dest_path: str) -> str:
    if not os.path.exists(dest_path):
        return dest_path
    base, ext = os.path.splitext(dest_path)
    i = 1
    while True:
        candidate = f"{base}_{i}{ext}"
        if not os.path.exists(candidate):
            return candidate
        i += 1


def move_to_category(
    file_path: str,
    category: str,
    sorted_dir: str,
    invoice_date: Optional[str],
    vendor: Optional[str],
) -> str:
    safe_category = category if category in CATEGORIES else "Other"
    dest_dir = os.path.join(sorted_dir, safe_category)
    os.makedirs(dest_dir, exist_ok=True)

    if invoice_date:
        vendor_slug = slugify(vendor or "vendor")
        filename = f"{invoice_date}__{vendor_slug}.pdf"
    else:
        filename = os.path.basename(file_path)
    dest_path = unique_destination(os.path.join(dest_dir, filename))
    shutil.move(file_path, dest_path)
    return dest_path


def infer_document_type(category: str, file_path: str) -> str:
    lower = os.path.basename(file_path).lower() if file_path else ""
    if "bewirtungsbeleg" in lower:
        return "Bewirtungsbeleg"
    if category == "Travel":
        return "Reisekostenbeleg"
    if category in {"Work Equipment", "Insurance", "Food", "Lifestyle", "Other"}:
        return "Eingangsrechnung"
    return "Sonstiges"

