<div align="center">
  <!-- Replace with your actual logo path -->
  <img src="logo.png" alt="TranspaRent Logo: A sleek geometric open door intersecting with a structured document" width="250"/>
  
  
  **Unlocking affordable housing with clear data, not black-box decisions.**
  
  *Built by Team EigenBrains for the 6th Global AI Hack-Nation*  
  *Challenge 03 (Powered by RealPage)*
</div>

**Transparent Financial Readiness:** RealDoor transforms fragmented synthetic
rental documents into an evidence-linked financial-readiness profile that
describes affordability, income stability, accessible liquidity, downside
scenarios, and cross-document consistency. Every metric exposes its formula,
inputs, source evidence, policy threshold, and uncertainty; the system produces
no aggregate applicant score or housing decision.

---

## 🎯 Mission Overview
Navigating affordable housing applications shouldn't require a law degree. A single paperwork error can delay a family's move for weeks. **TranspaRent** is an assistive, AI-powered application-readiness copilot that helps applicants securely extract document data and navigate complex program rules with total clarity. 

**Strict System Boundary:** This system is strictly designed for application-readiness tooling[cite: 4]. It absolutely does **not** determine eligibility, approval, denial, priority, or current property availability[cite: 4]. Our focus is solely on evidence extraction, deterministic calculation, threshold comparison, document readiness, and human-review handoff[cite: 4].

---

## 📦 Challenge Data & Environment
This prototype operates on the source-backed, frozen challenge simulation for the Boston-Cambridge-Quincy, MA-NH HUD Metro FMR Area[cite: 4]. 

Our system validates against the official organizer inventory:
*   **Income Thresholds:** FY 2026 50% context and 60% scored MTSP limits for household sizes 1-8[cite: 4]. *(HUD FY 2026 MTSP effective date: 2026-05-01)*[cite: 4].
*   **Property Context:** 32 public HUD LIHTC project records[cite: 4]. *(ArcGIS layer retrieved: 2026-07-18)*[cite: 4].
*   **Synthetic Input:** 24 synthetic one-page PDF documents spanning 6 fictional households[cite: 4].
*   **Validation:** 36 gold Q&A records and 24 adversarial tests to guarantee safety and accuracy[cite: 4].

---

## ⚙️ Core Architecture (The 3-Stage Flow)

### 1. Profile: Human-Confirmed Extraction
*   **Secure OCR Pipeline:** Extracts allowlisted fields from synthetic household documents.
*   **Evidence Mapping:** Displays precise page-level PDF-point source boxes to prove where data originated[cite: 4].
*   **Renter Control:** Requires human confirmation or correction before downstream reuse.

### 2. Understand: Cited Rules & Deterministic Math
*   **Knowledge Retrieval:** Queries the frozen 2026 MTSP limits and official rule corpus to provide authoritative citations.
*   **Deterministic Calculations:** Uses hard-coded Python logic to calculate thresholds based strictly on confirmed inputs.
*   **Uncertainty Handling:** Automatically abstains and explicitly flags uncertainty when rules or inputs are unclear.

### 3. Prepare: Renter-Controlled Packet
*   **Gap Analysis:** Cross-references uploaded documents against the gold standard checklist.
*   **Secure Export:** Generates an editable, downloadable application-readiness packet.
*   **Ephemeral State:** Features a strict "Delete Session" protocol to instantly wipe all local memory and uploaded data.

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
*   **Frontend (UI/UX):** React (via Lovable) / TanStack – *WCAG 2.2 AA Compliant*
*   **Backend API:** FastAPI (Python) with strict Pydantic v2 validation
*   **Intelligence Layer:** OpenAI API (Strictly constrained for structured data extraction and rule retrieval)
*   **Testing:** Standard-library Python testing framework (`unittest`)[cite: 4]

---

## 🔒 Safety & Privacy Features
*   **Adversarial Resistance:** Tested against 24 adversarial prompts to ensure the system safely deflects "Am I eligible?" queries[cite: 4].
*   **Zero Retention:** Uploads are not used for training; local sessions are fully ephemeral. No real applicant data or real private documents are included in this simulation[cite: 4].
*   **No Hidden Proxies:** Zero inference of protected traits or demographic features.

---

## 🚀 Quick Start (Local Development)

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/Ismailea4/eigenbrains-realdoor-agent.git](https://github.com/Ismailea4/eigenbrains-realdoor-agent.git)
   cd eigenbrains-realdoor-agent
   ```

2. **Set up the virtual environment & install dependencies:**
```bash
python -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt

```


3. **Run the organizer-provided tests:**
```bash
cd backend/starter
python -m unittest discover -s tests -v

```


4. **Launch the FastAPI backend:**
```bash
uvicorn app.main:app --reload

```


5. **Launch the Lovable frontend:**
```bash
cd ../frontend
npm install
npm run dev

```


## 🏗️ Architecture & Constraints

- **Strict Type Safety:** Pydantic v2 models are enforced for all payloads.
- **Stateless:** Ephemeral processing with isolated user sessions.
- **No Decisioning:** The engine only provides application readiness assistance, never final eligibility logic.
- **Deterministic Math:** Pure Python calculations are used for financial validations.
