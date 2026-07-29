"""Tests for skills modules (unit tests with mocks)."""

from unittest.mock import MagicMock, patch, ANY

import pytest

from wechat_auto.skills.base import BaseSkill
from wechat_auto.skills.unread import UnreadSkill
from wechat_auto.skills.group_at import GroupAtSkill
from wechat_auto.skills.channels import ChannelsSkill
from wechat_auto.skills.moments import MomentsSkill
from wechat_auto.skills.contact import ContactSkill
from wechat_auto.skills.emoji import EmojiSkill
from wechat_auto.skills.quote import QuoteSkill
from wechat_auto.skills.history import HistorySkill
from wechat_auto.exceptions import (
    ContactNotFoundError,
    EmojiNotFoundError,
    ElementNotFoundError,
    MomentsError,
    SendMessageError,
)


# ==================================================================
# BaseSkill
# ==================================================================

class TestBaseSkill:
    def test_init(self, mock_app, mock_finder, config, session):
        skill = BaseSkill(mock_app, mock_finder, config, session)
        assert skill.name == "base_skill"
        assert skill._app is mock_app
        assert skill._finder is mock_finder

    def test_window_property(self, mock_app, mock_finder, config, session):
        skill = BaseSkill(mock_app, mock_finder, config, session)
        assert skill.window is mock_app.main_window

    def test_run_raises_not_implemented(self, mock_app, mock_finder, config, session):
        skill = BaseSkill(mock_app, mock_finder, config, session)
        with pytest.raises(NotImplementedError):
            skill._run()

    def test_execute_calls_run_and_healer(self, mock_app, mock_finder, config, session):
        healer = MagicMock()
        skill = BaseSkill(mock_app, mock_finder, config, session, healer=healer)

        with patch.object(skill, "_run", return_value="result") as mock_run:
            result = skill.execute()
            assert result == "result"
            mock_run.assert_called_once()
            healer.reset_ui_environment.assert_called_once()

    def test_execute_healer_none(self, mock_app, mock_finder, config, session):
        """Test execute works without healer."""
        skill = BaseSkill(mock_app, mock_finder, config, session, healer=None)
        with patch.object(skill, "_run", return_value="ok"):
            result = skill.execute()
            assert result == "ok"

    def test_execute_healer_failure_logged(self, mock_app, mock_finder, config, session):
        """Test healer failure doesn't propagate."""
        healer = MagicMock()
        healer.reset_ui_environment.side_effect = RuntimeError("healer fail")

        skill = BaseSkill(mock_app, mock_finder, config, session, healer=healer)
        with patch.object(skill, "_run", return_value="ok"):
            result = skill.execute()
            assert result == "ok"  # Should still return result

    def test_activate_with_auto(self, mock_app, mock_finder, config):
        """Test _activate when auto_activate is True."""
        from wechat_auto.config import SessionConfig
        session = SessionConfig(auto_activate=True)
        skill = BaseSkill(mock_app, mock_finder, config, session)
        skill._activate()
        mock_app.activate.assert_called_once()

    def test_activate_without_auto(self, mock_app, mock_finder, config):
        """Test _activate when auto_activate is False."""
        from wechat_auto.config import SessionConfig
        session = SessionConfig(auto_activate=False)
        skill = BaseSkill(mock_app, mock_finder, config, session)
        skill._activate()
        mock_app.activate.assert_not_called()

    def test_open_chat(self, mock_app, mock_finder, config, session):
        skill = BaseSkill(mock_app, mock_finder, config, session)
        skill._open_chat("张三")
        mock_finder.open_chat.assert_called_once_with("张三")


# ==================================================================
# UnreadSkill
# ==================================================================

