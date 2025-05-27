import streamlit as st
import os
import tempfile
from pdf2image import convert_from_path
from PIL import Image
from bewirtungsbeleg import screen_pdf_for_info, generate_filled_pdf, attach_to_invoice, get_pdf_status, set_pdf_status, get_pdf_form_data
from PyPDF2 import PdfReader, PdfWriter

st.set_page_config(page_title="🍽️ Bewirtungsbeleg Generator", layout="wide")

def show_pdf(file_path):
    if not os.path.exists(file_path):
        st.error("PDF file not found.")
        return
    try:
        images = convert_from_path(file_path, dpi=150)
        for img in images:
            st.image(img, use_container_width=True)
    except Exception as e:
        st.error(f"Failed to render PDF: {e}")

def check_for_beleg_marker(pdf_path):
    try:
        with open(pdf_path, "rb") as f:
            reader = PdfReader(f)
            md = reader.metadata
            return md and md.get("/BewirtungsbelegPrepended") == "True"
    except Exception:
        return False

def remove_beleg_from_invoice(pdf_path):
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    if len(reader.pages) > 1:
        for page in reader.pages[1:]:
            writer.add_page(page)
        temp_path = f"{pdf_path}.temp.pdf"
        with open(temp_path, "wb") as f:
            writer.write(f)
        os.replace(temp_path, pdf_path)
        return True
    return False

def normalize_amount(value_str):
    """Normalize decimal separator (comma or dot) to dot, and strip whitespace."""
    if not value_str:
        return "0"
    return value_str.replace(",", ".").strip()

