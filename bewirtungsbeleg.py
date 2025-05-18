import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from PyPDF2 import PdfReader, PdfWriter
from datetime import datetime

def prompt_user_info(initial_info=None):
    """
    Prompt the user for all relevant Bewirtungsbeleg fields.
    initial_info: dict with pre-extracted fields to pre-fill.
    Returns a dict with all necessary info.
    """
    info = initial_info.copy() if initial_info else {}
    print("Bitte geben Sie die Informationen für den Bewirtungsbeleg ein (Enter zum Überspringen/Beibehalten):")
    def prompt_field(key, label, default=None):
        val = input(f"{label} [{default if default else ''}]: ").strip()
        if not val and default is not None:
            return default
        return val
    info['datum_bewirtung'] = prompt_field('datum_bewirtung', "Datum der Bewirtung", info.get('datum_bewirtung', datetime.today().strftime('%d.%m.%Y')))
    info['ort_bewirtung'] = prompt_field('ort_bewirtung', "Ort der Bewirtung (Name, Anschrift)", info.get('ort_bewirtung', ''))
    info['anlass'] = prompt_field('anlass', "Anlass der Bewirtung", info.get('anlass', ''))
    print("Bitte geben Sie die bewirteten Personen ein (max 10, mit Komma trennen, oder leer lassen):")
    if 'personen' in info and info['personen']:
        personen_default = ', '.join(info['personen'])
    else:
        personen_default = ''
    personen_input = input(f"Bewirtete Personen [{personen_default}]: ").strip()
    if personen_input:
        info['personen'] = [p.strip() for p in personen_input.split(',')]
    else:
        info['personen'] = info.get('personen', [])
    info['rechnungsbetrag'] = prompt_field('rechnungsbetrag', "Rechnungsbetrag (EUR)", info.get('rechnungsbetrag', ''))
    info['trinkgeld'] = prompt_field('trinkgeld', "Trinkgeld (EUR)", info.get('trinkgeld', ''))
    info['ort_datum_unterschrift'] = prompt_field('ort_datum_unterschrift', "Ort, Datum (Unterschrift)", info.get('ort_datum_unterschrift', info.get('ort_bewirtung', '')))
    return info

def screen_pdf_for_info(pdf_path):
    """
    Placeholder LLM extraction: Simulate extracting info from invoice PDF.
    Returns a dict with guessed values.
    """
    print(f"Simuliere LLM-Extraktion für PDF: {pdf_path}")
    # Placeholder: Just return empty/guessed fields
    return {
        'datum_bewirtung': '',
        'ort_bewirtung': '',
        'anlass': '',
        'personen': [],
        'rechnungsbetrag': '',
        'trinkgeld': '',
        'ort_datum_unterschrift': ''
    }

