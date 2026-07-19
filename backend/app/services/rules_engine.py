"""Frozen, citation-grounded rules service for the RealDoor challenge.

The service supports one explicit program, geography, percentage, and rule year.
It never calls a model or the network at runtime and never returns an eligibility
decision. Any uncertainty produces a visible abstention instead of a guess.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, ValidationError

from ..schemas.calculator import (
    Citation,
    Comparison,
    InputCalculationTrace,
    ProgramScope,
    ReviewReason,
    ReviewReasonCode,
    ReviewStatus,
    RuleQuestionIntent,
    RuleQuestionRequest,
    RuleQuestionResponse,
    RulesEvaluationRequest,
    RulesEvaluationResponse,
    ThresholdRow,
)
from .calculator import (
    ANNUAL_PERIODS,
    CalculationInputError,
    annualize,
    compare_to_threshold,
    format_money,
    normalize_frequency,
    sum_money,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST_PATH = REPOSITORY_ROOT / "data" / "rule_corpus" / "manifest.json"

EXPECTED_CORPUS_SHA256 = "4da5bf5d3e6a737627d3d4ece75bbc16617069c25ab23848e2aa222cbc2702af"
EXPECTED_PROGRAM_ID = "LIHTC_MTSP_60"
EXPECTED_RULE_YEAR = 2026
EXPECTED_AREA = "Boston-Cambridge-Quincy, MA-NH HMFA"
EXPECTED_AMI_PERCENTAGE = 60
EXPECTED_EFFECTIVE_DATE = date(2026, 5, 1)

DECISION_BOUNDARY = (
    "This is an application-readiness calculation for human review only. "
    "It does not approve, deny, score, rank, or determine eligibility."
)


class CorpusIntegrityError(RuntimeError):
    """The versioned rule package is missing, changed, or internally inconsistent."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Manifest(_FrozenModel):
    schema_version: str
    corpus_version: str
    frozen_at: date
    runtime_network_access: bool
    corpus_path: str
    corpus_sha256: str
    program_id: str
    program_name: str
    rule_year: int
    area: str
    ami_percentage: int
    threshold_rule_id: str
    effective_date_rule_id: str
    income_rule_id: str
    decision_boundary_rule_id: str


class _RuleRecord(_FrozenModel):
    rule_id: str
    authority: str
    effective_date: date | None
    text: str
    source_url: str
    source_locator: str


