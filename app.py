from flask import (Flask,render_template,request)
from matplotlib import category

from ocr_service import extract_text
from gemini_extractor import extract_structured_data
from compliance_engine import run_compliance_check

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        images = request.files.getlist("images")
        images = [image for image in images if image and image.filename]

        if not images:
            return render_template("index.html",error="Please select an image.")

        all_ocr_text = []

        try:
            # =============================================
            # OCR
            # =============================================

            for image in images:
                text = extract_text(image)
                all_ocr_text.append({"filename": image.filename,"text": text})

            # =============================================
            # COMBINE OCR
            # =============================================

            combined_ocr = "\n\n".join(f"--- IMAGE {item['filename']} ---\n{item['text']}" for item in all_ocr_text)

            # =============================================
            # GEMINI
            # =============================================

            structured_data = extract_structured_data(combined_ocr)

            # =============================================
            # COMPLIANCE ENGINE
            # =============================================

            category = structured_data.get("category", {}).get("value")
            category_data = structured_data.get("category", {})

            if isinstance(category_data, dict):
                category = category_data.get("value")
            else:
                category = category_data

            compliance_results = run_compliance_check(structured_data, category)
            # =============================================
            # DISPLAY RESULTS
            # =============================================

            return render_template("index.html", ocr_results=all_ocr_text, structured_data=structured_data, compliance_results=compliance_results)


        except Exception as e:

            return render_template("index.html", error=str(e), ocr_results=all_ocr_text)

    return render_template("index.html")


if __name__ == "__main__":
    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )