from __future__ import annotations

import argparse
import csv
import os
import re
import uuid
from datetime import datetime

from dotenv import load_dotenv

from invoice_app import export as accountant_export
from invoice_app import index
from invoice_app.models import InvoiceRecord, InvoiceStatus, SourceType
from invoice_app.storage import (
    ensure_dirs,
    file_sha256,
    first_date_from_text,
    move_to_category,
    parse_amount,
)

load_dotenv()

DOWNLOAD_DIR = "temp_invoices"
SORTED_DIR = "Invoices"
BLACKLISTED_SENDERS = [
    "noreply@paypal.com",
    "service@paypal.de",
    "no-reply@payments.google.com",
    "noreply@accounts.google.com",
    "notification@facebookmail.com",
    "noreply@apple.com",
]


# Legacy compatibility wrappers used by server.py and older scripts.
def extract_text_from_pdf(pdf_path):
    from invoice_app.classifier import extract_text_from_pdf as _extract_text_from_pdf

    return _extract_text_from_pdf(pdf_path)


def categorize_invoice(text, model=None):
    from invoice_app.classifier import categorize_invoice as _categorize_invoice

    return _categorize_invoice(text)


def infer_vendor(subject, text):
    from invoice_app.classifier import infer_vendor as _infer_vendor

    return _infer_vendor(subject, text)


def sort_file_to_category(
    file_path,
    category,
    text=None,
    rename_by_date=False,
    base_dir=SORTED_DIR,
    calendar_context=None,
):
    invoice_date = first_date_from_text(text or "") if rename_by_date else None
    vendor = os.path.splitext(os.path.basename(file_path))[0]
    return move_to_category(file_path, category, base_dir, invoice_date, vendor)


def _tax_parts(invoice_date: str | None, fallback_date: str | None = None) -> tuple[int | None, int | None]:
    value = invoice_date or fallback_date
    if not value:
        return None, None
    try:
        dt = datetime.strptime(value, "%Y-%m-%d")
        return dt.year, dt.month
    except ValueError:
        return None, None


def _persist_record(record: InvoiceRecord) -> None:
    try:
        index.upsert_invoice(record)
    except Exception as exc:
        print(f"[!] Failed to write index row for {record.invoice_id}: {exc}")


def _migrate_review_queue(csv_path: str = "review_queue.csv") -> None:
    if not os.path.exists(csv_path):
        return
    conn = None
    try:
        conn = index.get_conn()
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                gmail_link = row.get("Gmail Link") or ""
                message_id = gmail_link.split("/")[-1] if "mail.google.com" in gmail_link else None
                subject = row.get("Subject", "Legacy Review Item")
                reason = row.get("Reason", "Legacy review queue item")
                exists = conn.execute(
                    "SELECT 1 FROM invoices WHERE gmail_link = ? AND review_reason = ? LIMIT 1",
                    (gmail_link or None, reason),
                ).fetchone()
                if exists:
                    continue
                record = InvoiceRecord(
                    invoice_id=str(uuid.uuid4()),
                    source_type=SourceType.GMAIL_LINK.value,
                    source_message_id=message_id,
                    gmail_thread_id=None,
                    gmail_link=gmail_link or None,
                    vendor=infer_vendor(subject, ""),
                    subject=subject,
                    invoice_date=None,
                    ingest_date=InvoiceRecord.now_iso(),
                    amount=None,
                    currency="EUR",
                    category="Other",
                    file_path=None,
                    sha256=None,
                    status=InvoiceStatus.NEEDS_REVIEW.value,
                    review_reason=reason,
                    tax_year=None,
                    tax_month=None,
                    notes="migrated_from_review_queue_csv",
                )
                _persist_record(record)
    except Exception as exc:
        print(f"[!] Failed to migrate review queue: {exc}")
    finally:
        if conn is not None:
            conn.close()


