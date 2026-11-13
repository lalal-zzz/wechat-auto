from unittest.mock import MagicMock, patch

import pytest

from wechat_auto.actions.basic import BasicSkill
from wechat_auto.exceptions import ChatNotFoundError


def fixture(mock_app,config,session):
    skill=BasicSkill(mock_app,config,session)
    mock_app.handle=1
    metadata={'hwnd':1,'pid':2,'rect':[0,0,1000,800],'client_rect':[0,0,1000,800],'dpi':96}
    mock_app.describe_window.return_value=metadata
    mock_app.list_windows.return_value=[{'is_main':True}]
    mock_app.for_window.return_value.handle=3
    pending={'username':'wxid_test_test','query':'测试联系人','metadata':metadata}
    auxiliary=[{'hwnd':3,'pid':2,'owner_hwnd':0,'class':'Qt51514QWindowToolSaveBits'}]
    skill._vision_auto=MagicMock()
    skill.vision.observe_page.return_value={'ok':True,'state':{'regions':{'conversation_header':[{'text':'测试联系人'}]}}}
    skill.page_operation=MagicMock(return_value={'success':True})
    skill.close_private_chat_details=MagicMock(return_value={'success':True})
    observer=MagicMock()
    observer.observe_page.return_value={'ok':True,'state':{'page':'contact_profile'},'boxes':[]}
    return skill,pending,auxiliary,observer


def test_ownerless_same_process_profile_closes_via_root_and_renews_identity(mock_app,config,session):
    skill,pending,auxiliary,observer=fixture(mock_app,config,session)
    skill._verify_contact_alias=MagicMock()
    with patch('wechat_auto.primitives.vision.VisionAutomation',return_value=observer):
        result=skill._finish_searched_contact_alias('alias_test',pending,auxiliary)
    assert result['identity_verified']
    skill.page_operation.assert_called_once_with('close',hwnd=3,expected_page='contact_profile',max_attempts=1)
    skill._verify_contact_alias.assert_called_once_with('alias_test',observer=observer)
    assert skill._recipient_lease['username']=='wxid_test_test'


def test_wrong_alias_never_closes_or_renews_sender_lease(mock_app,config,session):
    skill,pending,auxiliary,observer=fixture(mock_app,config,session)
    skill._verify_contact_alias=MagicMock(side_effect=ChatNotFoundError('Mismatch'))
    with patch('wechat_auto.primitives.vision.VisionAutomation',return_value=observer), \
            pytest.raises(ChatNotFoundError):
        skill._finish_searched_contact_alias('alias_test',pending,auxiliary)
    skill.page_operation.assert_not_called()
    assert not getattr(skill,'_recipient_lease',None)


def test_foreign_profile_window_is_rejected_before_observation(mock_app,config,session):
    skill,pending,auxiliary,_observer=fixture(mock_app,config,session)
    auxiliary[0]['pid']=99
    with pytest.raises(RuntimeError,match='same-process'):
        skill._finish_searched_contact_alias('alias_test',pending,auxiliary)
    skill.page_operation.assert_not_called()
