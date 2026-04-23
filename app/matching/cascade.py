"""
Cascade Column Matcher — L0 → L1 → L2 → L4.

L0: Template recognition (Form 26, Tally registers) — 0 LLM calls
L1: Exact match with alias + abbreviation expansion
L2: Fuzzy match (rapidfuzz) + fingerprint tie-breaking
L4: Gemini LLM batch call for remaining unresolved columns

L3 (Valentine) is optional — skipped by default, can be added later.

Usage:
    from app.matching.cascade import CascadeMatcher
    matcher = CascadeMatcher(fingerprints, file_type="tds", llm=llm_client)
    results = matcher.match()
"""

import re
import yaml
from pathlib import Path
from dataclasses import dataclass, field

from app.services.llm_client import LLMClient


# ═══════════════════════════════════════════════════════════
# Config loading
# ═══════════════════════════════════════════════════════════

CONFIG_DIR = Path(__file__).parent.parent / "config"


def _load_yaml(filename: str) -> dict:
    path = CONFIG_DIR / filename
    with open(path) as f:
        return yaml.safe_load(f)


def _load_target_schema() -> dict:
    return _load_yaml("target_schema.yaml")


def _load_templates() -> list[dict]:
    data = _load_yaml("templates.yaml")
    return data.get("templates", [])


# ═══════════════════════════════════════════════════════════
# Abbreviation expansion
# ═══════════════════════════════════════════════════════════

ABBREVIATIONS = {
    "inv": "invoice", "amt": "amount", "dt": "date", "no": "number",
    "pmt": "payment", "qty": "quantity", "pct": "percent", "yr": "year",
    "nos": "numbers", "vol": "volume", "tot": "total", "bal": "balance",
    "sr": "serial", "sl": "serial", "ref": "reference", "desc": "description",
    "acc": "account", "acct": "account", "txn": "transaction",
}


def normalise(text: str) -> str:
    """Normalise column name for matching."""
    text = text.lower().strip()
    text = text.replace("\n", " ").replace("\r", " ")
    text = re.sub(r"[^\w\s]", " ", text)  # remove special chars except underscore
    text = re.sub(r"\s+", " ", text).strip()
    # Expand abbreviations
    words = text.split()
    expanded = [ABBREVIATIONS.get(w, w) for w in words]
    return " ".join(expanded)


# ═══════════════════════════════════════════════════════════
# Mapping Result
# ═══════════════════════════════════════════════════════════

@dataclass
class MappingResult:
    source_name: str
    col_index: int
    target: str | None = None         # None if unmapped
    confidence: float = 0.0
    method: str = "unmapped"          # exact | fuzzy | template | llm | manual | skip
    tier: str = "UNMAPPED"            # HIGH | MEDIUM | LOW | UNMAPPED
    alternatives: list[str] = field(default_factory=list)
    reason: str = ""
    dtype_inferred: str = "string"
    sample_values: list = field(default_factory=list)
    is_gst_column: bool = False
    is_expense_head: bool = False

    def to_dict(self) -> dict:
        return {
            "source_name": self.source_name,
            "col_index": self.col_index,
            "target": self.target,
            "confidence": self.confidence,
            "method": self.method,
            "tier": self.tier,
            "alternatives": self.alternatives,
            "reason": self.reason,
            "dtype_inferred": self.dtype_inferred,
            "sample_values": self.sample_values,
            "is_gst_column": self.is_gst_column,
            "is_expense_head": self.is_expense_head,
        }


def _compute_tier(confidence: float) -> str:
    if confidence >= 0.90:
        return "HIGH"
    elif confidence >= 0.70:
        return "MEDIUM"
    elif confidence >= 0.50:
        return "LOW"
    return "UNMAPPED"


# ═══════════════════════════════════════════════════════════
# Cascade Matcher
# ═══════════════════════════════════════════════════════════

