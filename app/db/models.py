"""
Pydantic models for all 15 database tables.

These define the shape of data in Python. Every time data comes from
or goes to the database, it passes through these models.

Usage:
    firm = CaFirm(**row_from_database)
    firm.name  # typed, validated
"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Layer 1: Identity & Tenancy ──

class CaFirm(BaseModel):
    id: str = ""
    name: str
    address: str | None = None
    pan_no: str | None = None
    created_at: str | None = None


class AppUser(BaseModel):
    id: str
    ca_firm_id: str
    name: str
    email: str
    mobile: str | None = None
    created_at: str | None = None


# ── Layer 2: Company Master ──

class Company(BaseModel):
    id: str = ""
    ca_firm_id: str
    company_name: str
    pan: str
    tan: str | None = None
    gstin: str | None = None
    address: str | None = None
    state_code: str | None = None
    company_type: str | None = None  # individual, huf, firm, llp, company, trust, aop
    created_at: str | None = None


# ── Layer 3: File Upload & Column Mapping ──

class UploadedFile(BaseModel):
    id: str = ""
    company_id: str
    reconciliation_run_id: str | None = None
    file_type: str  # ledger, tds_26as, tds_certificate
    file_name: str
    storage_path: str
    sheet_count: int = 1
    row_count: int | None = None
    uploaded_at: str | None = None


class ColumnMap(BaseModel):
    id: str = ""
    company_id: str
    file_type: str  # ledger, tds
    source_column: str
    mapped_to: str
    confidence: float | None = None
    confirmed: bool = False
    updated_at: str | None = None


# ── Layer 4: Reconciliation Run & Progress ──

class ReconciliationRun(BaseModel):
    id: str = ""
    company_id: str
    financial_year: str  # '2025-26'
    quarter: str | None = None  # 'Q1'-'Q4' or 'ALL'
    status: str = "uploading"  # uploading, mapping, processing, review, completed
    current_section: str | None = None
    current_party: str | None = None
    processing_status: str | None = None
    archived_at: str | None = None
    archive_storage_path: str | None = None
    created_at: str | None = None
    completed_at: str | None = None


class RunProgress(BaseModel):
    id: str = ""
    reconciliation_run_id: str
    section: str  # '194C', '194J', etc.
    total: int = 0
    matched: int = 0
    unmatched: int = 0
    status: str = "pending"  # pending, processing, completed
    updated_at: str | None = None


# ── Layer 5: Entries ──

class LedgerEntry(BaseModel):
    id: str = ""
    reconciliation_run_id: str
    company_id: str
    financial_year: str
    party_name: str | None = None
    pan: str | None = None
    expense_type: str | None = None
    amount: float
    gst_amount: float | None = None
    tds_section: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    raw_data: dict | None = None
    created_at: str | None = None


class TdsEntry(BaseModel):
    id: str = ""
    reconciliation_run_id: str
    company_id: str
    financial_year: str
    party_name: str | None = None
    pan: str | None = None
    tds_section: str
    tds_amount: float
    gross_amount: float | None = None
    date_of_deduction: str | None = None
    certificate_number: str | None = None
    raw_data: dict | None = None
    created_at: str | None = None


# ── Layer 6: Matching, Discrepancies & Summary ──

class MatchResult(BaseModel):
    id: str = ""
    reconciliation_run_id: str
    tds_entry_id: str | None = None
    ledger_entry_ids: list[str] | None = None
    match_type: str | None = None
    match_method: dict | None = None  # flexible: steps the matching took
    confidence: float | None = None
    amount: float | None = None
    status: str = "auto_matched"  # auto_matched, pending_review, confirmed, rejected
    resolved_by: str | None = None
    created_at: str | None = None
    resolved_at: str | None = None


class DiscrepancyAction(BaseModel):
    id: str = ""
    match_result_id: str
    stage: str | None = None
    llm_reasoning: str | None = None
    proposed_action: dict | None = None
    action_status: str = "proposed"  # proposed, approved, rejected, modified
    user_feedback: str | None = None
    user_decision: dict | None = None
    resolution_applied: dict | None = None
    created_by: str = "llm"  # llm, user
    created_at: str | None = None


class MatchSummary(BaseModel):
    id: str = ""
    reconciliation_run_id: str
    section: str
    group_type: str  # 'match_type' or 'error_type'
    group_key: str
    entry_count: int
    total_amount: float | None = None
    sample_entry_ids: list[str] | None = None
    llm_summary: str | None = None
    status: str = "resolved"  # resolved, pending_review, needs_attention
    created_at: str | None = None


# ── Layer 7: Learning & Patterns ──

class MatchTypeRegistry(BaseModel):
    id: str = ""
    type_name: str
    description: str | None = None
    ca_firm_id: str | None = None  # null = universal
    occurrence_count: int = 1
    first_seen_at: str | None = None
    last_seen_at: str | None = None


class ResolvedPattern(BaseModel):
    id: str = ""
    pattern_type: str
    input_snapshot: dict
    resolution_snapshot: dict
    embedding: list[float] | None = None  # pgvector (1536 dimensions)
    ca_firm_id: str | None = None  # null = universal
    usage_count: int = 0
    success_rate: float = 1.0
    created_at: str | None = None


class ResolutionFeedback(BaseModel):
    id: str = ""
    discrepancy_action_id: str | None = None
    feedback_type: str  # correction, confirmation, new_rule, context
    user_input: str
    llm_interpretation: str | None = None
    rule_extracted: dict | None = None
    applied_successfully: bool | None = None
    reuse_scope: str = "this_company"  # this_company, this_firm, universal
    ca_firm_id: str | None = None
    embedding: list[float] | None = None  # pgvector
    created_at: str | None = None


# ── Helper: Convert model to dict for Supabase insert ──

def to_insert_dict(model: BaseModel, exclude_empty_id: bool = True) -> dict:
    """Convert a Pydantic model to a dict for database insert.

    Removes 'id' if empty (let DB generate it).
    Removes None values (let DB use defaults).
    Removes 'embedding' field (handled separately for pgvector).
    """
    data = model.model_dump()
    if exclude_empty_id and not data.get("id"):
        data.pop("id", None)
    # Remove None values — let DB defaults apply
    data = {k: v for k, v in data.items() if v is not None}
    # Remove embedding — needs special pgvector handling
    data.pop("embedding", None)
    return data
