"""Strict schemas for evidence-linked synthetic document extraction.

These models intentionally describe proposed profile facts. Extracted values
must be confirmed by a human before another service may reuse them.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DocumentType(str, Enum):
    APPLICATION_SUMMARY = "application_summary"
    PAY_STUB = "pay_stub"
    EMPLOYMENT_LETTER = "employment_letter"
    BENEFIT_LETTER = "benefit_letter"
    GIG_STATEMENT = "gig_statement"
    RENT_STATEMENT = "rent_statement"
    BANK_DEPOSIT_STATEMENT = "bank_deposit_statement"
    SELF_EMPLOYMENT_STATEMENT = "self_employment_statement"
    GOVERNMENT_ID = "government_id"
    UNKNOWN = "unknown"


class FieldName(str, Enum):
    """The only document fields the parser may return.

    ``untrusted_instruction_text`` from the organizer gold set is deliberately
    absent. It is represented as a :class:`SecurityFlag`, never as reusable
    applicant data.
    """

    PERSON_NAME = "person_name"
    HOUSEHOLD_SIZE = "household_size"
    ADDRESS = "address"
    APPLICATION_DATE = "application_date"
    PAY_DATE = "pay_date"
    PAY_PERIOD_START = "pay_period_start"
    PAY_PERIOD_END = "pay_period_end"
    PAY_FREQUENCY = "pay_frequency"
    REGULAR_HOURS = "regular_hours"
    HOURLY_RATE = "hourly_rate"
    GROSS_PAY = "gross_pay"
    NET_PAY = "net_pay"
    DOCUMENT_DATE = "document_date"
    WEEKLY_HOURS = "weekly_hours"
    MONTHLY_BENEFIT = "monthly_benefit"
    BENEFIT_FREQUENCY = "benefit_frequency"
    STATEMENT_MONTH = "statement_month"
    GROSS_RECEIPTS = "gross_receipts"
    PLATFORM_FEES = "platform_fees"
    PROPERTY_NAME = "property_name"
    UNIT_NUMBER = "unit_number"
    STATEMENT_DATE = "statement_date"
    LEASE_START_DATE = "lease_start_date"
    LEASE_END_DATE = "lease_end_date"
    MONTHLY_RENT = "monthly_rent"
    CURRENT_BALANCE = "current_balance"
    STATEMENT_PERIOD_START = "statement_period_start"
    STATEMENT_PERIOD_END = "statement_period_end"
    TOTAL_DEPOSITS = "total_deposits"
    BUSINESS_NAME = "business_name"
    BUSINESS_EXPENSES = "business_expenses"
    NET_BUSINESS_INCOME = "net_business_income"
    YTD_GROSS_PAY = "ytd_gross_pay"
    ISSUING_AGENCY = "issuing_agency"
    DATE_OF_BIRTH = "date_of_birth"
    EXPIRATION_DATE = "expiration_date"
    BANK_NAME = "bank_name"
    ENDING_BALANCE = "ending_balance"


class ExtractionEngine(str, Enum):
    PDF_TEXT = "pdf_text"
    OCR = "ocr"


class ExtractionStatus(str, Enum):
    EXTRACTED = "extracted"
    NEEDS_REVIEW = "needs_review"


Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
BoxTuple = tuple[float, float, float, float]


class EvidenceRef(BaseModel):
    """A value's source location in the organizer coordinate system."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)
    bbox: BoxTuple
    bbox_units: Literal["pdf_points_bottom_left_origin"] = (
        "pdf_points_bottom_left_origin"
    )
    text: str = Field(min_length=1)
    engine: ExtractionEngine
    confidence: Confidence

    @model_validator(mode="after")
    def validate_box(self) -> "EvidenceRef":
        x1, y1, x2, y2 = self.bbox
        if not (x1 < x2 and y1 < y2):
            raise ValueError("bbox must have positive width and height")
        if x1 < 0 or y1 < 0:
            raise ValueError("bbox coordinates must be non-negative")
        return self


class ExtractedField(BaseModel):
    """A proposed, evidence-linked value awaiting human confirmation."""

    model_config = ConfigDict(extra="forbid")

    field: FieldName
    value: str | int | float
    confidence: Confidence
    evidence: EvidenceRef
    confirmed: Literal[False] = False
    reusable: Literal[False] = False
    sensitive: bool = False


class SecurityFlag(BaseModel):
    """Untrusted document text that was detected and ignored."""

    model_config = ConfigDict(extra="forbid")

    code: Literal["embedded_instruction"] = "embedded_instruction"
    message: str
    evidence: EvidenceRef


class StructuredDocumentBase(BaseModel):
    """Base for document-specific data with evidence retained at every leaf."""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_field_slots(self) -> "StructuredDocumentBase":
        for slot, item in self:
            if slot != "document_type" and item is not None and item.field.value != slot:
                raise ValueError(f"{slot} must contain the matching extracted field")
        return self