class RulesEngine:
    """Load and evaluate the checked-in, frozen RealDoor rule corpus."""

    def __init__(self, manifest_path: str | Path = DEFAULT_MANIFEST_PATH) -> None:
        self.manifest_path = Path(manifest_path).resolve()
        self._manifest = self._load_manifest()
        self._rules = self._load_rules()
        self._thresholds = self._parse_thresholds()
        self._validate_authoritative_rules()
        self._program = self._build_program_scope()

    @property
    def program(self) -> ProgramScope:
        return self._program.model_copy(deep=True)

    def _load_manifest(self) -> _Manifest:
        try:
            raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            manifest = _Manifest.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise CorpusIntegrityError("Frozen rule manifest is unreadable or invalid") from exc

        expected_fields = {
            "program_id": EXPECTED_PROGRAM_ID,
            "rule_year": EXPECTED_RULE_YEAR,
            "area": EXPECTED_AREA,
            "ami_percentage": EXPECTED_AMI_PERCENTAGE,
            "corpus_sha256": EXPECTED_CORPUS_SHA256,
            "runtime_network_access": False,
        }
        for field_name, expected in expected_fields.items():
            if getattr(manifest, field_name) != expected:
                raise CorpusIntegrityError(
                    f"Frozen manifest field {field_name!r} does not match the audited value"
                )
        return manifest

    def _load_rules(self) -> dict[str, _RuleRecord]:
        corpus_path = (self.manifest_path.parent / self._manifest.corpus_path).resolve()
        if not corpus_path.is_relative_to(REPOSITORY_ROOT):
            raise CorpusIntegrityError("Frozen corpus path escapes the repository")
        try:
            corpus_bytes = corpus_path.read_bytes()
        except OSError as exc:
            raise CorpusIntegrityError("Frozen rule corpus is unavailable") from exc

        actual_hash = hashlib.sha256(corpus_bytes).hexdigest()
        if actual_hash != EXPECTED_CORPUS_SHA256:
            raise CorpusIntegrityError("Frozen rule corpus checksum mismatch")

        records: dict[str, _RuleRecord] = {}
        line_number = 0
        try:
            for line_number, line in enumerate(corpus_bytes.decode("utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                record = _RuleRecord.model_validate(json.loads(line))
                if record.rule_id in records:
                    raise CorpusIntegrityError(f"Duplicate rule_id {record.rule_id!r}")
                records[record.rule_id] = record
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
            raise CorpusIntegrityError(
                f"Frozen rule corpus contains an invalid record near line {line_number}"
            ) from exc

        required_ids = {
            self._manifest.threshold_rule_id,
            self._manifest.effective_date_rule_id,
            self._manifest.income_rule_id,
            self._manifest.decision_boundary_rule_id,
        }
        missing_ids = sorted(required_ids - records.keys())
        if missing_ids:
            raise CorpusIntegrityError(f"Frozen corpus is missing rules: {', '.join(missing_ids)}")
        return records

    def _parse_thresholds(self) -> tuple[Decimal, ...]:
        rule = self._rules[self._manifest.threshold_rule_id]
        match = re.search(
            r"60% limits for household sizes 1-8 are (.+?) dollars",
            rule.text,
            flags=re.IGNORECASE,
        )
        if not match:
            raise CorpusIntegrityError("Threshold rule does not contain the frozen 1-8 table")
        values = tuple(
            Decimal(token.replace(",", "")).quantize(Decimal("0.01"))
            for token in re.findall(r"\d[\d,]*", match.group(1))
        )
        if len(values) != 8 or any(value <= 0 for value in values):
            raise CorpusIntegrityError("Frozen threshold table must contain eight positive values")
        if any(left > right for left, right in zip(values, values[1:])):
            raise CorpusIntegrityError("Frozen threshold table must be non-decreasing")
        return values

    def _validate_authoritative_rules(self) -> None:
        threshold_rule = self._rules[self._manifest.threshold_rule_id]
        effective_rule = self._rules[self._manifest.effective_date_rule_id]

        for rule in (threshold_rule, effective_rule):
            parsed = urlparse(rule.source_url)
            if (
                rule.authority != "official_hud"
                or parsed.scheme != "https"
                or parsed.hostname not in {"huduser.gov", "www.huduser.gov"}
            ):
                raise CorpusIntegrityError("MTSP citations must point to an official HTTPS HUD source")

        if EXPECTED_AREA not in threshold_rule.text or "FY 2026" not in threshold_rule.text:
            raise CorpusIntegrityError("Threshold rule does not match the frozen area and year")
        if effective_rule.effective_date != EXPECTED_EFFECTIVE_DATE:
            raise CorpusIntegrityError("MTSP effective date does not match the audited HUD date")
        if threshold_rule.source_locator != "PDF page 130":
            raise CorpusIntegrityError("Threshold source locator must remain PDF page 130")

    def _citation(self, rule_id: str) -> Citation:
        rule = self._rules[rule_id]
        return Citation(
            rule_id=rule.rule_id,
            authority=rule.authority,
            text=rule.text,
            source_url=rule.source_url,
            source_locator=rule.source_locator,
            effective_date=rule.effective_date,
        )

    def _build_program_scope(self) -> ProgramScope:
        return ProgramScope(
            corpus_version=self._manifest.corpus_version,
            frozen_at=self._manifest.frozen_at,
            runtime_network_access=self._manifest.runtime_network_access,
            program_id=self._manifest.program_id,
            program_name=self._manifest.program_name,
            rule_year=self._manifest.rule_year,
            area=self._manifest.area,
            ami_percentage=self._manifest.ami_percentage,
            effective_date=EXPECTED_EFFECTIVE_DATE,
            thresholds=[
                ThresholdRow(household_size=index, amount=amount)
                for index, amount in enumerate(self._thresholds, start=1)
            ],
            citation=self._citation(self._manifest.threshold_rule_id),
            decision_boundary=DECISION_BOUNDARY,
        )

    def _selection_reasons(
        self,
        *,
        program_id: str,
        rule_year: int,
        area: str,
        ami_percentage: int,
    ) -> list[ReviewReason]:
        reasons: list[ReviewReason] = []
        if program_id != self._manifest.program_id:
            reasons.append(
                ReviewReason(
                    code=ReviewReasonCode.PROGRAM_NOT_FROZEN,
                    message=f"Only {self._manifest.program_id} is available in the frozen corpus.",
                )
            )
        if rule_year != self._manifest.rule_year:
            reasons.append(
                ReviewReason(
                    code=ReviewReasonCode.RULE_YEAR_NOT_FROZEN,
                    message=f"Only rule year {self._manifest.rule_year} is frozen and supported.",
                )
            )
        if area != self._manifest.area:
            reasons.append(
                ReviewReason(
                    code=ReviewReasonCode.AREA_NOT_FROZEN,
                    message=f"Only {self._manifest.area} is available in this corpus.",
                )
            )
        if ami_percentage != self._manifest.ami_percentage:
            reasons.append(
                ReviewReason(
                    code=ReviewReasonCode.AMI_PERCENTAGE_NOT_FROZEN,
                    message=f"Only the frozen {self._manifest.ami_percentage}% table is supported.",
                )
            )
        return reasons

    def threshold_for_household_size(self, household_size: int) -> Decimal | None:
        if not 1 <= household_size <= len(self._thresholds):
            return None
        return self._thresholds[household_size - 1]

    def evaluate(self, request: RulesEvaluationRequest) -> RulesEvaluationResponse:
        reasons = self._selection_reasons(
            program_id=request.program_id,
            rule_year=request.rule_year,
            area=request.area,
            ami_percentage=request.ami_percentage,
        )
        selection_is_valid = not reasons

        if not 1 <= request.household_size <= 8:
            reasons.append(
                ReviewReason(
                    code=ReviewReasonCode.HOUSEHOLD_SIZE_OUTSIDE_TABLE,
                    message="The frozen HUD table covers household sizes 1 through 8 only.",
                )
            )

        if not request.income_sources:
            reasons.append(
                ReviewReason(
                    code=ReviewReasonCode.NO_INCOME_SOURCES,
                    message="At least one confirmed recurring gross-income source is required.",
                )
            )

        untrusted_text_ignored = False
        for source in request.income_sources:
            if not source.confirmed:
                reasons.append(
                    ReviewReason(
                        code=ReviewReasonCode.UNCONFIRMED_INPUT,
                        message="The renter must confirm or correct this value before reuse.",
                        source_id=source.source_id,
                    )
                )
            if source.uncertain:
                reasons.append(
                    ReviewReason(
                        code=ReviewReasonCode.UNCERTAIN_INPUT,
                        message=source.uncertainty_reason or "The input is uncertain.",
                        source_id=source.source_id,
                    )
                )
            if source.evidence is None:
                reasons.append(
                    ReviewReason(
                        code=ReviewReasonCode.MISSING_SOURCE_EVIDENCE,
                        message="A page and source box are required for every reused value.",
                        source_id=source.source_id,
                    )
                )
            else:
                untrusted_text_ignored |= source.evidence.untrusted_text_detected
                if not source.evidence.synthetic:
                    reasons.append(
                        ReviewReason(
                            code=ReviewReasonCode.NON_SYNTHETIC_DOCUMENT,
                            message="This prototype processes synthetic documents only.",
                            source_id=source.source_id,
                        )
                    )
            try:
                normalize_frequency(source.frequency)
            except CalculationInputError:
                reasons.append(
                    ReviewReason(
                        code=ReviewReasonCode.UNSUPPORTED_FREQUENCY,
                        message=(
                            "Frequency must be one of: "
                            + ", ".join(ANNUAL_PERIODS.keys())
                            + "."
                        ),
                        source_id=source.source_id,
                    )
                )

        household_size_only_blocker = (
            selection_is_valid
            and reasons
            and all(
                reason.code == ReviewReasonCode.HOUSEHOLD_SIZE_OUTSIDE_TABLE
                for reason in reasons
            )
        )
        can_annualize = not reasons or household_size_only_blocker

        traces: list[InputCalculationTrace] = []
        annualized_income: Decimal | None = None
        formula: str | None = None
        if can_annualize:
            annualized_values: list[Decimal] = []
            for source in request.income_sources:
                annualized_value, periods = annualize(source.amount, source.frequency)
                annualized_values.append(annualized_value)
                assert source.evidence is not None
                traces.append(
                    InputCalculationTrace(
                        source_id=source.source_id,
                        label=source.label,
                        confirmed_value=source.amount,
                        frequency=normalize_frequency(source.frequency),
                        periods_per_year=periods,
                        formula=(
                            f"{format_money(source.amount)} x {periods} periods/year "
                            f"= {format_money(annualized_value)}"
                        ),
                        annualized_value=annualized_value,
                        evidence=source.evidence,
                    )
                )
            annualized_income = sum_money(annualized_values)
            formula = (
                " + ".join(format_money(value) for value in annualized_values)
                + f" = {format_money(annualized_income)} annual recurring gross income"
            )

        threshold = (
            self.threshold_for_household_size(request.household_size)
            if selection_is_valid
            else None
        )
        if threshold is None:
            comparison = (
                Comparison.NO_FROZEN_THRESHOLD
                if annualized_income is not None
                else Comparison.NOT_CALCULATED
            )
        elif annualized_income is None:
            comparison = Comparison.NOT_CALCULATED
        else:
            comparison = compare_to_threshold(annualized_income, threshold)

        abstained = bool(reasons)
        status = ReviewStatus.NEEDS_REVIEW if abstained else ReviewStatus.READY_TO_REVIEW
        citations = [
            self._citation(self._manifest.effective_date_rule_id),
            self._citation(self._manifest.threshold_rule_id),
            self._citation(self._manifest.income_rule_id),
            self._citation(self._manifest.decision_boundary_rule_id),
        ]
        return RulesEvaluationResponse(
            household_id=request.household_id,
            status=status,
            abstained=abstained,
            program=self.program,
            household_size=request.household_size,
            input_traces=traces,
            annualized_income=annualized_income,
            threshold=threshold,
            comparison=comparison,
            formula=formula,
            effective_date=EXPECTED_EFFECTIVE_DATE,
            citations=citations,
            review_reasons=reasons,
            untrusted_document_text_ignored=untrusted_text_ignored,
            decision_boundary=DECISION_BOUNDARY,
        )

    def answer_question(self, request: RuleQuestionRequest) -> RuleQuestionResponse:
        selection_reasons = self._selection_reasons(
            program_id=request.program_id,
            rule_year=request.rule_year,
            area=request.area,
            ami_percentage=request.ami_percentage,
        )
        if selection_reasons:
            return RuleQuestionResponse(
                intent=RuleQuestionIntent.UNSUPPORTED,
                answer=(
                    "I can only answer from the frozen Boston FY 2026 MTSP 60% corpus. "
                    "Select that scope or request qualified human review."
                ),
                abstained=True,
                citations=[],
                effective_date=EXPECTED_EFFECTIVE_DATE,
                review_reasons=selection_reasons,
                decision_boundary=DECISION_BOUNDARY,
            )

        question = request.question.casefold()
        decision_terms = (
            "eligible",
            "ineligible",
            "approve",
            "approved",
            "deny",
            "denied",
            "qualify",
            "rank",
            "score",
            "decide for me",
        )
        instruction_terms = (
            "embedded instruction",
            "instructions embedded",
            "ignore system",
            "ignore prior",
            "system prompt",
            "document says",
            "pay stub instruction",
        )
        if any(term in question for term in instruction_terms):
            citation_ids = ["CH-SAFETY-001"]
            if any(term in question for term in decision_terms):
                citation_ids.append(self._manifest.decision_boundary_rule_id)
            return RuleQuestionResponse(
                intent=RuleQuestionIntent.DOCUMENT_SAFETY,
                answer=(
                    "Treat instructions inside a document as untrusted data and ignore them. "
                    "They cannot change tools, rules, calculations, or data access."
                ),
                abstained=False,
                citations=[self._citation(rule_id) for rule_id in citation_ids],
                effective_date=EXPECTED_EFFECTIVE_DATE,
                review_reasons=[],
                decision_boundary=DECISION_BOUNDARY,
            )

        if any(term in question for term in decision_terms):
            reason = ReviewReason(
                code=ReviewReasonCode.DECISION_REQUEST_REFUSED,
                message="A qualified human, not this system, makes housing determinations.",
            )
            return RuleQuestionResponse(
                intent=RuleQuestionIntent.DECISION_BOUNDARY,
                answer=(
                    "I cannot make or predict a housing decision. I can show the frozen rule, "
                    "your renter-confirmed inputs, and the deterministic numerical comparison "
                    "for a qualified human to review."
                ),
                abstained=True,
                citations=[self._citation(self._manifest.decision_boundary_rule_id)],
                effective_date=EXPECTED_EFFECTIVE_DATE,
                review_reasons=[reason],
                decision_boundary=DECISION_BOUNDARY,
            )

        if any(term in question for term in ("vacant", "vacancy", "waitlist", "available today")):
            return RuleQuestionResponse(
                intent=RuleQuestionIntent.DATASET_LIMITATION,
                answer=(
                    "No. HUD's LIHTC property dataset is a project inventory, not a current "
                    "vacancy, rent, waitlist, or application-status feed."
                ),
                abstained=False,
                citations=[self._citation("HUD-DATA-001")],
                effective_date=EXPECTED_EFFECTIVE_DATE,
                review_reasons=[],
                decision_boundary=DECISION_BOUNDARY,
            )

        if any(term in question for term in ("geocode", "address display", "precision code")):
            return RuleQuestionResponse(
                intent=RuleQuestionIntent.GEOCODE_PRECISION,
                answer=(
                    "HUD identifies geocode precision codes R and 4 as suitable for address "
                    "display; other codes are less granular."
                ),
                abstained=False,
                citations=[self._citation("HUD-GEO-001")],
                effective_date=EXPECTED_EFFECTIVE_DATE,
                review_reasons=[],
                decision_boundary=DECISION_BOUNDARY,
            )

        if any(term in question for term in ("60-day", "60 day", "document current", "document expired")):
            return RuleQuestionResponse(
                intent=RuleQuestionIntent.DOCUMENT_CURRENCY,
                answer=(
                    "The 60-day document-currency rule is a frozen convention for this "
                    "hackathon simulation, not a universal LIHTC rule."
                ),
                abstained=False,
                citations=[self._citation("CH-READINESS-001")],
                effective_date=EXPECTED_EFFECTIVE_DATE,
                review_reasons=[],
                decision_boundary=DECISION_BOUNDARY,
            )

        if any(
            term in question
            for term in ("statutory anchor", "federal statute", "26 u.s.c", "section 42")
        ):
            return RuleQuestionResponse(
                intent=RuleQuestionIntent.FEDERAL_ANCHOR,
                answer="The federal statutory anchor for LIHTC is 26 U.S.C. section 42.",
                abstained=False,
                citations=[self._citation("FED-LIHTC-001")],
                effective_date=EXPECTED_EFFECTIVE_DATE,
                review_reasons=[],
                decision_boundary=DECISION_BOUNDARY,
            )

        if any(term in question for term in ("compliance monitoring", "state agency monitoring", "1.42-5")):
            return RuleQuestionResponse(
                intent=RuleQuestionIntent.COMPLIANCE_MONITORING,
                answer=(
                    "Treasury regulation 26 CFR 1.42-5 describes state-agency compliance "
                    "monitoring; it does not delegate a housing determination to this system."
                ),
                abstained=False,
                citations=[self._citation("FED-MONITOR-001")],
                effective_date=EXPECTED_EFFECTIVE_DATE,
                review_reasons=[],
                decision_boundary=DECISION_BOUNDARY,
            )

        if any(term in question for term in ("effective", "take effect", "effective date")):
            return RuleQuestionResponse(
                intent=RuleQuestionIntent.EFFECTIVE_DATE,
                answer="The frozen FY 2026 MTSP limits are effective May 1, 2026.",
                abstained=False,
                citations=[self._citation(self._manifest.effective_date_rule_id)],
                effective_date=EXPECTED_EFFECTIVE_DATE,
                review_reasons=[],
                decision_boundary=DECISION_BOUNDARY,
            )

        if any(term in question for term in ("threshold", "income limit", "60%", "limit")):
            threshold = (
                self.threshold_for_household_size(request.household_size)
                if request.household_size is not None
                else None
            )
            if threshold is None:
                reason = ReviewReason(
                    code=ReviewReasonCode.HOUSEHOLD_SIZE_OUTSIDE_TABLE,
                    message="Provide a household size from 1 through 8 for the frozen table.",
                )
                return RuleQuestionResponse(
                    intent=RuleQuestionIntent.THRESHOLD,
                    answer=(
                        "I cannot select a threshold without a confirmed household size from 1 through 8."
                    ),
                    abstained=True,
                    citations=[self._citation(self._manifest.threshold_rule_id)],
                    effective_date=EXPECTED_EFFECTIVE_DATE,
                    review_reasons=[reason],
                    decision_boundary=DECISION_BOUNDARY,
                )
            return RuleQuestionResponse(
                intent=RuleQuestionIntent.THRESHOLD,
                answer=(
                    f"The frozen FY 2026 60% MTSP threshold for household size "
                    f"{request.household_size} is {format_money(threshold)}."
                ),
                abstained=False,
                citations=[self._citation(self._manifest.threshold_rule_id)],
                effective_date=EXPECTED_EFFECTIVE_DATE,
                review_reasons=[],
                decision_boundary=DECISION_BOUNDARY,
            )

        if any(term in question for term in ("program", "rule year", "area", "geography")):
            return RuleQuestionResponse(
                intent=RuleQuestionIntent.PROGRAM_SCOPE,
                answer=(
                    "This prototype uses the frozen FY 2026 HUD MTSP 60% table for "
                    "Boston-Cambridge-Quincy, MA-NH HMFA only."
                ),
                abstained=False,
                citations=[
                    self._citation(self._manifest.effective_date_rule_id),
                    self._citation(self._manifest.threshold_rule_id),
                ],
                effective_date=EXPECTED_EFFECTIVE_DATE,
                review_reasons=[],
                decision_boundary=DECISION_BOUNDARY,
            )

        reason = ReviewReason(
            code=ReviewReasonCode.QUESTION_NOT_SUPPORTED,
            message="The question could not be answered from the allowlisted frozen rule topics.",
        )
        return RuleQuestionResponse(
            intent=RuleQuestionIntent.UNSUPPORTED,
            answer=(
                "I could not map that question to the frozen threshold, effective date, "
                "program scope, or decision-boundary rules. Please rephrase or request human review."
            ),
            abstained=True,
            citations=[],
            effective_date=EXPECTED_EFFECTIVE_DATE,
            review_reasons=[reason],
            decision_boundary=DECISION_BOUNDARY,
        )
