import json
import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from PyPDF2 import PdfReader, PdfWriter
from PyPDF2.generic import NameObject, createStringObject
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

DEFAULT_SIGNATURE_PATH = os.getenv("DEFAULT_SIGNATURE_PATH", "signature.png")
DEFAULT_SIGNATURE_NAME = os.getenv("DEFAULT_SIGNATURE_NAME", "")

def prompt_user_info(initial_info=None):
    """
    Prompt the user for all relevant Bewirtungsbeleg fields.
    initial_info: dict with pre-extracted fields to pre-fill.
    Returns a dict with all necessary info.
    """
    info = initial_info.copy() if initial_info else {}
    print("Bitte bestätigen oder bearbeiten Sie die vom LLM vorgeschlagenen Informationen für den Bewirtungsbeleg (Enter = übernehmen, sonst editieren):")

    def prompt_field(key, label, default=None):
        shown_default = default if default is not None else ''
        val = input(f"{label} [{shown_default}]: ").strip()
        if not val and default is not None:
            return default
        return val

    # Ask for every field, always showing the LLM guess as default
    info['datum_bewirtung'] = prompt_field('datum_bewirtung', "Datum der Bewirtung", info.get('datum_bewirtung', datetime.today().strftime('%d.%m.%Y')))
    info['ort_bewirtung'] = prompt_field('ort_bewirtung', "Ort der Bewirtung (Name, Anschrift)", info.get('ort_bewirtung', ''))
    info['anlass'] = prompt_field('anlass', "Anlass der Bewirtung", info.get('anlass', ''))
    # Personen: always prompt with default, allow edit
    personen_default = ', '.join(info['personen']) if 'personen' in info and info['personen'] else ''
    personen_input = input(f"Bewirtete Personen (max 10, mit Komma trennen) [{personen_default}]: ").strip()
    if personen_input:
        info['personen'] = [p.strip() for p in personen_input.split(',')]
    else:
        info['personen'] = info.get('personen', [])
    # Ensure host is always included in the list, case-insensitively and trimmed
    if DEFAULT_SIGNATURE_NAME:
        normalized_persons = [p.strip().lower() for p in info['personen']]
        if DEFAULT_SIGNATURE_NAME.strip().lower() not in normalized_persons:
            info['personen'].append(DEFAULT_SIGNATURE_NAME)
    info['rechnungsbetrag'] = prompt_field('rechnungsbetrag', "Rechnungsbetrag (EUR)", info.get('rechnungsbetrag', ''))
    info['trinkgeld'] = prompt_field('trinkgeld', "Trinkgeld (EUR)", info.get('trinkgeld', ''))
    info['ort_datum_unterschrift'] = prompt_field('ort_datum_unterschrift', "Ort, Datum (Unterschrift)", info.get('ort_datum_unterschrift', ''))
    return info

