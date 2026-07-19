# 🚪 RealDoor Application-Readiness Copilot

**Built by Team EigenBrains for HackNation 6th Edition**
**Challenge 03 (Powered by RealPage)**

## 🎯 Mission Overview

Navigating affordable housing applications is complex, and a single paperwork error can delay a family's move for weeks. Our solution is a renter-side copilot that turns synthetic household documents into a human-confirmed profile, maps clear rule citations, and generates a renter-controlled application-readiness packet.

**Core Constraint Met:** This system is strictly assistive. It does **not** make eligibility decisions, approve, deny, or rank applicants. Final decisions remain securely in the hands of qualified human reviewers.

---

## ⚙️ Core Architecture & Pipeline

Our three-stage pipeline focuses on extraction accuracy, deterministic math, and strict data privacy.

### 1. Profile: Human-Confirmed Extraction

* **Secure OCR Pipeline:** Extracts only allowlisted fields from synthetic household documents (pay stubs, benefit letters).
* **Evidence Mapping:** Displays precise source bounding boxes and calibrated confidence scores.
* **Renter Control:** Requires human confirmation or correction before downstream reuse.

### 2. Understand: Cited Rules & Deterministic Math

* **Knowledge Retrieval:** Queries the frozen 2026 MTSP limits and official rule corpus to provide authoritative citations.
* **Deterministic Calculations:** Uses hard-coded Python logic (not LLM generation) to calculate thresholds and effective dates based on confirmed inputs.
* **Uncertainty Handling:** Automatically abstains and explicitly flags uncertainty when rules or inputs are unclear.

### 3. Prepare: Renter-Controlled Packet

* **Gap Analysis:** Cross-references uploaded documents against the gold standard checklist to flag missing or expired items.
* **Secure Export:** Generates an editable, downloadable application-readiness packet.
* **Ephemeral State:** Features a strict "Delete Session" protocol to instantly wipe all local memory and uploaded data.

---

## 📂 Repository Structure

```text
realdoor-readiness-copilot/
├── frontend/                  # 🎨 OWNED BY THE FRONTEND TEAM (LOVABLE GENERATED)
├── backend/                   # ⚙️ OWNED BY THE BACKEND TEAM
│   ├── app/
│   │   ├── schemas/           # Pydantic models for strict type & validation enforcement
│   │   ├── services/          # Core algorithmic logic (Isolated by engineer domain)
│   │   └── core/              # Configuration and security logic
│   └── requirements.txt       # Backend dependencies
├── data/                      # 📦 ORGANIZER PACK STORAGE
│   ├── rule_corpus/           # Frozen 2026 MTSP tables and guidelines
│   └── synthetic_docs/        # Evaluation PDFs/images provided by organizers
├── .env.example               # Template for environment variables
├── .gitignore
└── README.md
```

---

## 🛠️ Technology Stack

* **Frontend / UI:** [Insert Framework, e.g., Lovable / Next.js / Streamlit] - *WCAG 2.2 AA Compliant*
* **Backend & Data Pipeline:** Python
* **Language Models:** OpenAI API (Strictly prompted for rule retrieval and safe deflections)
* **Document Parsing:** PyMuPDF for grounded text/source geometry, with an
  optional Tesseract OCR adapter for raster-only PDFs. Responses include
  document-specific structured data whose leaves retain confidence and source
  evidence.
* **Backend Runtime:** Python 3.11 (pinned by `.python-version`).

---

## 🔒 Safety & Privacy Features

* **No Decisioning:** Defensive system prompts gracefully deflect "Am I eligible?" queries to the authoritative rule text.
* **Prompt-Injection Resistance:** Strict input sanitization and bounded conversational scopes.
* **Ephemeral App Processing:** The parser processes bytes in memory and does
  not persist uploads. Provider-side retention must be described separately if
  a hosted model is later added.
* **No Hidden Proxies:** Zero inference of protected traits or demographic features.

---

## 🚀 Quick Start (Local Development)

1. **Clone the repository:**

   ```bash
   git clone [https://github.com/Ismailea4/eigenbrains-realdoor-agent.git](https://github.com/Ismailea4/eigenbrains-realdoor-agent.git)
   cd eigenbrains-realdoor-agent
   ```
2. **Set up the virtual environment:**

```bash
C:\Users\PC\AppData\Local\Programs\Python\Python311\python.exe -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. **Install dependencies:**

```bash
python -m pip install -r backend\requirements.txt
```

4. **Configure environment variables:**
   Create a `.env` file in the root directory and add your API keys:

```env
OPENAI_API_KEY=your_api_key_here
```

5. **Run the application:**

Document parser tests can be run before API integration:

```powershell
python -m unittest discover -s backend\tests -v
```

## 🏗️ Architecture & Constraints

- **Strict Type Safety:** Pydantic v2 models are enforced for all payloads.
- **Stateless:** Ephemeral processing with isolated user sessions.
- **No Decisioning:** The engine only provides application readiness assistance, never final eligibility logic.
- **Deterministic Math:** Pure Python calculations are used for financial validations.
