import os
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
    """
    Loads compliance rules from the legal_rules table.

    Actual Neon schema:

        rule_id
        product_category
        field
        requirement
        requirement_type
        exception_condition
        applicable_section
        engine_check
        source_notes
    """

    conn = get_db_connection()

    try:
        cursor = conn.cursor()

        if category:
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
                WHERE LOWER(product_category) = LOWER(%s)
                ORDER BY rule_id
            """

            cursor.execute(query, (category,))

        else:
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
                ORDER BY rule_id
            """

            cursor.execute(query)

        rows = cursor.fetchall()

        rules = []

        for row in rows:

            rules.append({
                "rule_id": row[0],
                "product_category": row[1],
                "field": row[2],
                "requirement": row[3],
                "requirement_type": row[4],
                "exception_condition": row[5],
                "applicable_section": row[6],
                "engine_check": row[7],
                "source_notes": row[8]
            })

        return rules

    finally:
        conn.close()


# ============================================================
# CATEGORY MAPPING
# ============================================================

def normalize_category(category):
    """
    Gemini may identify a practical product category such as:

        personal_care
        cosmetic
        food
        beverage
        household
        etc.

    Our current legal database is based on
    Packaged Commodities rules.

    Therefore these products are currently evaluated
    against the Packaged Commodities rule set.
    """

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
        "other"
    }

    if category in packaged_categories:
        return "Packaged Commodities"

    if category == "packaged commodities":
        return "Packaged Commodities"

    return "Packaged Commodities"


# ============================================================
# VALUE HELPERS
# ============================================================

def get_field(data, field_name):
    """
    Gets a field from Gemini structured output.

    Gemini format:

        {
            "mrp": {
                "value": "249.00",
                "status": "detected",
                "evidence": "..."
            }
        }
    """

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
    """
    Converts database field names into the keys used
    by Gemini structured extraction.
    """

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
# RULE CHECK
# ============================================================

def check_rule(rule, structured_data):
    """
    Performs a basic compliance check for one database rule.

    Important:
    The database tells us WHICH field and requirement
    should be checked.

    We do not blindly require every possible field.
    """

    field = normalize_field_name(rule.get("field"))

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

    value = get_field(structured_data, field)
    status = get_field_status(structured_data, field)

    # --------------------------------------------------------
    # If the field was not detected
    # --------------------------------------------------------

    if value is None or str(value).strip() == "":

        # Conditional rules cannot be judged when their
        # triggering information is unavailable.
        if (
            "conditional" in requirement_type
            or "where applicable" in requirement_type
            or "if applicable" in requirement_type
        ):
            return {
                "rule_id": rule["rule_id"],
                "field": field,
                "status": "not_applicable",
                "value": None,
                "requirement": requirement,
                "details": "Required condition was not established.",
                "source": rule.get("source_notes")
            }

        return {
            "rule_id": rule["rule_id"],
            "field": field,
            "status": "review",
            "value": None,
            "requirement": requirement,
            "details": "Required declaration was not detected.",
            "source": rule.get("source_notes")
        }

    # --------------------------------------------------------
    # Gemini already flagged uncertainty
    # --------------------------------------------------------

    if status == "needs_verification":

        return {
            "rule_id": rule["rule_id"],
            "field": field,
            "status": "review",
            "value": value,
            "requirement": requirement,
            "details": "Value was extracted but requires verification.",
            "source": rule.get("source_notes")
        }

    # --------------------------------------------------------
    # Specific engine checks
    # --------------------------------------------------------

    if engine_check:

        # MRP
        if "mrp" in engine_check:

            if value:
                return {
                    "rule_id": rule["rule_id"],
                    "field": field,
                    "status": "pass",
                    "value": value,
                    "requirement": requirement,
                    "details": "MRP value detected.",
                    "source": rule.get("source_notes")
                }

        # NET QUANTITY
        elif (
            "quantity" in engine_check
            or "net_quantity" in engine_check
        ):

            if value:
                return {
                    "rule_id": rule["rule_id"],
                    "field": field,
                    "status": "pass",
                    "value": value,
                    "requirement": requirement,
                    "details": "Net quantity declaration detected.",
                    "source": rule.get("source_notes")
                }

        # MANUFACTURER
        elif "manufacturer" in engine_check:

            if value:
                return {
                    "rule_id": rule["rule_id"],
                    "field": field,
                    "status": "pass",
                    "value": value,
                    "requirement": requirement,
                    "details": "Manufacturer declaration detected.",
                    "source": rule.get("source_notes")
                }

        # PACKER
        elif "packer" in engine_check:

            if value:
                return {
                    "rule_id": rule["rule_id"],
                    "field": field,
                    "status": "pass",
                    "value": value,
                    "requirement": requirement,
                    "details": "Packer declaration detected.",
                    "source": rule.get("source_notes")
                }

        # IMPORTER
        elif "importer" in engine_check:

            if value:
                return {
                    "rule_id": rule["rule_id"],
                    "field": field,
                    "status": "pass",
                    "value": value,
                    "requirement": requirement,
                    "details": "Importer declaration detected.",
                    "source": rule.get("source_notes")
                }

        # COUNTRY OF ORIGIN
        elif "country" in engine_check:

            if value:
                return {
                    "rule_id": rule["rule_id"],
                    "field": field,
                    "status": "pass",
                    "value": value,
                    "requirement": requirement,
                    "details": "Country of origin declaration detected.",
                    "source": rule.get("source_notes")
                }

        # CONSUMER CARE
        elif "consumer" in engine_check:

            if value:
                return {
                    "rule_id": rule["rule_id"],
                    "field": field,
                    "status": "pass",
                    "value": value,
                    "requirement": requirement,
                    "details": "Consumer care information detected.",
                    "source": rule.get("source_notes")
                }

        # DATE
        elif (
            "date" in engine_check
            or "expiry" in engine_check
            or "best_before" in engine_check
        ):

            if value:
                return {
                    "rule_id": rule["rule_id"],
                    "field": field,
                    "status": "pass",
                    "value": value,
                    "requirement": requirement,
                    "details": "Required date declaration detected.",
                    "source": rule.get("source_notes")
                }

    # --------------------------------------------------------
    # Generic fallback
    # --------------------------------------------------------

    return {
        "rule_id": rule["rule_id"],
        "field": field,
        "status": "pass",
        "value": value,
        "requirement": requirement,
        "details": "Required information detected.",
        "source": rule.get("source_notes")
    }


