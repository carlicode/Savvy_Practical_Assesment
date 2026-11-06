"""Build presentation/data.js from the real pipeline outputs.

Run after `python triage.py`:
    python presentation/build_data.py

Reads output/processed_leads.csv, data/*.csv and output/ai_classification_*.txt.
Nothing in the presentation is typed by hand: every number comes from these files.
"""

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
SOURCE_CSV = ROOT / "data" / "Savvy_Mock_Lead_Dataset.csv"
PROCESSED_CSV = OUTPUT / "processed_leads.csv"
TARGET = Path(__file__).resolve().parent / "data.js"

# What changed before each saved run (keyed by run time HH-MM).
RUN_NOTES = {
    "20-12": ("Sprint 2 · v1", "First AI classification: intent, priority, rationale."),
    "20-19": ("Sprint 2 · v1", "Re-run before the new prompt was saved. Same results."),
    "20-20": ("Sprint 2 · v2", "Stricter priority rules, confidence score, human-review rules. Data_Notes removed from the payload."),
    "20-23": ("Sprint 2 · v3", "Duplicates copy their primary. Missing email or budget no longer means low intent."),
    "20-28": ("Sprint 2 · v4", "Next action and draft follow-up added. Token usage logged."),
    "20-31": ("Sprint 2 · v5", "Bug fix: contact channel computed in code instead of guessed by the AI."),
    "20-38": ("Sprint 3 · final", "Unclear intent forced to Low in code. Missing contact sent to the AI."),
}

LINE_RE = re.compile(r"^(SAV-\d+): (.*)$")


def parse_run(path):
    """Parse one ai_classification_*.txt log into {lead_id: result}."""
    leads, current = {}, None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        match = LINE_RE.match(line)
        if match:
            lead_id, rest = match.groups()
            current = {"id": lead_id, "duplicate": False, "review": None,
                       "confidence": None, "next": "", "draft": ""}
            if rest.startswith("skipped"):
                current["duplicate"] = True
            else:
                parts = [p.strip() for p in rest.split(" | ")]
                current["intent"], current["priority"] = parts[0], parts[1]
                for part in parts[2:]:
                    if re.fullmatch(r"\d\.\d+", part):
                        current["confidence"] = float(part)
                    elif part.startswith("review="):
                        current["review"] = part == "review=true"
                    elif part.startswith("copied from"):
                        current["duplicate"] = True
                    elif not part.startswith("tokens="):
                        current["rationale"] = part
            leads[lead_id] = current
        elif current and line.startswith("Next:"):
            current["next"] = line[5:].strip()
        elif current and line.startswith("Draft:"):
            current["draft"] = line[6:].strip()
    return leads