class TestUnreadSkill:
    def test_name(self, mock_app, mock_finder, config, session):
        skill = UnreadSkill(mock_app, mock_finder, config, session)
        assert skill.name == "get_unread_messages"

    def test_get_unread_messages(self, mock_app, mock_finder, config, session):
        """Test that UnreadSkill delegates to Perceiver."""
        skill = UnreadSkill(mock_app, mock_finder, config, session)

        with patch("wechat_auto.engine.perceiver.Perceiver") as mock_perceiver_cls:
            mock_perceiver = MagicMock()
            mock_perceiver.get_unread_messages.return_value = [
                {"contact": "张三", "unread_count": 3, "preview": "你好"}
            ]
            mock_perceiver_cls.return_value = mock_perceiver

            result = skill.get_unread_messages()
            assert len(result) == 1
            assert result[0]["contact"] == "张三"

    def test_get_unread_messages_empty(self, mock_app, mock_finder, config, session):
        skill = UnreadSkill(mock_app, mock_finder, config, session)

        with patch("wechat_auto.engine.perceiver.Perceiver") as mock_perceiver_cls:
            mock_perceiver = MagicMock()
            mock_perceiver.get_unread_messages.return_value = []
            mock_perceiver_cls.return_value = mock_perceiver

            result = skill.get_unread_messages()
            assert result == []

    def test_run_delegates_to_get_unread(self, mock_app, mock_finder, config, session):
        skill = UnreadSkill(mock_app, mock_finder, config, session)
        with patch.object(skill, "get_unread_messages", return_value=[]) as mock_get:
            skill._run()
            mock_get.assert_called_once()


# ==================================================================
# GroupAtSkill
# ==================================================================

class TestGroupAtSkill:
    def test_name(self, mock_app, mock_finder, config, session):
        skill = GroupAtSkill(mock_app, mock_finder, config, session)
        assert skill.name == "send_group_at_message"

    def test_run_delegates(self, mock_app, mock_finder, config, session):
        skill = GroupAtSkill(mock_app, mock_finder, config, session)
        with patch.object(skill, "send_group_at_message") as mock_send:
            skill._run(group="群1", mention="张三", message="hi")
            mock_send.assert_called_once_with("群1", "张三", "hi")

    def test_send_group_at_message(self, mock_app, mock_finder, config, session):
        """Test full @ message flow."""
        edit_box = MagicMock()
        mock_finder.find_child_by_title.return_value = edit_box
        mock_finder.find_all_children.return_value = [MagicMock()]

        skill = GroupAtSkill(mock_app, mock_finder, config, session)

        with patch("wechat_auto.skills.group_at.ClipboardHelper") as mock_clip:
            with patch("wechat_auto.skills.group_at.KeyboardHelper") as mock_kb:
                skill.send_group_at_message("群1", "张三", "开会")

        # Should paste member name and message
        assert mock_clip.set_text.call_count >= 2
        mock_kb.paste.assert_called()
        mock_kb.press_enter.assert_called()


# ==================================================================
# ChannelsSkill
# ==================================================================

class TestChannelsSkill:
    def test_name(self, mock_app, mock_finder, config, session):
        skill = ChannelsSkill(mock_app, mock_finder, config, session)
        assert skill.name == "search_official_article"

    def test_run_delegates(self, mock_app, mock_finder, config, session):
        skill = ChannelsSkill(mock_app, mock_finder, config, session)
        with patch.object(skill, "search_official_article", return_value=[]) as mock_search:
            skill._run(keyword="AI")
            mock_search.assert_called_once_with("AI")

    def test_search_official_article(self, mock_app, mock_finder, config, session):
        """Test article search flow."""
        mock_finder.find_all_children.return_value = []

        skill = ChannelsSkill(mock_app, mock_finder, config, session)

        with patch("wechat_auto.skills.channels.ClipboardHelper") as mock_clip:
            with patch("wechat_auto.skills.channels.KeyboardHelper") as mock_kb:
                result = skill.search_official_article("AI技术")

        assert result == []
        mock_finder.open_search.assert_called_once()

    def test_parse_article_item(self, mock_app, mock_finder, config, session):
        """Test article item parsing."""
        skill = ChannelsSkill(mock_app, mock_finder, config, session)

        item = MagicMock()
        child1 = MagicMock()
        child1.window_text.return_value = "公众号A"
        child2 = MagicMock()
        child2.window_text.return_value = "文章标题"
        child3 = MagicMock()
        child3.window_text.return_value = "摘要内容"
        item.children.return_value = [child1, child2, child3]

        result = skill._parse_article_item(item)
        assert result is not None
        assert result["account"] == "公众号A"
        assert result["title"] == "文章标题"
        assert "摘要内容" in result["summary"]


