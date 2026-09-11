import base64
import os
from google.genai import types

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
mark it as needs_verification merely because the currency symbol was misread.

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

    prompt = (
        PROMPT
        + "\n\nOCR TEXT:\n\n"
        + ocr_text
    )

    try:

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=LabelData,
                temperature=0
            )
        )

    except Exception as e:

        raise RuntimeError(
            f"Gemini API error: {e}"
        ) from e

    if not response.text:

        raise ValueError(
            "Gemini returned an empty response."
        )

    try:

        result = LabelData.model_validate_json(
            response.text
        )

    except Exception as e:

        raise ValueError(
            f"Could not parse Gemini JSON: {e}\n\n"
            f"Gemini output:\n{response.text}"
        ) from e

    return result.model_dump()

# =========================================================
# FONT LEGIBILITY (IMAGE-BASED - SEPARATE FROM TEXT EXTRACTION)
# =========================================================
#
# extract_structured_data() above only ever sees OCR TEXT - the prompt
# explicitly tells the model "you are NOT looking at the image". Text
# has no font size, contrast, or layout information in it, so that
# call has no basis to judge legibility.
#
# This is therefore a deliberately separate, genuinely multimodal call
# that sends the actual image bytes to Gemini. Keep it that way - don't
# fold font_legibility_score into LabelData/PROMPT above, or you'll be
# asking a text-only call to invent a number it can't actually see.

class FontLegibilityResult(BaseModel):
    score: int = Field(
        description=(
            "Estimated visual legibility score from 1-100, based on "
            "apparent text size relative to the label, contrast, and "
            "background clutter around mandatory declarations. This is "
            "a perceptual estimate from a photo, not a calibrated "
            "character-height-in-millimetres measurement."
        )
    )

    concerns: list[str] = Field(
        default_factory=list,
        description=(
            "Specific legibility issues observed, e.g. 'MRP text is very "
            "small relative to the brand logo', 'Low contrast white text "
            "on light background'. Empty list if none."
        )
    )

    reasoning: str = Field(
        description="One or two sentences explaining the score."
    )


FONT_LEGIBILITY_PROMPT = """
You are a visual legibility assessment system for LabelCheck, an Indian
Legal Metrology compliance tool.

Look at the attached product label image and estimate how legible its
mandatory declarations (MRP, net quantity, manufacturing date, expiry
date, manufacturer/packer/importer details) are to an ordinary consumer
under normal shopping conditions.

Score from 1 to 100 based on:
- Apparent relative text size of the mandatory declarations versus the
  rest of the label
- Contrast between text and its background
- Clutter, overlapping graphics, or busy backgrounds behind the text
- Whether declarations are visibly cut off, blurry, or obscured

IMPORTANT LIMITATIONS - respect these:
- You are estimating RELATIVE, PERCEIVED legibility from a photograph.
  You cannot measure exact character height in millimetres against the
  physical package, and you must not claim that precision.
- Do not penalize the score for OCR errors, camera resolution, or
  photo angle unless they reflect a genuine legibility problem on the
  label itself (e.g. the text truly is tiny relative to the pack).
- If the image is too blurry, cropped, or low-quality to judge
  legibility at all, say so explicitly in `reasoning` and return a
  mid-range score (40-60) rather than guessing confidently in either
  direction.

Return a score, a short list of specific concerns (empty list if none),
and one or two sentences of reasoning.
"""


def assess_font_legibility(image_bytes, mime_type="image/jpeg"):
    """
    Sends the actual product image to Gemini for a visual legibility
    estimate.

    Returns a dict: {"score": int, "concerns": [...], "reasoning": str}
    Returns None if no image bytes were provided - callers should treat
    None as "no assessment available" (REVIEW), never as a pass or fail.
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not configured.")

    if not image_bytes:
        return None

    client = genai.Client(api_key=GEMINI_API_KEY)

    try:
        interaction = client.interactions.create(
            model=GEMINI_MODEL,
            input=[
                {"type": "text", "text": FONT_LEGIBILITY_PROMPT},
                {
                    "type": "image",
                    "data": base64.b64encode(image_bytes).decode("utf-8"),
                    "mime_type": mime_type or "image/jpeg"
                }
            ],
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": FontLegibilityResult.model_json_schema()
            }
        )

    except Exception as e:
        raise RuntimeError(
            f"Gemini API error during legibility assessment: {e}"
        ) from e

    if not interaction.output_text:
        return None

    try:
        result = FontLegibilityResult.model_validate_json(
            interaction.output_text
        )

    except Exception as e:
        raise ValueError(
            f"Could not parse Gemini legibility JSON: {e}\n\n"
            f"Gemini output:\n{interaction.output_text}"
        ) from e

    # Clamp defensively in case the model drifts outside 1-100
    score = max(1, min(100, result.score))

    return {
        "score": score,
        "concerns": result.concerns,
        "reasoning": result.reasoning
    }

# =========================================================
# VISUAL LEGIBILITY CHECK
# =========================================================

class LegibilityResult(BaseModel):

    score: int = Field(
        description="Visual legibility estimate from 0 to 100."
    )

    summary: str = Field(
        description="Short explanation of the visual legibility."
    )


VISUAL_LEGIBILITY_PROMPT = """
You are performing a visual screening check for a packaged-product label.

Inspect the supplied product image(s) and estimate how clearly the mandatory
printed declarations appear to be presented and readable.

Look for visible declarations such as:

- MRP
- net quantity
- manufacturer / packer / importer information
- manufacturing date
- expiry / best before
- batch / lot number
- consumer care details
- country of origin
- other prominent mandatory declarations visible in the image

Return a visual legibility score from 0 to 100 and a short explanation.

IMPORTANT:

- This is an AI visual estimate only.
- Do NOT claim that you physically measured font height.
- Do NOT claim legal compliance from the image alone.
- Do NOT invent text that is not visibly present.
- Consider blur, glare, tiny text, low contrast, obstruction and image quality.
- A clear image can receive a high score even though physical font size has
  not been calibrated.
- If only part of the package is visible, judge only what can be seen.
"""


def check_visual_legibility(image_payloads):

    if not GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY is not configured."
        )

    if not image_payloads:
        raise ValueError(
            "No images were available for visual verification."
        )

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    contents = [
        VISUAL_LEGIBILITY_PROMPT
    ]

    for payload in image_payloads:

        contents.append(
            types.Part.from_bytes(
                data=payload["bytes"],
                mime_type=payload["mimetype"]
            )
        )

    try:

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=LegibilityResult,
                temperature=0
            )
        )

    except Exception as e:

        raise RuntimeError(
            f"Gemini visual verification error: {e}"
        ) from e

    if not response.text:

        raise ValueError(
            "Gemini returned an empty visual verification response."
        )

    try:

        result = LegibilityResult.model_validate_json(
            response.text
        )

    except Exception as e:

        raise ValueError(
            f"Could not parse visual verification JSON: {e}\n\n"
            f"Gemini output:\n{response.text}"
        ) from e

    return {
        "score": max(
            0,
            min(
                100,
                int(result.score)
            )
        ),
        "summary": result.summary
    }