class CascadeMatcher:
    """Orchestrate L0 → L1 → L2 → L4 cascade."""

    def __init__(
        self,
        fingerprints: list[dict],
        file_type: str = "auto",      # "tds" | "ledger" | "auto"
        llm: LLMClient | None = None,
        events=None,                   # EventEmitter for SSE streaming
    ):
        self.fingerprints = fingerprints
        self.file_type = file_type
        self.llm = llm
        self.events = events

        # Load configs
        schema = _load_target_schema()
        self.target_fields = schema.get(f"{file_type}_fields", schema.get("ledger_fields", []))
        self.templates = _load_templates()

        # Auto-detect file type from fingerprints
        if file_type == "auto":
            self.file_type = self._detect_file_type()
            self.target_fields = schema.get(f"{self.file_type}_fields", schema.get("ledger_fields", []))

        # Results
        self.results: list[MappingResult] = []
        self._resolved_indices: set[int] = set()

    def match(self) -> list[MappingResult]:
        """Run the cascade. Returns MappingResult per column."""
        self._log("Starting column matching cascade...")

        # Initialize results for all columns
        self.results = [
            MappingResult(
                source_name=fp["source_name"],
                col_index=fp["col_index"],
                dtype_inferred=fp.get("dtype_inferred", "string"),
                sample_values=fp.get("sample_values", []),
            )
            for fp in self.fingerprints
        ]

        # L0: Template recognition
        l0_count = self._l0_template()
        if l0_count == len(self.results):
            self._log(f"L0 Template: all {l0_count} columns resolved")
            return self.results
        if l0_count > 0:
            self._log(f"L0 Template: {l0_count} columns resolved")

        # L0.5: Hard fingerprint override
        # If a column's values match PAN/TAN/Section regex, assign directly
        hard_count = self._apply_hard_fingerprints()
        if hard_count > 0:
            self._log(f"Hard fingerprint: {hard_count} columns identified by value patterns")

        # L1: Exact match
        l1_count = self._l1_exact()
        if l1_count > 0:
            self._log(f"L1 Exact: {l1_count} columns resolved")

        # L2: Fuzzy + fingerprint
        l2_count = self._l2_fuzzy()
        if l2_count > 0:
            self._log(f"L2 Fuzzy: {l2_count} columns resolved")

        # Check if anything is still unresolved
        unresolved = [r for r in self.results if r.target is None and not r.is_gst_column and not r.is_expense_head]
        if unresolved:
            from app.config import settings
            if settings.enable_llm_column_mapping:
                # L4: LLM batch
                l4_count = self._l4_llm(unresolved)
                self._log(f"L4 LLM: {l4_count} columns resolved")
            else:
                self._log(f"L4 LLM: skipped (enable_llm_column_mapping=False). {len(unresolved)} columns unresolved.")

        # Final tier assignment
        for r in self.results:
            if r.target and r.tier == "UNMAPPED":
                r.tier = _compute_tier(r.confidence)

        resolved = sum(1 for r in self.results if r.target is not None or r.is_gst_column or r.is_expense_head)
        self._log(f"Done: {resolved}/{len(self.results)} columns mapped")

        return self.results

    # ─── L0: Template Recognition ────────────────────────────

    def _l0_template(self) -> int:
        """Check if file matches a known template."""
        col_names_lower = [normalise(fp["source_name"]) for fp in self.fingerprints]
        col_names_raw = [fp["source_name"].lower().replace("\n", " ").strip() for fp in self.fingerprints]

        for template in self.templates:
            sig = template.get("signature", {})

            # Check must_contain_all
            must_all = sig.get("must_contain_all", [])
            if not all(
                any(term in cn for cn in col_names_raw) for term in must_all
            ):
                continue

            # Check must_contain_any
            must_any = sig.get("must_contain_any", [])
            if must_any and not any(
                any(term in cn for cn in col_names_raw) for term in must_any
            ):
                continue

            # Template matches — apply its column mapping
            self._log(f"L0: Matched template '{template['label']}'")
            self.file_type = template.get("file_type", self.file_type)

            return self._apply_template(template)

        return 0

    def _apply_template(self, template: dict) -> int:
        """Apply a matched template's column mapping."""
        count = 0
        col_names_raw = [fp["source_name"].lower().replace("\n", " ").strip() for fp in self.fingerprints]

        # Map columns defined in template
        columns = template.get("columns", []) + template.get("structural_columns", [])
        for col_spec in columns:
            match_terms = col_spec.get("match", [])
            not_contains = col_spec.get("not_contains", [])
            must_contain = col_spec.get("must_contain", [])
            target = col_spec["target"]

            for idx, raw_name in enumerate(col_names_raw):
                if idx in self._resolved_indices:
                    continue

                # Check if any match term is in the column name
                if not any(term in raw_name for term in match_terms):
                    continue

                # Check not_contains exclusions
                if any(excl in raw_name for excl in not_contains):
                    continue

                # Check must_contain requirements
                if must_contain and not all(req in raw_name for req in must_contain):
                    continue

                # Match found
                self.results[idx].target = target
                self.results[idx].confidence = 1.0
                self.results[idx].method = "template"
                self.results[idx].tier = "HIGH"
                self.results[idx].reason = f"Template: {template['label']}"
                self._resolved_indices.add(idx)
                count += 1
                break  # One column per spec

        # Handle skip patterns
        skip_patterns = template.get("skip_patterns", [])
        for idx, raw_name in enumerate(col_names_raw):
            if idx in self._resolved_indices:
                continue
            if any(pat in raw_name for pat in skip_patterns):
                self.results[idx].target = "skip"
                self.results[idx].confidence = 1.0
                self.results[idx].method = "template"
                self.results[idx].tier = "HIGH"
                self.results[idx].reason = "Template: skip pattern"
                self._resolved_indices.add(idx)
                count += 1

        # Handle GST columns (Tally)
        gst_patterns = template.get("gst_patterns", [])
        for idx, raw_name in enumerate(col_names_raw):
            if idx in self._resolved_indices:
                continue
            if any(pat in raw_name for pat in gst_patterns):
                self.results[idx].target = "gst_column"
                self.results[idx].confidence = 1.0
                self.results[idx].method = "template"
                self.results[idx].tier = "HIGH"
                self.results[idx].is_gst_column = True
                self.results[idx].reason = "Template: GST column"
                self._resolved_indices.add(idx)
                count += 1

        # Everything else in a Tally register = expense head
        if template.get("file_type") == "ledger":
            for idx in range(len(self.results)):
                if idx not in self._resolved_indices:
                    self.results[idx].target = "expense_head"
                    self.results[idx].confidence = 0.9
                    self.results[idx].method = "template"
                    self.results[idx].tier = "HIGH"
                    self.results[idx].is_expense_head = True
                    self.results[idx].reason = "Template: remaining = expense head"
                    self._resolved_indices.add(idx)
                    count += 1

        return count

    # ─── L1: Exact Match ─────────────────────────────────────

    def _apply_hard_fingerprints(self) -> int:
        """Apply bulletproof value-based identification.

        If a column's values match PAN/TAN/Section regex with high confidence,
        assign it directly — regardless of header name.
        """
        HARD_MATCH_TO_TARGET = {
            "pan": "pan",
            "tan": "tan",
            "tds_section": "tds_section",
            "financial_year": "financial_year",
            "quarter": "quarter",
        }

        count = 0
        for idx, fp in enumerate(self.fingerprints):
            if idx in self._resolved_indices:
                continue

            hard_match = fp.get("hard_match")
            if not hard_match:
                continue

            target = HARD_MATCH_TO_TARGET.get(hard_match)
            if not target:
                continue

            # Verify this target field exists in our schema
            target_exists = any(t["name"] == target for t in self.target_fields)
            if not target_exists:
                continue

            self.results[idx].target = target
            self.results[idx].confidence = 0.98
            self.results[idx].method = "hard_fingerprint"
            self.results[idx].tier = "HIGH"
            self.results[idx].reason = f"Value pattern match: {hard_match} (data-verified, header-independent)"
            self._resolved_indices.add(idx)
            count += 1

        return count

    # ─── L1: Exact Match ─────────────────────────────────────

    def _l1_exact(self) -> int:
        """Exact match with normalisation + alias expansion."""
        count = 0
        for idx, fp in enumerate(self.fingerprints):
            if idx in self._resolved_indices:
                continue

            source_norm = normalise(fp["matching_name"])

            for target_field in self.target_fields:
                target_norm = normalise(target_field["name"])
                aliases = [normalise(a) for a in target_field.get("aliases", [])]

                if source_norm == target_norm:
                    self.results[idx].target = target_field["name"]
                    self.results[idx].confidence = 1.0
                    self.results[idx].method = "exact"
                    self.results[idx].tier = "HIGH"
                    self.results[idx].reason = f"Exact match: '{source_norm}'"
                    self._resolved_indices.add(idx)
                    count += 1
                    break
                elif source_norm in aliases:
                    self.results[idx].target = target_field["name"]
                    self.results[idx].confidence = 0.98
                    self.results[idx].method = "exact"
                    self.results[idx].tier = "HIGH"
                    self.results[idx].reason = f"Alias match: '{source_norm}' → '{target_field['name']}'"
                    self._resolved_indices.add(idx)
                    count += 1
                    break

        return count

    # ─── L2: Fuzzy + Fingerprint ─────────────────────────────

    def _l2_fuzzy(self) -> int:
        """Fuzzy match with fingerprint-based tie-breaking."""
        try:
            from rapidfuzz import fuzz
        except ImportError:
            # Fallback to stdlib SequenceMatcher
            from difflib import SequenceMatcher
            fuzz = None

        count = 0

        # Collect all fuzzy scores for unresolved columns
        # {target_name: [(col_idx, score, fp)]}
        target_candidates: dict[str, list[tuple[int, float, dict]]] = {}

        for idx, fp in enumerate(self.fingerprints):
            if idx in self._resolved_indices:
                continue

            source_norm = normalise(fp["matching_name"])

            for target_field in self.target_fields:
                target_name = target_field["name"]
                target_dtype = target_field.get("dtype", "string")
                all_names = [normalise(target_field["name"])] + [normalise(a) for a in target_field.get("aliases", [])]

                best_score = 0.0
                for name in all_names:
                    if fuzz:
                        score = fuzz.token_sort_ratio(source_norm, name) / 100.0
                    else:
                        score = SequenceMatcher(None, source_norm, name).ratio()
                    best_score = max(best_score, score)

                if best_score >= 0.65:  # Lower threshold than final — we'll filter with fingerprints
                    if target_name not in target_candidates:
                        target_candidates[target_name] = []
                    target_candidates[target_name].append((idx, best_score, fp))

        # Resolve: for each target, pick the best candidate using fingerprint tie-breaking
        assigned_indices = set()

        for target_name, candidates in target_candidates.items():
            if not candidates:
                continue

            target_field = next((t for t in self.target_fields if t["name"] == target_name), None)
            if not target_field:
                continue

            target_dtype = target_field.get("dtype", "string")

            # Phase A: Filter by dtype compatibility
            compatible = []
            for col_idx, score, fp in candidates:
                if col_idx in assigned_indices or col_idx in self._resolved_indices:
                    continue

                fp_dtype = fp.get("dtype_inferred", "string")

                # Date target needs date-like column
                if target_dtype == "date":
                    if fp.get("looks_like_date") or fp_dtype == "date":
                        compatible.append((col_idx, score, fp))
                # Float target needs numeric column (not date, not string)
                elif target_dtype == "float":
                    if fp_dtype == "float" and not fp.get("looks_like_date"):
                        compatible.append((col_idx, score, fp))
                # String target needs string column
                elif target_dtype == "string":
                    if fp_dtype == "string":
                        compatible.append((col_idx, score, fp))
                    elif fp_dtype == "float" and fp.get("null_pct", 0) > 0.5:
                        # Mostly null numeric column is probably not a good string candidate
                        pass
                    else:
                        compatible.append((col_idx, score, fp))

            if not compatible:
                continue

            # Phase B: Pick best among compatible candidates
            # Sort by fuzzy score, break ties with fingerprint heuristics
            compatible.sort(key=lambda x: x[1], reverse=True)

            # If only one compatible → take it
            if len(compatible) == 1:
                best_idx, best_score, best_fp = compatible[0]
            else:
                # Multiple compatible → use magnitude for amount disambiguation
                if target_dtype == "float" and target_name in ("gross_amount", "amount"):
                    # Gross/primary amount = highest mean
                    compatible.sort(key=lambda x: x[2].get("mean") or 0, reverse=True)
                elif target_dtype == "float" and target_name in ("tds_amount",):
                    # TDS amount = smaller than gross, typically 1-10% of gross
                    compatible.sort(key=lambda x: x[2].get("mean") or float("inf"))
                elif target_dtype == "float" and target_name in ("tax_rate",):
                    # Tax rate = percentage (0-100)
                    compatible = [c for c in compatible if c[2].get("looks_like_percentage")]
                    if not compatible:
                        continue

                best_idx, best_score, best_fp = compatible[0]

            if best_score >= 0.85:
                # Collect alternatives (top 2 other targets this column could match)
                alternatives = []
                for other_target, other_cands in target_candidates.items():
                    if other_target == target_name:
                        continue
                    for oi, os, ofp in other_cands:
                        if oi == best_idx and os >= 0.65:
                            alternatives.append(other_target)
                            break

                self.results[best_idx].target = target_name
                self.results[best_idx].confidence = round(best_score, 2)
                self.results[best_idx].method = "fuzzy"
                self.results[best_idx].tier = _compute_tier(best_score)
                self.results[best_idx].alternatives = alternatives[:3]
                self.results[best_idx].reason = f"Fuzzy match (score={best_score:.2f}) + fingerprint compatible (dtype={best_fp.get('dtype_inferred')})"
                self._resolved_indices.add(best_idx)
                assigned_indices.add(best_idx)
                count += 1

        return count

    # ─── L4: LLM Batch ───────────────────────────────────────

    def _l4_llm(self, unresolved: list[MappingResult]) -> int:
        """Send ALL unresolved columns to LLM in one batch call."""
        if not self.llm or not self.llm.available:
            return 0

        # Build column descriptions with full fingerprint
        col_descriptions = []
        for r in unresolved:
            fp = self.fingerprints[r.col_index]
            desc = (
                f"- Column {r.col_index}: \"{r.source_name}\"\n"
                f"  dtype: {fp.get('dtype_inferred', '?')}, "
                f"samples: {fp.get('sample_values', [])}, "
                f"null%: {fp.get('null_pct', '?')}, "
                f"mean: {fp.get('mean', 'N/A')}\n"
                f"  left: \"{fp.get('left_neighbor', '?')}\", "
                f"right: \"{fp.get('right_neighbor', '?')}\"\n"
                f"  looks_like_date: {fp.get('looks_like_date')}, "
                f"looks_like_pan: {fp.get('looks_like_pan')}, "
                f"looks_like_pct: {fp.get('looks_like_percentage')}"
            )
            col_descriptions.append(desc)

        # Build target field descriptions
        target_desc = "\n".join(
            f"- {t['name']} ({t['dtype']}): {t['description']}"
            for t in self.target_fields
        )

        prompt = (
            f"Map these unresolved columns to target fields.\n\n"
            f"Target fields:\n{target_desc}\n\n"
            f"Unresolved columns:\n" + "\n".join(col_descriptions) + "\n\n"
            f"For each column, respond in JSON:\n"
            f"{{\"mappings\": [\n"
            f"  {{\"col_index\": 0, \"target\": \"field_name_or_null\", "
            f"\"confidence\": 0.0-1.0, \"reason\": \"...\"}}\n"
            f"]}}\n\n"
            f"Use null for target if the column should be skipped (not a required field).\n"
            f"Use the dtype, samples, and neighbor context to make accurate mappings."
        )

        result = self.llm.complete_json(
            prompt,
            system="You are an expert at mapping Excel columns to canonical data fields. "
                   "Use the column data characteristics (dtype, samples, neighbors) to make accurate mappings. "
                   "Be conservative — use null for columns you can't confidently map.",
            agent_name="Column Mapper",
            include_knowledge=False,
        )

        if not result or "mappings" not in result:
            return 0

        count = 0
        for mapping in result["mappings"]:
            col_idx = mapping.get("col_index")
            target = mapping.get("target")
            confidence = mapping.get("confidence", 0.5)
            reason = mapping.get("reason", "LLM mapping")

            if col_idx is None:
                continue

            # Find the result by col_index
            for r in unresolved:
                if r.col_index == col_idx:
                    if target and target != "null":
                        r.target = target
                        r.confidence = confidence
                        r.method = "llm"
                        r.tier = _compute_tier(confidence)
                        r.reason = reason
                        self._resolved_indices.add(col_idx)
                        count += 1
                    else:
                        r.target = "skip"
                        r.confidence = confidence
                        r.method = "llm"
                        r.tier = "HIGH"
                        r.reason = f"LLM: skip — {reason}"
                        self._resolved_indices.add(col_idx)
                        count += 1
                    break

        return count

    # ─── Helpers ──────────────────────────────────────────────

    def _detect_file_type(self) -> str:
        """Auto-detect tds vs ledger from column names."""
        names = " ".join(fp["source_name"].lower() for fp in self.fingerprints)
        if any(kw in names for kw in ["section", "tax deducted", "tds"]):
            return "tds"
        return "ledger"

    def _log(self, message: str):
        """Log to console and optionally SSE."""
        print(f"  [Cascade] {message}")
        if self.events:
            self.events.detail("Column Mapper", message)
