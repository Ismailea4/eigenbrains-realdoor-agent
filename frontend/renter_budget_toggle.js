/** Renter-controlled toggle for the optional budgeting stage. */

let nextControlId = 1;

export function withRenterBudgetPreference(payload, enabled) {
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    throw new TypeError("payload must be an object");
  }
  return { ...payload, include_renter_budget: Boolean(enabled) };
}

export async function checkRenterBudgetAvailability({
  baseUrl = "",
  fetchImpl = globalThis.fetch,
} = {}) {
  if (typeof fetchImpl !== "function") {
    throw new TypeError("A fetch implementation is required");
  }
  const response = await fetchImpl(`${baseUrl}/renter-budget/policy`, {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  if (response.status === 404) {
    return false;
  }
  if (!response.ok) {
    throw new Error(`Unable to read renter-budget capability (${response.status})`);
  }
  return true;
}

export function mountRenterBudgetToggle(
  container,
  { available = true, initialEnabled = false, onChange = () => {} } = {},
) {
  if (!(container instanceof Element)) {
    throw new TypeError("container must be a DOM Element");
  }
  if (typeof onChange !== "function") {
    throw new TypeError("onChange must be a function");
  }

  const controlId = `renter-budget-status-${nextControlId++}`;
  let isAvailable = Boolean(available);
  let enabled = isAvailable && Boolean(initialEnabled);

  const wrapper = document.createElement("section");
  wrapper.className = "renter-budget-control";
  wrapper.setAttribute("aria-labelledby", `${controlId}-label`);

  const copy = document.createElement("div");
  copy.className = "renter-budget-control__copy";

  const label = document.createElement("h3");
  label.id = `${controlId}-label`;
  label.className = "renter-budget-control__label";
  label.textContent = "Optional renter budgeting";

  const description = document.createElement("p");
  description.className = "renter-budget-control__description";
  description.textContent =
    "Show transparent renter-only calculations. This never affects eligibility or approval.";

  const status = document.createElement("p");
  status.id = controlId;
  status.className = "renter-budget-control__status";
  status.setAttribute("aria-live", "polite");

  const button = document.createElement("button");
  button.type = "button";
  button.className = "renter-budget-toggle";
  button.setAttribute("role", "switch");
  button.setAttribute("aria-describedby", controlId);

  const stateText = document.createElement("span");
  stateText.className = "renter-budget-toggle__state";
  button.append(stateText);

  function render() {
    button.disabled = !isAvailable;
    button.setAttribute("aria-checked", String(enabled));
    button.setAttribute("aria-disabled", String(!isAvailable));
    button.classList.toggle("is-enabled", enabled);
    stateText.textContent = enabled ? "On" : "Off";
    status.textContent = !isAvailable
      ? "Renter budgeting is disabled by the server administrator."
      : enabled
        ? "Renter budgeting will be included in evaluation and export."
        : "Renter budgeting will not be calculated or exported.";
  }

  function setEnabled(nextEnabled, { notify = true } = {}) {
    const next = isAvailable && Boolean(nextEnabled);
    if (next === enabled) {
      render();
      return;
    }
    enabled = next;
    render();
    if (notify) {
      onChange(enabled);
    }
  }

  button.addEventListener("click", () => setEnabled(!enabled));
  copy.append(label, description, status);
  wrapper.append(copy, button);
  container.replaceChildren(wrapper);
  render();

  return {
    element: wrapper,
    isEnabled: () => enabled,
    setEnabled,
    setAvailable(nextAvailable) {
      isAvailable = Boolean(nextAvailable);
      if (!isAvailable) {
        enabled = false;
      }
      render();
    },
    applyToPayload(payload) {
      return withRenterBudgetPreference(payload, enabled);
    },
    destroy() {
      wrapper.remove();
    },
  };
}

