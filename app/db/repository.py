"""
Repository — all database operations in one place.

Every agent, API endpoint, and service uses this to talk to the database.
Never write Supabase queries directly in other files.

Usage:
    from app.db.repository import Repository
    repo = Repository()
    firm = repo.firms.create("ScaleUp CFO", pan_no="AAACS1234A")
    companies = repo.companies.list_by_firm(firm.id)
"""

from supabase import Client

from app.db.client import get_client
from app.db.models import (
    CaFirm, AppUser, Company, UploadedFile, ColumnMap,
    ReconciliationRun, RunProgress, LedgerEntry, TdsEntry,
    MatchResult, DiscrepancyAction, MatchSummary,
    MatchTypeRegistry, ResolvedPattern, ResolutionFeedback,
    to_insert_dict,
)


# ── Firm ──

class FirmRepository:
    def __init__(self, client: Client):
        self.client = client

    def create(self, name: str, address: str = "", pan_no: str = "") -> CaFirm:
        data = {"name": name}
        if address:
            data["address"] = address
        if pan_no:
            data["pan_no"] = pan_no
        result = self.client.table("ca_firm").insert(data).execute()
        return CaFirm(**result.data[0])

    def get_by_id(self, firm_id: str) -> CaFirm | None:
        result = self.client.table("ca_firm").select("*").eq("id", firm_id).execute()
        return CaFirm(**result.data[0]) if result.data else None


# ── Company ──

class CompanyRepository:
    def __init__(self, client: Client):
        self.client = client

    def create(self, firm_id: str, company_name: str, pan: str, **kwargs) -> Company:
        data = {"ca_firm_id": firm_id, "company_name": company_name, "pan": pan}
        data.update({k: v for k, v in kwargs.items() if v is not None})
        result = self.client.table("company").insert(data).execute()
        return Company(**result.data[0])

    def list_by_firm(self, firm_id: str) -> list[Company]:
        result = self.client.table("company").select("*").eq("ca_firm_id", firm_id).execute()
        return [Company(**row) for row in result.data]

    def get_by_id(self, company_id: str) -> Company | None:
        result = self.client.table("company").select("*").eq("id", company_id).execute()
        return Company(**result.data[0]) if result.data else None


# ── Uploaded File ──

class FileRepository:
    def __init__(self, client: Client):
        self.client = client

    def create(self, company_id: str, file_type: str, file_name: str,
               storage_path: str, run_id: str | None = None, **kwargs) -> UploadedFile:
        data = {
            "company_id": company_id,
            "file_type": file_type,
            "file_name": file_name,
            "storage_path": storage_path,
        }
        if run_id:
            data["reconciliation_run_id"] = run_id
        data.update({k: v for k, v in kwargs.items() if v is not None})
        result = self.client.table("uploaded_file").insert(data).execute()
        return UploadedFile(**result.data[0])

    def list_by_run(self, run_id: str) -> list[UploadedFile]:
        result = self.client.table("uploaded_file").select("*").eq("reconciliation_run_id", run_id).execute()
        return [UploadedFile(**row) for row in result.data]


# ── Column Map ──

class ColumnMapRepository:
    def __init__(self, client: Client):
        self.client = client

    def upsert(self, company_id: str, file_type: str,
               source_column: str, mapped_to: str, confidence: float = 1.0) -> ColumnMap:
        data = {
            "company_id": company_id,
            "file_type": file_type,
            "source_column": source_column,
            "mapped_to": mapped_to,
            "confidence": confidence,
        }
        result = self.client.table("column_map").upsert(
            data, on_conflict="company_id,file_type,source_column"
        ).execute()
        return ColumnMap(**result.data[0])

    def get_confirmed(self, company_id: str, file_type: str) -> list[ColumnMap]:
        result = (self.client.table("column_map")
                  .select("*")
                  .eq("company_id", company_id)
                  .eq("file_type", file_type)
                  .eq("confirmed", True)
                  .execute())
        return [ColumnMap(**row) for row in result.data]


# ── Reconciliation Run ──

class RunRepository:
    def __init__(self, client: Client):
        self.client = client

    def create(self, company_id: str, financial_year: str,
               quarter: str = "ALL") -> ReconciliationRun:
        data = {
            "company_id": company_id,
            "financial_year": financial_year,
            "quarter": quarter,
            "status": "uploading",
        }
        result = self.client.table("reconciliation_run").insert(data).execute()
        return ReconciliationRun(**result.data[0])

    def get_by_id(self, run_id: str) -> ReconciliationRun | None:
        result = self.client.table("reconciliation_run").select("*").eq("id", run_id).execute()
        return ReconciliationRun(**result.data[0]) if result.data else None

    def update_status(self, run_id: str, status: str, **kwargs) -> ReconciliationRun:
        data = {"status": status}
        data.update({k: v for k, v in kwargs.items() if v is not None})
        result = self.client.table("reconciliation_run").update(data).eq("id", run_id).execute()
        return ReconciliationRun(**result.data[0])

    def list_by_company(self, company_id: str) -> list[ReconciliationRun]:
        result = (self.client.table("reconciliation_run")
                  .select("*")
                  .eq("company_id", company_id)
                  .order("created_at", desc=True)
                  .execute())
        return [ReconciliationRun(**row) for row in result.data]


