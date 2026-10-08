import sqlite3
from pathlib import Path
import pytest
from wechat_auto.storage.history_store import HistoryStore
from wechat_auto.storage.voice_transcription import VoiceTranscriptions
from wechat_auto.memory.reading import readable_message
from wechat_auto.memory.store import MemoryStore
from wechat_auto.memory.markdown import MarkdownMemory
from wechat_auto.memory.analysis import AnalysisService


def test_native_audio_import_transcript_reading_and_corrections(tmp_path):
    media=tmp_path/"media.db"
    with sqlite3.connect(media) as db:
        db.execute("CREATE TABLE Name2Id(user_name TEXT)")
        db.execute("INSERT INTO Name2Id VALUES('friend')")
        db.execute("CREATE TABLE VoiceInfo(chat_name_id INTEGER,svr_id INTEGER,voice_data BLOB,voice_text TEXT)")
        db.execute("INSERT INTO VoiceInfo VALUES(1,456,?,?)",(b'#!SILK_V3test','native words'))
    with HistoryStore(tmp_path/"history.db") as history:
        history.save_messages([dict(id='stable',chat='friend',content='<msg><voicemsg/></msg>',time='2026-09-13',raw={'type':'语音','server_id':'456'})])
        voice=VoiceTranscriptions(history)
        assert voice.import_native('friend',[media])["audio_saved"]==1
        assert voice.import_native('friend',[media])["audio_saved"]==0
        message=history.fetch_month('friend','2026-09')[0]
        assert message['transcription']['text']=='native words'
        assert 'native words' in ' '.join(readable_message(message)[0])
        assert message['content']=='<msg><voicemsg/></msg>'
        assert voice.save('stable','corrected',engine='user_corrected',source_ref='user')
        assert not voice.save('stable','bad',engine='local_asr',source_ref='model')
        assert history.get_message('stable')['transcription']['version']==2
        with pytest.raises(ValueError):voice.save('missing','bad',engine='wechat_native',source_ref='ui')


def test_new_transcription_changes_analysis_fingerprint(tmp_path):
    hp=tmp_path/'history.db'
    with HistoryStore(hp) as history, MemoryStore(tmp_path/'memory.db') as store:
        history.save_messages([dict(id='voice',chat='friend',content='<msg><voicemsg/></msg>',time='2026-09-13',raw={'type':'语音'})])
        cv=store.ensure_conversation('friend',conversation_type='direct')
        service=AnalysisService(store,MarkdownMemory(tmp_path/'memory',store),hp)
        kwargs=dict(scope_type='conversation',scope_id=cv,period='2026-09',evidence_ids=['voice'],template_version='7')
        first=service.submit(markdown='# Before',**kwargs)
        VoiceTranscriptions(history).save('voice','new text',engine='wechat_native',source_ref='ui')
        second=service.submit(markdown='# After',expected_parent=1,**kwargs)
        assert second['version']==2
        assert first['input_fingerprint']!=second['input_fingerprint']
        assert service.submit(markdown='# Ignored',**kwargs)['reason']=='input_unchanged'


def test_local_asr_uses_existing_model_and_preserves_segments(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    calls=[]
    class Model:
        def __init__(self, path, **options):
            calls.append(options)
        def transcribe(self, path, **options):
            return iter([SimpleNamespace(start=0.0,end=1.2,text='words',avg_logprob=-0.2,no_speech_prob=0.01)]), None
    monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=Model))
    model=tmp_path/'model';model.mkdir()
    with HistoryStore(tmp_path/'history.db') as history:
        history.save_messages([dict(id='voice',chat='friend',content='<msg><voicemsg/></msg>',time='2026-09-13',raw={'type':'34'},media=[dict(kind='voice',data=b'RIFFwav')])])
        voice=VoiceTranscriptions(history)
        assert voice.transcribe_local('friend',model,device='cpu')['transcribed']==1
        assert calls[0]['local_files_only'] is True
        assert voice.transcribe_local('friend',model,device='cpu')['attempted']==0
        assert history.get_message('voice')['transcription']['status']=='transcribed_unreviewed'


