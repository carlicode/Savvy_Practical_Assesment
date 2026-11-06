"""Steps 1 and 2: load the CSV, normalize fields, and mark flags."""

import csv
import re


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TIMELINE_RANGE_RE = re.compile(
    r"(\d+)\s*-\s*(\d+)\s*(days?|months?)$", re.IGNORECASE
)
TIMELINE_SINGLE_RE = re.compile(r"(\d+)\s*(days?|months?)$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# 1. Load CSV
# ---------------------------------------------------------------------------

def load_leads(path):
    """Load the CSV and keep Lead_ID exactly as provided."""
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# ---------------------------------------------------------------------------
# 2. Validate and normalize
# ---------------------------------------------------------------------------

def _clean(value):
    """Strip whitespace; None or empty becomes an empty string."""
    if value is None:
        return ""
    return str(value).strip()


def normalize_email(value):
    """Lowercase email. Empty = missing; odd format = doubtful."""
    email = _clean(value).lower()
    if not email:
        return "", "email_missing"
    if not EMAIL_RE.match(email):
        return email, "email_doubtful"
    return email, None


def normalize_phone(value):
    """Phone as +1XXXXXXXXXX. Empty = missing; invalid digits = doubtful."""
    phone = _clean(value)
    if not phone:
        return "", "phone_missing"

    digits = re.sub(r"\D", "", phone)
    if digits.startswith("1") and len(digits) == 11:
        return f"+{digits}", None
    if len(digits) == 10:
        return f"+1{digits}", None
    return phone, "phone_doubtful"


def normalize_budget(value, lead_type):
    """Numeric budget. Empty is normal for Property Management."""
    raw = _clean(value)
    lead_type = _clean(lead_type)

    if not raw:
        if lead_type.lower() == "property management":
            return "", None
        return "", "budget_missing"

    try:
        return float(raw), None
    except ValueError:
        return raw, "budget_doubtful"


def normalize_timeline(value):
    """Timeline in days. Ranges use the floor. ASAP = 0. Unknown = missing."""
    raw = _clean(value)
    if not raw or raw.lower() == "unknown":
        return "", "timeline_missing"

    if raw.lower() == "asap":
        return 0, None

    range_match = TIMELINE_RANGE_RE.match(raw)
    if range_match:
        low, _high, unit = range_match.groups()
        factor = 30 if unit.lower().startswith("month") else 1
        return int(low) * factor, None

    single_match = TIMELINE_SINGLE_RE.match(raw)
    if single_match:
        amount, unit = single_match.groups()
        factor = 30 if unit.lower().startswith("month") else 1
        return int(amount) * factor, None

    return raw, "timeline_doubtful"


def lead_type_flag(value):
    """Mark Other/Unknown as lead_type_unclear."""
    lead_type = _clean(value).lower()
    if lead_type in {"other", "unknown"}:
        return "lead_type_unclear"
    return None


def validate_lead(row):
    """Return the original lead plus normalized fields and quality flags."""
    email, email_flag = normalize_email(row.get("Email"))
    phone, phone_flag = normalize_phone(row.get("Phone"))
    budget, budget_flag = normalize_budget(
        row.get("Budget_USD"), row.get("Lead_Type")
    )
    timeline_days, timeline_flag = normalize_timeline(
        row.get("Purchase_or_Action_Timeline")
    )
    type_flag = lead_type_flag(row.get("Lead_Type"))

    flags = [
        flag
        for flag in (email_flag, phone_flag, budget_flag, timeline_flag, type_flag)
        if flag
    ]

    validated = dict(row)
    validated["Email_Normalized"] = email
    validated["Phone_Normalized"] = phone
    validated["Budget_USD_Normalized"] = budget
    validated["Timeline_Days"] = timeline_days
    validated["Data_Flags"] = ";".join(flags)
    return validated


def validate_leads(leads):
    return [validate_lead(row) for row in leads]
