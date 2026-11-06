"""Savvy lead triage: run the pipeline steps in order."""

from pathlib import Path

from pipeline.ai import classify_leads_with_ai
from pipeline.data import load_leads, validate_leads
from pipeline.duplicates import detect_duplicates, print_duplicates
from pipeline.output import export_results

CSV_PATH = Path(__file__).resolve().parent / "data" / "Savvy_Mock_Lead_Dataset.csv"


def main():
    leads = load_leads(CSV_PATH)
    validated = validate_leads(leads)
    validated = detect_duplicates(validated)

    print(f"Leads loaded: {len(validated)}")
    print(f"{'Lead_ID':<10} {'Email':<28} {'Phone':<14} {'Budget':<12} {'Days':<6} Flags")
    print("-" * 100)
    for row in validated:
        budget = row["Budget_USD_Normalized"]
        budget_txt = "" if budget == "" else f"{budget:.0f}"
        days = "" if row["Timeline_Days"] == "" else str(row["Timeline_Days"])
        print(
            f"{row['Lead_ID']:<10} "
            f"{row['Email_Normalized']:<28} "
            f"{row['Phone_Normalized']:<14} "
            f"{budget_txt:<12} "
            f"{days:<6} "
            f"{row['Data_Flags']}"
        )

    print_duplicates(validated)
    classify_leads_with_ai(validated)
    export_results(validated)


if __name__ == "__main__":
    main()
