from __future__ import annotations

import csv
import os
import shutil
import uuid
import zipfile
from datetime import datetime

from . import index
from .storage import infer_document_type, slugify

TYPE_PRIORITY = {
    "Eingangsrechnung": 0,
    "Bewirtungsbeleg": 1,
    "Reisekostenbeleg": 2,
    "Sonstiges": 3,
}


def _sort_key(row: dict) -> tuple:
    document_type = infer_document_type(row["category"], row["file_path"] or "")
    return (
        row["invoice_date"] or "9999-12-31",
        TYPE_PRIORITY.get(document_type, 99),
        (row["vendor"] or "").lower(),
        (row["file_path"] or "").lower(),
    )


def export_month(
    *,
    year: int,
    month: int,
    include_status: list[str],
    output_root: str = "Exports",
    db_path: str = index.DB_PATH,
) -> tuple[str, str]:
    rows = [dict(r) for r in index.list_for_export(year, month, include_status, db_path=db_path)]
    rows.sort(key=_sort_key)

    month_dir = os.path.join(output_root, str(year), f"{year}-{month:02d}")
    os.makedirs(month_dir, exist_ok=True)
    zip_path = os.path.join(month_dir, f"{year}-{month:02d}-invoices.zip")
    manifest_path = os.path.join(month_dir, f"{year}-{month:02d}-manifest.csv")

    manifest_headers = [
        "sort_key",
        "invoice_date",
        "document_type",
        "vendor",
        "amount",
        "currency",
        "category",
        "file_name",
        "gmail_subject",
        "gmail_link",
        "source_message_id",
        "status",
        "notes",
    ]

    invoice_ids: list[str] = []
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf, open(
        manifest_path, "w", newline="", encoding="utf-8"
    ) as mf:
        writer = csv.DictWriter(mf, fieldnames=manifest_headers)
        writer.writeheader()
        for i, row in enumerate(rows, start=1):
            if not row["file_path"] or not os.path.exists(row["file_path"]):
                continue
            doc_type = infer_document_type(row["category"], row["file_path"])
            vendor_slug = slugify(row["vendor"], fallback="vendor")
            short_hash = (row["sha256"] or "nohash")[:8]
            date_key = row["invoice_date"] or f"{year}-{month:02d}-01"
            out_name = f"{date_key}__{doc_type}__{vendor_slug}__{short_hash}.pdf"
            tmp_copy = os.path.join(month_dir, out_name)
            shutil.copy2(row["file_path"], tmp_copy)
            zf.write(tmp_copy, arcname=out_name)
            os.remove(tmp_copy)

            writer.writerow(
                {
                    "sort_key": i,
                    "invoice_date": row["invoice_date"] or "",
                    "document_type": doc_type,
                    "vendor": row["vendor"] or "",
                    "amount": row["amount"] or "",
                    "currency": row["currency"] or "EUR",
                    "category": row["category"] or "",
                    "file_name": out_name,
                    "gmail_subject": row["subject"] or "",
                    "gmail_link": row["gmail_link"] or "",
                    "source_message_id": row["source_message_id"] or "",
                    "status": row["status"] or "",
                    "notes": row["notes"] or "",
                }
            )
            invoice_ids.append(row["invoice_id"])

    export_id = str(uuid.uuid4())
    index.record_export(
        export_id=export_id,
        created_at=datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        year=year,
        month=month,
        zip_path=zip_path,
        manifest_path=manifest_path,
        invoice_ids=invoice_ids,
        db_path=db_path,
    )
    return zip_path, manifest_path

