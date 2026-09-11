import os
import re
import psycopg2
from dotenv import load_dotenv

load_dotenv()


# ============================================================
# DATABASE
# ============================================================

def get_db_connection():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise Exception("DATABASE_URL is not set in .env")

    return psycopg2.connect(database_url)


# ============================================================
# LOAD RULES
# ============================================================

def load_rules(category=None):
    conn = get_db_connection()

    try:
        cursor = conn.cursor()

        query = """
            SELECT
                rule_id,
                product_category,
                field,
                requirement,
                requirement_type,
                exception_condition,
                applicable_section,
                engine_check,
                source_notes
            FROM legal_rules
        """

        if category:
            query += " WHERE LOWER(product_category) = LOWER(%s)"
            query += " ORDER BY rule_id"
            cursor.execute(query, (category,))
        else:
            query += " ORDER BY rule_id"
            cursor.execute(query)

        rows = cursor.fetchall()

        return [
            {
                "rule_id": row[0],
                "product_category": row[1],
                "field": row[2],
                "requirement": row[3],
                "requirement_type": row[4],
                "exception_condition": row[5],
                "applicable_section": row[6],
                "engine_check": row[7],
                "source_notes": row[8]
            }
            for row in rows
        ]

    finally:
        conn.close()


# ============================================================
# CATEGORY MAPPING
# ============================================================

def normalize_category(category):
    if not category:
        return "Packaged Commodities"

    category = category.strip().lower()

    packaged_categories = {
        "personal_care",
        "personal care",
        "cosmetic",
        "cosmetics",
        "food",
        "beverage",
        "household",
        "healthcare",
        "health care",
        "packaged_goods",
        "packaged good",
        "general",
        "other",
        "packaged commodities"
    }

    if category in packaged_categories:
        return "Packaged Commodities"

    return "Packaged Commodities"


# ============================================================
# VALUE HELPERS
# ============================================================

def get_field(data, field_name):
    if not isinstance(data, dict):
        return None

    field = data.get(field_name)

    if isinstance(field, dict):
        return field.get("value")

    return field


def get_field_status(data, field_name):
    if not isinstance(data, dict):
        return "not_found"

    field = data.get(field_name)

    if isinstance(field, dict):
        return field.get("status", "not_found")

    return "not_found"


# ============================================================
# FIELD NAME NORMALIZATION
# ============================================================

def normalize_field_name(field):
    if not field:
        return ""

    field = field.strip().lower()

    mappings = {
        "mrp": "mrp",
        "maximum retail price": "mrp",

        "net quantity": "net_quantity",
        "net quantity / net content": "net_quantity",
        "net content": "net_quantity",
        "quantity": "net_quantity",

        "manufacturer": "manufacturer",
        "manufactured by": "manufacturer",

        "packer": "packer",
        "packed by": "packer",

        "importer": "importer",
        "imported by": "importer",

        "country of origin": "country_of_origin",

        "manufacturing date": "manufacturing_date",
        "manufacture date": "manufacturing_date",
        "mfg date": "manufacturing_date",
        "mfg. date": "manufacturing_date",

        "expiry": "expiry_or_best_before",
        "expiry date": "expiry_or_best_before",
        "best before": "expiry_or_best_before",
        "expiry or best before": "expiry_or_best_before",

        "batch number": "batch_number",
        "batch no": "batch_number",
        "batch no.": "batch_number",

        "consumer care": "consumer_care",
        "consumer care details": "consumer_care",

        "unit sale price": "unit_sale_price",
        "unit sale price / usp": "unit_sale_price",

        "product name": "product_name",

        "fssai license number": "fssai_license_number",
        "fssai licence number": "fssai_license_number"
    }

    return mappings.get(field, field.replace(" ", "_"))