def screen_pdf_for_info(pdf_path):
    """
    Use LLM (OpenAI or Ollama) to extract Bewirtungsbeleg fields from the PDF text.
    Returns a dict with guessed values.
    """
    print(f"Starte LLM-Extraktion für PDF: {pdf_path}")
    # Import here to avoid dependency issues if unused
    import importlib
    # Extract text from PDF (reuse extract_text_from_pdf from main.py)
    try:
        from main import extract_text_from_pdf
    except ImportError:
        # fallback: do minimal extraction if import fails
        import fitz
        def extract_text_from_pdf(pdf_path):
            doc = fitz.open(pdf_path)
            text = "\n".join(page.get_text() for page in doc)
            return text[:2000]
    text = extract_text_from_pdf(pdf_path)
    # Prepare prompt
    prompt = f"""
Du bist ein Assistent für Bewirtungsbelege. Extrahiere die folgenden Felder aus dem folgenden Bewirtungsbeleg oder Restaurantbeleg (so gut wie möglich, auch wenn nicht alle Informationen vorhanden sind):

- datum_bewirtung: Datum der Bewirtung (z.B. 12.03.2024)
- ort_bewirtung: Name und Anschrift des Restaurants
- anlass: Anlass der Bewirtung (z.B. Geschäftsessen mit Kunde XY)
- personen: Liste der bewirteten Personen (nur Namen, max 10)
- rechnungsbetrag: Gesamtbetrag der Rechnung in EUR (ohne €-Zeichen)
- trinkgeld: Trinkgeld in EUR (nur Zahl, falls erkennbar, sonst leer)
- ort_datum_unterschrift: Ort und Datum für Unterschrift (z.B. Ort, Datum)

Gib das Ergebnis als JSON-Objekt mit diesen Feldern zurück.

PDF-Text:
\"\"\"
{text}
\"\"\"
"""
    # Try OpenAI or Ollama depending on config
    try:
        import os
        if os.getenv("USE_OPENAI", "False").lower() in ["1", "true", "yes"]:
            import openai
            model = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
            openai.api_key = os.getenv("OPENAI_API_KEY")
            response = openai.ChatCompletion.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=512
            )
            content = response.choices[0].message['content']
        else:
            import ollama
            model = os.getenv("MODEL", "mistral")
            response = ollama.chat(model=model, messages=[{"role": "user", "content": prompt}])
            content = response['message']['content']
    except Exception as e:
        print(f"[!] LLM-Extraktion fehlgeschlagen: {e}")
        content = ""

    # Parse JSON from LLM output
    import json
    import re
    info = {
        'datum_bewirtung': '',
        'ort_bewirtung': '',
        'anlass': '',
        'personen': [],
        'rechnungsbetrag': '',
        'trinkgeld': '',
        'ort_datum_unterschrift': ''
    }
    # Try to extract JSON block from content
    json_match = re.search(r'\{.*\}', content, re.DOTALL)
    if json_match:
        json_str = json_match.group(0)
        try:
            raw = json.loads(json_str)
            # Copy fields if present
            for k in info:
                if k in raw:
                    info[k] = raw[k]
        except Exception as e:
            print(f"[!] Fehler beim Parsen des LLM-JSON: {e}")
    else:
        # fallback: try to parse simple key: value lines
        for line in (content or "").splitlines():
            for k in info:
                if line.lower().startswith(k.replace("_", " ")):
                    val = line.split(":", 1)[-1].strip()
                    info[k] = val
    # Ensure personen is a list
    if isinstance(info.get('personen'), str):
        info['personen'] = [p.strip() for p in info['personen'].split(',') if p.strip()]
    elif not isinstance(info.get('personen'), list):
        info['personen'] = []

    # Extract city from ort_bewirtung for default ort_datum_unterschrift
    ort_bewirtung_lines = info.get('ort_bewirtung', '').splitlines()
    city = ''
    postal_code_pattern = re.compile(r'^\s*\d{5}\b')
    for line in ort_bewirtung_lines:
        if postal_code_pattern.match(line):
            # Split line by spaces, remove postal code, rest is city
            parts = line.strip().split()
            if len(parts) > 1:
                city = ' '.join(parts[1:])
                break
    # Set default ort_datum_unterschrift if empty
    if not info.get('ort_datum_unterschrift') and city:
        info['ort_datum_unterschrift'] = city

    return info

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
    # Optionally insert signature image (no signature box anymore)
    if signature_img_path and os.path.isfile(signature_img_path):
        # Place image at x=275, y=height-445, max width=180, height=25
        try:
            c.drawImage(signature_img_path, 275, height - 445, width=180, height=25, preserveAspectRatio=True, mask='auto')
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
    Always ask:
      1. Add signature image? (y/n/custom)
      2. If y, use default if it exists
      3. If custom, prompt for a custom path
      4. If n, return None
    """
    while True:
        resp = input("Unterschrift als Bild einfügen? (y/n/custom): ").strip().lower()
        if resp == "y":
            if os.path.isfile(DEFAULT_SIGNATURE_PATH):
                print(f"Standard-Signaturbild gefunden: {DEFAULT_SIGNATURE_PATH}")
                return DEFAULT_SIGNATURE_PATH
            else:
                print("Kein Standard-Signaturbild gefunden.")
                continue
        elif resp == "n":
            return None
        elif resp == "custom":
            custom_path = input("Pfad zum eigenen Unterschriftsbild (PNG/JPG): ").strip()
            if custom_path and os.path.isfile(custom_path):
                return custom_path
            else:
                print("Datei nicht gefunden. Bitte erneut versuchen.")
                continue
        else:
            print("Bitte 'y', 'n' oder 'custom' eingeben.")

def attach_to_invoice(original_pdf, filled_beleg_pdf, info_dict, output_path=None):
    """
    Prepend filled Bewirtungsbeleg to the invoice PDF and save result.
    Write to a temporary file first, only replacing the original if successful.
    Also embed a Bewirtungsbeleg status field into the PDF metadata.
    """
    output_path = output_path or original_pdf
    tmp_path = f"{original_pdf}.tmp.pdf"
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
    # Add marker and status to metadata
    info_json = json.dumps(info_dict)
    merger.add_metadata({
        "/BewirtungsbelegPrepended": "True",
        "/BewirtungsbelegStatus": "done",
        "/BewirtungsbelegData": info_json
    })
    try:
        with open(tmp_path, "wb") as out_f:
            merger.write(out_f)
        os.replace(tmp_path, output_path)
        print(f"Neue PDF gespeichert als {output_path}")
        return output_path
    except Exception as e:
        print(f"[!] Fehler beim Schreiben der kombinierten PDF: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return None


# --- PDF Form Data Helper ---
def get_pdf_form_data(pdf_path):
    """
    Read and return the BewirtungsbelegData field from PDF metadata, if available.
    Returns a dict or empty dict.
    """
    try:
        with open(pdf_path, "rb") as f:
            reader = PdfReader(f)
            md = reader.metadata
            raw_data = md.get("/BewirtungsbelegData")
            if raw_data:
                return json.loads(raw_data)
    except Exception as e:
        print(f"[!] Fehler beim Lesen von PDF-Formulardaten: {e}")
    return {}


# --- PDF Status Helpers ---
def get_pdf_status(pdf_path):
    """
    Get the current status metadata of a PDF.
    Returns 'done', 'in progress', or 'missing'.
    """
    try:
        with open(pdf_path, "rb") as f:
            reader = PdfReader(f)
            md = reader.metadata
            return md.get("/BewirtungsbelegStatus", "in progress")
    except Exception:
        return "in progress"

def set_pdf_status(pdf_path, new_status):
    """
    Update the status metadata of a PDF.
    """
    try:
        reader = PdfReader(pdf_path)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        md = reader.metadata or {}
        new_md = {NameObject(k): createStringObject(str(v)) for k, v in md.items()}
        new_md[NameObject("/BewirtungsbelegStatus")] = createStringObject(new_status)
        writer.add_metadata(new_md)
        temp_path = f"{pdf_path}.tmp.pdf"
        with open(temp_path, "wb") as f:
            writer.write(f)
        os.replace(temp_path, pdf_path)
        return True
    except Exception as e:
        print(f"[!] Fehler beim Aktualisieren des Status: {e}")
        return False

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

def main(invoice_path=None, use_llm=False):
    global DEFAULT_SIGNATURE_NAME
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
    # Simulate screening only if use_llm is True
    if use_llm:
        extracted = screen_pdf_for_info(invoice_path)
    else:
        extracted = {}
    # Prompt user for all fields
    info = prompt_user_info(extracted)
    # Ask user to confirm or update DEFAULT_SIGNATURE_NAME after document content, before signature insertion
    name_input = input(f"Name für Unterschrift bestätigen oder ändern [{DEFAULT_SIGNATURE_NAME}]: ").strip()
    if name_input:
        DEFAULT_SIGNATURE_NAME = name_input
    # Optional signature
    sig_path = insert_signature_area()
    # Generate filled PDF
    beleg_pdf = generate_filled_pdf(info, signature_img_path=sig_path)
    # Prepend to invoice
    attach_to_invoice(invoice_path, beleg_pdf, info)

if __name__ == "__main__":
    main()