from __future__ import annotations

import os
import sqlite3
from typing import Iterable

from .models import InvoiceRecord

DB_PATH = os.path.join("data", "invoice_index.db")


def get_conn(db_path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    conn = get_conn(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS invoices (
                invoice_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                source_message_id TEXT,
                gmail_thread_id TEXT,
                gmail_link TEXT,
                vendor TEXT NOT NULL,
                subject TEXT NOT NULL,
                invoice_date TEXT,
                ingest_date TEXT NOT NULL,
                amount REAL,
                currency TEXT NOT NULL DEFAULT 'EUR',
                category TEXT NOT NULL,
                file_path TEXT,
                sha256 TEXT UNIQUE,
                status TEXT NOT NULL,
                review_reason TEXT,
                tax_year INTEGER,
                tax_month INTEGER,
                notes TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_invoices_vendor ON invoices(vendor);
            CREATE INDEX IF NOT EXISTS idx_invoices_date ON invoices(invoice_date);
            CREATE INDEX IF NOT EXISTS idx_invoices_category ON invoices(category);
            CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);
            CREATE INDEX IF NOT EXISTS idx_invoices_source_message ON invoices(source_message_id);

            CREATE TABLE IF NOT EXISTS exports (
                export_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                zip_path TEXT NOT NULL,
                manifest_path TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS export_items (
                export_id TEXT NOT NULL,
                invoice_id TEXT NOT NULL,
                PRIMARY KEY (export_id, invoice_id)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def upsert_invoice(record: InvoiceRecord, db_path: str = DB_PATH) -> None:
    conn = get_conn(db_path)
    try:
        conn.execute(
            """
            INSERT INTO invoices (
                invoice_id, source_type, source_message_id, gmail_thread_id, gmail_link,
                vendor, subject, invoice_date, ingest_date, amount, currency, category,
                file_path, sha256, status, review_reason, tax_year, tax_month, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(invoice_id) DO UPDATE SET
                source_type=excluded.source_type,
                source_message_id=excluded.source_message_id,
                gmail_thread_id=excluded.gmail_thread_id,
                gmail_link=excluded.gmail_link,
                vendor=excluded.vendor,
                subject=excluded.subject,
                invoice_date=excluded.invoice_date,
                ingest_date=excluded.ingest_date,
                amount=excluded.amount,
                currency=excluded.currency,
                category=excluded.category,
                file_path=excluded.file_path,
                sha256=excluded.sha256,
                status=excluded.status,
                review_reason=excluded.review_reason,
                tax_year=excluded.tax_year,
                tax_month=excluded.tax_month,
                notes=excluded.notes
            """,
            (
                record.invoice_id,
                record.source_type,
                record.source_message_id,
                record.gmail_thread_id,
                record.gmail_link,
                record.vendor,
                record.subject,
                record.invoice_date,
                record.ingest_date,
                record.amount,
                record.currency,
                record.category,
                record.file_path,
                record.sha256,
                record.status,
                record.review_reason,
                record.tax_year,
                record.tax_month,
                record.notes,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def find_invoices(
    *,
    vendor: str | None = None,
    category: str | None = None,
    status: str | None = None,
    year: int | None = None,
    month: int | None = None,
    text: str | None = None,
    db_path: str = DB_PATH,
) -> list[sqlite3.Row]:
    query = "SELECT * FROM invoices WHERE 1=1"
    params: list[object] = []
    if vendor:
        query += " AND lower(vendor) LIKE ?"
        params.append(f"%{vendor.lower()}%")
    if category:
        query += " AND category = ?"
        params.append(category)
    if status:
        query += " AND status = ?"
        params.append(status)
    if year:
        query += " AND tax_year = ?"
        params.append(year)
    if month:
        query += " AND tax_month = ?"
        params.append(month)
    if text:
        query += " AND (lower(subject) LIKE ? OR lower(notes) LIKE ?)"
        like = f"%{text.lower()}%"
        params.extend([like, like])
    query += " ORDER BY invoice_date ASC, vendor ASC, file_path ASC"

    conn = get_conn(db_path)
    try:
        return list(conn.execute(query, params))
    finally:
        conn.close()


def find_by_sha(sha256: str, db_path: str = DB_PATH) -> sqlite3.Row | None:
    conn = get_conn(db_path)
    try:
        return conn.execute("SELECT * FROM invoices WHERE sha256 = ?", (sha256,)).fetchone()
    finally:
        conn.close()


def list_for_export(
    year: int, month: int, include_status: Iterable[str], db_path: str = DB_PATH
) -> list[sqlite3.Row]:
    placeholders = ",".join(["?"] * len(tuple(include_status)))
    query = f"""
        SELECT * FROM invoices
        WHERE tax_year = ? AND tax_month = ? AND status IN ({placeholders})
        ORDER BY invoice_date ASC, vendor ASC, file_path ASC
    """
    params: list[object] = [year, month]
    params.extend(include_status)
    conn = get_conn(db_path)
    try:
        return list(conn.execute(query, params))
    finally:
        conn.close()


def record_export(
    export_id: str,
    created_at: str,
    year: int,
    month: int,
    zip_path: str,
    manifest_path: str,
    invoice_ids: list[str],
    db_path: str = DB_PATH,
) -> None:
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO exports(export_id, created_at, year, month, zip_path, manifest_path) VALUES(?, ?, ?, ?, ?, ?)",
            (export_id, created_at, year, month, zip_path, manifest_path),
        )
        for invoice_id in invoice_ids:
            conn.execute(
                "INSERT INTO export_items(export_id, invoice_id) VALUES(?, ?)",
                (export_id, invoice_id),
            )
            conn.execute(
                "UPDATE invoices SET status = ? WHERE invoice_id = ?",
                ("exported", invoice_id),
            )
        conn.commit()
    finally:
        conn.close()