def test_save_messages_with_model_transcribes_in_archive_stage(tmp_path, monkeypatch):
    def transcribe(self, chat, model_path, **options):
        mid=next(iter(options['message_ids']))
        self.save(mid,'archive text',engine='local_asr',source_ref=str(model_path))
        return dict(transcribed=1,failed=0)
    monkeypatch.setattr(VoiceTranscriptions,'transcribe_local',transcribe)
    model=tmp_path/'model';model.mkdir()
    with HistoryStore(tmp_path/'history.db',voice_model_path=model) as history:
        history.save_messages([dict(id='stable',chat='friend',content='<msg><voicemsg/></msg>',time='2026-09-13',raw={'type':'34'},media=[dict(kind='voice',data=b'original')])])
        item=history.get_message('stable')
        assert item['media'][0]['data']==b'original'
        assert item['transcription']['text']=='archive text'
        assert history.last_voice_processing[0]['transcribed']==1


def test_failed_asr_is_recorded_and_does_not_block_next_audio(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    class Model:
        def __init__(self,*args,**kwargs):pass
        def transcribe(self,*args,**kwargs):raise ValueError('private failure text')
    monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=Model))
    model=tmp_path/'model';model.mkdir()
    with HistoryStore(tmp_path/'history.db') as history:
        history.save_messages([dict(id=str(i),chat='friend',content='voice',time=f'2026-09-13 10:00:0{i}',raw={'type':'34','sort_seq':i+1},media=[dict(kind='voice',data=b'RIFFwav')]) for i in range(2)])
        voice=VoiceTranscriptions(history)
        result=voice.transcribe_local('friend',model,device='cpu')
        assert result['failed']==2
        assert history._connection.execute('SELECT DISTINCT error_code FROM voice_transcription_attempts').fetchall()==[('ValueError',)]
        assert voice.transcribe_local('friend',model,device='cpu')['attempted']==0
        assert voice.transcribe_local('friend',model,device='cpu',retry_failed=True)['attempted']==2


def test_repair_exported_ids_requires_exact_sort_time_and_body(tmp_path):
    source=tmp_path/'export.db';media=tmp_path/'media.db'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE messages(username TEXT,type TEXT,sort_seq INTEGER,create_time INTEGER,content TEXT,server_id INTEGER,local_id INTEGER)')
        db.execute("INSERT INTO messages VALUES('friend','语音',9,1789257600,'exact body',456,123)")
    with sqlite3.connect(media) as db:
        db.execute('CREATE TABLE Name2Id(user_name TEXT)')
        db.execute("INSERT INTO Name2Id VALUES('friend')")
        db.execute('CREATE TABLE VoiceInfo(chat_name_id INTEGER,svr_id INTEGER,voice_data BLOB)')
        db.execute('INSERT INTO VoiceInfo VALUES(1,456,?)',(b'original audio',))
    with HistoryStore(tmp_path/'history.db') as history:
        history.save_messages([dict(id='good',chat='friend',content='exact body',time='1789257600',raw={'type':'语音','sort_seq':9}),dict(id='wrong',chat='friend',content='another body',time='1789257600',raw={'type':'语音','sort_seq':10})])
        service=VoiceTranscriptions(history)
        result=service.import_native('friend',[media],[source])
        assert result['identities_recovered']==1 and result['audio_saved']==1
        assert history.get_message('good')['media'][0]['data']==b'original audio'
        assert not history.get_message('wrong')['media']
        assert history.get_message('good')['raw'].get('server_id') is None
        assert service.import_native('friend',[media])['audio_saved']==0


def test_parallel_asr_keeps_message_audio_and_text_associated(tmp_path, monkeypatch):
    import sys
    import threading
    from pathlib import Path
    from types import SimpleNamespace
    gate=threading.Barrier(2)
    class Model:
        def __init__(self,*args,**kwargs):
            assert kwargs['num_workers']==2
        def transcribe(self,path,**kwargs):
            text=Path(path).read_bytes().decode()
            gate.wait(timeout=5)
            return iter([SimpleNamespace(start=0,end=1,text=text,avg_logprob=-0.1,no_speech_prob=0)]),None
    monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=Model))
    model=tmp_path/'model';model.mkdir()
    with HistoryStore(tmp_path/'history.db') as history:
        history.save_messages([dict(id=str(i),chat='friend',content='voice',time=f'2026-09-13 10:00:0{i}',raw={'type':'34','sort_seq':i+1},media=[dict(kind='voice',data=f'audio-{i}'.encode())]) for i in range(2)])
        result=VoiceTranscriptions(history).transcribe_local('friend',model,device='cpu',workers=2)
        assert result['transcribed']==2 and result['failed']==0
        for i in range(2):
            assert history.get_message(str(i))['transcription']['text']==f'audio-{i}'
