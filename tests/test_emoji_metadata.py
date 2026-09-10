from wechat_auto.storage.emoji_metadata import decode_emoji_hint, parse_emoji_metadata


def test_extracts_description_without_secret_fields():
    item = parse_emoji_metadata(
        '<msg><emoji md5="ABC" desc="开心" aeskey="secret" tpurl="https://x"/></msg>'
    )
    assert item["hint"] == "开心"
    assert item["hint_source"] == "desc"
    assert item["md5"] == "abc"
    assert "aeskey" not in item
    assert "tpurl" not in item


def test_unknown_when_no_semantic_hint():
    assert parse_emoji_metadata('<msg><emoji md5="abc"/></msg>')["hint"] == ""


def test_decodes_localized_protobuf_hint():
    assert decode_emoji_hint("Cg4KB2RlZmF1bHQSA+WTvA==") == "哼"
