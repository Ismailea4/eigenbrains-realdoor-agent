"""Pure deterministic money calculations for the frozen RealDoor simulation.

This module deliberately has no model, network, storage, or eligibility logic.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from ..schemas.calculator import Comparison


CENT = Decimal("0.01")
ANNUAL_PERIODS: dict[str, int] = {
    "weekly": 52,
    "biweekly": 26,
    "semimonthly": 24,
    "monthly": 12,
    "annual": 1,
}


class CalculationInputError(ValueError):
    """Raised when a deterministic calculation cannot be performed safely."""


def money(value: Decimal | str | int) -> Decimal:
    """Normalize a non-negative monetary value to cents using half-up rounding."""

    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CalculationInputError("Amount must be a finite decimal value") from exc
    if not normalized.is_finite() or normalized < 0:
        raise CalculationInputError("Amount must be finite and non-negative")
    return normalized.quantize(CENT, rounding=ROUND_HALF_UP)


def normalize_frequency(frequency: str) -> str:
    normalized = frequency.strip().lower()
    if normalized not in ANNUAL_PERIODS:
        raise CalculationInputError(f"Unsupported frequency: {frequency}")
    return normalized


def annualize(amount: Decimal | str | int, frequency: str) -> tuple[Decimal, int]:
    """Return exact annualized dollars and the explicit periods-per-year factor."""

    normalized_frequency = normalize_frequency(frequency)
    periods = ANNUAL_PERIODS[normalized_frequency]
    annualized = (money(amount) * Decimal(periods)).quantize(CENT, rounding=ROUND_HALF_UP)
    return annualized, periods


def sum_money(values: list[Decimal]) -> Decimal:
    return sum(values, start=Decimal("0.00")).quantize(CENT, rounding=ROUND_HALF_UP)


def compare_to_threshold(annualized_income: Decimal, threshold: Decimal) -> Comparison:
    annualized = money(annualized_income)
    frozen_threshold = money(threshold)
    if annualized <= frozen_threshold:
        return Comparison.BELOW_OR_EQUAL
    return Comparison.ABOVE


def format_money(value: Decimal) -> str:
    return f"${money(value):,.2f}"