def _ingest_pdf(
    *,
    pdf_path: str,
    source_type: SourceType,
    subject: str,
    source_message_id: str | None,
    gmail_thread_id: str | None,
    gmail_link: str | None,
    fallback_date: str | None,
) -> str:
    text = extract_text_from_pdf(pdf_path)
    category = categorize_invoice(text)
    vendor = infer_vendor(subject, text)
    invoice_date = first_date_from_text(text) or fallback_date
    amount = parse_amount(text)
    tax_year, tax_month = _tax_parts(invoice_date, fallback_date)

    digest = file_sha256(pdf_path)
    existing = index.find_by_sha(digest)
    if existing:
        # Keep one canonical PDF on disk, but index this source as a duplicate event.
        os.remove(pdf_path)
        record = InvoiceRecord(
            invoice_id=str(uuid.uuid4()),
            source_type=source_type.value,
            source_message_id=source_message_id,
            gmail_thread_id=gmail_thread_id,
            gmail_link=gmail_link,
            vendor=vendor,
            subject=subject,
            invoice_date=invoice_date,
            ingest_date=InvoiceRecord.now_iso(),
            amount=amount,
            currency="EUR",
            category=existing["category"],
            file_path=existing["file_path"],
            sha256=None,
            status=InvoiceStatus.DUPLICATE.value,
            review_reason=None,
            tax_year=tax_year,
            tax_month=tax_month,
            notes=f"duplicate_sha256_of:{existing['invoice_id']}",
        )
        _persist_record(record)
        return InvoiceStatus.DUPLICATE.value

    moved_path = move_to_category(
        file_path=pdf_path,
        category=category,
        sorted_dir=SORTED_DIR,
        invoice_date=invoice_date,
        vendor=vendor,
    )

    record = InvoiceRecord(
        invoice_id=str(uuid.uuid4()),
        source_type=source_type.value,
        source_message_id=source_message_id,
        gmail_thread_id=gmail_thread_id,
        gmail_link=gmail_link,
        vendor=vendor,
        subject=subject,
        invoice_date=invoice_date,
        ingest_date=InvoiceRecord.now_iso(),
        amount=amount,
        currency="EUR",
        category=category,
        file_path=moved_path,
        sha256=digest,
        status=InvoiceStatus.PROCESSED.value,
        review_reason=None,
        tax_year=tax_year,
        tax_month=tax_month,
        notes=None,
    )
    _persist_record(record)
    return InvoiceStatus.PROCESSED.value


def run_sync_gmail(args) -> None:
    from invoice_app import gmail_sync

    service = gmail_sync.gmail_authenticate()
    query = gmail_sync.build_search_query(since=args.since, window_months=args.window_months)
    print(f"[i] Gmail search query: {query}")
    messages = gmail_sync.search_messages(service, query)
    print(f"[i] Found {len(messages)} matching emails.")

    for item in messages:
        message_id = item["id"]
        full_message = gmail_sync.load_message(service, message_id)
        summary = gmail_sync.message_summary(full_message)

        sender = summary["sender"].lower()
        if any(bad in sender for bad in BLACKLISTED_SENDERS):
            continue

        subject = summary["subject"]
        thread_id = summary["thread_id"]
        message_date = summary["message_date"]
        gmail_link = f"https://mail.google.com/mail/u/0/#inbox/{message_id}"

        statuses = []
        attachment_paths = list(gmail_sync.download_pdf_attachments(service, message_id, DOWNLOAD_DIR))
        for path in attachment_paths:
            status = _ingest_pdf(
                pdf_path=path,
                source_type=SourceType.GMAIL_ATTACHMENT,
                subject=subject,
                source_message_id=message_id,
                gmail_thread_id=thread_id,
                gmail_link=gmail_link,
                fallback_date=message_date,
            )
            statuses.append(status)

        urls = gmail_sync.extract_pdf_links(full_message, use_llm_fallback=True)
        for url in urls:
            downloaded = gmail_sync.download_pdf_from_url(url, DOWNLOAD_DIR)
            if not downloaded:
                continue
            status = _ingest_pdf(
                pdf_path=downloaded,
                source_type=SourceType.GMAIL_LINK,
                subject=subject,
                source_message_id=message_id,
                gmail_thread_id=thread_id,
                gmail_link=gmail_link,
                fallback_date=message_date,
            )
            statuses.append(status)

        if not statuses:
            tax_year, tax_month = _tax_parts(message_date, message_date)
            review_record = InvoiceRecord(
                invoice_id=str(uuid.uuid4()),
                source_type=SourceType.GMAIL_LINK.value,
                source_message_id=message_id,
                gmail_thread_id=thread_id,
                gmail_link=gmail_link,
                vendor=infer_vendor(subject, ""),
                subject=subject,
                invoice_date=message_date,
                ingest_date=InvoiceRecord.now_iso(),
                amount=None,
                currency="EUR",
                category="Other",
                file_path=None,
                sha256=None,
                status=InvoiceStatus.NEEDS_REVIEW.value,
                review_reason="No downloadable PDF found",
                tax_year=tax_year,
                tax_month=tax_month,
                notes="needs_manual_review",
            )
            _persist_record(review_record)
            statuses.append(InvoiceStatus.NEEDS_REVIEW.value)

        if args.apply_labels:
            if InvoiceStatus.NEEDS_REVIEW.value in statuses:
                gmail_sync.apply_label(service, message_id, gmail_sync.LABEL_REVIEW)
            elif InvoiceStatus.DUPLICATE.value in statuses and all(
                s == InvoiceStatus.DUPLICATE.value for s in statuses
            ):
                gmail_sync.apply_label(service, message_id, gmail_sync.LABEL_DUPLICATE)
            else:
                gmail_sync.apply_label(service, message_id, gmail_sync.LABEL_PROCESSED)


