from flask import Flask, render_template, request, send_file
from ocr_service import extract_text
from gemini_extractor import extract_structured_data, check_visual_legibility
from compliance_engine import run_compliance_check

import io
import re

from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle
)
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


app = Flask(__name__)

# Hard safety cap on the whole request body (all images combined).
# The front-end already compresses each photo to well under 1 MB
# before upload, so a normal scan never gets close to this. This
# just stops a truly oversized request from crashing the server
# with an unhandled error and turns it into a friendly message.
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB


@app.errorhandler(413)
def handle_payload_too_large(_error):
    return render_template(
        "index.html",
        error=(
            "That upload was too large. Please try again — "
            "images are compressed automatically, but very large "
            "batches of photos can still exceed the limit."
        )
    ), 413


# =========================================================
# ADVANCED VERIFICATIONS
# =========================================================

def is_food_category(category):
    category = (category or "").strip().lower()

    return category in {
        "food",
        "beverage",
        "packaged_food",
        "packaged food"
    }


def run_advanced_verifications(
    structured_data,
    image_payloads,
    category
):
    checks = []

    # -----------------------------------------------------
    # FSSAI LICENSE NUMBER FORMAT
    # -----------------------------------------------------

    fssai_data = structured_data.get(
        "fssai_license_number",
        {}
    )

    fssai_value = fssai_data.get("value")
    fssai_status = fssai_data.get(
        "status",
        "not_found"
    )

    if not is_food_category(category):

        checks.append({
            "rule": "FSSAI License Number - Format Validation",
            "status": "not_applicable",
            "details": (
                "FSSAI license validation is not applicable "
                "to the detected non-food category."
            ),
            "verification_method": "format validation"
        })

    elif not fssai_value:

        checks.append({
            "rule": "FSSAI License Number - Format Validation",
            "status": "review",
            "details": (
                "No FSSAI license number was detected. "
                "Verify the product label manually."
            ),
            "verification_method": "format validation"
        })

    elif fssai_status == "needs_verification":

        checks.append({
            "rule": "FSSAI License Number - Format Validation",
            "status": "review",
            "details": (
                f"Detected FSSAI value '{fssai_value}' is uncertain "
                "and should be verified manually."
            ),
            "verification_method": "format validation"
        })

    else:

        digits = re.sub(
            r"\D",
            "",
            str(fssai_value)
        )

        if len(digits) == 14:

            checks.append({
                "rule": "FSSAI License Number - Format Validation",
                "status": "pass",
                "details": (
                    f"'{fssai_value}' matches the expected "
                    "14-digit FSSAI license number structure. "
                    "This validates format only, not active status, "
                    "assignment or authenticity."
                ),
                "verification_method": "format validation"
            })

        else:

            checks.append({
                "rule": "FSSAI License Number - Format Validation",
                "status": "fail",
                "details": (
                    f"'{fssai_value}' does not contain the expected "
                    "14-digit FSSAI license number structure."
                ),
                "verification_method": "format validation"
            })

    # -----------------------------------------------------
    # VISUAL LEGIBILITY
    # -----------------------------------------------------

    try:

        visual_result = check_visual_legibility(
            image_payloads
        )

        score = visual_result["score"]

        if score >= 70:
            visual_status = "pass"

        elif score >= 50:
            visual_status = "review"

        else:
            visual_status = "fail"

        checks.append({
            "rule": "Minimum Font Size & Visual Legibility Check",
            "status": visual_status,
            "details": (
                f"AI-estimated visual legibility score: {score}/100. "
                f"{visual_result['summary']} "
                "This is an AI visual estimate, not a calibrated "
                "physical font-size measurement."
            ),
            "verification_method": "ai visual estimate",
            "score": score
        })

    except Exception as e:

        checks.append({
            "rule": "Minimum Font Size & Visual Legibility Check",
            "status": "review",
            "details": (
                "Visual verification could not be completed. "
                f"Manual verification is recommended. ({e})"
            ),
            "verification_method": "ai visual estimate"
        })

    passed = sum(
        1
        for check in checks
        if check["status"] == "pass"
    )

    failed = sum(
        1
        for check in checks
        if check["status"] == "fail"
    )

    review = sum(
        1
        for check in checks
        if check["status"] == "review"
    )

    not_applicable = sum(
        1
        for check in checks
        if check["status"] == "not_applicable"
    )

    if failed:
        overall_status = "FAIL"

    elif review:
        overall_status = "REVIEW"

    else:
        overall_status = "PASS"

    return {
        "overall_status": overall_status,
        "checks": checks,
        "passed": passed,
        "failed": failed,
        "review": review,
        "not_applicable": not_applicable,
        "summary": (
            f"{passed} passed, {failed} failed, "
            f"{review} require verification."
        )
    }


