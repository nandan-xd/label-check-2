import os

from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel, Field

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash"
)


# =========================================================
# STRUCTURED OUTPUT SCHEMA
# =========================================================

class FieldResult(BaseModel):
    value: str | None = Field(
        default=None,
        description="Value found in the OCR text."
    )

    status: str = Field(
        description="detected, needs_verification, or not_found"
    )

    evidence: str | None = Field(
        default=None,
        description="Short explanation of the OCR evidence."
    )


class LabelData(BaseModel):

    product_name: FieldResult
    category: FieldResult

    mrp: FieldResult
    net_quantity: FieldResult

    manufacturing_date: FieldResult
    expiry_or_best_before: FieldResult

    batch_number: FieldResult

    manufacturer: FieldResult
    packer: FieldResult
    importer: FieldResult

    consumer_care: FieldResult

    country_of_origin: FieldResult

    unit_sale_price: FieldResult

    fssai_license_number: FieldResult


# =========================================================
# PROMPT
# =========================================================

PROMPT = """
You are a structured text extraction system for LabelCheck.

You receive RAW OCR TEXT extracted from a product label.

Your task is ONLY to organize the OCR information into structured
product-label fields.

You are NOT looking at the image.

IMPORTANT RULES:

1. Never invent information.
2. Never use outside knowledge to fill missing information.
3. OCR may contain character recognition mistakes.
4. You may correct an obvious OCR mistake when the surrounding
   context makes the intended value very clear.
5. If a value is uncertain, use "needs_verification".
6. If there is no usable evidence, use "not_found".
7. Do not confuse unrelated numbers with declaration values.
8. Preserve the printed value whenever possible.
9. Do not make any legal compliance decision.
10. For product_name, combine brand + product type only when both are clearly
present in the OCR text and the relationship is obvious.

11. Do not invent a specific product variant, formulation, flavor, model,
or product name that is not present in the OCR text.

MRP:
Look for MRP, MRP:, MRP(R), Rs., ₹ and similar declarations.
Return ONLY the price.

NET QUANTITY:
Examples:
200 ml
800 g
1 L
250 ml

MANUFACTURING DATE:
Look for:
Mfg Date
Mfg. Date
Manufacturing Date

EXPIRY / BEST BEFORE:
Look for:
Exp Date
Exp. Date
Use Before
Best Before

BATCH NUMBER:
Look for:
Batch No.
Batch Number
Lot No.
Lot Number

MANUFACTURER:
Look for:
Manufactured By
Manufacturer

PACKER:
Look for:
Packed By
Packer

IMPORTER:
Look for:
Imported By
Importer

CONSUMER CARE:
Look for:
Customer Care
Consumer Care
Complaints
Queries
Toll-Free
phone numbers
email addresses

COUNTRY OF ORIGIN:
Only extract when explicitly stated.

Examples:
Made in India
Country of Origin: India

FSSAI LICENSE:
Look for FSSAI, FSSAI Lic. No., License No.
A typical FSSAI license number is 14 digits.

CATEGORY:
Use one of:
food
beverage
cosmetic
personal_care
household
packaged_goods
unknown

EVIDENCE:
Briefly explain what OCR text caused the field to be extracted.

OCR TEXT:

STATUS RULES:

Use "detected" when the OCR text provides strong contextual evidence for
the field and the intended value can be determined despite minor OCR errors.

OCR may incorrectly recognize symbols or characters. Do not automatically
mark a field as needs_verification just because OCR contains a typo,
misrecognized symbol, or formatting error.

Examples:

- "MRP: 3 249.00" or "MRP: #249.00" may represent "MRP: ₹249.00".
  Extract the value as "249.00" and mark it "detected" if the price is clear.

- "Net content: THOLUME 100ml" can reasonably be interpreted as
  "100 ml" when the quantity is clearly present.

- "MADE IN INDIA" should be detected as country_of_origin = India.

- "Mfg. Date: 05/26" should be detected as 05/26 when the date is clearly
  associated with the manufacturing-date label.

Use "needs_verification" ONLY when the actual value itself is genuinely
uncertain, incomplete, contradictory, or too corrupted to determine.

Examples:

- "Batch No: TAPF 02?" → needs_verification
- "MRP: 2?9.00" → needs_verification
- "Mfg Date: 0?/26" → needs_verification

Do NOT use needs_verification merely because OCR contains minor spelling,
spacing, punctuation, or symbol-recognition errors.

OCR ERROR HANDLING:

The OCR output may contain common recognition errors such as:

₹ → #, 3, R, Rs, or other characters
O ↔ 0
I ↔ 1
S ↔ 5
B ↔ 8
missing punctuation
incorrect spaces
words split across lines
words merged together

Use the surrounding field label and nearby text to resolve obvious OCR
recognition errors when the intended meaning is clear.

Do not invent missing information. Only correct an OCR error when the
correction is strongly supported by the surrounding context.
IMPORTANT LABEL LAYOUT RULES:

The OCR text may not preserve the physical layout of the package correctly.
Text that appears together visually may be separated in the OCR output, and text
from different parts of the package may be mixed together.

Pay special attention to printed/stamped information such as:
- MRP
- Manufacturing Date
- Expiry / Best Before Date
- Batch Number
- Net Quantity
- Unit Sale Price

These values are often printed separately from the main label, for example:
- on a bottom seal
- on a top/bottom crimp
- on a sticker
- near the barcode
- on a small stamped area
- above or below the main printed label
- in another image of the same product

Therefore, do NOT assume that MRP, dates, or batch number must appear
immediately next to their field names in the OCR text.

If OCR contains a field label such as "MRP", "Mfg. Date", "Exp. Date",
"Batch No." etc., search the ENTIRE OCR text for a nearby-looking value,
including values that may have been separated from the label because of OCR
layout errors.

Also inspect other supplied OCR outputs because multiple images may represent
different sides/areas of the SAME product.

For example, if OCR produces something similar to:

MRP(R)
#440.00
Batch No.
B260081
05/26
04/28

interpret the surrounding context and relationships rather than requiring the
value to be on the same OCR line.

OCR may also misread the Indian Rupee symbol (₹) as characters such as:
R, Rs, #, 3, or other symbols.

When a price is clearly associated with "MRP" and the surrounding OCR strongly
supports that relationship, normalize the value to the numeric price and do not
mark it as needs_verification merely because the currency symbol was
misread.

For example:
"MRP(R) #440.00"
"MRP 3 249.00"
"MRP Rs. 99.00"

should be interpreted as:
MRP = "440.00"
MRP = "249.00"
MRP = "99.00"

respectively, when the association is clear.

Similarly, OCR may separate dates from their labels. If multiple date-like
values appear near Mfg. Date / Exp. Date / Use Before / Best Before,
use the surrounding context and common label ordering to associate them,
but mark the field needs_verification if the association remains genuinely
ambiguous.

Do not mark a value as needs_verification solely because OCR contains a
minor character recognition error when the intended value and its field
association are otherwise clear.

Use needs_verification when the VALUE itself is genuinely uncertain, not
merely because OCR formatting or punctuation is imperfect.
"""


# =========================================================
# GEMINI
# =========================================================

def extract_structured_data(ocr_text):

    if not GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY is not configured."
        )

    if not ocr_text or not ocr_text.strip():
        raise ValueError(
            "No OCR text was available."
        )

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    prompt = PROMPT + "\n\n" + ocr_text

    interaction = client.interactions.create(
        model=GEMINI_MODEL,
        input=prompt,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": LabelData.model_json_schema()
        }
    )

    if not interaction.output_text:
        raise ValueError(
            "Gemini returned an empty response."
        )

    try:

        result = LabelData.model_validate_json(
            interaction.output_text
        )

    except Exception as e:

        raise ValueError(
            f"Could not parse Gemini JSON: {e}\n\n"
            f"Gemini output:\n{interaction.output_text}"
        ) from e

    return result.model_dump()