def main():
    st.title("🍽️ Bewirtungsbeleg Generator")

    # Choose input method
    mode = st.radio("Select invoice source", ["Upload PDF", "Choose from 'Invoices/Food/' folder"])

    pdf_path = None
    if mode == "Upload PDF":
        uploaded_file = st.file_uploader("Upload a PDF invoice", type="pdf")
        if uploaded_file:
            temp_dir = tempfile.mkdtemp()
            pdf_path = os.path.join(temp_dir, uploaded_file.name)
            with open(pdf_path, "wb") as f:
                f.write(uploaded_file.read())
    else:
        food_dir = os.path.join("Invoices", "Food")
        if not os.path.exists(food_dir):
            st.error(f"No such directory: {food_dir}")
            return
        pdfs = [f for f in os.listdir(food_dir) if f.lower().endswith(".pdf")]
        if not pdfs:
            st.warning("No PDFs found in the Food folder.")
            return

        statuses = {f: get_pdf_status(os.path.join(food_dir, f)) for f in pdfs}
        sort_order = st.selectbox("Sort order", ["A–Z", "Z–A"], index=0)

        # --- State for filter controls ---
        if "status_filter" not in st.session_state:
            st.session_state["status_filter"] = ["in progress", "missing"]

        status_options = ["in progress", "done", "missing"]

        def on_status_filter_change():
            pass  # No-op, but can be used for future logic

        # --- Controls ---
        st.multiselect(
            "Filter by status",
            options=status_options,
            default=st.session_state["status_filter"],
            key="status_filter",
            on_change=on_status_filter_change
        )

        filtered_pdfs = [f for f in pdfs if statuses[f] in st.session_state["status_filter"]]
        filtered_pdfs = sorted(filtered_pdfs, reverse=(sort_order == "Z–A"))

        if not filtered_pdfs:
            st.success("🎉 All invoices are processed!")
            return

        default_pdf = filtered_pdfs[0]
        selected_pdf = st.selectbox("📁 Select an invoice", filtered_pdfs, index=0)
        pdf_path = os.path.join(food_dir, selected_pdf)
        # Show and update status
        current_status = get_pdf_status(pdf_path)
        new_status = st.selectbox("Status", ["in progress", "done", "missing"], index=["in progress", "done", "missing"].index(current_status))
        if new_status != current_status:
            set_pdf_status(pdf_path, new_status)

    if not pdf_path or not os.path.exists(pdf_path):
        st.info("Please upload or select a PDF to begin.")
        return

    # --- Check for existing Bewirtungsbeleg and allow removal ---
    if check_for_beleg_marker(pdf_path):
        st.warning("⚠️ This PDF already includes a Bewirtungsbeleg.")
        if st.button("🗑️ Remove existing Bewirtungsbeleg"):
            if remove_beleg_from_invoice(pdf_path):
                st.success("Bewirtungsbeleg removed.")
            else:
                st.error("Failed to remove Bewirtungsbeleg. It may be the only page.")
            st.stop()

    col1, col2 = st.columns([1, 1.5])

    # --- State management ---
    if "filled" not in st.session_state:
        st.session_state["filled"] = False
    if "filled_pdf_path" not in st.session_state:
        st.session_state["filled_pdf_path"] = None
    if "form_data" not in st.session_state:
        st.session_state["form_data"] = None

    with col1:
        if st.session_state["filled"]:
            st.subheader("📄 Preview of the new PDF")
            show_pdf(st.session_state["filled_pdf_path"])
        else:
            st.subheader("📄 Invoice Preview")
            show_pdf(pdf_path)

    with col2:
        st.subheader("🧾 Bewirtungsbeleg Details")

        if st.session_state["filled"]:
            st.success("✅ Bewirtungsbeleg created successfully!")
            # Action buttons
            colA, colB, colC = st.columns([1,1,1])
            with colA:
                if st.button("✏️ Edit again"):
                    remove_beleg_from_invoice(pdf_path)
                    set_pdf_status(pdf_path, "in progress")
                    current_status = "in progress"
                    if current_status not in st.session_state["status_filter"]:
                        st.session_state["status_filter"].append(current_status)
                    st.session_state["filled"] = False
                    st.rerun()
            with colB:
                if st.button("➡️ Next document"):
                    st.session_state["filled"] = False
                    st.rerun()
            with colC:
                with open(st.session_state["filled_pdf_path"], "rb") as f:
                    st.download_button("📥 Download PDF", f, file_name=os.path.basename(st.session_state["filled_pdf_path"]), mime="application/pdf")
        else:
            use_llm = st.checkbox("Prefill form using LLM", value=True)
            pdf_status = get_pdf_status(pdf_path)

            with st.spinner("🔎 Extrahiere Formulardaten..."):
                form_data = get_pdf_form_data(pdf_path)
            if form_data:
                with st.spinner("📄 Lade bereits gespeicherte Formulardaten aus PDF..."):
                    extracted = form_data
            elif use_llm and pdf_status != "done":
                with st.spinner("🤖 Extrahiere Formulardaten mit KI..."):
                    extracted = screen_pdf_for_info(pdf_path)
            else:
                extracted = {}

            with st.form("bewirtungs_form"):
                datum = st.text_input("Datum der Bewirtung", extracted.get("datum_bewirtung", ""))
                ort = st.text_area("Ort der Bewirtung", extracted.get("ort_bewirtung", ""))
                anlass = st.text_input("Anlass", extracted.get("anlass", ""))
                personen = st.text_area("Bewirtete Personen (comma-separated)", ", ".join(extracted.get("personen", [])))
                betrag = st.text_input("Rechnungsbetrag (EUR)", extracted.get("rechnungsbetrag", ""))
                trinkgeld = st.text_input("Trinkgeld (EUR)", extracted.get("trinkgeld", ""))
                unterschrift = st.text_input("Ort, Datum (Unterschrift)", extracted.get("ort_datum_unterschrift", ""))

                signature_img = st.file_uploader("Optional: Signature Image (PNG/JPG)", type=["png", "jpg", "jpeg"])

                submitted = st.form_submit_button("Generate Bewirtungsbeleg")

            if submitted:
                # Normalize amounts
                betrag_norm = normalize_amount(betrag)
                trinkgeld_norm = normalize_amount(trinkgeld)
                info = {
                    "datum_bewirtung": datum,
                    "ort_bewirtung": ort,
                    "anlass": anlass,
                    "personen": [p.strip() for p in personen.split(",") if p.strip()],
                    "rechnungsbetrag": betrag_norm,
                    "trinkgeld": trinkgeld_norm,
                    "ort_datum_unterschrift": unterschrift
                }

                sig_path = None
                if signature_img:
                    sig_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                    sig_temp.write(signature_img.read())
                    sig_temp.close()
                    sig_path = sig_temp.name

                with st.spinner("Generating Bewirtungsbeleg..."):
                    filled_pdf = generate_filled_pdf(info, signature_img_path=sig_path)
                    final_pdf = attach_to_invoice(pdf_path, filled_pdf, info)

                    if final_pdf:
                        set_pdf_status(pdf_path, "done")
                        st.session_state["filled"] = True
                        st.session_state["filled_pdf_path"] = final_pdf
                        st.session_state["form_data"] = info
                        st.rerun()

if __name__ == "__main__":
    main()