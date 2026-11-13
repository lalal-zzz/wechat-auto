import pytest

from wechat_auto.memory.reading import readable_message


@pytest.mark.parametrize('tag', ['voicetrans', 'transcription'])
def test_embedded_transcription_is_not_unlabelled_speech(tag):
    xml = f'<msg><{tag}>embedded words</{tag}></msg>'
    parts, errors = readable_message({'content': xml, 'readable': xml})
    assert not errors
    assert len(parts) == 1
    assert '内嵌' in parts[0] and '未经复核' in parts[0]
    assert parts[0].count('embedded words') == 1


def test_same_attached_native_text_is_read_once():
    parts, errors = readable_message({'content': '<msg><voicetrans>same words</voicetrans></msg>',
        'transcription': {'text': 'same words', 'engine': 'wechat_native', 'status': 'transcribed_unreviewed'}})
    assert not errors
    assert ' '.join(parts).count('same words') == 1
    assert '未经复核' in ' '.join(parts)


def test_correction_retains_distinct_embedded_candidate_with_provenance():
    parts, errors = readable_message({'content': '<msg><title>audio title</title><voicetrans>old words</voicetrans></msg>',
        'transcription': {'text': 'corrected words', 'engine': 'user_corrected', 'status': 'user_corrected'}})
    assert not errors and 'audio title' in parts
    assert any('内嵌' in p and 'old words' in p and '未经复核' in p for p in parts)
    assert any('用户修订' in p and 'corrected words' in p for p in parts)


def test_embedded_attribute_secrets_are_never_rendered():
    parts, errors = readable_message({'content': '<msg><voicetrans aeskey="secret">words</voicetrans></msg>'})
    assert not errors and 'secret' not in ' '.join(parts)
    assert '未经复核' in ' '.join(parts)


def test_multiline_attached_native_deduplicates_embedded_segments():
    parts, errors = readable_message({'content': '<msg><voicetrans>first</voicetrans><transcription>second</transcription></msg>',
        'transcription': {'text': 'first\nsecond', 'engine': 'wechat_native', 'status': 'transcribed_unreviewed'}})
    assert not errors and len(parts) == 1
    assert 'first\nsecond' in parts[0] and '未经复核' in parts[0]


def test_failed_attached_record_does_not_erase_independent_embedded_candidate():
    parts, errors = readable_message({'content': '<msg><voicetrans>native words</voicetrans></msg>',
        'transcription': {'text': 'failed words', 'engine': 'local_asr', 'status': 'failed'}})
    assert errors and 'failed words' not in ' '.join(parts)
    assert any('XML内嵌候选' in p and 'native words' in p for p in parts)
    assert '[语音转写不可用]' in parts


def test_nested_quote_transcription_keeps_candidate_label():
    parts, errors = readable_message({'content': '<msg><content><![CDATA[<msg><voicetrans>quoted voice</voicetrans></msg>]]></content></msg>'})
    assert not errors and len(parts) == 1
    assert 'XML内嵌候选' in parts[0] and 'quoted voice' in parts[0]
