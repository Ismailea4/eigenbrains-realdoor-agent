"""Review extracted documents against a rules list using an LLM."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


# ----------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent

# Load backend/tools/.env
load_dotenv(dotenv_path=SCRIPT_DIR / ".env", override=True)

EXTRACTION_DIR = SCRIPT_DIR / "extraction_results"
RULES_PATH = SCRIPT_DIR / "references" / "rules.json"
OUTPUT_PATH = EXTRACTION_DIR / "review_reports.json"


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def load_rules(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_extraction_results(directory: Path) -> List[Dict[str, Any]]:
    docs = []

    for file in sorted(directory.glob("*_result.json")):
        try:
            with file.open("r", encoding="utf-8") as f:
                docs.append(json.load(f))
        except Exception as e:
            print(f"Skipping {file.name}: {e}")

    return docs


def summarize_extraction(doc: Dict[str, Any]) -> str:
    lines = []

    lines.append(f"Document ID: {doc.get('document_id')}")
    lines.append(f"Document type: {doc.get('document_type')}")
    lines.append("Extracted fields:")

    structured = doc.get("structured_data", {})

    for field, info in structured.items():
        if not isinstance(info, dict):
            continue

        value = info.get("value")
        confidence = info.get("confidence")
        evidence = info.get("evidence")

        lines.append(
            f"- {field}: {value} (confidence={confidence})"
        )

        if evidence:
            lines.append(
                f"  page={evidence.get('page')}, "
                f"bbox={evidence.get('bbox')}, "
                f"text={repr(evidence.get('text'))}"
            )

    return "\n".join(lines)


def build_prompt(rules, summary):

    rules_text = []

    for rule in rules:
        rules_text.append(
            f"- {rule.get('title')} (page {rule.get('page')}): "
            f"{rule.get('rule')}"
        )

    return f"""
You are a rules compliance assistant.

RULES

{chr(10).join(rules_text)}

DOCUMENT

{summary}

Return ONLY valid JSON of the form:

{{
  "potential_issues": [...],
  "relevant_rules": [
      {{
         "title": "...",
         "page": ...
      }}
  ],
  "explanation": "..."
}}
"""


# ----------------------------------------------------------------------
# OpenAI
# ----------------------------------------------------------------------

def call_llm(prompt: str, model: str | None = None) -> str:

    if OpenAI is None:
        raise RuntimeError(
            "Install the OpenAI package:\n\npip install -U openai"
        )

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY not found in backend/tools/.env"
        )

    model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a careful rules compliance assistant."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.2,
        max_tokens=1000,
    )

    return response.choices[0].message.content


# ----------------------------------------------------------------------
# Checks
# ----------------------------------------------------------------------

def check_paths():

    missing = []

    if not RULES_PATH.exists():
        missing.append(RULES_PATH)

    if not EXTRACTION_DIR.exists():
        missing.append(EXTRACTION_DIR)

    if missing:

        print("Missing:")

        for p in missing:
            print(" -", p)

        return False

    return True


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():

    if not check_paths():
        return

    rules = load_rules(RULES_PATH)

    docs = load_extraction_results(EXTRACTION_DIR)

    if not docs:
        print("No extraction files found.")
        return

    reports = []

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    for doc in docs:

        print(f"Processing {doc.get('document_id')}...")

        prompt = build_prompt(
            rules,
            summarize_extraction(doc),
        )

        try:
            result = call_llm(prompt, model)

        except Exception as e:
            result = f"LLM call failed: {e}"

        reports.append(
            {
                "document_id": doc.get("document_id"),
                "document_type": doc.get("document_type"),
                "llm_raw": result,
            }
        )

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(
            reports,
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(f"Saved {len(reports)} reports to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()