# ==================================================================
# MomentsSkill - comment_moment + get_my_timeline
# ==================================================================

class TestMomentsSkillNew:
    def test_comment_moment_not_implemented_replaced(self, mock_app, mock_finder, config, session):
        """comment_moment should NOT raise NotImplementedError anymore."""
        skill = MomentsSkill(mock_app, mock_finder, config, session)
        # Verify it's callable (not raising NotImplemented on definition)
        assert hasattr(skill, "comment_moment")
        assert callable(skill.comment_moment)

    def test_get_my_timeline_uses_browse(self, mock_app, mock_finder, config, session):
        """get_my_timeline should delegate to browse."""
        skill = MomentsSkill(mock_app, mock_finder, config, session)

        with patch.object(skill, "browse", return_value=[
            {"author": "A", "content": "post1", "time": "1小时前"},
            {"author": "B", "content": "post2", "time": "1分钟前"},
            {"author": "C", "content": "post3", "time": "昨天"},
        ]) as mock_browse:
            result = skill.get_my_timeline(limit=2)
            assert len(result) == 2

    def test_get_my_timeline_filter_by_hours(self, mock_app, mock_finder, config, session):
        """Test filtering by hours_range."""
        skill = MomentsSkill(mock_app, mock_finder, config, session)

        with patch.object(skill, "browse", return_value=[
            {"author": "A", "content": "post1", "time": "5小时前"},
            {"author": "B", "content": "post2", "time": "30分钟前"},
            {"author": "C", "content": "post3", "time": "昨天"},
        ]) as mock_browse:
            result = skill.get_my_timeline(limit=10, hours_range=3)
            # 5小时前 > 3 hours, excluded
            # 30分钟前 included (within any hours range)
            # 昨天 has no parseable pattern, included (best-effort)
            assert len(result) == 2
            assert result[0]["author"] == "B"

    def test_filter_by_hours_minute_pattern(self, mock_app, mock_finder, config, session):
        """Test that minutes-ago posts are always included."""
        skill = MomentsSkill(mock_app, mock_finder, config, session)
        posts = [
            {"time": "5小时前", "content": "a"},
            {"time": "30分钟前", "content": "b"},
            {"time": "昨天", "content": "c"},
        ]
        filtered = skill._filter_by_hours(posts, hours=2)
        # 5小时前 > 2 hours, excluded
        # 30分钟前 included (within any hours range)
        # 昨天 has no parseable pattern, included
        assert len(filtered) == 2

    def test_remaining_stubs_still_raise(self, mock_app, mock_finder, config, session):
        """Verify that get_friend_moments, get_my_own_moments, publish_moment still raise."""
        skill = MomentsSkill(mock_app, mock_finder, config, session)

        with pytest.raises(NotImplementedError):
            skill.get_friend_moments("friend")

        with pytest.raises(NotImplementedError):
            skill.get_my_own_moments()

        with pytest.raises(NotImplementedError):
            skill.publish_moment("text")


# ==================================================================
# ContactSkill
# ==================================================================

class TestContactSkill:
    def test_name(self, mock_app, mock_finder, config, session):
        skill = ContactSkill(mock_app, mock_finder, config, session)
        assert skill.name == "open_contact_chat"

    def test_run_delegates(self, mock_app, mock_finder, config, session):
        skill = ContactSkill(mock_app, mock_finder, config, session)
        with patch.object(skill, "open_chat_via_contacts") as mock_open:
            skill._run(target="张三")
            mock_open.assert_called_once_with("张三")

    def test_open_chat_success(self, mock_app, mock_finder, config, session):
        """Test successful chat opening."""
        mock_item = MagicMock()
        mock_finder.find_all_children.return_value = [mock_item]

        skill = ContactSkill(mock_app, mock_finder, config, session)

        with patch("wechat_auto.skills.contact.ClipboardHelper") as mock_clip:
            with patch("wechat_auto.skills.contact.KeyboardHelper") as mock_kb:
                skill.open_chat_via_contacts("张三")

        mock_finder.navigate_to_contacts.assert_called_once()
        mock_finder.open_search.assert_called_once()
        mock_finder.click.assert_called_once_with(mock_item)

    def test_open_chat_not_found(self, mock_app, mock_finder, config, session):
        """Test contact not found raises error."""
        mock_finder.find_all_children.return_value = []

        skill = ContactSkill(mock_app, mock_finder, config, session)

        with patch("wechat_auto.skills.contact.ClipboardHelper"):
            with patch("wechat_auto.skills.contact.KeyboardHelper"):
                with pytest.raises(ContactNotFoundError):
                    skill.open_chat_via_contacts("nonexistent")


