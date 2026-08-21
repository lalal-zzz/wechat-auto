"""Tests for SkillRouter engine module (unit tests with mocks)."""

from unittest.mock import MagicMock, patch

import pytest

from wechat_auto.engine.router import SkillRouter
from wechat_auto.exceptions import SkillExecutionError, AtomicToolError


class TestSkillRouter:
    def test_init(self):
        router = SkillRouter()
        assert router.available_skills == []
        assert router._atomic_tools is None

    def test_register_skill(self):
        router = SkillRouter()
        handler = MagicMock(return_value="ok")
        router.register_skill("test_skill", handler)
        assert "test_skill" in router.available_skills

    def test_set_atomic_tools(self):
        router = SkillRouter()
        mock_tools = MagicMock()
        router.set_atomic_tools(mock_tools)
        assert router._atomic_tools is mock_tools

    def test_route_tier1_success(self):
        router = SkillRouter()
        handler = MagicMock(return_value="result")
        router.register_skill("send_text", handler)

        result = router.route("send_text", {"contact": "张三", "message": "hi"})
        assert result == "result"
        handler.assert_called_once_with(contact="张三", message="hi")

    def test_route_tier1_failure_degrades_to_tier2(self):
        router = SkillRouter()
        handler = MagicMock(side_effect=RuntimeError("tier1 failed"))
        router.register_skill("click", handler)

        mock_tools = MagicMock()
        mock_tools.click = MagicMock(return_value="tier2_ok")
        router.set_atomic_tools(mock_tools)

        result = router.route("click", {"component_id": "btn1"})
        assert result == "tier2_ok"
        mock_tools.click.assert_called_once()

    def test_route_unknown_intent_no_atomic(self):
        router = SkillRouter()
        with pytest.raises(SkillExecutionError, match="No handler"):
            router.route("nonexistent", {})

    def test_route_both_tiers_fail(self):
        router = SkillRouter()
        handler = MagicMock(side_effect=RuntimeError("tier1"))
        router.register_skill("click", handler)

        mock_tools = MagicMock()
        mock_tools.click = MagicMock(side_effect=RuntimeError("tier2"))
        router.set_atomic_tools(mock_tools)

        with pytest.raises(SkillExecutionError, match="Both Tier 1 and Tier 2 failed"):
            router.route("click", {"component_id": "btn"})

    def test_send_failure_does_not_degrade_to_atomic_tools(self):
        router = SkillRouter()
        handler = MagicMock(side_effect=RuntimeError("exact recipient not found"))
        router.register_skill("send_text_message", handler)
        mock_tools = MagicMock()
        router.set_atomic_tools(mock_tools)

        with pytest.raises(SkillExecutionError, match="Tier 1 skill 'send_text_message' failed"):
            router.route("send_text_message", {"contact": "文件传输助手", "message": "test"})

        mock_tools.click.assert_not_called()

    def test_route_atomic_direct(self):
        """Test routing directly to atomic tools when no tier1 match."""
        router = SkillRouter()
        mock_tools = MagicMock()
        mock_tools.scroll = MagicMock(return_value=None)
        router.set_atomic_tools(mock_tools)

        router.route("scroll", {"component_id": "list1", "direction": "down", "distance": 3})
        mock_tools.scroll.assert_called_once_with(component_id="list1", direction="down", distance=3)

    def test_route_unknown_atomic_intent(self):
        router = SkillRouter()
        mock_tools = MagicMock()
        router.set_atomic_tools(mock_tools)

        # Unknown intent that's not a known atomic tool name raises
        # SkillExecutionError (wrapping AtomicToolError)
        with pytest.raises(SkillExecutionError, match="Unknown atomic intent"):
            router.route("nonexistent_atomic", {})

    def test_available_skills_property(self):
        router = SkillRouter()
        router.register_skill("skill_a", MagicMock())
        router.register_skill("skill_b", MagicMock())
        skills = router.available_skills
        assert "skill_a" in skills
        assert "skill_b" in skills
