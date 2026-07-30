"""Structured logging and report generation for the pipeline.

Every pipeline action registers here. The entries go to the console and into
a markdown report at the same time, so that a run stays traceable without
anyone having followed along in the terminal.

Two principles:

* **report-then-raise** - the report is always written before a hard abort
  propagates upwards. Even a failed run leaves a complete protocol behind.
* **compute, don't transcribe** - every number in the report comes from the
  current DataFrame at runtime, never from a plan or an earlier run.

The three stages run as separate scripts but should add up to one shared
report. Each stage therefore drops a JSON fragment; the markdown report is
reassembled from all fragments present. A stage-3 run thus does not erase the
protocol of stages 1 and 2.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils import config

FRAGMENT_DIR = config.REPORTS / ".fragments"

_LABEL_WIDTH = 46
_RULE_WIDTH = 72


class PipelineCheckError(RuntimeError):
    """A hard sanity check has failed."""


def fmt(value: Any) -> str:
    """Numbers with thousands separators, everything else unchanged."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value != value:  # NaN
            return "n/a"
        return f"{value:,.2f}"
    return str(value)


class Reporter:
    """Collects steps, metrics and check results of one pipeline stage."""

    def __init__(self, stage: int, title: str) -> None:
        self.stage = stage
        self.title = title
        self.started_at = datetime.now(timezone.utc)
        self.entries: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []
        self._current_step: str | None = None

        print()
        print("=" * _RULE_WIDTH)
        print(f" STAGE {stage} - {title}")
        print("=" * _RULE_WIDTH)

    # -- Recording ---------------------------------------------------------

    def step(self, name: str) -> None:
        """New work step. All following entries belong to it."""
        self._current_step = name
        self.entries.append({"kind": "step", "name": name})
        print(f"\n> {name}")

    def metric(self, label: str, value: Any, unit: str = "") -> None:
        """One metric of the current step."""
        self.entries.append(
            {"kind": "metric", "step": self._current_step, "label": label, "value": value, "unit": unit}
        )
        shown = fmt(value) + (f" {unit}" if unit else "")
        print(f"    {label:.<{_LABEL_WIDTH}} {shown}")

    def note(self, text: str) -> None:
        """Free-text note, e.g. about an assumption that was made."""
        self.entries.append({"kind": "note", "step": self._current_step, "text": text})
        print(f"    - {text}")

    def check(self, name: str, ok: bool, detail: str = "", hard: bool = True) -> bool:
        """Record the result of a sanity check.

        `hard=True` means: the run must not continue like this. The failure is
        collected but not raised immediately - that way a run gathers all
        violations instead of stopping at the first one. The abort happens at
        the next `raise_on_failures()`.
        """
        entry = {
            "kind": "check",
            "step": self._current_step,
            "name": name,
            "ok": bool(ok),
            "detail": detail,
            "hard": hard,
        }
        self.entries.append(entry)

        if ok:
            marker = "[ok]  "
        elif hard:
            marker = "[FAIL]"
            self.failures.append(entry)
        else:
            marker = "[warn]"

        line = f"  {marker} {name}"
        if detail:
            line += f": {detail}"
        print(line)
        return ok

    # -- Gates -------------------------------------------------------------

    def raise_on_failures(self) -> None:
        """Aborts if hard checks have failed since the last gate."""
        if not self.failures:
            return
        names = ", ".join(f["name"] for f in self.failures)
        raise PipelineCheckError(f"{len(self.failures)} hard sanity checks failed: {names}")

    # -- Output ------------------------------------------------------------

    def _fragment(self, status: str, error: str | None) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "title": self.title,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": status,
            "error": error,
            "entries": self.entries,
            "n_failures": len(self.failures),
        }

    def finish(self, status: str = "ok", error: str | None = None) -> None:
        """Write the fragment and reassemble the combined report."""
        FRAGMENT_DIR.mkdir(parents=True, exist_ok=True)
        fragment = self._fragment(status, error)
        path = FRAGMENT_DIR / f"stage{self.stage}.json"
        # default=str so that date and numpy values from metrics do not fail
        # serialisation - the report must never die on its own output.
        path.write_text(
            json.dumps(fragment, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )

        write_combined_report()

        print()
        print("-" * _RULE_WIDTH)
        if status == "ok":
            print(f" Stage {self.stage} completed. Report: {_rel(config.DATA_PREP_REPORT_MD)}")
        else:
            print(f" Stage {self.stage} FAILED. Report: {_rel(config.DATA_PREP_REPORT_MD)}")
        print("-" * _RULE_WIDTH)

    # -- Context manager (report-then-raise) -------------------------------

    def __enter__(self) -> "Reporter":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.finish("ok")
        else:
            self.finish("failed", f"{exc_type.__name__}: {exc}")
        return False  # propagate the exception


# --------------------------------------------------------------------------
# Combined report
# --------------------------------------------------------------------------


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(config.ROOT))
    except ValueError:
        return str(path)