# ── Run Progress ──

class ProgressRepository:
    def __init__(self, client: Client):
        self.client = client

    def upsert(self, run_id: str, section: str, total: int = 0,
               matched: int = 0, unmatched: int = 0, status: str = "pending") -> RunProgress:
        data = {
            "reconciliation_run_id": run_id,
            "section": section,
            "total": total,
            "matched": matched,
            "unmatched": unmatched,
            "status": status,
        }
        result = self.client.table("run_progress").upsert(
            data, on_conflict="reconciliation_run_id,section"
        ).execute()
        return RunProgress(**result.data[0])

    def list_by_run(self, run_id: str) -> list[RunProgress]:
        result = self.client.table("run_progress").select("*").eq("reconciliation_run_id", run_id).execute()
        return [RunProgress(**row) for row in result.data]


# ── Entries (Ledger + TDS) ──

class EntryRepository:
    def __init__(self, client: Client):
        self.client = client

    def bulk_insert_ledger(self, entries: list[dict]) -> int:
        """Insert multiple ledger entries in one call. Returns count inserted."""
        if not entries:
            return 0
        # Supabase accepts a list of dicts for bulk insert
        result = self.client.table("ledger_entry").insert(entries).execute()
        return len(result.data)

    def bulk_insert_tds(self, entries: list[dict]) -> int:
        """Insert multiple TDS entries in one call. Returns count inserted."""
        if not entries:
            return 0
        result = self.client.table("tds_entry").insert(entries).execute()
        return len(result.data)

    def get_ledger_by_run(self, run_id: str) -> list[LedgerEntry]:
        result = (self.client.table("ledger_entry")
                  .select("*")
                  .eq("reconciliation_run_id", run_id)
                  .execute())
        return [LedgerEntry(**row) for row in result.data]

    def get_tds_by_run(self, run_id: str) -> list[TdsEntry]:
        result = (self.client.table("tds_entry")
                  .select("*")
                  .eq("reconciliation_run_id", run_id)
                  .execute())
        return [TdsEntry(**row) for row in result.data]

    def get_ledger_by_section(self, run_id: str, section: str) -> list[LedgerEntry]:
        result = (self.client.table("ledger_entry")
                  .select("*")
                  .eq("reconciliation_run_id", run_id)
                  .eq("tds_section", section)
                  .execute())
        return [LedgerEntry(**row) for row in result.data]

    def get_tds_by_section(self, run_id: str, section: str) -> list[TdsEntry]:
        result = (self.client.table("tds_entry")
                  .select("*")
                  .eq("reconciliation_run_id", run_id)
                  .eq("tds_section", section)
                  .execute())
        return [TdsEntry(**row) for row in result.data]


# ── Match Results ──

class MatchRepository:
    def __init__(self, client: Client):
        self.client = client

    def bulk_insert(self, matches: list[dict]) -> int:
        if not matches:
            return 0
        result = self.client.table("match_result").insert(matches).execute()
        return len(result.data)

    def get_by_run(self, run_id: str) -> list[MatchResult]:
        result = (self.client.table("match_result")
                  .select("*")
                  .eq("reconciliation_run_id", run_id)
                  .execute())
        return [MatchResult(**row) for row in result.data]

    def update_status(self, match_id: str, status: str,
                      resolved_by: str | None = None) -> MatchResult:
        data = {"status": status}
        if resolved_by:
            data["resolved_by"] = resolved_by
            data["resolved_at"] = "now()"
        result = self.client.table("match_result").update(data).eq("id", match_id).execute()
        return MatchResult(**result.data[0])


# ── Discrepancy Actions ──

class DiscrepancyRepository:
    def __init__(self, client: Client):
        self.client = client

    def create(self, match_result_id: str, stage: str = "",
               llm_reasoning: str = "", proposed_action: dict | None = None) -> DiscrepancyAction:
        data = {"match_result_id": match_result_id}
        if stage:
            data["stage"] = stage
        if llm_reasoning:
            data["llm_reasoning"] = llm_reasoning
        if proposed_action:
            data["proposed_action"] = proposed_action
        result = self.client.table("discrepancy_action").insert(data).execute()
        return DiscrepancyAction(**result.data[0])

    def get_by_match(self, match_result_id: str) -> list[DiscrepancyAction]:
        result = (self.client.table("discrepancy_action")
                  .select("*")
                  .eq("match_result_id", match_result_id)
                  .execute())
        return [DiscrepancyAction(**row) for row in result.data]

    def update_status(self, action_id: str, action_status: str,
                      user_feedback: str = "", resolution_applied: dict | None = None):
        data = {"action_status": action_status}
        if user_feedback:
            data["user_feedback"] = user_feedback
        if resolution_applied:
            data["resolution_applied"] = resolution_applied
        self.client.table("discrepancy_action").update(data).eq("id", action_id).execute()


