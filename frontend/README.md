# Frontend integration contract

The repository does not contain the Lovable application source. This directory
therefore provides a dependency-free component and the exact API contract the
frontend team can import without changing its framework or build system.

## Optional renter-budget toggle

`renter_budget_toggle.js` exports an accessible enable/disable switch for the
risk-management branch. Its user-facing label is **Optional renter budgeting**
because the feature cannot score, rank, approve, deny, or determine eligibility.

The toggle defaults to off, stores no browser data, and adds one boolean to both
backend requests:

```json
{
  "include_renter_budget": true
}
```

It does not mutate a process-wide backend setting. The server environment flag
`REALDOOR_RENTER_BUDGET_ENABLED` remains an administrator kill switch. When the
kill switch is off, the backend returns a typed `DISABLED` stage.

### Lovable integration

```javascript
import {
  checkRenterBudgetAvailability,
  mountRenterBudgetToggle,
} from "./renter_budget_toggle.js";

const available = await checkRenterBudgetAvailability({
  baseUrl: "http://localhost:8000",
});

const budgetToggle = mountRenterBudgetToggle(
  document.querySelector("#renter-budget-control"),
  { available },
);

const evaluationPayload = budgetToggle.applyToPayload({
  as_of_date: "2026-07-19",
});

await fetch(`/sessions/${sessionId}/evaluate`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(evaluationPayload),
});
```

Use the same `applyToPayload` call for
`POST /sessions/{session_id}/export`. The export payload must also contain
`renter_requested_export: true`.

Open `renter_budget_toggle_demo.html` to inspect the component without a
frontend build. The demo shows the exact evaluation and export JSON that changes
when the button is pressed.

## Complete backend journey

1. `POST /sessions` creates the short-lived session.
2. `POST /sessions/{session_id}/documents` extracts an uploaded synthetic PDF.
3. The frontend displays every proposed value and its evidence box.
4. `POST /sessions/{session_id}/confirm` records explicit consent and each
   `CONFIRM` or `CORRECT` action.
5. `POST /sessions/{session_id}/evaluate` receives `as_of_date` and the toggle's
   `include_renter_budget` value.
6. `POST /sessions/{session_id}/export` runs only after an explicit renter export
   action and receives the same toggle value.
7. `DELETE /sessions/{session_id}` immediately removes ephemeral state.

The frontend must never infer an applicant outcome, silently enable budgeting,
auto-submit a packet, or hide missing/expired/uncertain evidence.

## Accessibility behavior

- Native `<button>` keyboard semantics support Enter and Space.
- `role="switch"` and `aria-checked` expose the current state.
- Visible On/Off text means state is not communicated by color alone.
- The control meets a 44-pixel minimum target and has a visible focus ring.
- An `aria-live` status explains administrator-disabled and user-enabled states.

## Verification

```powershell
node --check frontend\renter_budget_toggle.js
```
