from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# Set up PDF
pdf_path = "bewirtungskosten_formular_vector_precise.pdf"
c = canvas.Canvas(pdf_path, pagesize=A4)
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

label("Ort der Bewirtung (Name, Anschrift):", 270, height - 95)
box(270, height - 125, 280, 20)
box(270, height - 145, 280, 20)

# Anlass der Bewirtung
label("Anlass der Bewirtung:", 40, height - 160)
box(40, height - 190, 510, 20)

# Bewirtete Personen (5 lines, 2 columns)
label("Bewirtete Personen:", 40, height - 205)
for i in range(5):
    box(40, height - 235 - i*20, 255, 18)
    box(295, height - 235 - i*20, 255, 18)

# Höhe der Aufwendungen
label("Höhe der Aufwendungen laut beigefügter Rechnung:", 40, height - 340)

label("Rechnungsbetrag", 40, height - 360)
box(130, height - 375, 50, 18)
label("EUR", 190, height - 360)

label("Trinkgeld", 250, height - 360)
box(310, height - 375, 50, 18)
label("EUR", 370, height - 360)

# Ort, Datum and Unterschrift
label("Ort, Datum:", 40, height - 400)
box(40, height - 430, 200, 20)

label("Unterschrift des Gastgebers:", 270, height - 400)
box(270, height - 430, 280, 20)

# Save PDF
c.save()
print(f"PDF saved as {pdf_path}")