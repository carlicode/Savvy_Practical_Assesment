"""Steps 5-7: route leads, estimate cost, and export the CSV."""

import csv
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_PATH = BASE_DIR / "output" / "processed_leads.csv"

# Standard gpt-4o-mini rates, USD per token.
INPUT_USD = 0.15 / 1_000_000
OUTPUT_USD = 0.60 / 1_000_000

TEAM_BY_INTENT = {
    "Buyer": "Buyer team",
    "Seller": "Seller team",
    "Property Management": "Property Management",
}

PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}

CSV_FIELDS = [
    "Lead_ID",
    "Full_Name",
    "intent",
    "priority",
    "confidence",
    "rationale",
    "data_flags",
    "duplicate_of",
    "needs_human_review",
    "route",
    "suggested_team",
    "next_action",
    "draft_followup",
    "tokens_in",
    "tokens_out",
    "cost_usd",
]


def suggested_team(row):
    """Team implied by intent. Unclear and errors have no team."""
    return TEAM_BY_INTENT.get(row.get("ai_intent") or "", "")


def is_ai_error(row):
    """A non-duplicate with no classification."""
    return not row.get("duplicate_of") and not row.get("ai_intent")


def apply_routing_and_cost(leads):
    """Human review wins. suggested_team stays available for the reviewer."""
    for row in leads:
        team = suggested_team(row)
        review = row.get("ai_needs_human_review") is True
        if review or row.get("duplicate_of") or is_ai_error(row):
            route = "Human review"
        else:
            route = team or "Human review"

        tokens_in = row.get("ai_tokens_in")
        tokens_out = row.get("ai_tokens_out")
        if tokens_in == "" or tokens_out == "" or tokens_in is None:
            cost = 0.0
        else:
            cost = tokens_in * INPUT_USD + tokens_out * OUTPUT_USD

        row["route"] = route
        row["suggested_team"] = team
        row["cost_usd"] = cost
    return leads


def sorted_leads(leads):
    """High, Medium, Low, then blank. Same priority keeps Lead_ID order."""
    return sorted(
        leads,
        key=lambda row: (
            PRIORITY_ORDER.get(row.get("ai_priority") or "", 3),
            row.get("Lead_ID") or "",
        ),
    )


def print_costs(leads):
    print("\nRouting and cost")
    print("-" * 100)
    total = 0.0
    for row in sorted_leads(leads):
        cost = row["cost_usd"]
        total += cost
        print(
            f"{row['Lead_ID']:<10} {row['route']:<22} "
            f"suggested={row['suggested_team'] or '-':<22} ${cost:.6f}"
        )
    print(f"Total: ${total:.6f}")


def _csv_row(row):
    confidence = row.get("ai_confidence")
    if confidence == "" or confidence is None:
        confidence_txt = ""
    else:
        confidence_txt = f"{confidence:.2f}"

    tokens_in = row.get("ai_tokens_in")
    tokens_out = row.get("ai_tokens_out")
    return {
        "Lead_ID": row.get("Lead_ID", ""),
        "Full_Name": row.get("Full_Name", ""),
        "intent": row.get("ai_intent", ""),
        "priority": row.get("ai_priority", ""),
        "confidence": confidence_txt,
        "rationale": row.get("ai_rationale", ""),
        "data_flags": row.get("Data_Flags", ""),
        "duplicate_of": row.get("duplicate_of", ""),
        "needs_human_review": "true" if row.get("ai_needs_human_review") is True else "false",
        "route": row.get("route", ""),
        "suggested_team": row.get("suggested_team", ""),
        "next_action": row.get("ai_next_action", ""),
        "draft_followup": row.get("ai_draft_followup", ""),
        "tokens_in": "" if tokens_in in ("", None) else tokens_in,
        "tokens_out": "" if tokens_out in ("", None) else tokens_out,
        "cost_usd": f"{row.get('cost_usd', 0.0):.6f}",
    }


def write_csv(leads):
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in sorted_leads(leads):
            writer.writerow(_csv_row(row))
    print(f"Saved to {OUTPUT_PATH.relative_to(BASE_DIR)}")


def _result(lead_id, ok, checks):
    """checks are (label, actual, expected)."""
    parts = [f"{label}={actual} (expected {expected})" for label, actual, expected in checks]
    print(f"{lead_id}: {'PASS' if ok else 'FAIL'} | " + " | ".join(parts))


def _expect(row, checks):
    failed = [(label, actual, expected) for label, actual, expected in checks if actual != expected]
    _result(row["Lead_ID"], not failed, checks)


def _route_follows_rule(row):
    review = row.get("ai_needs_human_review") is True
    if review or row.get("duplicate_of") or is_ai_error(row):
        return "Human review"
    return row.get("suggested_team") or "Human review"


def print_test_summary(leads):
    by_id = {row["Lead_ID"]: row for row in leads}
    print("\nTest cases")
    print("-" * 100)

    for lead_id in ("SAV-1003", "SAV-1020"):
        row = by_id[lead_id]
        _expect(row, [
            ("route", row["route"], "Buyer team"),
            ("priority", row.get("ai_priority"), "High"),
            ("suggested_team", row["suggested_team"], "Buyer team"),
        ])

    row = by_id["SAV-1004"]
    email_missing = "yes" if not row.get("Email_Normalized") else "no"
    phone_present = "yes" if row.get("Phone_Normalized") else "no"
    _expect(row, [
        ("email_missing", email_missing, "yes"),
        ("phone_present", phone_present, "yes"),
        ("route", row["route"], _route_follows_rule(row)),
    ])
    print(
        f"         review={str(row.get('ai_needs_human_review') is True).lower()} | "
        f"suggested_team={row['suggested_team'] or '-'}"
    )

    row = by_id["SAV-1005"]
    phone_missing = "yes" if not row.get("Phone_Normalized") else "no"
    email_present = "yes" if row.get("Email_Normalized") else "no"
    _expect(row, [
        ("phone_missing", phone_missing, "yes"),
        ("email_present", email_present, "yes"),
        ("route", row["route"], _route_follows_rule(row)),
    ])
    print(
        f"         review={str(row.get('ai_needs_human_review') is True).lower()} | "
        f"suggested_team={row['suggested_team'] or '-'}"
    )

    row = by_id["SAV-1001"]
    _expect(row, [
        ("route", row["route"], "Buyer team"),
        ("duplicate_of", row.get("duplicate_of") or "-", "-"),
        ("suggested_team", row["suggested_team"], "Buyer team"),
    ])

    row = by_id["SAV-1011"]
    _expect(row, [
        ("route", row["route"], "Human review"),
        ("duplicate_of", row.get("duplicate_of") or "-", "SAV-1001"),
        ("suggested_team", row["suggested_team"], "Buyer team"),
    ])

    for lead_id in ("SAV-1014", "SAV-1019"):
        row = by_id[lead_id]
        _expect(row, [
            ("route", row["route"], "Human review"),
            ("priority", row.get("ai_priority") or "-", "Low"),
        ])
        print(f"         intent={row.get('ai_intent') or '-'} | suggested_team={row['suggested_team'] or '-'}")


def export_results(leads):
    apply_routing_and_cost(leads)
    print_costs(leads)
    write_csv(leads)
    print_test_summary(leads)
    return leads