def run_process_local(args) -> None:
    processed = 0
    for root, _, files in os.walk(DOWNLOAD_DIR):
        for file_name in files:
            if not file_name.lower().endswith(".pdf"):
                continue
            file_path = os.path.join(root, file_name)
            _ingest_pdf(
                pdf_path=file_path,
                source_type=SourceType.LOCAL_DROP,
                subject=file_name,
                source_message_id=None,
                gmail_thread_id=None,
                gmail_link=None,
                fallback_date=datetime.utcnow().strftime("%Y-%m-%d"),
            )
            processed += 1
    print(f"[✓] Processed local PDFs: {processed}")


def run_find(args) -> None:
    rows = index.find_invoices(
        vendor=args.vendor,
        category=args.category,
        status=args.status,
        year=args.year,
        month=args.month,
        text=args.text,
    )
    if not rows:
        print("No matching invoices.")
        return

    print("invoice_date | category | vendor | status | file_path | gmail_link")
    print("-" * 140)
    for row in rows:
        print(
            f"{row['invoice_date'] or ''} | {row['category']} | {row['vendor']} | {row['status']} | "
            f"{row['file_path'] or ''} | {row['gmail_link'] or ''}"
        )
    if args.open_gmail_link:
        for row in rows:
            if row["gmail_link"]:
                print(row["gmail_link"])


def _months_for_year(year: int) -> list[int]:
    return list(range(1, 13))


def run_export_accountant(args) -> None:
    include_status = [s.strip() for s in args.include_status.split(",") if s.strip()]
    months = _months_for_year(args.year) if args.all_months else [args.month]

    for month in months:
        zip_path, manifest_path = accountant_export.export_month(
            year=args.year,
            month=month,
            include_status=include_status,
        )
        print(f"[✓] Exported month {args.year}-{month:02d}")
        print(f"    ZIP: {zip_path}")
        print(f"    CSV: {manifest_path}")


def run_reindex(args) -> None:
    count = 0
    for category in [
        "Work Equipment",
        "Insurance",
        "Travel",
        "Food",
        "Lifestyle",
        "Other",
    ]:
        category_dir = os.path.join(SORTED_DIR, category)
        if not os.path.isdir(category_dir):
            continue
        for file_name in os.listdir(category_dir):
            if not file_name.lower().endswith(".pdf"):
                continue
            path = os.path.join(category_dir, file_name)
            text = extract_text_from_pdf(path)
            invoice_date = first_date_from_text(text)
            if not invoice_date:
                m = re.search(r"(\d{4})-(\d{2})-(\d{2})", file_name)
                if m:
                    invoice_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            vendor = infer_vendor(file_name, text)
            amount = parse_amount(text)
            digest = file_sha256(path)
            tax_year, tax_month = _tax_parts(invoice_date, None)
            record = InvoiceRecord(
                invoice_id=str(uuid.uuid4()),
                source_type=SourceType.LOCAL_DROP.value,
                source_message_id=None,
                gmail_thread_id=None,
                gmail_link=None,
                vendor=vendor,
                subject=file_name,
                invoice_date=invoice_date,
                ingest_date=InvoiceRecord.now_iso(),
                amount=amount,
                currency="EUR",
                category=category,
                file_path=path,
                sha256=digest,
                status=InvoiceStatus.PROCESSED.value,
                review_reason=None,
                tax_year=tax_year,
                tax_month=tax_month,
                notes="reindexed",
            )
            _persist_record(record)
            count += 1
    print(f"[✓] Reindexed invoices: {count}")