def generate_filled_pdf(info_dict, output_pdf_path="bewirtungsbeleg_ausgefuellt.pdf", signature_img_path=None):
    """
    Generate a filled Bewirtungsbeleg PDF with fields from info_dict.
    Optionally place a signature image.
    """
    c = canvas.Canvas(output_pdf_path, pagesize=A4)
    width, height = A4
    # Helper functions
    def label(text, x, y, size=9, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(x, y, text)
    def box(x, y, w, h):
        c.rect(x, y, w, h)
    # Header
    label("Bewirtungskosten", 40, height - 40, 12, bold=True)
    label("Angaben zum Nachweis der Höhe und der geschäftlichen Veranlassung von", 40, height - 55)
    label("Bewirtungsaufwendungen (§ 4 Abs. 5 Nr. 2 EStG).", 40, height - 67)
    # Datum / Ort der Bewirtung
    label("Datum der Bewirtung:", 40, height - 95)
    box(40, height - 125, 200, 20)
    c.drawString(45, height - 120, info_dict.get('datum_bewirtung', ''))
    label("Ort der Bewirtung (Name, Anschrift):", 270, height - 95)
    box(270, height - 125, 280, 20)
    box(270, height - 145, 280, 20)
    ort_lines = info_dict.get('ort_bewirtung', '').split('\n')
    for i, line in enumerate(ort_lines[:2]):
        c.drawString(275, height - 120 - i*20, line)
    # Anlass der Bewirtung
    label("Anlass der Bewirtung:", 40, height - 160)
    box(40, height - 190, 510, 20)
    c.drawString(45, height - 185, info_dict.get('anlass', ''))
    # Bewirtete Personen (5 lines, 2 columns)
    label("Bewirtete Personen:", 40, height - 205)
    personen = info_dict.get('personen', [])
    for i in range(5):
        box(40, height - 235 - i*20, 255, 18)
        box(295, height - 235 - i*20, 255, 18)
        idx1 = i * 2
        idx2 = i * 2 + 1
        if idx1 < len(personen):
            c.drawString(45, height - 230 - i*20, personen[idx1])
        if idx2 < len(personen):
            c.drawString(300, height - 230 - i*20, personen[idx2])
    # Höhe der Aufwendungen
    label("Höhe der Aufwendungen laut beigefügter Rechnung:", 40, height - 340)
    label("Rechnungsbetrag", 40, height - 360)
    box(130, height - 375, 50, 18)
    c.drawString(135, height - 370, info_dict.get('rechnungsbetrag', ''))
    label("EUR", 190, height - 360)
    label("Trinkgeld", 250, height - 360)
    box(310, height - 375, 50, 18)
    c.drawString(315, height - 370, info_dict.get('trinkgeld', ''))
    label("EUR", 370, height - 360)
    # Ort, Datum and Unterschrift
    label("Ort, Datum:", 40, height - 400)
    box(40, height - 430, 200, 20)
    c.drawString(45, height - 425, info_dict.get('ort_datum_unterschrift', ''))
    label("Unterschrift des Gastgebers:", 270, height - 400)
    box(270, height - 430, 280, 20)
    # Optionally insert signature image
    if signature_img_path and os.path.isfile(signature_img_path):
        # Place image inside signature box (size: 280x20, adjust as needed)
        try:
            c.drawImage(signature_img_path, 275, height - 428, width=120, height=16, preserveAspectRatio=True, mask='auto')
        except Exception as e:
            print(f"Fehler beim Einfügen der Signatur: {e}")
    # Save PDF
    c.save()
    print(f"Ausgefüllter Bewirtungsbeleg gespeichert als {output_pdf_path}")
    return output_pdf_path

def insert_signature_area():
    """
    Ask user if they want to insert a signature image.
    Return path to the image, or None.
    """
    sig_path = input("Pfad zu Unterschriftsbild (PNG/JPG, Enter zum Überspringen): ").strip()
    if sig_path and os.path.isfile(sig_path):
        return sig_path
    return None

def attach_to_invoice(original_pdf, filled_beleg_pdf, output_path=None):
    """
    Prepend filled Bewirtungsbeleg to the invoice PDF and save result.
    """
    output_path = output_path or f"combined_{os.path.basename(original_pdf)}"
    merger = PdfWriter()
    # Add filled beleg
    with open(filled_beleg_pdf, "rb") as beleg_f:
        beleg_reader = PdfReader(beleg_f)
        for page in beleg_reader.pages:
            merger.add_page(page)
    # Add invoice
    with open(original_pdf, "rb") as inv_f:
        inv_reader = PdfReader(inv_f)
        for page in inv_reader.pages:
            merger.add_page(page)
    # Add marker to first page (metadata)
    merger.add_metadata({"/BewirtungsbelegPrepended": "True"})
    with open(output_path, "wb") as out_f:
        merger.write(out_f)
    print(f"Neue PDF gespeichert als {output_path}")
    return output_path

def check_for_beleg_marker(pdf_path):
    """
    Check if PDF contains the Bewirtungsbeleg marker in metadata.
    """
    try:
        with open(pdf_path, "rb") as f:
            reader = PdfReader(f)
            md = reader.metadata
            return md and md.get("/BewirtungsbelegPrepended") == "True"
    except Exception as e:
        return False

def main(invoice_path=None):
    print("==== Bewirtungsbeleg-Generator ====")
    if not invoice_path:
        invoice_path = input("Pfad zur Rechnungs-PDF: ").strip()
    if not os.path.isfile(invoice_path):
        print("Datei nicht gefunden.")
        return
    if check_for_beleg_marker(invoice_path):
        print("Warnung: Diese Rechnung enthält bereits einen Bewirtungsbeleg (laut Metadaten).")
        proceed = input("Fortfahren? (j/N): ").strip().lower()
        if proceed != "j":
            print("Abbruch.")
            return
    # Simulate screening
    extracted = screen_pdf_for_info(invoice_path)
    # Prompt user for all fields
    info = prompt_user_info(extracted)
    # Optional signature
    sig_path = insert_signature_area()
    # Generate filled PDF
    beleg_pdf = generate_filled_pdf(info, signature_img_path=sig_path)
    # Prepend to invoice
    attach_to_invoice(invoice_path, beleg_pdf)

if __name__ == "__main__":
    main()