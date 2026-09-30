import pytest

from wechat_auto.actions.contracts import LayoutProfile
from wechat_auto.actions.semantics import PageId, semantic_key


def test_semantic_ids_are_stable_and_layout_points_are_explicit():
    key = semantic_key(PageId.CONTACT_MORE, 3)
    assert key == "22.03:delete_contact"
    profile = LayoutProfile(
        "4.1.13.12", 1000, 800,
        elements={key: [.8, .7]},
    )
    assert profile.point_for(22, 3) == (.8, .7)
    with pytest.raises(RuntimeError, match="not calibrated"):
        profile.point_for(21, 9)


def test_unknown_semantic_element_is_rejected():
    with pytest.raises(ValueError, match="Unknown semantic element"):
        semantic_key(22, 99)