def parse_args():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    sync_cmd = sub.add_parser("sync-gmail", help="Sync Gmail invoices into local folders + index")
    sync_cmd.add_argument("--since", help="Gmail after: date format YYYY/MM/DD")
    sync_cmd.add_argument("--window-months", type=int, default=18)
    sync_cmd.add_argument("--apply-labels", action="store_true", default=True)
    sync_cmd.add_argument("--no-apply-labels", action="store_false", dest="apply_labels")

    find_cmd = sub.add_parser("find", help="Search indexed invoices")
    find_cmd.add_argument("--vendor")
    find_cmd.add_argument("--category")
    find_cmd.add_argument("--status")
    find_cmd.add_argument("--year", type=int)
    find_cmd.add_argument("--month", type=int)
    find_cmd.add_argument("--text")
    find_cmd.add_argument("--open-gmail-link", action="store_true")

    export_cmd = sub.add_parser("export-accountant", help="Build monthly accountant export")
    export_cmd.add_argument("--year", required=True, type=int)
    export_scope = export_cmd.add_mutually_exclusive_group(required=True)
    export_scope.add_argument("--month", type=int)
    export_scope.add_argument("--all-months", action="store_true")
    export_cmd.add_argument("--include-status", default="processed,exported")

    sub.add_parser("reindex", help="Reindex sorted invoice folders into SQLite")
    sub.add_parser("process-local", help="Process local PDFs in temp_invoices/")

    # Legacy flags retained for backward compatibility.
    parser.add_argument("--scan-gmail", action="store_true", help="Legacy alias for sync-gmail")
    parser.add_argument("--process-local", action="store_true", help="Legacy local processing mode")
    parser.add_argument("--generate-travel-report", type=int, help="Generate Reisekosten report for year")
    parser.add_argument("--full-run", action="store_true", help="Legacy full run")
    parser.add_argument("--lang", default="en", choices=["de", "en"])
    parser.add_argument("--use-cache", action="store_true")
    parser.add_argument("--parallel", action="store_true")
    parser.add_argument("--generate-bewirtungsbeleg", action="store_true")
    parser.add_argument("--use-llm-for-beleg", action="store_true")

    return parser.parse_args()


def main():
    ensure_dirs(DOWNLOAD_DIR, SORTED_DIR, "data", "Exports")
    index.init_db()
    _migrate_review_queue()
    args = parse_args()

    if args.full_run:
        args.scan_gmail = True
        args.process_local = True
        if not args.generate_travel_report:
            args.generate_travel_report = datetime.now().year

    # Legacy execution path.
    if args.scan_gmail:
        run_sync_gmail(argparse.Namespace(since=None, window_months=18, apply_labels=True))
    if getattr(args, "process_local", False):
        run_process_local(args)
    if args.generate_travel_report:
        from generate_reisekosten_excel import generate_travel_report

        generate_travel_report(
            args.generate_travel_report,
            SORTED_DIR,
            {},
            language=args.lang,
            use_cache=args.use_cache,
            use_parallel=args.parallel,
        )
    if args.generate_bewirtungsbeleg:
        from bewirtungsbeleg import main as generate_bewirtungsbeleg

        food_dir = os.path.join(SORTED_DIR, "Food")
        if os.path.isdir(food_dir):
            for pdf in sorted(os.listdir(food_dir)):
                if pdf.lower().endswith(".pdf"):
                    generate_bewirtungsbeleg(os.path.join(food_dir, pdf), use_llm=args.use_llm_for_beleg)

    # New command path.
    if args.command == "sync-gmail":
        run_sync_gmail(args)
    elif args.command == "find":
        run_find(args)
    elif args.command == "export-accountant":
        run_export_accountant(args)
    elif args.command == "reindex":
        run_reindex(args)
    elif args.command == "process-local":
        run_process_local(args)


if __name__ == "__main__":
    main()
