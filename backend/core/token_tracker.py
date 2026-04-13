"""Token usage tracker — persists to JSON file."""

import json
import os
import time
from datetime import datetime, timedelta
from threading import Lock
from pathlib import Path
from utils.logger import log

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
USAGE_FILE = DATA_DIR / "token_usage.json"


class TokenTracker:
    """Tracks LLM token usage per call, persisted to disk."""

    def __init__(self):
        self._lock = Lock()
        self._records: list[dict] = []
        self._load()

    def _load(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if USAGE_FILE.exists():
            try:
                with open(USAGE_FILE, "r", encoding="utf-8") as f:
                    self._records = json.load(f)
                log.info("token_tracker_loaded", records=len(self._records))
            except Exception as e:
                log.warning("token_tracker_load_failed", error=str(e))
                self._records = []

    def _save(self):
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(USAGE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._records, f, ensure_ascii=False)
        except Exception as e:
            log.warning("token_tracker_save_failed", error=str(e))

    def record(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        feature: str = "",  # e.g. "simulation", "db_chat", "persona_chat"
    ):
        """Record a single LLM call's token usage."""
        entry = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "provider": provider,
            "model": model,
            "input": input_tokens,
            "output": output_tokens,
            "total": total_tokens,
            "feature": feature,
        }
        with self._lock:
            self._records.append(entry)
            # Batch save every 10 records
            if len(self._records) % 10 == 0:
                self._save()

        log.info("token_recorded",
                 provider=provider, model=model,
                 input=input_tokens, output=output_tokens, total=total_tokens)

    def flush(self):
        """Force save to disk."""
        with self._lock:
            self._save()

    def get_summary(
        self,
        days: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        """Get usage summary, optionally filtered by date range.

        Args:
            days: Last N days (convenience shortcut)
            date_from: ISO date string "2024-01-01"
            date_to: ISO date string "2024-12-31"
        """
        with self._lock:
            records = list(self._records)

        # Date filtering
        if days is not None:
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
            records = [r for r in records if r["ts"] >= cutoff]
        else:
            if date_from:
                records = [r for r in records if r["ts"] >= date_from]
            if date_to:
                # Include the full day
                records = [r for r in records if r["ts"] <= date_to + "T23:59:59Z"]

        # Aggregate
        total_input = sum(r.get("input", 0) for r in records)
        total_output = sum(r.get("output", 0) for r in records)
        total_tokens = sum(r.get("total", 0) for r in records)
        call_count = len(records)

        # By model
        by_model: dict[str, dict] = {}
        for r in records:
            key = f"{r['provider']}/{r['model']}"
            if key not in by_model:
                by_model[key] = {"input": 0, "output": 0, "total": 0, "calls": 0}
            by_model[key]["input"] += r.get("input", 0)
            by_model[key]["output"] += r.get("output", 0)
            by_model[key]["total"] += r.get("total", 0)
            by_model[key]["calls"] += 1

        # By feature
        by_feature: dict[str, dict] = {}
        for r in records:
            feat = r.get("feature", "unknown") or "unknown"
            if feat not in by_feature:
                by_feature[feat] = {"input": 0, "output": 0, "total": 0, "calls": 0}
            by_feature[feat]["input"] += r.get("input", 0)
            by_feature[feat]["output"] += r.get("output", 0)
            by_feature[feat]["total"] += r.get("total", 0)
            by_feature[feat]["calls"] += 1

        # By date (daily breakdown)
        by_date: dict[str, dict] = {}
        for r in records:
            day = r["ts"][:10]  # "2024-01-15"
            if day not in by_date:
                by_date[day] = {"input": 0, "output": 0, "total": 0, "calls": 0}
            by_date[day]["input"] += r.get("input", 0)
            by_date[day]["output"] += r.get("output", 0)
            by_date[day]["total"] += r.get("total", 0)
            by_date[day]["calls"] += 1

        return {
            "total_input": total_input,
            "total_output": total_output,
            "total_tokens": total_tokens,
            "call_count": call_count,
            "by_model": by_model,
            "by_feature": by_feature,
            "by_date": dict(sorted(by_date.items())),
        }

    def get_recent(self, limit: int = 50) -> list[dict]:
        """Get most recent usage records."""
        with self._lock:
            return list(reversed(self._records[-limit:]))

    def clear(self):
        """Clear all records."""
        with self._lock:
            self._records = []
            self._save()


# Singleton
token_tracker = TokenTracker()
