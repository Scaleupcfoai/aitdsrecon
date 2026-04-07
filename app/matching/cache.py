"""
Column Mapping Cache — backed by Supabase column_map table.

On first upload: cascade runs → user confirms in frontend → DB saves with confirmed=True.
On repeat upload: DB lookup → if confirmed mappings exist → skip cascade entirely.

Usage:
    from app.matching.cache import MappingCache
    cache = MappingCache(db)
    result = cache.lookup(company_id="abc", file_type="tds")
    if result:
        # Cache hit — use saved confirmed mappings
    else:
        # Cache miss — run cascade, then save after user confirms
        cache.save(company_id="abc", file_type="tds", mappings=[...])
"""

from app.db.repository import Repository


class MappingCache:
    """Database-backed column mapping cache using column_map table."""

    def __init__(self, db: Repository):
        self.db = db

    def lookup(self, company_id: str, file_type: str) -> list[dict] | None:
        """Check DB for confirmed mappings for this company + file type.

        Returns list of {source_column, mapped_to, confidence} if found,
        None if no confirmed mappings exist.
        """
        if not company_id:
            return None

        confirmed = self.db.column_maps.get_confirmed(company_id, file_type)
        if not confirmed:
            return None

        return [
            {
                "source": c.source_column,
                "target": c.mapped_to,
                "confidence": c.confidence or 1.0,
                "method": "cached",
            }
            for c in confirmed
        ]

    def save(self, company_id: str, file_type: str, mappings: list[dict]):
        """Save confirmed mappings to DB.

        Only call this AFTER user confirms in the frontend.
        Sets confirmed=True so future lookups hit the cache.

        Args:
            company_id: Company identifier
            file_type: "tds" or "ledger"
            mappings: List of {source_name, target, confidence, method}
        """
        if not company_id:
            return

        for m in mappings:
            target = m.get("target")
            source = m.get("source_name") or m.get("source", "")

            if not source or not target:
                continue
            if target in ("skip", "gst_column", "expense_head"):
                continue  # Don't cache non-field mappings

            self.db.column_maps.upsert(
                company_id=company_id,
                file_type=file_type,
                source_column=source,
                mapped_to=target,
                confidence=m.get("confidence", 1.0),
            )

        # Mark all as confirmed
        self._mark_confirmed(company_id, file_type)

    def _mark_confirmed(self, company_id: str, file_type: str):
        """Mark all mappings for this company+file_type as confirmed."""
        try:
            self.db._client.table("column_map").update(
                {"confirmed": True}
            ).eq("company_id", company_id).eq("file_type", file_type).execute()
        except Exception as e:
            print(f"[warn] Could not mark mappings as confirmed: {e}")
