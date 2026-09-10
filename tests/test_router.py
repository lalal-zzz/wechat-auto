from unittest.mock import MagicMock

import pytest

from wechat_auto.engine.router import SkillRouter
from wechat_auto.exceptions import SkillExecutionError


def test_route_registered_skill():
    router = SkillRouter()
    handler = MagicMock(return_value="ok")
    router.register_skill("basic_action", handler)
    assert router.route("basic_action", {"action": "click"}) == "ok"
    handler.assert_called_once_with(action="click")


def test_unknown_action_has_no_fallback():
    with pytest.raises(SkillExecutionError, match="No handler"):
        SkillRouter().route("legacy", {})


def test_handler_failure_is_not_retried_elsewhere():
    router = SkillRouter()
    router.register_skill("basic_action", MagicMock(side_effect=ValueError("bad")))
    with pytest.raises(SkillExecutionError, match="bad"):
        router.route("basic_action", {})