# ============================================================
# DATA-FIELD RESOLUTION
# ============================================================
#
# The `field` column in legal_rules holds a human-readable rule
# title (e.g. "Manufacturer / packer / importer name and address"),
# not the key used in the extracted structured data. Looking it up
# directly (via normalize_field_name) almost never matches the
# extractor's schema, which forces every such rule into "review"
# even when the data was actually detected.
#
# The `engine_check` column already carries the machine-readable
# key that lines up with the Gemini extraction schema. Prefer that
# for resolving which structured-data field a rule is about, and
# only fall back to the title-based guess for anything with no
# direct data equivalent (packaging/procedural rules that aren't
# extractable from OCR text at all).

STRUCTURED_DATA_FIELDS = {
    "product_name", "category", "mrp", "net_quantity",
    "manufacturing_date", "expiry_or_best_before", "batch_number",
    "manufacturer", "packer", "importer", "consumer_care",
    "country_of_origin", "unit_sale_price", "fssai_license_number",
}

# engine_check values that don't map 1:1 to a schema key but should
# resolve against a specific field (or set of fields) anyway.
ENGINE_CHECK_ALIASES = {
    "manufacturer_packer_importer": "manufacturer_packer_importer",
}


def resolve_data_field(rule):
    engine_check = (rule.get("engine_check") or "").strip().lower()

    if engine_check in STRUCTURED_DATA_FIELDS:
        return engine_check

    if engine_check in ENGINE_CHECK_ALIASES:
        return ENGINE_CHECK_ALIASES[engine_check]

    # No direct structured-data equivalent (e.g. font size, package
    # presentation, registration, enforcement/procedural rules) -
    # fall back to the old title-based guess so behavior for those
    # is unchanged.
    return normalize_field_name(rule.get("field"))


def get_manufacturer_packer_importer(data):
    """
    'Manufacturer / packer / importer' is satisfied by any one of the
    three being declared, so check all three and return whichever is
    present.
    """
    for key in ("manufacturer", "packer", "importer"):
        value = get_field(data, key)
        status = get_field_status(data, key)
        if value is not None and str(value).strip() != "":
            return value, status
    return None, "not_found"


# ============================================================
# RESULT BUILDER
# ============================================================

def build_result(rule, field, status, value, details):
    return {
        "rule_id": rule["rule_id"],
        "field": field,
        "status": status,
        "value": value,
        "requirement": rule.get("requirement"),
        "details": details,
        "source": rule.get("source_notes"),
        "section": rule.get("applicable_section")
    }


# ============================================================
# RULE CHECK
# ============================================================