def build_runs():
    runs = []
    for path in sorted(OUTPUT.glob("ai_classification_*.txt")):
        stamp = path.stem.replace("ai_classification_", "")
        hhmm = stamp[-5:]
        leads = parse_run(path)
        unique = [l for l in leads.values() if not l["duplicate"]]
        sprint, note = RUN_NOTES.get(hhmm, ("Reproduction", "Re-run of the final pipeline from reproduce.ipynb."))
        runs.append({
            "file": path.name,
            "time": hhmm.replace("-", ":"),
            "sprint": sprint,
            "note": note,
            "high": sum(1 for l in unique if l.get("priority") == "High"),
            "medium": sum(1 for l in unique if l.get("priority") == "Medium"),
            "low": sum(1 for l in unique if l.get("priority") == "Low"),
            "review": sum(1 for l in unique if l.get("review")),
            "drafts": sum(1 for l in unique if l.get("draft")),
            "find_contact": sum(1 for l in unique if l.get("next") == "Find contact info"),
            "leads": leads,
        })
    return runs


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def build_tests(by_id):
    """Same expectations as pipeline/output.py, recomputed from the CSV."""
    def rule_route(row):
        if row["needs_human_review"] == "true" or row["duplicate_of"]:
            return "Human review"
        return row["suggested_team"] or "Human review"

    def check(lead_id, checks):
        return {"id": lead_id,
                "pass": all(actual == expected for _, actual, expected in checks),
                "checks": [{"label": l, "actual": a, "expected": e} for l, a, e in checks]}

    r = by_id
    cases = [
        ("Urgent inquiry", [
            check(i, [("route", r[i]["route"], "Buyer team"), ("priority", r[i]["priority"], "High")])
            for i in ("SAV-1003", "SAV-1020")]),
        ("Missing information", [
            check("SAV-1004", [("email_missing", "email_missing" in r["SAV-1004"]["data_flags"], True),
                               ("route", r["SAV-1004"]["route"], rule_route(r["SAV-1004"]))]),
            check("SAV-1005", [("phone_missing", "phone_missing" in r["SAV-1005"]["data_flags"], True),
                               ("route", r["SAV-1005"]["route"], rule_route(r["SAV-1005"]))])]),
        ("Duplicate records", [
            check("SAV-1001", [("route", r["SAV-1001"]["route"], "Buyer team"),
                               ("duplicate_of", r["SAV-1001"]["duplicate_of"] or "-", "-")]),
            check("SAV-1011", [("route", r["SAV-1011"]["route"], "Human review"),
                               ("duplicate_of", r["SAV-1011"]["duplicate_of"], "SAV-1001")])]),
        ("Ambiguous inquiry", [
            check(i, [("route", r[i]["route"], "Human review"), ("priority", r[i]["priority"], "Low")])
            for i in ("SAV-1014", "SAV-1019")]),
    ]
    return [{"case": name, "results": results} for name, results in cases]


def main():
    processed = read_csv(PROCESSED_CSV)
    source = read_csv(SOURCE_CSV)
    by_id = {row["Lead_ID"]: row for row in processed}

    for row in processed:
        row["confidence"] = float(row["confidence"]) if row["confidence"] else None
        row["tokens_in"] = int(row["tokens_in"]) if row["tokens_in"] else 0
        row["tokens_out"] = int(row["tokens_out"]) if row["tokens_out"] else 0
        row["cost_usd"] = float(row["cost_usd"] or 0)
        # Keep the location for context in the table (no contact details).
        src = next((s for s in source if s["Lead_ID"] == row["Lead_ID"]), {})
        row["location"] = src.get("Property_Location", "")
        row["source"] = src.get("Lead_Source", "")
        row["notes"] = src.get("Inquiry_Notes", "")
        row["timeline"] = src.get("Purchase_or_Action_Timeline", "")

    ai_rows = [r for r in processed if r["tokens_in"]]
    data = {
        "summary": {
            "leads": len(processed),
            "ai_calls": len(ai_rows),
            "high": sum(1 for r in processed if r["priority"] == "High" and not r["duplicate_of"]),
            "human_review": sum(1 for r in processed if r["route"] == "Human review"),
            "duplicates": sum(1 for r in processed if r["duplicate_of"]),
            "tokens_in": sum(r["tokens_in"] for r in processed),
            "tokens_out": sum(r["tokens_out"] for r in processed),
            "cost": round(sum(r["cost_usd"] for r in processed), 6),
            "cost_per_lead": round(sum(r["cost_usd"] for r in ai_rows) / max(len(ai_rows), 1), 7),
            "routes": {},
            "sources": {},
            "missing_contact": sum(1 for r in processed if "email_missing" in r["data_flags"] or "phone_missing" in r["data_flags"]),
            "unclear_type": sum(1 for r in processed if "lead_type_unclear" in r["data_flags"]),
        },
        "leads": processed,
        "tests": build_tests(by_id),
        "runs": build_runs(),
    }
    for r in processed:
        data["summary"]["routes"][r["route"]] = data["summary"]["routes"].get(r["route"], 0) + 1
    for s in source:
        data["summary"]["sources"][s["Lead_Source"]] = data["summary"]["sources"].get(s["Lead_Source"], 0) + 1

    TARGET.write_text("window.TRIAGE_DATA = " + json.dumps(data, indent=1) + ";\n", encoding="utf-8")
    print(f"Wrote {TARGET.relative_to(ROOT)}: {len(processed)} leads, {len(data['runs'])} runs")


if __name__ == "__main__":
    main()
