import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('analysis_reader', Path(__file__).parents[1] / 'scripts/read_analysis_block.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


def test_long_text_and_link_sentence_are_preserved():
    body = '完整正文' * 300 + ' 看这个 https://example.test/ 之后决定明天再说。'
    parts, errors = reader.readable_message({'readable': body, 'content': body})
    assert parts == [body]
    assert not errors


def test_nested_quote_text_is_not_capped_and_xml_attributes_not_exposed():
    quote = '引用原话' * 200
    content = '<msg><appmsg secret="hidden"><title>标题</title><refermsg><content><![CDATA[<msg><title>' + quote + '</title></msg>]]></content></refermsg></appmsg></msg>'
    parts, errors = reader.readable_message({'readable': '[卡片]', 'content': content})
    assert quote in parts and 'hidden' not in ''.join(parts)
    assert not errors


def test_parse_failure_is_an_explicit_gap():
    parts, errors = reader.readable_message({'readable': '[卡片]', 'content': '<msg>broken'})
    assert parts == ['[卡片]'] and errors


def test_raw_media_xml_in_readable_never_exposes_attributes():
    media = '<msg><emoji encryptedkey="private-key" cdnurl="private-url" /></msg>'
    parts, errors = reader.readable_message({'readable': media, 'content': media})
    assert parts == ['[XML/媒体正文未解读]']
    assert not errors
    assert 'private' not in ''.join(parts)


def test_prefixed_media_xml_never_exposes_transport_or_attributes():
    media = 'binary\x01transport' + '<msg><emoji aeskey="private-key" cdnurl="private-url" /></msg>'
    parts, errors = reader.readable_message({'readable': '[动画表情未解读]',
        'content': media, 'raw': {'type': '动画表情'}})
    assert parts == ['[动画表情未解读]'] and not errors
    assert 'private' not in ''.join(parts) and 'transport' not in ''.join(parts)


def test_natural_prefix_and_comparison_survive_xml_detection():
    parts, errors = reader.readable_message({'content': '他说：<msg><title>完整引用</title></msg>',
                                           'raw': {'type': '文本'}})
    assert parts == ['他说：', '完整引用'] and not errors
    parts, errors = reader.readable_message({'content': 'a < b，接着说明原因。'})
    assert parts == ['a < b，接着说明原因。'] and not errors


def test_optional_recovery_displays_only_whitelist_text_and_retains_gap():
    import pytest
    pytest.importorskip('lxml')
    content = 'binary\x01transport<msg><appmsg aeskey="private"><title>完整恢复正文</title>'
    parts, errors = reader.readable_message({'readable': '[卡片]', 'content': content,
        'raw': {'type': '动画表情'}}, recover_xml=True)
    assert parts == ['[卡片]', '完整恢复正文'] and errors
    assert 'private' not in ''.join(parts) and 'transport' not in ''.join(parts)


def test_optional_recovery_does_not_resolve_external_entities(tmp_path):
    import pytest
    pytest.importorskip('lxml')
    secret = tmp_path / 'fixture.txt'
    secret.write_text('fixture-must-not-be-read', encoding='utf-8')
    content = ('<?xml version="1.0"?><!DOCTYPE msg [<!ENTITY external SYSTEM "' +
               secret.as_uri() + '">]><msg><title>&external;</title></msg>')
    parts, errors = reader.readable_message({'content': content}, recover_xml=True)
    assert 'fixture-must-not-be-read' not in ''.join(parts)
    assert errors


def test_seconds_and_milliseconds_preserve_explicit_beijing_date():
    assert reader.display_time('1719035604') == '2024-06-22T13:53:24+08:00'
    assert reader.display_time('1719035604000') == '2024-06-22T13:53:24+08:00'
    assert reader.display_time(None) == 'unknown'


def test_media_folding_preserves_natural_text_and_parsing_gaps():
    def row(n, text, errors=(), kind='图片'):
        return {'ordinal': n, 'time_Beijing': str(n), 'analysis_direction': 'incoming',
                    'text': [text], 'parse_gaps': list(errors), '_media_type': kind}
    records = [row(1, '[图片未解读]'), row(2, '[XML/媒体正文未解读]'),
               row(3, '这张图是我喜欢的菜'), row(4, '[图片未解读]', ['recover needed']),
               row(5, '[图片未解读]', kind='文本')]
    result = list(reader.fold_media_records(records))
    assert result[0]['unread_media_range'] == [1, 2] and result[0]['count'] == 2
    assert result[1:] == records[2:]
    assert result[0]['directions'] == {'incoming': 2}


def test_lean_display_preserves_long_text_quotes_dates_and_gaps():
    body='完整正文' * 300
    row={'ordinal': 9,'analysis_direction': 'incoming','time_Beijing': '2024-06-22T13:53:24+08:00',
             'text': [body,body,'不同的引用'],'parse_gaps': ['XML parse failure']}
    value=reader.lean_record(row,'2024-06')
    assert value==[9,'C','22 13:53:24',[body,'不同的引用'],['XML parse failure']]
    row.update(analysis_direction='unknown',time_Beijing='2024-07-01T00:00:00+08:00',parse_gaps=[])
    assert reader.lean_record(row,'2024-06')[1:3]==['?','2024-07-01T00:00:00+08:00']