def check_rule(rule, structured_data):
    field = resolve_data_field(rule)

    requirement_type = (
        rule.get("requirement_type") or ""
    ).strip().lower()

    requirement = (
        rule.get("requirement") or ""
    ).strip()

    exception = (
        rule.get("exception_condition") or ""
    ).strip()

    engine_check = (
        rule.get("engine_check") or ""
    ).strip().lower()

    if field == "manufacturer_packer_importer":
        value, status = get_manufacturer_packer_importer(structured_data)
    else:
        value = get_field(structured_data, field)
        status = get_field_status(structured_data, field)

    # --------------------------------------------------------
    # Missing field
    # --------------------------------------------------------

    if value is None or str(value).strip() == "":
        requirement_type_normalized = requirement_type.replace("_", " ")
        conditional = (
            "conditional" in requirement_type_normalized
            or "where applicable" in requirement_type_normalized
            or "if applicable" in requirement_type_normalized
            or bool(exception)
        )

        if conditional:
            return build_result(
                rule,
                field,
                "not_applicable",
                None,
                "Condition for this requirement was not established."
            )

        return build_result(
            rule,
            field,
            "review",
            None,
            "Required declaration was not detected."
        )

    # --------------------------------------------------------
    # Gemini uncertainty
    # --------------------------------------------------------

    if status == "needs_verification":
        return build_result(
            rule,
            field,
            "review",
            value,
            "Value was extracted but requires verification."
        )

    # --------------------------------------------------------
    # MRP
    # --------------------------------------------------------

    if "mrp" in engine_check:
        return build_result(
            rule,
            field,
            "pass",
            value,
            "MRP value detected."
        )

    # --------------------------------------------------------
    # NET QUANTITY
    # --------------------------------------------------------

    if (
        "quantity" in engine_check
        or "net_quantity" in engine_check
    ):
        return build_result(
            rule,
            field,
            "pass",
            value,
            "Net quantity declaration detected."
        )

    # --------------------------------------------------------
    # MANUFACTURER
    # --------------------------------------------------------

    if (
        "manufacturer" in engine_check
        or "manufactured_by" in engine_check
    ):
        return build_result(
            rule,
            field,
            "pass",
            value,
            "Manufacturer declaration detected."
        )

    # --------------------------------------------------------
    # PACKER
    # --------------------------------------------------------

    if "packer" in engine_check:
        return build_result(
            rule,
            field,
            "pass",
            value,
            "Packer declaration detected."
        )

    # --------------------------------------------------------
    # IMPORTER
    # --------------------------------------------------------

    if "importer" in engine_check:
        return build_result(
            rule,
            field,
            "pass",
            value,
            "Importer declaration detected."
        )

    # --------------------------------------------------------
    # COUNTRY OF ORIGIN
    # --------------------------------------------------------

    if "country" in engine_check:
        return build_result(
            rule,
            field,
            "pass",
            value,
            "Country of origin declaration detected."
        )

    # --------------------------------------------------------
    # CONSUMER CARE
    # --------------------------------------------------------

    if "consumer" in engine_check:
        return build_result(
            rule,
            field,
            "pass",
            value,
            "Consumer care information detected."
        )

    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    if (
        "date" in engine_check
        or "expiry" in engine_check
        or "best_before" in engine_check
    ):
        return build_result(
            rule,
            field,
            "pass",
            value,
            "Required date declaration detected."
        )

    # --------------------------------------------------------
    # BATCH NUMBER
    # --------------------------------------------------------

    if (
        "batch" in engine_check
        or "lot" in engine_check
    ):
        return build_result(
            rule,
            field,
            "pass",
            value,
            "Batch or lot information detected."
        )

    # --------------------------------------------------------
    # UNIT SALE PRICE
    # --------------------------------------------------------

    if (
        "unit_sale_price" in engine_check
        or "unit sale price" in engine_check
        or "usp" in engine_check
    ):
        return build_result(
            rule,
            field,
            "pass",
            value,
            "Unit sale price information detected."
        )

    # --------------------------------------------------------
    # PRODUCT NAME
    # --------------------------------------------------------

    if (
        "product_name" in engine_check
        or "product name" in engine_check
        or "name" == engine_check
    ):
        return build_result(
            rule,
            field,
            "pass",
            value,
            "Product name detected."
        )

    # --------------------------------------------------------
    # GENERIC RULE
    # --------------------------------------------------------

    if value:
        return build_result(
            rule,
            field,
            "pass",
            value,
            "Required information detected."
        )

    return build_result(
        rule,
        field,
        "review",
        value,
        "Unable to determine compliance for this requirement."
    )


# ============================================================
# OVERALL COMPLIANCE CHECK
# ============================================================

