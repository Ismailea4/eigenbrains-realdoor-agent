"""Review extracted documents against a rules list using an LLM."""
from __future__ import annotations

from tavily import TavilyClient
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


def build_prompt(rules, summary, tavily_results):

    rules_text = []

    for rule in rules:
        rules_text.append(
            f"- {rule['title']} (page {rule['page']}): {rule['rule']}"
        )

    return f"""
You are a legal compliance assistant.

You must use BOTH:

1. Internal Rules
2. Web references from Tavily.

If the web references contradict the internal rules,
mention the contradiction.

Every conclusion MUST cite one or more Source numbers.

------------------------
INTERNAL RULES
------------------------

{chr(10).join(rules_text)}

------------------------
WEB REFERENCES
------------------------

{tavily_results}

------------------------
DOCUMENT
------------------------

{summary}

Return ONLY valid JSON.

{{
  "potential_issues":[
      {{
         "issue":"...",
         "severity":"Low|Medium|High",
         "sources":[1,3]
      }}
  ],

  "relevant_rules":[
      {{
          "title":"...",
          "page":4
      }}
  ],

  "references":[
      {{
          "source":1,
          "title":"...",
          "url":"..."
      }}
  ],

  "explanation":"..."
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

# ----------------------------------------------------------------------
def search_rental_laws(doc: Dict[str, Any], max_results: int = 5) -> str:
    """
    Search the web for applicable US rental regulations
    using Tavily and return formatted sources.
    """

    api_key = os.getenv("TAVILY_API_KEY")

    if not api_key:
        raise RuntimeError("TAVILY_API_KEY not found in .env")

    client = TavilyClient(api_key=api_key)

    document_type = doc.get("document_type", "")
    structured = doc.get("structured_data", {})

    fields = []

    for field, info in structured.items():
        if isinstance(info, dict):
            value = info.get("value")
            if value:
                fields.append(f"{field}: {value}")

    query = f"""
        US residential rental law compliance.

        Document type:
        {document_type}

        Extracted information:
        {'; '.join(fields)}

        Find the relevant federal or state landlord-tenant laws,
        HUD guidance, lease requirements, tenant rights,
        security deposits, signatures,
        required disclosures and compliance.
        """
    query = summarize_for_tavily(doc)

    print("\nTavily query:")
    print(query)
    print(f"Length: {len(query)} characters\n")

    response = client.search(
        query=query,
        search_depth="advanced",
        topic="general",
        max_results=max_results,
    )

    lines = []

    for i, result in enumerate(response.get("results", []), start=1):
        lines.append(
            f"""
Source {i}

Title:
{result.get("title")}

URL:
{result.get("url")}

Content:
{result.get("content")}
"""
        )

    return "\n".join(lines)



# --------------------
# Tavily
# --------------------

def summarize_for_tavily(doc: Dict[str, Any], model: str | None = None) -> str:
    """
    Convert the extracted document into a concise search query
    suitable for Tavily (max 350 characters).
    """

    model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    summary = summarize_extraction(doc)

    prompt = f"""
You are preparing a search query for a legal search engine.

Below is an extracted rental-related document.

Create ONE concise search query.

Requirements:
- Maximum 350 characters.
- Keep only information useful for identifying applicable US landlord-tenant laws.
- Include state if mentioned.
- Include lease type if mentioned.
- Include relevant legal topics:
  security deposit,
  disclosures,
  landlord,
  tenant,
  eviction,
  rent,
  signatures,
  lease,
  utilities,
  late fees,
  notice,
  habitability,
  pets,
  etc.
- Do NOT explain.
- Output ONLY the search query.

DOCUMENT

{summary}
"""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You create concise search engine queries."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0,
        max_tokens=120,
    )

    query = response.choices[0].message.content.strip()

    # Safety
    return query[:350]


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

        summary = summarize_extraction(doc)

        tavily_results = search_rental_laws(doc)

        prompt = build_prompt(
            rules,
            summary,
            tavily_results,
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