"""
Column Mapping Cache — skip cascade on repeat uploads.

Cache key: client_id + md5(sorted(lowercase column names))
Same column set = same template, regardless of row count or data.

On first upload: cascade runs → user confirms → cache saves.
On repeat upload: cache hit → return saved mapping → skip everything.

Storage: YAML files in data/mappings/{client_id}.yaml
Future: move to Supabase for multi-user access.

Usage:
    from app.matching.cache import MappingCache
    cache = MappingCache()
    result = cache.lookup(client_id="hpc", column_names=["Date", "Name", "Amount"])
    if result:
        # Cache hit — use saved mappings
    else:
        # Cache miss — run cascade
        ...
        cache.save(client_id="hpc", column_names=[...], mappings=[...], confirmed_by="user")
"""

import hashlib
import yaml
from datetime import datetime
from pathlib import Path


CACHE_DIR = Path("data/mappings")


class MappingCache:
    """File-based column mapping cache."""

    def __init__(self, cache_dir: str | Path | None = None):
        self.cache_dir = Path(cache_dir) if cache_dir else CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def lookup(self, client_id: str, column_names: list[str]) -> dict | None:
        """Check cache for a matching column set.

        Args:
            client_id: Company/client identifier
            column_names: List of column header names from the file

        Returns:
            Saved mapping dict if found, None if cache miss.
        """
        fingerprint = self._compute_fingerprint(column_names)
        cache_file = self.cache_dir / f"{self._safe_filename(client_id)}.yaml"

        if not cache_file.exists():
            return None

        try:
            with open(cache_file) as f:
                data = yaml.safe_load(f)
        except Exception:
            return None

        if not data or "mappings" not in data:
            return None

        for entry in data["mappings"]:
            if entry.get("file_fingerprint") == fingerprint:
                return {
                    "columns": entry.get("columns", []),
                    "file_label": entry.get("file_label", ""),
                    "confirmed_at": entry.get("confirmed_at", ""),
                    "confirmed_by": entry.get("confirmed_by", ""),
                    "from_cache": True,
                }

        return None

    def save(
        self,
        client_id: str,
        column_names: list[str],
        mappings: list[dict],
        file_label: str = "",
        confirmed_by: str = "user",
    ):
        """Save confirmed mappings to cache.

        Only call this AFTER user confirms in the review UI.

        Args:
            client_id: Company/client identifier
            column_names: Column header names (for fingerprint)
            mappings: List of {source, target, method, confidence}
            file_label: Human-readable label (e.g., "tds_26q_working")
            confirmed_by: Who confirmed ("user" or "auto")
        """
        fingerprint = self._compute_fingerprint(column_names)
        cache_file = self.cache_dir / f"{self._safe_filename(client_id)}.yaml"

        # Load existing
        data = {"client_id": client_id, "mappings": []}
        if cache_file.exists():
            try:
                with open(cache_file) as f:
                    data = yaml.safe_load(f) or data
            except Exception:
                pass

        # Remove existing entry with same fingerprint (update)
        data["mappings"] = [
            m for m in data.get("mappings", [])
            if m.get("file_fingerprint") != fingerprint
        ]

        # Add new entry
        data["mappings"].append({
            "file_fingerprint": fingerprint,
            "file_label": file_label,
            "confirmed_at": datetime.now().isoformat(),
            "confirmed_by": confirmed_by,
            "columns": [
                {
                    "source": m.get("source_name", ""),
                    "target": m.get("target"),
                    "method": m.get("method", "unknown"),
                    "confidence": m.get("confidence", 0),
                }
                for m in mappings
            ],
        })

        # Write
        with open(cache_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    def _compute_fingerprint(self, column_names: list[str]) -> str:
        """md5 hash of sorted lowercase column names."""
        normalized = sorted(c.lower().strip().replace("\n", " ") for c in column_names if c.strip())
        text = "|".join(normalized)
        return hashlib.md5(text.encode()).hexdigest()[:12]

    def _safe_filename(self, client_id: str) -> str:
        """Convert client_id to safe filename."""
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in client_id)
