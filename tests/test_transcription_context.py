import pytest

from tests.test_reply_memory_context import setup_context
from wechat_auto.memory.reading import readable_message


@pytest.mark.parametrize('transcript', [None, {'text': 'rejected-candidate', 'engine': 'local_asr', 'status': 'failed'},
                                      {'text': 'rejected-candidate', 'engine': 'local_asr', 'status': 'pending'}])
def test_reply_handles_absent_or_unsuccessful_transcript(tmp_path, transcript):
    store, _, cv, builder = setup_context(tmp_path)
    try:
        result = builder.reply_context(cv, [{'chat': 'friend', 'content': '[语音]', 'transcription': transcript}])
        assert 'rejected-candidate' not in result['text']
    finally:
        store.close()


@pytest.mark.parametrize('engine,status,label', [('local_asr', 'transcribed_unreviewed', '未经复核'),
                                               ('wechat_native', 'transcribed_unreviewed', '未经复核'),
                                               ('user_corrected', 'user_corrected', '用户修订')])
def test_transcription_provenance_is_visible(tmp_path, engine, status, label):
    transcript = {'text': 'candidate-speech', 'engine': engine, 'status': status}
    parts, _ = readable_message({'transcription': transcript})
    assert label in ' '.join(parts)
    store, _, cv, builder = setup_context(tmp_path)
    try:
        text = builder.reply_context(cv, [{'chat': 'friend', 'transcription': transcript}])['text']
        assert label in text and 'candidate-speech' in text
    finally:
        store.close()


def test_failed_transcript_is_a_reader_gap():
    parts, errors = readable_message({'transcription': {'text': 'rejected-candidate', 'status': 'failed'}})
    assert 'rejected-candidate' not in ' '.join(parts)
    assert errors
