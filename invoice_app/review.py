from __future__ import annotations

import webbrowser
from typing import Callable

from . import index
from .classifier import triage_review_item
from .models import InvoiceStatus


def fetch_review_items(year: int | None = None) -> list:
    return index.find_invoices(status=InvoiceStatus.NEEDS_REVIEW.value, year=year)


def run_triage(items: list) -> list[tuple]:
    triaged: list[tuple] = []
    total = len(items)
    for i, item in enumerate(items, 1):
        print(f"  Triaging {i}/{total}...", end="\r")
        label = triage_review_item(item["subject"], item["vendor"])
        triaged.append((item, label))
    print()

    order = {"not_invoice": 0, "uncertain": 1, "likely_invoice": 2}
    triaged.sort(key=lambda t: (order.get(t[1], 1), t[0]["vendor"] or ""))
    return triaged


def run_interactive_review(
    triaged_items: list[tuple],
    ingest_fn: Callable | None = None,
) -> dict[str, int]:
    stats = {"dismissed": 0, "skipped": 0, "attached": 0}
    total = len(triaged_items)

    for idx, (item, label) in enumerate(triaged_items, 1):
        print(f"\n[{idx}/{total}] {label}")
        print(f"  Subject: {item['subject']}")
        print(f"  Vendor:  {item['vendor']}")
        print(f"  Date:    {item['invoice_date'] or 'unknown'}")
        if item["gmail_link"]:
            print(f"  Gmail:   {item['gmail_link']}")
        if item["review_reason"]:
            print(f"  Reason:  {item['review_reason']}")

        while True:
            print("\n  [d]ismiss  [s]kip  [o]pen Gmail  [a]ttach PDF  [q]uit")
            choice = input("  > ").strip().lower()

            if choice == "d":
                index.update_invoice(item["invoice_id"], status=InvoiceStatus.DISMISSED.value)
                stats["dismissed"] += 1
                print("  -> Dismissed")
                break
            elif choice == "s":
                stats["skipped"] += 1
                break
            elif choice == "o":
                if item["gmail_link"]:
                    webbrowser.open(item["gmail_link"])
                else:
                    print("  No Gmail link available.")
            elif choice == "a":
                if ingest_fn is None:
                    print("  Attach not available (no ingest function provided).")
                    continue
                pdf_path = input("  PDF path: ").strip()
                if not pdf_path:
                    continue
                import os
                if not os.path.isfile(pdf_path):
                    print(f"  File not found: {pdf_path}")
                    continue
                from .models import SourceType
                status = ingest_fn(
                    pdf_path=pdf_path,
                    source_type=SourceType.LOCAL_DROP,
                    subject=item["subject"],
                    source_message_id=item["source_message_id"],
                    gmail_thread_id=item["gmail_thread_id"],
                    gmail_link=item["gmail_link"],
                    fallback_date=item["invoice_date"],
                )
                index.update_invoice(item["invoice_id"], status=InvoiceStatus.PROCESSED.value,
                                     notes=f"resolved_via_attach:{status}")
                stats["attached"] += 1
                print(f"  -> Attached and processed ({status})")
                break
            elif choice == "q":
                print(f"\n  Summary: {stats['dismissed']} dismissed, {stats['skipped']} skipped, {stats['attached']} attached")
                return stats
            else:
                print("  Invalid choice.")

    print(f"\n  Summary: {stats['dismissed']} dismissed, {stats['skipped']} skipped, {stats['attached']} attached")
    return stats