# ============================================================
# OVERALL COMPLIANCE CHECK
# ============================================================

def run_compliance_check(structured_data, category):
    """
    Main compliance engine.

    Input:
        structured_data = Gemini JSON
        category = Gemini detected category

    Output:
        structured compliance result
    """

    try:

        normalized_category = normalize_category(category)

        # ----------------------------------------------------
        # Load Packaged Commodities rules
        # ----------------------------------------------------

        rules = load_rules(normalized_category)

        if not rules:

            return {
                "overall_status": "NO_RULES_FOUND",
                "score": 0,
                "category": normalized_category,
                "checks": [],
                "summary": (
                    f"No compliance rules are configured "
                    f"for category '{normalized_category}'."
                )
            }

        # ----------------------------------------------------
        # Run every applicable rule
        # ----------------------------------------------------

        checks = []

        for rule in rules:

            result = check_rule(
                rule,
                structured_data
            )

            checks.append(result)

        # ----------------------------------------------------
        # Calculate score
        # ----------------------------------------------------

        applicable_checks = [
            check
            for check in checks
            if check["status"] != "not_applicable"
        ]

        passed = [
            check
            for check in applicable_checks
            if check["status"] == "pass"
        ]

        failed = [
            check
            for check in applicable_checks
            if check["status"] == "fail"
        ]

        review = [
            check
            for check in applicable_checks
            if check["status"] == "review"
        ]

        total = len(applicable_checks)

        if total == 0:
            score = 0
        else:
            score = round(
                (len(passed) / total) * 100
            )

        # ----------------------------------------------------
        # Overall status
        # ----------------------------------------------------

        if failed:
            overall_status = "NON_COMPLIANT"

        elif review:
            overall_status = "REVIEW_REQUIRED"

        else:
            overall_status = "COMPLIANT"

        # ----------------------------------------------------
        # Summary
        # ----------------------------------------------------

        summary = (
            f"{len(passed)} passed, "
            f"{len(failed)} failed, "
            f"{len(review)} require verification "
            f"out of {total} applicable checks."
        )

        return {
            "overall_status": overall_status,
            "score": score,
            "category": normalized_category,
            "checks": checks,
            "summary": summary
        }

    except Exception as e:

        return {
            "overall_status": "ENGINE_ERROR",
            "score": 0,
            "category": category,
            "checks": [],
            "summary": "Could not load compliance rules from database.",
            "error": str(e)
        }