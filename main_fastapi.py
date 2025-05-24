import os
from fastapi import FastAPI, UploadFile, File, Request, Query
from fastapi.responses import RedirectResponse, JSONResponse
from supabase import create_client, Client
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import tempfile
import ollama
from dotenv import load_dotenv

load_dotenv()

# --- Supabase Setup ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# --- FastAPI App ---
app = FastAPI()

# --- Gmail OAuth Setup ---
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
REDIRECT_URI = "http://localhost:8000/gmail/callback"

# In-memory store for credentials (for demo; use DB in production)
user_credentials = {}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    contents = await file.read()
    # Upload to Supabase Storage
    supabase.storage.from_('invoices').upload(file.filename, contents, {"content-type": file.content_type})
    # Store metadata in Supabase DB (optional)
    supabase.table('invoices').insert({"pdfUrl": file.filename}).execute()
    return {"pdfUrl": file.filename}

@app.get("/retrieve")
def retrieve_file(filename: str = Query(...)):
    # Download file from Supabase Storage
    res = supabase.storage.from_('invoices').download(filename)
    return JSONResponse(content={"file": res})

@app.post("/process")
def process_file(filename: str = Query(...)):
    # Download file from Supabase Storage
    file_bytes = supabase.storage().from_('invoices').download(filename)
    # Use Ollama for LLM processing (example: summarize file)
    prompt = f"Summarize the following document:\n\n{file_bytes[:2000].decode(errors='ignore')}"
    response = ollama.chat(model="mistral", messages=[{"role": "user", "content": prompt}])
    summary = response['message']['content']
    # Store result in Supabase DB
    supabase.table('results').insert({"pdfUrl": filename, "summary": summary}).execute()
    return {"status": "processed", "summary": summary}

@app.get("/gmail/auth-url")
def gmail_auth_url():
    flow = Flow.from_client_secrets_file(
        'credentials.json',
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    auth_url, _ = flow.authorization_url(prompt='consent')
    # Store flow in memory (for demo; use session/DB in production)
    user_credentials['flow'] = flow
    return {"auth_url": auth_url}

@app.get("/gmail/callback")
def gmail_callback(request: Request, code: str):
    flow = user_credentials.get('flow')
    if not flow:
        return JSONResponse(content={"error": "No flow found"}, status_code=400)
    flow.fetch_token(code=code)
    credentials = flow.credentials
    # Store credentials in memory (for demo; use DB in production)
    user_credentials['credentials'] = credentials
    return RedirectResponse(url="/gmail/success")

@app.get("/gmail/success")
def gmail_success():
    return {"message": "Gmail authentication successful!"}

@app.get("/gmail/fetch")
def gmail_fetch():
    credentials = user_credentials.get('credentials')
    if not credentials:
        return JSONResponse(content={"error": "Not authenticated"}, status_code=401)
    service = build('gmail', 'v1', credentials=credentials)
    results = service.users().messages().list(userId='me', maxResults=5).execute()
    messages = results.get('messages', [])
    return {"messages": messages} 