class ApplicationSummaryData(StructuredDocumentBase):
    document_type: Literal[DocumentType.APPLICATION_SUMMARY] = (
        DocumentType.APPLICATION_SUMMARY
    )
    person_name: ExtractedField | None = None
    household_size: ExtractedField | None = None
    address: ExtractedField | None = None
    application_date: ExtractedField | None = None


class PayStubData(StructuredDocumentBase):
    document_type: Literal[DocumentType.PAY_STUB] = DocumentType.PAY_STUB
    person_name: ExtractedField | None = None
    pay_date: ExtractedField | None = None
    pay_period_start: ExtractedField | None = None
    pay_period_end: ExtractedField | None = None
    pay_frequency: ExtractedField | None = None
    regular_hours: ExtractedField | None = None
    hourly_rate: ExtractedField | None = None
    gross_pay: ExtractedField | None = None
    net_pay: ExtractedField | None = None
    ytd_gross_pay: ExtractedField | None = None


class EmploymentLetterData(StructuredDocumentBase):
    document_type: Literal[DocumentType.EMPLOYMENT_LETTER] = (
        DocumentType.EMPLOYMENT_LETTER
    )
    person_name: ExtractedField | None = None
    document_date: ExtractedField | None = None
    weekly_hours: ExtractedField | None = None
    hourly_rate: ExtractedField | None = None


class BenefitLetterData(StructuredDocumentBase):
    document_type: Literal[DocumentType.BENEFIT_LETTER] = DocumentType.BENEFIT_LETTER
    person_name: ExtractedField | None = None
    document_date: ExtractedField | None = None
    monthly_benefit: ExtractedField | None = None
    benefit_frequency: ExtractedField | None = None
    issuing_agency: ExtractedField | None = None


class GigStatementData(StructuredDocumentBase):
    document_type: Literal[DocumentType.GIG_STATEMENT] = DocumentType.GIG_STATEMENT
    person_name: ExtractedField | None = None
    statement_month: ExtractedField | None = None
    gross_receipts: ExtractedField | None = None
    platform_fees: ExtractedField | None = None


class RentStatementData(StructuredDocumentBase):
    document_type: Literal[DocumentType.RENT_STATEMENT] = DocumentType.RENT_STATEMENT
    person_name: ExtractedField | None = None
    property_name: ExtractedField | None = None
    address: ExtractedField | None = None
    unit_number: ExtractedField | None = None
    statement_date: ExtractedField | None = None
    lease_start_date: ExtractedField | None = None
    lease_end_date: ExtractedField | None = None
    monthly_rent: ExtractedField | None = None
    current_balance: ExtractedField | None = None


class BankDepositStatementData(StructuredDocumentBase):
    document_type: Literal[DocumentType.BANK_DEPOSIT_STATEMENT] = (
        DocumentType.BANK_DEPOSIT_STATEMENT
    )
    person_name: ExtractedField | None = None
    statement_period_start: ExtractedField | None = None
    statement_period_end: ExtractedField | None = None
    total_deposits: ExtractedField | None = None
    bank_name: ExtractedField | None = None
    ending_balance: ExtractedField | None = None


class SelfEmploymentStatementData(StructuredDocumentBase):
    document_type: Literal[DocumentType.SELF_EMPLOYMENT_STATEMENT] = (
        DocumentType.SELF_EMPLOYMENT_STATEMENT
    )
    person_name: ExtractedField | None = None
    business_name: ExtractedField | None = None
    statement_month: ExtractedField | None = None
    gross_receipts: ExtractedField | None = None
    business_expenses: ExtractedField | None = None
    net_business_income: ExtractedField | None = None


class GovernmentIdData(StructuredDocumentBase):
    document_type: Literal[DocumentType.GOVERNMENT_ID] = DocumentType.GOVERNMENT_ID
    person_name: ExtractedField | None = None
    date_of_birth: ExtractedField | None = None
    expiration_date: ExtractedField | None = None


StructuredDocumentData = Annotated[
    ApplicationSummaryData
    | PayStubData
    | EmploymentLetterData
    | BenefitLetterData
    | GigStatementData
    | RentStatementData
    | BankDepositStatementData
    | SelfEmploymentStatementData
    | GovernmentIdData,
    Field(discriminator="document_type"),
]


class DocumentExtraction(BaseModel):
    """Complete parser output for one synthetic document."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    document_type: DocumentType
    synthetic: Literal[True]
    page_count: int = Field(ge=1)
    page_size_points: tuple[float, float]
    rasterized: bool
    status: ExtractionStatus
    fields: list[ExtractedField]
    structured_data: StructuredDocumentData | None = None
    security_flags: list[SecurityFlag] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def field_map(self) -> dict[FieldName, ExtractedField]:
        """Return a typed lookup without weakening the serialized contract."""

        return {item.field: item for item in self.fields}
