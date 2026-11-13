"""Explicit UI inventory and conservative multi-anchor observation rules."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace

from wechat_auto.actions.semantics import PageId

PAGE_CATALOG_VERSION = 5


@dataclass(frozen=True)
class PageSpec:
    page_id: PageId
    key: str
    label: str
    layer: str
    parent: str
    anchors: tuple[tuple[str, ...], ...] = ()
    region: str = "workspace"
    variants: tuple[str, ...] = ("light", "dark", "DPI_scaled")
    verification: str = "needs_real_capture"


# Each anchor group is mandatory; alternatives within one group are OR-ed.
# No anchors means catalogued only: cannot be recognized without templates.
PAGES = (
    PageSpec(PageId.LOGIN, "login", "登录/扫码", "base", "", (("扫码登录", "扫描二维码"), ("微信", "登录")), "window"),
    PageSpec(PageId.LOCKED, "locked", "锁定", "overlay", "", (("微信已锁定", "已锁定"), ("解锁", "在手机上解锁")), "window"),
    PageSpec(PageId.CONNECTION_ERROR, "connection_error", "网络/连接异常", "overlay", "", (("连接已断开", "网络连接异常"), ("重试", "重新连接")), "window"),
    PageSpec(PageId.MAIN_EMPTY, "main_without_selected_chat", "主界面未选会话", "base", ""),
    PageSpec(PageId.CHAT, "chat", "聊天", "base", "", verification="dark_main_captured"),
    PageSpec(PageId.GROUP_CHAT, "group_chat", "群聊", "base", "chat"),
    PageSpec(PageId.SEARCH, "search", "本地搜索结果", "panel", "", (("联系人", "群聊", "功能"), ("聊天记录", "搜索结果", "服务号", "功能", "最近使用过的小程序")), "window"),
    PageSpec(PageId.CHAT_HISTORY, "chat_history", "聊天记录检索", "panel", "chat", (("聊天记录",), ("全部", "图片与视频", "文件", "日期"))),
    PageSpec(PageId.MESSAGE_MENU, "message_menu", "消息右键菜单", "overlay", "chat", (("复制",), ("引用", "转发", "多选")), "window"),
    PageSpec(PageId.COMPOSER_MENU, "composer_menu", "输入区右键菜单", "overlay", "chat", (("粘贴",), ("边写边译",)), "window"),
    PageSpec(PageId.COMPOSER_SELECTION_MENU, "composer_selection_menu", "输入区选择菜单", "overlay", "chat", (("剪切",), ("复制",), ("粘贴", "另存为", "另存为.", "另存为...", "另存为…"), ("删除", "编辑")), "window"),
    PageSpec(PageId.EMOJI_PANEL, "emoji_panel", "表情面板", "panel", "chat"),
    PageSpec(PageId.MEDIA_VIEWER, "media_viewer", "图片/视频查看器", "window", "chat"),
    PageSpec(PageId.FILE_PREVIEW, "file_preview", "文件预览", "window", "chat"),
    PageSpec(PageId.DISCOVER, "discover", "发现", "base", "", (("发现",), ("朋友圈", "视频号", "搜一搜")), "list"),
    PageSpec(PageId.CONTACTS, "contacts", "通讯录", "base", "", (("通讯录", "通讯录管理"), ("新的朋友", "群聊", "标签")), "list"),
    PageSpec(PageId.CONTACT_PROFILE, "contact_profile", "联系人资料", "base", "contacts", (("微信号", "微信号:"), ("发消息", "设置备注和标签", "音视频通话"))),
    PageSpec(PageId.CONTACT_MORE, "contact_more", "联系人更多菜单", "overlay", "contact_profile", (("删除联系人",), ("推荐给朋友", "把他推荐给朋友", "设置朋友权限", "投诉", "举报")), "window"),
    PageSpec(PageId.CONTACT_REMARK, "contact_remark", "备注编辑", "overlay", "contact_profile", (("设置备注和标签", "备注"), ("完成", "保存")), "window"),
    PageSpec(PageId.CONTACT_PERMISSIONS, "contact_permissions", "朋友权限", "overlay", "contact_profile", (("朋友权限",), ("仅聊天", "聊天、朋友圈、微信运动等"))),
    PageSpec(PageId.CONTACT_TAGS, "contact_tags", "标签编辑", "overlay", "contact_profile", (("标签", "设置标签"), ("新建标签", "添加标签"))),
    PageSpec(PageId.NEW_FRIENDS, "new_friends", "新的朋友", "base", "contacts", (("新的朋友",), ("接受", "添加朋友", "已添加"))),
    PageSpec(PageId.CHAT_DETAILS, "chat_details", "私聊信息侧栏", "panel", "chat", (("聊天信息", "聊天详情"), ("消息免打扰", "置顶聊天", "查找聊天记录")), "window"),
    PageSpec(PageId.GROUP_LIST, "group_list", "群聊列表", "base", "contacts"),
    PageSpec(PageId.GROUP_DETAILS, "group_details", "群资料/管理", "panel", "group_chat", (("群聊名称",), ("群公告", "群管理", "我在本群的昵称"))),
    PageSpec(PageId.GROUP_MEMBERS, "group_members", "群成员", "panel", "group_details", (("群成员", "查看全部群成员"), ("搜索", "添加成员"))),
    PageSpec(PageId.GROUP_ANNOUNCEMENT, "group_announcement", "群公告", "overlay", "group_details", (("群公告",), ("发布", "编辑", "完成"))),
    PageSpec(PageId.GROUP_NAME, "group_name", "群名称编辑", "overlay", "group_details", (("群聊名称",), ("保存", "完成"))),
    PageSpec(PageId.GROUP_INVITE, "group_invite", "邀请群成员", "overlay", "group_details", (("选择联系人",), ("确定", "邀请"))),
    PageSpec(PageId.MOMENTS_FEED, "moments_feed", "朋友圈信息流", "base", "", (("朋友圈",), ("朋友的新动态", "今天", "昨天", "赞", "评论")), "window"),
    PageSpec(PageId.MOMENTS_PERSON, "moments_person", "个人朋友圈/相册", "base", "contact_profile", (("相册", "个人相册"), ("今天", "昨天", "朋友圈")), "window"),
    PageSpec(PageId.MOMENTS_DETAIL, "moments_detail", "单条朋友圈详情", "window", "moments_feed"),
    PageSpec(PageId.MOMENTS_COMMENT, "moments_comment", "朋友圈评论输入", "overlay", "moments_detail", (("评论",), ("取消", "发表"))),
    PageSpec(PageId.MOMENTS_PUBLISH, "moments_publish", "发布朋友圈", "window", "moments_feed", (("发表朋友圈", "发布朋友圈"), ("发表", "谁可以看", "所在位置")), "window"),
    PageSpec(PageId.MOMENTS_MENU, "moments_menu", "朋友圈点赞评论菜单", "overlay", "moments_feed", (("赞", "取消赞"), ("评论",)), "window"),
    PageSpec(PageId.OFFICIAL_ACCOUNTS, "official_accounts", "公众号列表", "base", "", (("公众号", "订阅号"),), "header"),
    PageSpec(PageId.ARTICLE, "article", "公众号文章", "panel", "official_accounts", (("阅读原文",), ("阅读", "赞", "在看"))),
    PageSpec(PageId.CHANNELS, "channels", "视频号", "window", "", (("视频号",), ("推荐", "关注", "朋友")), "window"),
    PageSpec(PageId.CHANNELS_LIVE, "channels_live", "视频号直播", "window", "channels", (("直播",), ("直播中", "进入直播间", "观看")), "window"),
    PageSpec(PageId.WEB_SEARCH, "web_search", "搜一搜", "panel", "", (("搜一搜",), ("搜索", "全部", "文章")), "window"),
    PageSpec(PageId.MINI_PROGRAM, "mini_program", "小程序", "window", ""),
    PageSpec(PageId.SETTINGS, "settings", "设置", "window", "", (("设置", "账号与存储", "关于微信"), ("账号设置", "通用设置", "消息通知", "通用", "快捷键")), "window"),
    PageSpec(PageId.FILE_TRANSFER, "file_transfer", "文件传输助手", "base", "chat", (("文件传输助手",),), "header"),
    PageSpec(PageId.FAVORITES, "favorites", "收藏", "base", "", (("收藏",), ("全部", "笔记", "链接", "文件")), "window"),
    PageSpec(PageId.MAIN_MENU, "main_menu", "主菜单", "overlay", "", (("设置",), ("收藏", "锁定", "备份与恢复", "迁移与备份")), "window"),
    PageSpec(PageId.MINI_PROGRAM_LIST, "mini_program_list", "小程序列表", "base", "discover", (("小程序",), ("最近使用", "我的小程序")), "window"),
    PageSpec(PageId.SEARCH_SUGGESTIONS, "search_suggestions", "网络搜索建议", "panel", "search", (("搜索网络结果",),), "window"),
    PageSpec(PageId.CALL, "call", "语音/视频通话", "window", "chat", (("挂断", "接听"), ("视频通话", "语音通话", "拒绝")), "window"),
    PageSpec(PageId.CONFIRM_DIALOG, "confirm_dialog", "确认弹窗", "overlay", "", (("取消",), ("确定", "删除", "确认"))),
    PageSpec(PageId.FILE_PICKER, "file_picker", "文件选择器", "window", "chat", (("文件名", "文件名:"), ("打开", "保存")), "window"),
    PageSpec(PageId.ERROR_DIALOG, "error_dialog", "错误提示", "overlay", "", (("操作失败", "加载失败", "无法打开"), ("确定", "重试", "关闭"))),
)

# Sampling is one environment, not certification of every layout/operation.
CAPTURED_DARK_PAGES = {"chat", "file_transfer", "contacts", "contact_profile", "contact_more",
                       "contact_remark", "contact_permissions", "discover", "moments_feed",
                       "channels", "web_search", "mini_program_list", "main_menu", "settings",
                       "search", "search_suggestions"}
PAGES = tuple(replace(spec, verification="sampled_dark_4_1_15_9")
              if spec.key in CAPTURED_DARK_PAGES else spec for spec in PAGES)


def list_page_catalog() -> list[dict]:
    result = []
    for spec in PAGES:
        row = asdict(spec)
        row["page_id"] = int(spec.page_id)
        row["recognition"] = "anchor_rule" if spec.anchors else "template_required"
        if spec.page_id in {PageId.CHAT, PageId.MAIN_EMPTY}:
            row["recognition"] = "runtime_fusion"
        elif spec.page_id == PageId.GROUP_CHAT:
            row["recognition"] = "stable_identity_required"
        row["actions_calibrated"] = False
        row["presentations"] = (
            ["embedded_main", "embedded_right_tab", "auxiliary_window"]
            if spec.key in {"channels", "web_search", "article", "mini_program", "official_accounts", "moments_person"}
            else ["embedded_overlay", "auxiliary_popup"] if spec.layer in {"overlay", "panel"}
            else ["auxiliary_window"] if spec.layer == "window" else ["embedded_main"])
        result.append(row)
    return result


def match_page_catalog(boxes: list[dict], size: tuple[int, int], *,
                       bounds: dict, minimum_score: float = .65) -> list[dict]:
    """Return candidate observations without discarding competing matches."""
    width, height = size
    regions = {
        "window": (0, 0, 1, 1),
        "workspace": (bounds["conversation_header"][0], .02, 1, 1),
        "header": bounds["conversation_header"],
        "list": bounds["conversation_list"],
    }
    matches = []
    for spec in PAGES:
        if not spec.anchors:
            continue
        left, top, right, bottom = regions[spec.region]
        eligible = [i for i, b in enumerate(boxes)
                    if b.get("score", 0) >= minimum_score
                    and left <= (b["x"] + b["w"] / 2) / width <= right
                    and top <= (b["y"] + b["h"] / 2) / height <= bottom]
        indices = []
        for group in spec.anchors:
            hits = [i for i in eligible for word in group
                    if _anchor_matches(str(boxes[i].get("text", "")), word)]
            if not hits:
                break
            indices.extend(hits)
        else:
            matches.append({"page_id": int(spec.page_id), "key": spec.key,
                            "label": spec.label, "layer": spec.layer,
                            "parent": spec.parent, "state": "candidate",
                            "evidence_box_indices": sorted(set(indices)),
                            "verification": spec.verification,
                            "action_authorized": False})
    return matches


def _anchor_matches(text: str, word: str) -> bool:
    normalized = re.sub(r"\s+", "", text).replace("：", ":")
    expected = word.replace("：", ":").rstrip(":")
    # Paddle can merge the people icon into this specific management label.
    # Keep this narrow; personal names and identity values stay exact.
    if expected == "通讯录管理" and normalized in {"&通讯录管理", "＆通讯录管理"}:
        return True
    return (normalized.rstrip(":") == expected
            or expected == "微信号" and normalized.startswith("微信号:"))
