import pytest

from wechat_auto.memory.report_visuals import render_visuals


def spec():
    return {"source_versions": [{"scope_type": "conversation", "scope_id": "test",
                                 "period": "2025-01", "version": 2, "content_hash": "hash"}],
            "panels": [{"type": "relationships", "title": "各自描述的人际关系",
                        "items": [{"owner": "本人", "label": "本人的朋友",
                                   "detail": "朋友喜欢茶", "status": "observed",
                                   "source_excerpt": "本人描述朋友喜欢茶"},
                                  {"owner": "联系人", "label": "联系人的朋友",
                                   "detail": "另一位朋友喜欢音乐", "status": "observed",
                                   "source_excerpt": "联系人描述朋友喜欢音乐"}]}]}


def test_graph_keeps_scoped_owners_and_bound_prose():
    sources = {("conversation", "test", "2025-01"): (2, "hash", "本人描述朋友喜欢茶；联系人描述朋友喜欢音乐")}
    html = render_visuals(spec(), sources)
    assert html.count('class="visual-group"') == 2
    assert "本人的朋友" in html and "联系人的朋友" in html
    assert "正文依据" in html
    changed = spec()
    changed["source_versions"][0]["version"] = 1
    with pytest.raises(ValueError, match="version/hash"):
        render_visuals(changed, sources)
    changed = spec()
    changed["panels"][0]["items"][0]["source_excerpt"] = "不存在的事实"
    with pytest.raises(ValueError, match="exact excerpt"):
        render_visuals(changed, sources)


def test_timeline_keeps_date_precision_and_escapes_labels():
    value = spec()
    value["panels"][0]["type"] = "timeline"
    value["panels"][0]["items"] = [{"date": "2025年1月（具体日未知）", "label": "<script>bad</script>",
                                     "source_excerpt": "计划尚未落实", "status": "unknown"}]
    html = render_visuals(value, {("conversation", "test", "2025-01"): (2, "hash", "计划尚未落实")})
    assert "2025年1月（具体日未知）" in html
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_activity_counts_are_bound_and_cannot_be_negative_or_scores():
    value = spec()
    value['panels'][0] = {'type': 'activity', 'title': '消息数量', 'items': [
        {'label': '2025-01', 'value': 10, 'source_excerpt': '2025-01共10条'},
        {'label': '2025-02', 'value': 0, 'source_excerpt': '2025-02共0条'}]}
    sources = {('conversation', 'test', '2025-01'): (2, 'hash', '2025-01共10条；2025-02共0条')}
    html = render_visuals(value, sources)
    assert html.count('<rect ') == 2 and 'height="0.00"' in html
    assert '数量不代表感情' in html
    for invalid in (-1, .8, True):
        value['panels'][0]['items'][0]['value'] = invalid
        with pytest.raises(ValueError, match='nonnegative integers'):
            render_visuals(value, sources)
