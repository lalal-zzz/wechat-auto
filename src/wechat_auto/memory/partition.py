"""Plan bounded chronological agent work without treating traversal as analysis."""
from __future__ import annotations

from dataclasses import dataclass

from wechat_auto.memory.reading import readable_message


@dataclass(frozen=True)
class AnalysisBudget:
    max_records: int = 3000
    max_text_chars: int = 60000
    max_months: int = 12
    context_records: int = 12

    def __post_init__(self):
        if min(self.max_records, self.max_text_chars, self.max_months) < 1 or self.context_records < 0:
            raise ValueError("analysis budgets must be positive; context must be nonnegative")


def plan_analysis(months: dict[str, list[dict]], budget: AnalysisBudget | None = None) -> dict:
    """Sparse adjacent months share a worker; dense months retain distinct core blocks.

    Character budgets include available local card/quote natural text, excluding
    media XML attributes. Parsing gaps are flagged and require reader inspection.
    Overlap is context only and never contributes to completed core coverage.
    A single oversized message is marked for an explicit continuation by its reader.
    No semantic completeness or execution capability is implied by this plan.
    """
    budget = budget or AnalysisBudget()
    jobs, pending, parsing_gaps = [], [], []
    pending_records = pending_chars = 0

    def flush():
        nonlocal pending, pending_records, pending_chars
        if pending:
            jobs.append({"blocks": pending, "records": pending_records,
                         "text_chars": pending_chars, "status": "pending"})
            pending, pending_records, pending_chars = [], 0, 0

    previous_month = None
    for period, rows in sorted(months.items()):
        year, month = map(int, period.split("-"))
        if not 1 <= month <= 12:
            raise ValueError("invalid calendar month")
        month_number = year * 12 + month
        if previous_month is not None and month_number != previous_month + 1:
            flush()
        previous_month = month_number
        extracted = [readable_message(row) for row in rows]
        gap_ordinals = [index for index, (_, gaps) in enumerate(extracted, 1) if gaps]
        if gap_ordinals:
            parsing_gaps.append({"period": period, "ordinals": gap_ordinals})
        lengths = [sum(len(part) for part in parts) for parts, _ in extracted]
        total = sum(lengths)
        if not rows:
            flush()
            jobs.append({"blocks": [{"period": period, "core": None, "context": None}],
                         "records": 0, "text_chars": 0, "status": "empty_source"})
            continue
        if len(rows) <= budget.max_records and total <= budget.max_text_chars:
            if (pending_records + len(rows) > budget.max_records or
                    pending_chars + total > budget.max_text_chars or len(pending) >= budget.max_months):
                flush()
            pending.append({"period": period, "core": [1, len(rows)],
                            "context": [1, len(rows)], "oversized_message": False})
            pending_records += len(rows)
            pending_chars += total
            continue
        flush()
        start = 0
        while start < len(rows):
            end, chars = start, 0
            while end < len(rows) and end - start < budget.max_records:
                if end > start and chars + lengths[end] > budget.max_text_chars:
                    break
                chars += lengths[end]
                end += 1
            jobs.append({"blocks": [{"period": period, "core": [start + 1, end],
                         "context": [max(1, start + 1 - budget.context_records),
                                     min(len(rows), end + budget.context_records)],
                         "oversized_message": any(n > budget.max_text_chars for n in lengths[start:end])}],
                         "records": end - start, "text_chars": chars, "status": "pending"})
            start = end
    flush()
    for index, job in enumerate(jobs, 1):
        job["job_id"] = f"shard-{index:04d}"
    return {"template": "analysis-quality-v7", "status": "planned_not_read",
            "text_measurement": "natural_text_including_local_cards_and_quotes",
            "parsing_gaps": parsing_gaps,
            "budget": vars(budget), "months": len(months),
            "records": sum(len(rows) for rows in months.values()), "jobs": jobs,
            "acceptance": "each month requires complete core reading and independent subject/relation review"}
