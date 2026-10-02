import asyncio
import json
from unittest.mock import MagicMock


def _call(server, name, arguments):
    result = asyncio.run(server.call_tool(name, arguments))
    return result.structured_content or json.loads(result.content[0].text)

from wechat_auto.mcp_server import create_server
from wechat_auto.storage import ProfileStore


def test_verified_profile_capture_indexes_new_snapshot(tmp_path):
    path = tmp_path / 'profiles.db'
    with ProfileStore(path) as profiles:
        profiles.save({'wechat_id': 'wxid_test_one', 'alias': 'alias1'}, profile_type='contact')
        profiles.record_ui_observation('wxid_test_one', {'signature': 'explicit signature'}, evidence_ref='local.png')
    basic = MagicMock()
    basic.capture_contact_profile.return_value = {'success': True, 'observed_fields': ['signature']}
    server = create_server(memory_db=str(tmp_path / 'memory.db'), memory_root=str(tmp_path / 'memory'), basic_skill=basic)
    try:
        result = _call(server, 'sync.capture_contact_profile',
                       {'wechat_id': 'wxid_test_one', 'expected_alias': 'alias1', 'database_path': str(path)})
        basic.capture_contact_profile.assert_called_once_with('wxid_test_one', 'alias1', str(path))
        assert result['indexing']['snapshots_seen'] == 2
    finally:
        server._wechat_auto_store.close()
