from wechat_auto.primitives.profile_fields import extract_profile_fields
from wechat_auto.storage import ProfileStore


def box(text, x, y, w=100):
    return {'text': text, 'x': x, 'y': y, 'w': w, 'h': 20, 'score': .95}


def test_explicit_fields_exclude_contact_list_and_ambiguous_rows():
    data = [box('个性签名：旧的列表文字', 20, 30), box('微信号：alias1', 500, 30),
            box('个性签名', 500, 100), box('本周认真工作', 650, 100),
            box('地区', 500, 150), box('某地', 650, 150), box('其他按钮', 800, 150)]
    result = extract_profile_fields(data, (1000, 800), [.4, 0, 1, 1])
    assert result['fields'] == {'alias': 'alias1', 'signature': '本周认真工作'}
    assert 'region' in result['unobserved_fields']


def test_partial_enrichment_retains_old_fields_and_is_idempotent(tmp_path):
    with ProfileStore(tmp_path / 'profiles.db') as store:
        store.save({'wechat_id': 'wxid_test_1', 'alias': 'alias1', 'signature': '旧签名', 'remark': '旧备注'}, profile_type='contact')
        result = store.record_ui_observation('wxid_test_1', {'signature': '新签名', 'region': '某地'}, evidence_ref='local.png')
        assert result['snapshot_created']
        assert store.get('wxid_test_1')['remark'] == '旧备注'
        assert store.get('wxid_test_1')['region'] == '某地'
        before = len(store.history('wxid_test_1'))
        assert not store.record_ui_observation('wxid_test_1', {'signature': '新签名', 'region': '某地'}, evidence_ref='new.png')['snapshot_created']
        assert len(store.history('wxid_test_1')) == before
