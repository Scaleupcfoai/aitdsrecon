"""
AgentBase — base class for all reconciliation agents.

Every agent gets:
- run_id: which reconciliation run this is
- company_id: which company's data
- firm_id: which CA firm (for RLS/isolation)
- db: Repository instance for database access
- events: EventEmitter for streaming status to UI

Usage:
    class ParserAgent(AgentBase):
        def run(self, form26_path, tally_path):
            self.events.agent_start("Parser Agent", "Starting...")
            entries = self.parse_form26(form26_path)
            self.db.entries.bulk_insert_tds(entries)
            self.events.agent_done("Parser Agent", "Complete")
"""

from app.db.repository import Repository
from app.pipeline.events import EventEmitter


class AgentBase:
    """Base class for all agents. Provides run context + DB + events."""

    def __init__(
        self,
        run_id: str,
        company_id: str,
        firm_id: str,
        financial_year: str,
        db: Repository,
        events: EventEmitter,
    ):
        self.run_id = run_id
        self.company_id = company_id
        self.firm_id = firm_id
        self.financial_year = financial_year
        self.db = db
        self.events = events

    @property
    def agent_name(self) -> str:
        """Override in subclass — e.g. 'Parser Agent', 'Matcher Agent'."""
        return self.__class__.__name__
