import pytest

from wechat_auto.actions.semantics import PageId, semantic_key


def test_semantic_ids_are_meanings_not_static_coordinates():
    assert semantic_key(PageId.CONTACT_MORE, 3) == '22.03:delete_contact'


def test_unknown_semantic_element_is_rejected():
    with pytest.raises(ValueError, match="Unknown semantic element"):
        semantic_key(22, 99)