# =========================================================
# MAIN SCAN
# =========================================================

@app.route("/", methods=["GET", "POST"])
def index():

    if request.method == "POST":

        images = request.files.getlist("images")

        images = [
            image
            for image in images
            if image and image.filename
        ]

        if not images:

            return render_template(
                "index.html",
                error="Please select at least one image."
            )

        all_ocr_text = []
        image_payloads = []

        try:

            # -------------------------------------------------
            # STORE IMAGE BYTES
            # -------------------------------------------------

            for image in images:

                image.stream.seek(0)

                image_bytes = image.read()

                if not image_bytes:
                    continue

                image_payloads.append({
                    "filename": image.filename,
                    "bytes": image_bytes,
                    "mimetype": (
                        image.mimetype
                        or "image/jpeg"
                    )
                })

                # -------------------------------------------------
                # OCR
                # -------------------------------------------------

                image.stream.seek(0)

                try:

                    text = extract_text(image)

                except Exception:

                    try:

                        image.stream.seek(0)

                        text = extract_text(image)

                    except Exception as retry_error:

                        text = (
                            f"OCR failed: {retry_error}"
                        )

                all_ocr_text.append({
                    "filename": image.filename,
                    "text": text
                })

            valid_ocr = [
                item
                for item in all_ocr_text
                if not item["text"].startswith(
                    "OCR failed:"
                )
            ]

            if not valid_ocr:

                return render_template(
                    "index.html",
                    error=(
                        "Could not extract text from the "
                        "uploaded images."
                    ),
                    ocr_results=all_ocr_text
                )

            # -------------------------------------------------
            # COMBINE OCR
            # -------------------------------------------------

            combined_ocr = "\n\n".join(
                f"--- IMAGE {item['filename']} ---\n"
                f"{item['text']}"
                for item in valid_ocr
            )

            # -------------------------------------------------
            # GEMINI STRUCTURED EXTRACTION
            # -------------------------------------------------

            structured_data = extract_structured_data(
                combined_ocr
            )

            category = (
                structured_data
                .get("category", {})
                .get("value")
            )

            if not category:
                category = "packaged_commodities"

            # -------------------------------------------------
            # LEGAL METROLOGY COMPLIANCE
            # -------------------------------------------------

            compliance_results = run_compliance_check(
                structured_data,
                category
            )

            # -------------------------------------------------
            # ADVANCED VERIFICATIONS
            # -------------------------------------------------

            advanced_results = run_advanced_verifications(
                structured_data,
                image_payloads,
                category
            )

            # -------------------------------------------------
            # STORE RESULT FOR PDF
            # -------------------------------------------------

            app.config["LAST_RESULT"] = {
                "structured_data": structured_data,
                "compliance_results": compliance_results,
                "advanced_results": advanced_results,
                "ocr_results": all_ocr_text
            }

            return render_template(
                "index.html",
                ocr_results=all_ocr_text,
                structured_data=structured_data,
                compliance_results=compliance_results,
                advanced_results=advanced_results
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

        return (
            "No scan available for report generation.",
            400
        )

    structured_data = result["structured_data"]

    compliance_results = result[
        "compliance_results"
    ]

    advanced_results = result.get(
        "advanced_results",
        {}
    )

    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()

    body_style = ParagraphStyle(
        "ReportBody",
        parent=styles["BodyText"],
        fontSize=8,
        leading=10
    )

    story = []

    story.append(
        Paragraph(
            "LabelCheck Compliance Report",
            styles["Title"]
        )
    )

    story.append(Spacer(1, 18))

    # -----------------------------------------------------
    # PRODUCT INFORMATION
    # -----------------------------------------------------

    story.append(
        Paragraph(
            "Product Information",
            styles["Heading2"]
        )
    )

    product_rows = [
        ["Field", "Value", "Status"]
    ]

    for field, result_data in structured_data.items():

        product_rows.append([
            Paragraph(
                field.replace("_", " ").title(),
                body_style
            ),
            Paragraph(
                str(
                    result_data.get("value")
                    or "Not Found"
                ),
                body_style
            ),
            Paragraph(
                str(
                    result_data.get("status")
                    or ""
                ),
                body_style
            )
        ])

    product_table = Table(
        product_rows,
        colWidths=[120, 270, 90],
        repeatRows=1
    )

    product_table.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor("#0B4F9C")
            ),
            (
                "TEXTCOLOR",
                (0, 0),
                (-1, 0),
                colors.white
            ),
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor("#111111")
            ),
            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "TOP"
            ),
            (
                "FONTNAME",
                (0, 0),
                (-1, 0),
                "Helvetica-Bold"
            ),
            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                8
            ),
            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                5
            ),
            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                5
            )
        ])
    )

    story.append(product_table)

    story.append(Spacer(1, 22))

    # -----------------------------------------------------
    # COMPLIANCE RESULTS
    # -----------------------------------------------------

    story.append(
        Paragraph(
            "Compliance Results",
            styles["Heading2"]
        )
    )

    if compliance_results:

        story.append(
            Paragraph(
                str(
                    compliance_results.get(
                        "summary",
                        ""
                    )
                ),
                body_style
            )
        )

        story.append(Spacer(1, 10))

        compliance_rows = [
            [
                "Rule / Field",
                "Status",
                "Details"
            ]
        ]

        for check in compliance_results.get(
            "checks",
            []
        ):

            compliance_rows.append([
                Paragraph(
                    str(
                        check.get("rule")
                        or check.get("field")
                        or "Rule"
                    ),
                    body_style
                ),
                Paragraph(
                    str(
                        check.get("status", "")
                    ),
                    body_style
                ),
                Paragraph(
                    str(
                        check.get("details")
                        or check.get("message")
                        or ""
                    ),
                    body_style
                )
            ])

        compliance_table = Table(
            compliance_rows,
            colWidths=[150, 70, 260],
            repeatRows=1
        )

        compliance_table.setStyle(
            TableStyle([
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#0B4F9C")
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.HexColor("#111111")
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP"
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    "Helvetica-Bold"
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    8
                )
            ])
        )

        story.append(compliance_table)

    # -----------------------------------------------------
    # ADVANCED VERIFICATIONS
    # -----------------------------------------------------

    if advanced_results:

        story.append(Spacer(1, 22))

        story.append(
            Paragraph(
                "Advanced Statutory & Database Verifications",
                styles["Heading2"]
            )
        )

        story.append(
            Paragraph(
                str(
                    advanced_results.get(
                        "summary",
                        ""
                    )
                ),
                body_style
            )
        )

        story.append(Spacer(1, 10))

        advanced_rows = [
            [
                "Verification",
                "Status",
                "Details",
                "Method"
            ]
        ]

        for check in advanced_results.get(
            "checks",
            []
        ):

            advanced_rows.append([
                Paragraph(
                    str(
                        check.get(
                            "rule",
                            "Verification"
                        )
                    ),
                    body_style
                ),
                Paragraph(
                    str(
                        check.get(
                            "status",
                            ""
                        )
                    ),
                    body_style
                ),
                Paragraph(
                    str(
                        check.get(
                            "details",
                            ""
                        )
                    ),
                    body_style
                ),
                Paragraph(
                    str(
                        check.get(
                            "verification_method",
                            ""
                        ).replace("_", " ")
                    ),
                    body_style
                )
            ])

        advanced_table = Table(
            advanced_rows,
            colWidths=[130, 55, 230, 65],
            repeatRows=1
        )

        advanced_table.setStyle(
            TableStyle([
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#0B4F9C")
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.HexColor("#111111")
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP"
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    "Helvetica-Bold"
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    8
                )
            ])
        )

        story.append(advanced_table)

    doc.build(story)

    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="labelcheck_report.pdf",
        mimetype="application/pdf"
    )


if __name__ == "__main__":

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )