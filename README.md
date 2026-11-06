# Savvy lead triage

Loads 20 mock short-term rental leads, checks email, phone, budget, and timeline, links duplicates, and asks `gpt-4o-mini` for intent, priority, a next step, and a draft follow-up. Leads are then routed to a team or to human review. Results go to `output/`.

**Presentation:** https://main.d2rlekfkelg009.amplifyapp.com, hosted on AWS Amplify. To republish after a new run: `./deploy_presentation.sh`

## Quickest way: the notebook

Open [`reproduce.ipynb`](reproduce.ipynb) locally or in Google Colab and run the cells top to bottom. It installs the dependencies, downloads the CSV from a public, read-only Amazon S3 object (no manual upload; it falls back to the GitHub copy), asks for an OpenAI key in a hidden prompt, and runs every step with its output. The key is never printed or saved. A full run costs well under one cent.

[Open in Colab](https://colab.research.google.com/github/carlicode/Savvy_Practical_Assesment/blob/main/reproduce.ipynb)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Put your OpenAI key in `.env` as `OPENAI_API_KEY=...`.

## Run

```bash
python triage.py
```

Each run writes `output/ai_classification_YYYY-MM-DD_HH-MM.txt` and overwrites `output/processed_leads.csv`.

## Project structure

```
triage.py              CSV path and the step order
pipeline/data.py       load, normalize, quality flags
pipeline/duplicates.py duplicate detection
pipeline/ai.py         OpenAI classification
pipeline/output.py     routing, cost, CSV export
data/                  source CSV
output/                classification text and processed_leads.csv
```

## Design decisions

Validation, timeline in days, duplicate matching, contact channel, and routing are rules in code. The model only judges intent, priority, confidence, the next step, and the draft.

A duplicate stays in the file. It is linked with `duplicate_of` to the first matching lead and is not merged or deleted.

The model never receives a name, email, phone, lead ID, or `Data_Notes`. It receives `contact_channel` (`email`, `text`, or `none`) and `missing_contact` (`email`, `phone`, or `none`).

Human review is required when intent is unclear, the lead type is Other or Unknown, the lead is a possible duplicate, both contacts are missing, confidence is below 0.7, or the notes show a risk or contradiction. The route is also Human review for a confirmed duplicate or a failed AI call. `suggested_team` still shows where to send the lead after review.

## Cost of this run

The run on 2026-11-05 at 20:38 classified 19 leads with `gpt-4o-mini` (8,495 input tokens and 2,734 output tokens). At $0.15 per 1M input tokens and $0.60 per 1M output tokens, the total was **$0.002915**. The duplicate was not sent to the API, so its cost is $0.

## Limitation and next step

Priority from the model changes between runs for the same lead. The next step is to set priority from the timeline in code, and let the model keep intent and the draft.