def _render_stage(fragment: dict[str, Any]) -> list[str]:
    lines = [f"## Stage {fragment['stage']} - {fragment['title']}", ""]

    status = fragment["status"]
    badge = "successful" if status == "ok" else "**FAILED**"
    lines.append(f"_Run: {fragment['finished_at']} UTC - status: {badge}_")
    if fragment.get("error"):
        lines += ["", f"> Abort reason: `{fragment['error']}`"]
    lines.append("")

    metrics: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []

    def flush_step() -> None:
        if metrics:
            lines.append("| Metric | Value |")
            lines.append("|---|---|")
            for m in metrics:
                shown = fmt(m["value"]) + (f" {m['unit']}" if m["unit"] else "")
                lines.append(f"| {m['label']} | {shown} |")
            lines.append("")
            metrics.clear()
        for n in notes:
            lines.append(f"- {n['text']}")
        if notes:
            lines.append("")
            notes.clear()
        for c in checks:
            if c["ok"]:
                mark = "ok"
            elif c["hard"]:
                mark = "**FAIL**"
            else:
                mark = "_warn_"
            detail = f" - {c['detail']}" if c["detail"] else ""
            lines.append(f"- [{mark}] {c['name']}{detail}")
        if checks:
            lines.append("")
            checks.clear()

    for entry in fragment["entries"]:
        kind = entry["kind"]
        if kind == "step":
            flush_step()
            lines += [f"### {entry['name']}", ""]
        elif kind == "metric":
            metrics.append(entry)
        elif kind == "check":
            checks.append(entry)
        elif kind == "note":
            notes.append(entry)

    flush_step()
    return lines


def write_combined_report() -> None:
    """Reassembles reports/data_prep_report.md from all stage fragments."""
    config.REPORTS.mkdir(parents=True, exist_ok=True)

    fragments = []
    for stage in (1, 2, 3):
        path = FRAGMENT_DIR / f"stage{stage}.json"
        if path.exists():
            fragments.append(json.loads(path.read_text(encoding="utf-8")))

    lines = [
        "# Data Preparation Report",
        "",
        "_Generated automatically. Every number comes from the respective run, not from the plan._",
        "_Produced by `utils/reporting.py`; configuration in `utils/config.py`, reasoning in `docs/Project_Plan.md`._",
        "",
    ]

    if not fragments:
        lines += ["No run recorded yet.", ""]
    else:
        lines += ["| Stage | Title | Status | Run (UTC) |", "|---|---|---|---|"]
        for f in fragments:
            status = "ok" if f["status"] == "ok" else "**FAILED**"
            lines.append(f"| {f['stage']} | {f['title']} | {status} | {f['finished_at']} |")
        lines.append("")
        for f in fragments:
            lines += ["---", ""]
            lines += _render_stage(f)

    config.DATA_PREP_REPORT_MD.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_quality_report(payload: dict[str, Any]) -> None:
    """Machine-readable counterpart to the markdown report (for regression checks)."""
    config.INTERIM.mkdir(parents=True, exist_ok=True)
    config.QUALITY_REPORT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
