"""Step 4: connect to OpenAI and classify leads."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from openai import APIError, OpenAI
from pydantic import BaseModel, Field, ValidationError


BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
MODEL = "gpt-4o-mini"
LOW_CONFIDENCE = 0.7

# Do not send name, contact, IDs, or Data_Notes
PAYLOAD_FIELDS = (
    "Lead_Source",
    "Lead_Type",
    "Property_Location",
    "Budget_USD_Normalized",
    "Purchase_or_Action_Timeline",
    "Timeline_Days",
    "Inquiry_Notes",
    "Current_Status",
    "Data_Flags",
)

SYSTEM_PROMPT = """You triage incoming leads for Savvy, a short-term rental real estate company.
Return JSON only with these keys:
- intent: Buyer | Seller | Property Management | Unclear
- priority: High | Medium | Low
- rationale: 1-2 sentences
- confidence: number from 0.0 to 1.0
- risk_or_contradiction: true if the notes show a risk or contradiction
  (for example already under contract elsewhere)
- next_action: one concrete step
- draft_followup: 2-3 sentences. This is a draft only, not a sent message.
  Use contact_channel: "email" means write an email, "text" means write a text.
  Never ask for contact info the lead already gave; only ask for missing_contact.
  If missing_contact is none, do not ask for an email or a phone.
  Ask for other missing info. Do not ask Property Management leads for a budget.
  Do not promise returns, occupancy, or income.

Use notes, timeline, budget, lead type, and source. If intent is ambiguous, use Unclear.

Priority:
- High: ASAP or 7 days or less, financing or proof of funds ready,
  wants a tour or call this week, or an urgent sale (relocation).
- Medium: clear intent and a 30-90 day timeline.
- Low: 6+ months, researching, unknown timeline, or unclear intent.

Missing email or budget is not low intent. Missing budget is normal for Property Management.
Confidence should be lower when data is missing or intent is thin.
"""


class LeadAIResult(BaseModel):
    intent: Literal["Buyer", "Seller", "Property Management", "Unclear"]
    priority: Literal["High", "Medium", "Low"]
    rationale: str
    confidence: float = Field(ge=0, le=1)
    risk_or_contradiction: bool
    next_action: str
    draft_followup: str


def get_openai_client():
    """Read the key from .env. Do not print the value."""
    load_dotenv(BASE_DIR / ".env")
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("OPENAI_API_KEY is missing. Add it to the .env file to classify leads.")
        return None
    return OpenAI(api_key=api_key)


def contact_channel(row):
    """email if there is an email, text if only a phone, none if both are missing."""
    if row.get("Email_Normalized"):
        return "email"
    if row.get("Phone_Normalized"):
        return "text"
    return "none"


def missing_contact(row):
    """The one contact field still missing: email, phone, or none."""
    if not row.get("Email_Normalized"):
        return "email"
    if not row.get("Phone_Normalized"):
        return "phone"
    return "none"


def lead_payload_for_ai(row):
    """Build the payload without name, contact, IDs, or Data_Notes."""
    payload = {key: row.get(key) for key in PAYLOAD_FIELDS}
    flags = [
        item
        for item in (payload.get("Data_Flags") or "").split(";")
        if item and item not in {"email_missing", "phone_missing"}
    ]
    payload["Data_Flags"] = ";".join(flags)
    payload["contact_channel"] = contact_channel(row)
    payload["missing_contact"] = missing_contact(row)
    return payload


def both_contacts_missing(row):
    return contact_channel(row) == "none"


def needs_human_review(row, result):
    """OR the review rules after the model responds."""
    flags = {
        item for item in (row.get("Data_Flags") or "").split(";") if item
    }
    return (
        result.intent == "Unclear"
        or "lead_type_unclear" in flags
        or bool(row.get("possible_duplicate_of"))
        or both_contacts_missing(row)
        or result.confidence < LOW_CONFIDENCE
        or result.risk_or_contradiction
    )


def classify_one_lead(client, row):
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(lead_payload_for_ai(row), default=str),
            },
        ],
    )
    result = LeadAIResult.model_validate_json(response.choices[0].message.content)
    usage = response.usage
    tokens_in = usage.prompt_tokens if usage else 0
    tokens_out = usage.completion_tokens if usage else 0
    return result, tokens_in, tokens_out


def classify_leads_with_ai(leads):
    """Classify non-duplicates. Duplicates copy intent, priority, and confidence."""
    client = get_openai_client()
    if client is None:
        return leads

    run_at = datetime.now()
    lines = []
    by_id = {row["Lead_ID"]: row for row in leads}

    def emit(text):
        print(text)
        lines.append(text)

    emit("\nAI classification")
    emit("-" * 100)

    for row in leads:
        row["ai_intent"] = ""
        row["ai_priority"] = ""
        row["ai_rationale"] = ""
        row["ai_confidence"] = ""
        row["ai_needs_human_review"] = ""
        row["ai_next_action"] = ""
        row["ai_draft_followup"] = ""
        row["ai_tokens_in"] = ""
        row["ai_tokens_out"] = ""

        if row.get("duplicate_of"):
            primary = by_id.get(row["duplicate_of"])
            primary_id = row["duplicate_of"]
            row["ai_next_action"] = (
                f"No follow-up, duplicate of {primary_id}. Confirm in CRM."
            )
            if primary and primary.get("ai_intent"):
                row["ai_intent"] = primary["ai_intent"]
                row["ai_priority"] = primary["ai_priority"]
                row["ai_confidence"] = primary["ai_confidence"]
                emit(
                    f"{row['Lead_ID']}: {row['ai_intent']} | {row['ai_priority']} | "
                    f"{row['ai_confidence']:.2f} | copied from {primary_id} | "
                    f"tokens=n/a"
                )
            else:
                emit(
                    f"{row['Lead_ID']}: could not copy classification from "
                    f"{primary_id} | tokens=n/a"
                )
            emit(f"Next: {row['ai_next_action']}")
            continue

        try:
            result, tokens_in, tokens_out = classify_one_lead(client, row)
        except (ValidationError, json.JSONDecodeError, APIError) as exc:
            emit(f"{row['Lead_ID']}: classification error ({exc})")
            continue

        if result.intent == "Unclear":
            result.priority = "Low"

        review = needs_human_review(row, result)
        next_action = result.next_action
        draft = result.draft_followup
        if both_contacts_missing(row):
            next_action = "Find contact info"
            draft = ""

        row["ai_intent"] = result.intent
        row["ai_priority"] = result.priority
        row["ai_rationale"] = result.rationale
        row["ai_confidence"] = result.confidence
        row["ai_needs_human_review"] = review
        row["ai_next_action"] = next_action
        row["ai_draft_followup"] = draft
        row["ai_tokens_in"] = tokens_in
        row["ai_tokens_out"] = tokens_out
        emit(
            f"{row['Lead_ID']}: {result.intent} | {result.priority} | "
            f"{result.confidence:.2f} | review={str(review).lower()} | "
            f"tokens={tokens_in}/{tokens_out} | {result.rationale}"
        )
        emit(f"Next: {next_action}")
        if draft:
            emit(f"Draft: {draft}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / f"ai_classification_{run_at:%Y-%m-%d_%H-%M}.txt"
    header = (
        f"Model: {MODEL}\n"
        f"Run date: {run_at:%Y-%m-%d %H:%M:%S}\n"
    )
    output_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved to {output_path.relative_to(BASE_DIR)}")

    return leads