def run_compliance_check(structured_data, category):

    try:

        normalized_category = normalize_category(
            category
        )

        rules = load_rules(
            normalized_category
        )

        if not rules:

            return {
                "overall_status": "NO_RULES_FOUND",
                "category": normalized_category,
                "total_rules": 0,
                "applicable_rules": 0,
                "passed": 0,
                "failed": 0,
                "review": 0,
                "not_applicable": 0,
                "checks": [],
                "summary": (
                    f"No compliance rules are configured "
                    f"for category '{normalized_category}'."
                )
            }

        checks = [
            check_rule(
                rule,
                structured_data
            )
            for rule in rules
        ]

        passed = [
            check
            for check in checks
            if check["status"] == "pass"
        ]

        failed = [
            check
            for check in checks
            if check["status"] == "fail"
        ]

        review = [
            check
            for check in checks
            if check["status"] == "review"
        ]

        not_applicable = [
            check
            for check in checks
            if check["status"] == "not_applicable"
        ]

        applicable_count = (
            len(passed)
            + len(failed)
            + len(review)
        )

        if failed:

            overall_status = "NON_COMPLIANT"

        elif review:

            overall_status = "REVIEW_REQUIRED"

        else:

            overall_status = "COMPLIANT"

        summary = (
            f"{len(passed)} passed, "
            f"{len(failed)} failed, "
            f"{len(review)} require verification "
            f"out of {applicable_count} applicable checks."
        )

        return {
            "overall_status": overall_status,
            "category": normalized_category,

            "total_rules": len(rules),
            "applicable_rules": applicable_count,

            "passed": len(passed),
            "failed": len(failed),
            "review": len(review),
            "not_applicable": len(not_applicable),

            "checks": checks,
            "summary": summary
        }

    except Exception as e:

        return {
            "overall_status": "ENGINE_ERROR",
            "category": category,

            "total_rules": 0,
            "applicable_rules": 0,

            "passed": 0,
            "failed": 0,
            "review": 0,
            "not_applicable": 0,

            "checks": [],

            "summary": (
                "Could not load compliance rules "
                "from database."
            ),

            "error": str(e)
        }


# ============================================================
# ADVANCED CHECKS: FSSAI FORMAT VALIDATION + FONT LEGIBILITY
# ============================================================
#
# These two checks are engine-native (not sourced from the legal_rules
# table), so they're kept in a separate pipeline: run_advanced_checks().
# That way a DB outage never blocks them, and the UI can present them
# in their own "Advanced Statutory & Database Verifications" card
# instead of mixing them into the Legal Metrology rule table.

FSSAI_LICENSE_LENGTH = 14
FONT_LEGIBILITY_PASS_THRESHOLD = 70


def verify_government_database(identifier_type, value):
    """
    NOTE ON THE NAME: this function is kept as `verify_government_database`
    for interface compatibility, but it currently performs FORMAT
    VALIDATION ONLY - it does not call any live government registry.

    Why: as of writing, FSSAI/FoSCoS does not expose a free public
    verification API. The only "real-time" registry lookups available
    are paid third-party KYC providers that wrap FoSCoS, or the manual
    search on foscos.fssai.gov.in. Silently labeling a 14-digit regex
    check as "verified against the government database" would let this
    tool claim a guarantee it hasn't actually earned - a bad look for a
    legal-compliance product where "PASS" implies something has been
    checked against an authoritative source.

    If you later get access to a real provider, wire the call in at the
    marked spot below - the function signature and return shape won't
    need to change, and every caller (including the UI) will start
    reflecting genuine registry verification automatically.
    """
    identifier_type = (identifier_type or "").strip().lower()

    if identifier_type != "fssai":
        return {
            "status": "NOT_APPLICABLE",
            "verification_method": "unsupported_identifier_type",
            "message": (
                f"No verification routine is configured for identifier "
                f"type '{identifier_type}'."
            )
        }

    if not value or not str(value).strip():
        return {
            "status": "FAIL",
            "verification_method": "format_validation",
            "message": (
                "No FSSAI license number was detected on the label. Under "
                "the FSS Act 2006 and the FSS (Licensing and Registration "
                "of Food Businesses) Regulations, every food business "
                "operator must display a valid 14-digit FSSAI license "
                "number on the package."
            )
        }

    cleaned = re.sub(r"[^0-9]", "", str(value))

    # -----------------------------------------------------------------
    # REAL REGISTRY LOOKUP GOES HERE, e.g.:
    #
    #   provider_key = os.getenv("FSSAI_VERIFICATION_API_KEY")
    #   if provider_key:
    #       return _call_real_fssai_registry(cleaned, provider_key)
    #
    # Until a provider is configured, we fall through to a structural
    # (format-only) check below.
    # -----------------------------------------------------------------

    if len(cleaned) != FSSAI_LICENSE_LENGTH:
        return {
            "status": "FAIL",
            "verification_method": "format_validation",
            "message": (
                f"'{value}' does not match the required "
                f"{FSSAI_LICENSE_LENGTH}-digit FSSAI license number format "
                f"({len(cleaned)} digit(s) found after cleanup). This is a "
                f"structural check only, not a live registry lookup."
            )
        }

    return {
        "status": "PASS",
        "verification_method": "format_validation",
        "message": (
            f"'{value}' matches the {FSSAI_LICENSE_LENGTH}-digit FSSAI "
            f"license number structure. This confirms the FORMAT is "
            f"valid - it does not confirm the license is active, "
            f"assigned, or genuine. Verify manually on FoSCoS "
            f"(foscos.fssai.gov.in) or connect a licensed FSSAI "
            f"verification API for true registry confirmation."
        )
    }