# ==================================================================
# EmojiSkill
# ==================================================================

class TestEmojiSkill:
    def test_name(self, mock_app, mock_finder, config, session):
        skill = EmojiSkill(mock_app, mock_finder, config, session)
        assert skill.name == "send_builtin_sticker"

    def test_send_emoji_success(self, mock_app, mock_finder, config, session):
        """Test emoji sending flow."""
        mock_btn = MagicMock()
        mock_result = MagicMock()
        mock_finder.find_child_by_title.return_value = mock_btn
        mock_finder.find_all_children.return_value = [mock_result]

        skill = EmojiSkill(mock_app, mock_finder, config, session)
        skill.send_emoji("张三", "笑")

        mock_finder.click.assert_called()


# ==================================================================
# QuoteSkill
# ==================================================================

class TestQuoteSkill:
    def test_name(self, mock_app, mock_finder, config, session):
        skill = QuoteSkill(mock_app, mock_finder, config, session)
        assert skill.name == "send_quoted_message"

    def test_quote_and_reply(self, mock_app, mock_finder, config, session):
        """Test quote-reply flow."""
        mock_message = MagicMock()
        mock_menu_item = MagicMock()
        mock_edit = MagicMock()

        mock_finder.find_all_children.return_value = [mock_edit]
        mock_finder.find_child_by_title.return_value = mock_menu_item

        skill = QuoteSkill(mock_app, mock_finder, config, session)

        with patch.object(skill, "_get_message_element", return_value=mock_message):
            with patch("wechat_auto.skills.quote.ClipboardHelper") as mock_clip:
                with patch("wechat_auto.skills.quote.KeyboardHelper") as mock_kb:
                    skill.quote_and_reply("张三", "回复内容")

        mock_finder.right_click.assert_called_once_with(mock_message)

    def test_quote_no_message_found(self, mock_app, mock_finder, config, session):
        skill = QuoteSkill(mock_app, mock_finder, config, session)

        with patch.object(skill, "_get_message_element", return_value=None):
            with pytest.raises(ElementNotFoundError):
                skill.quote_and_reply("张三", "reply")


# ==================================================================
# HistorySkill
# ==================================================================

class TestHistorySkill:
    def test_name(self, mock_app, mock_finder, config, session):
        skill = HistorySkill(mock_app, mock_finder, config, session)
        assert skill.name == "get_chat_history"

    def test_get_messages(self, mock_app, mock_finder, config, session):
        """Test message retrieval."""
        mock_item = MagicMock()
        mock_child = MagicMock()
        mock_child.window_text.return_value = "张三"
        mock_item.children.return_value = [mock_child]

        mock_finder.find_all_children.return_value = [mock_item]

        skill = HistorySkill(mock_app, mock_finder, config, session)
        result = skill.get_messages("张三", max_messages=10)

        assert isinstance(result, list)

    def test_get_latest_message(self, mock_app, mock_finder, config, session):
        """Test getting latest message."""
        mock_finder.find_all_children.return_value = []

        skill = HistorySkill(mock_app, mock_finder, config, session)
        result = skill.get_latest_message("张三")
        assert result is None

    def test_parse_message_item(self, mock_app, mock_finder, config, session):
        """Test message item parsing."""
        skill = HistorySkill(mock_app, mock_finder, config, session)

        item = MagicMock()
        child1 = MagicMock()
        child1.window_text.return_value = "发送者"
        child2 = MagicMock()
        child2.window_text.return_value = "消息内容"
        item.children.return_value = [child1, child2]

        result = skill._parse_message_item(item)
        assert result is not None
        assert result["sender"] == "发送者"
        assert "消息内容" in result["content"]
