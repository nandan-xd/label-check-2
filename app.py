from flask import Flask, render_template, request, send_file
from ocr_service import extract_text
from gemini_extractor import extract_structured_data
from compliance_engine import run_compliance_check

import io
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet


app = Flask(__name__)


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        images = request.files.getlist("images")
        images = [image for image in images if image and image.filename]

        if not images:
            return render_template(
                "index.html",
                error="Please select at least one image."
            )

        all_ocr_text = []

        try:
            # OCR
            for image in images:
                try:
                    text = extract_text(image)

                    all_ocr_text.append({
                        "filename": image.filename,
                        "text": text
                    })

                except Exception:
                    # Retry once for temporary OCR failures
                    try:
                        image.stream.seek(0)
                        text = extract_text(image)

                        all_ocr_text.append({
                            "filename": image.filename,
                            "text": text
                        })

                    except Exception as retry_error:
                        all_ocr_text.append({
                            "filename": image.filename,
                            "text": f"OCR failed: {retry_error}"
                        })

            # Keep only successful OCR results
            valid_ocr = [
                item for item in all_ocr_text
                if not item["text"].startswith("OCR failed:")
            ]

            if not valid_ocr:
                return render_template(
                    "index.html",
                    error="Could not extract text from the uploaded images.",
                    ocr_results=all_ocr_text
                )

            # Combine OCR
            combined_ocr = "\n\n".join(
                f"--- IMAGE {item['filename']} ---\n{item['text']}"
                for item in valid_ocr
            )

            # Gemini
            structured_data = extract_structured_data(combined_ocr)

            # Category
            category = (
                structured_data
                .get("category", {})
                .get("value")
            )

            if not category:
                category = "packaged_commodities"

            # Compliance
            compliance_results = run_compliance_check(
                structured_data,
                category
            )

            # Store latest result for PDF report
            app.config["LAST_RESULT"] = {
                "structured_data": structured_data,
                "compliance_results": compliance_results,
                "ocr_results": all_ocr_text
            }

            return render_template(
                "index.html",
                ocr_results=all_ocr_text,
                structured_data=structured_data,
                compliance_results=compliance_results
            )

        except Exception as e:
            return render_template(
                "index.html",
                error=str(e),
                ocr_results=all_ocr_text
            )

    return render_template("index.html")


# =========================================================
# PDF REPORT
# =========================================================

@app.route("/download-report")
def download_report():
    result = app.config.get("LAST_RESULT")

    if not result:
        return "No scan available for report generation.", 400

    structured_data = result["structured_data"]
    compliance_results = result["compliance_results"]

    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )

    styles = getSampleStyleSheet()
    story = []

    story.append(
        Paragraph(
            "LabelCheck Compliance Report",
            styles["Title"]
        )
    )

    story.append(Spacer(1, 20))

    # Product Information
    story.append(
        Paragraph(
            "Product Information",
            styles["Heading2"]
        )
    )

    product_rows = [["Field", "Value", "Status"]]

    for field, result_data in structured_data.items():
        product_rows.append([
            field.replace("_", " ").title(),
            str(result_data.get("value") or "Not Found"),
            str(result_data.get("status") or "")
        ])

    product_table = Table(
        product_rows,
        repeatRows=1
    )

    product_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5)
        ])
    )

    story.append(product_table)
    story.append(Spacer(1, 25))

    # Compliance Results
    story.append(
        Paragraph(
            "Compliance Results",
            styles["Heading2"]
        )
    )

    if compliance_results:
        story.append(
            Paragraph(
                str(compliance_results.get("summary", "")),
                styles["BodyText"]
            )
        )

        story.append(Spacer(1, 12))

        compliance_rows = [
            ["Rule / Field", "Status", "Details"]
        ]

        for check in compliance_results.get("checks", []):
            compliance_rows.append([
                str(
                    check.get("rule")
                    or check.get("field")
                    or "Rule"
                ),
                str(check.get("status", "")),
                str(
                    check.get("details")
                    or check.get("message")
                    or ""
                )
            ])

        compliance_table = Table(
            compliance_rows,
            repeatRows=1
        )

        compliance_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5)
            ])
        )

        story.append(compliance_table)

    doc.build(story)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name="labelcheck_report.pdf", mimetype="application/pdf")

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)