def check_font_legibility(font_legibility):
    """
    font_legibility: dict shaped like
        {"score": int, "concerns": [str, ...], "reasoning": str}
    produced by gemini_extractor.assess_font_legibility() from the
    actual product image - or None if no assessment could be produced
    (e.g. the Gemini call failed, or no image bytes were available).

    A missing assessment is treated as REVIEW, not PASS or FAIL: we
    have no signal either way, so the honest answer is "needs a human
    look", not a guess dressed up as a result.
    """
    if not font_legibility or font_legibility.get("score") is None:
        return {
            "rule": "Minimum Font Size & Visual Legibility Check",
            "status": "REVIEW",
            "details": (
                "An AI visual legibility assessment could not be generated "
                "for this upload. Manually verify that mandatory "
                "declarations meet the minimum character height required "
                "under the Legal Metrology (Packaged Commodities) Rules "
                "for the pack's declared area."
            ),
            "verification_method": "unavailable"
        }

    score = font_legibility["score"]
    concerns = font_legibility.get("concerns") or []

    if score >= FONT_LEGIBILITY_PASS_THRESHOLD:
        return {
            "rule": "Minimum Font Size & Visual Legibility Check",
            "status": "PASS",
            "details": (
                f"AI-estimated visual legibility score: {score}/100. "
                f"Mandatory declarations appear reasonably legible in the "
                f"submitted image(s)."
            ),
            "verification_method": "ai_visual_estimate",
            "score": score
        }

    concern_text = "; ".join(concerns) if concerns else "no specific issues listed"

    return {
        "rule": "Minimum Font Size & Visual Legibility Check",
        "status": "REVIEW",
        "details": (
            f"AI-estimated visual legibility score: {score}/100, below "
            f"the {FONT_LEGIBILITY_PASS_THRESHOLD} threshold ({concern_text}). "
            f"This is a perceptual estimate from the photo, not a "
            f"calibrated character-height measurement in millimetres - "
            f"manually confirm against the minimum lettering size "
            f"prescribed for the declared pack size before treating this "
            f"as a confirmed violation."
        ),
        "verification_method": "ai_visual_estimate",
        "score": score
    }


def run_advanced_checks(structured_data, font_legibility=None):
    """
    Runs the two "advanced" checks (FSSAI format validation, font
    legibility) and returns them in the same {checks, summary} shape as
    run_compliance_check(), so the template can render them the same
    way in a separate card.
    """
    checks = []

    fssai_value = get_field(structured_data, "fssai_license_number")
    fssai_result = verify_government_database("fssai", fssai_value)

    checks.append({
        "rule": "FSSAI License Number - Format Validation",
        "status": fssai_result["status"],
        "details": fssai_result["message"],
        "verification_method": fssai_result["verification_method"]
    })

    checks.append(check_font_legibility(font_legibility))

    passed = len([c for c in checks if c["status"] == "PASS"])
    failed = len([c for c in checks if c["status"] == "FAIL"])
    review = len([c for c in checks if c["status"] == "REVIEW"])

    return {
        "checks": checks,
        "summary": (
            f"{passed} passed, {failed} failed, "
            f"{review} require verification."
        )
    }