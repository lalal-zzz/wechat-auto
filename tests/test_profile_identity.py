from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from wechat_auto.backends.profile import DatabaseProfileBackend


def test_public_alias_never_becomes_nickname_or_local_identity():
    profile = DatabaseProfileBackend._normalize({'username': 'wxid_test', 'alias': 'public-test'})
    assert profile['wechat_id'] == 'wxid_test' and profile['alias'] == 'public-test'
    assert profile['nickname'] == '' and profile['nickname_core'] == ''
    assert profile['display_name'] == 'wxid_test'


@pytest.mark.parametrize('record', [
    {'username': 'wxid_other'}, {'alias': 'wxid_test'},
    {'wechat_id': 'wxid_test', 'username': 'wxid_other'},
])
@pytest.mark.parametrize('mode', ['method', 'search'])
def test_contact_lookup_requires_exact_consistent_stable_identity(record, mode):
    db = SimpleNamespace(get_profile=(lambda username: record)) if mode == 'method' else SimpleNamespace(search_contact=lambda query: [record])
    with pytest.raises(ValueError):
        DatabaseProfileBackend(db).get_contact_profile('wxid_test')


@pytest.mark.parametrize('record', [{'username': 'wxid_other'}, {'nickname': 'me'}])
def test_self_profile_fallback_cannot_cross_known_account_identity(record):
    db = SimpleNamespace(wxid='wxid_test', get_self_profile=lambda: record)
    with pytest.raises(ValueError):
        DatabaseProfileBackend(db).get_self_profile()


@pytest.mark.parametrize('records', [[{'username': 'wxid_test', 'local_type': 3}, None], {'rows': []}])
def test_malformed_contact_collection_is_not_silently_a_partial_success(records, tmp_path):
    path = tmp_path / 'profiles.sqlite3'
    db = SimpleNamespace(get_contacts=lambda: records)
    with pytest.raises(ValueError):
        DatabaseProfileBackend(db).archive_all_contact_profiles(str(path))
    assert not path.exists()


def test_valid_profile_lookup_and_cached_only_archive(tmp_path):
    db = SimpleNamespace(get_profile=lambda username: {'username': username, 'alias': 'public-test'},
                         get_contacts=lambda: [{'username': 'wxid_test', 'local_type': 3, 'nick_name': 'synthetic'}])
    backend = DatabaseProfileBackend(db)
    assert backend.get_contact_profile('wxid_test')['wechat_id'] == 'wxid_test'
    result = backend.archive_all_contact_profiles(str(tmp_path / 'profiles.sqlite3'))
    assert result['snapshots_saved'] == 1
    assert result['coverage_status'] == 'cached_only'
    assert not result['server_contacts_complete']


def test_profile_sql_schema_failure_still_closes_connection():
    import sqlite3
    connection = MagicMock()
    connection.execute.side_effect = sqlite3.OperationalError('synthetic schema error')
    backend = DatabaseProfileBackend(SimpleNamespace(_contact_conn=lambda: connection))
    assert backend._contact_row('wxid_test') is None
    connection.close.assert_called_once()


def test_exact_stable_search_candidate_is_selected_among_unrelated_names():
    db = SimpleNamespace(search_contact=lambda query: [
        {'username': 'wxid_other', 'nickname': 'same'},
        {'username': 'wxid_test', 'nickname': 'same'},
    ])
    assert DatabaseProfileBackend(db).get_contact_profile('wxid_test')['wechat_id'] == 'wxid_test'


def test_duplicate_stable_search_matches_are_ambiguous():
    db = SimpleNamespace(search_contact=lambda query: [{'username': 'wxid_test'}, {'wxid': 'wxid_test'}])
    with pytest.raises(ValueError, match='exactly one stable'):
        DatabaseProfileBackend(db).get_contact_profile('wxid_test')


@pytest.mark.parametrize('record', [{'username': 123}, {'username': '  '},
                                    {'wxid': 'wxid_test', 'username': 'wxid_other'}])
def test_invalid_local_identity_fields_are_not_coerced_or_silently_preferred(record):
    with pytest.raises(ValueError):
        DatabaseProfileBackend._normalize(record)


def test_whitespace_normalization_preserves_alias_as_separate_field():
    profile = DatabaseProfileBackend._normalize({'wxid': ' wxid_test ', 'username': 'wxid_test',
                                                 'alias': 'public-test', 'nickname': 'synthetic'})
    assert profile['wechat_id'] == 'wxid_test' and profile['alias'] == 'public-test'
    assert profile['nickname'] == 'synthetic'


def test_mismatched_profile_is_rejected_before_archive_creation(tmp_path):
    db = SimpleNamespace(get_profile=lambda username: {'username': 'wxid_other'})
    path = tmp_path / 'profiles.sqlite3'
    with pytest.raises(ValueError):
        DatabaseProfileBackend(db).archive_contact_profile('wxid_test', str(path))
    assert not path.exists()
