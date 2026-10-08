import pytest

from wechat_auto.memory.partition import AnalysisBudget, plan_analysis


def test_sparse_year_shares_worker_and_dense_month_has_exact_core_coverage():
    months = {f"2025-{m:02d}": [{"readable": "短句"}] for m in range(1, 13)}
    plan = plan_analysis(months)
    assert len(plan["jobs"]) == 1
    assert len(plan["jobs"][0]["blocks"]) == 12
    dense = [{"readable": "长" * 40} for _ in range(17)]
    plan = plan_analysis({"2026-01": dense}, AnalysisBudget(5, 120, 12, 2))
    covered = []
    for job in plan["jobs"]:
        block = job["blocks"][0]
        a, b = block["core"]
        covered.extend(range(a, b + 1))
        assert job["records"] <= 5 and job["text_chars"] <= 120
        assert block["context"][0] <= a <= b <= block["context"][1]
    assert covered == list(range(1, 18))
    assert plan["status"] == "planned_not_read"


def test_gap_and_oversized_single_message_are_explicit():
    plan = plan_analysis({"2024-01": [{"readable": "a"}],
                          "2024-03": [{"readable": "b" * 300}]}, AnalysisBudget(10, 100))
    assert len(plan["jobs"]) == 2
    assert plan["jobs"][1]["blocks"][0]["oversized_message"]
    assert plan["jobs"][1]["blocks"][0]["core"] == [1, 1]
    with pytest.raises(ValueError):
        AnalysisBudget(max_records=0)


def test_card_quote_text_affects_budget_without_media_attributes():
    card = {'readable': '[卡片]', 'content': '<msg><title>' + '长' * 80 + '</title></msg>'}
    media = {'readable': '<msg><emoji encryptedkey="' + 'x' * 300 + '" /></msg>'}
    plan = plan_analysis({'2025-01': [card, card, media]}, AnalysisBudget(10, 100))
    assert len(plan['jobs']) == 2
    assert plan['jobs'][0]['records'] == 1
    assert plan['jobs'][1]['text_chars'] < 100
    broken = plan_analysis({'2025-01': [{'readable': '[卡片]', 'content': '<msg>broken'}]})
    assert broken['parsing_gaps'] == [{'period': '2025-01', 'ordinals': [1]}]