# ── Match Summary ──

class SummaryRepository:
    def __init__(self, client: Client):
        self.client = client

    def bulk_insert(self, summaries: list[dict]) -> int:
        if not summaries:
            return 0
        result = self.client.table("match_summary").insert(summaries).execute()
        return len(result.data)

    def get_by_run(self, run_id: str) -> list[MatchSummary]:
        result = (self.client.table("match_summary")
                  .select("*")
                  .eq("reconciliation_run_id", run_id)
                  .execute())
        return [MatchSummary(**row) for row in result.data]


# ── Learning: Match Type Registry ──

class MatchTypeRepository:
    def __init__(self, client: Client):
        self.client = client

    def register(self, type_name: str, description: str = "",
                 ca_firm_id: str | None = None) -> MatchTypeRegistry:
        data = {"type_name": type_name}
        if description:
            data["description"] = description
        if ca_firm_id:
            data["ca_firm_id"] = ca_firm_id
        result = self.client.table("match_type_registry").upsert(
            data, on_conflict="type_name"
        ).execute()
        return MatchTypeRegistry(**result.data[0])

    def list_all(self, ca_firm_id: str | None = None) -> list[MatchTypeRegistry]:
        q = self.client.table("match_type_registry").select("*")
        if ca_firm_id:
            q = q.or_(f"ca_firm_id.eq.{ca_firm_id},ca_firm_id.is.null")
        result = q.execute()
        return [MatchTypeRegistry(**row) for row in result.data]


# ── Learning: Resolved Patterns ──

class PatternRepository:
    def __init__(self, client: Client):
        self.client = client

    def create(self, pattern_type: str, input_snapshot: dict,
               resolution_snapshot: dict, ca_firm_id: str | None = None) -> ResolvedPattern:
        data = {
            "pattern_type": pattern_type,
            "input_snapshot": input_snapshot,
            "resolution_snapshot": resolution_snapshot,
        }
        if ca_firm_id:
            data["ca_firm_id"] = ca_firm_id
        result = self.client.table("resolved_pattern").insert(data).execute()
        return ResolvedPattern(**result.data[0])

    def increment_usage(self, pattern_id: str):
        # Use RPC or raw update to increment
        self.client.table("resolved_pattern").update(
            {"usage_count": "usage_count + 1"}  # This needs RPC for atomic increment
        ).eq("id", pattern_id).execute()


# ── Learning: Resolution Feedback ──

class FeedbackRepository:
    def __init__(self, client: Client):
        self.client = client

    def create(self, feedback_type: str, user_input: str,
               ca_firm_id: str | None = None, **kwargs) -> ResolutionFeedback:
        data = {"feedback_type": feedback_type, "user_input": user_input}
        if ca_firm_id:
            data["ca_firm_id"] = ca_firm_id
        data.update({k: v for k, v in kwargs.items() if v is not None})
        result = self.client.table("resolution_feedback").insert(data).execute()
        return ResolutionFeedback(**result.data[0])


# ══════════════════════════════════════════════════════════
# Main Repository — single entry point for all operations
# ══════════════════════════════════════════════════════════

class Repository:
    """Single access point for all database operations.

    Usage:
        repo = Repository()
        firm = repo.firms.create("ScaleUp CFO")
        company = repo.companies.create(firm.id, "HPC Ltd", "AAACH1234A")
        run = repo.runs.create(company.id, "2024-25")
        repo.entries.bulk_insert_tds([...])
    """

    def __init__(self, client: Client | None = None):
        self._client = client or get_client()
        self.firms = FirmRepository(self._client)
        self.companies = CompanyRepository(self._client)
        self.files = FileRepository(self._client)
        self.column_maps = ColumnMapRepository(self._client)
        self.runs = RunRepository(self._client)
        self.progress = ProgressRepository(self._client)
        self.entries = EntryRepository(self._client)
        self.matches = MatchRepository(self._client)
        self.discrepancies = DiscrepancyRepository(self._client)
        self.summaries = SummaryRepository(self._client)
        self.match_types = MatchTypeRepository(self._client)
        self.patterns = PatternRepository(self._client)
        self.feedback = FeedbackRepository(self._client)
