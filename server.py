from fastapi import FastAPI, File, UploadFile
from main import categorize_invoice, extract_text_from_pdf, sort_file_to_category
import os

app = FastAPI()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/upload-invoice/")
async def upload_invoice(file: UploadFile = File(...)):
    file_location = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_location, "wb") as f:
        f.write(await file.read())
    
    text = extract_text_from_pdf(file_location)
    category = categorize_invoice(text)
    sort_file_to_category(file_location, category, text)
    
    return {"filename": file.filename, "category": category}