"""Local voice extraction and provenance-preserving transcription. No network/UI."""
from __future__ import annotations
import hashlib
import json
import sqlite3
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor


def embedded_transcript(content: str) -> str:
    start = content.find("<msg")
    try:
        root = ET.fromstring(content[start:] if start >= 0 else content)
    except ET.ParseError:
        return ""
    return "\n".join(node.text.strip() for node in root.iter()
                     if node.tag.rsplit("}", 1)[-1].lower() in {"voicetrans", "transcription"}
                     and node.text and node.text.strip())


class VoiceTranscriptions:
    def __init__(self, history):
        self.history = history
        history._connection.execute("""CREATE TABLE IF NOT EXISTS voice_transcriptions(
            message_id TEXT NOT NULL, version INTEGER NOT NULL, text TEXT NOT NULL,
            engine TEXT NOT NULL, source_ref TEXT NOT NULL, audio_sha256 TEXT NOT NULL,
            segments_json TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(message_id,version), FOREIGN KEY(message_id) REFERENCES messages(id))""")
        history._connection.execute("""CREATE TABLE IF NOT EXISTS voice_transcription_attempts(
            message_id TEXT NOT NULL, audio_sha256 TEXT NOT NULL, model_ref TEXT NOT NULL,
            status TEXT NOT NULL, error_code TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(message_id,audio_sha256,model_ref))""")
        history._connection.execute("""CREATE TABLE IF NOT EXISTS voice_message_links(
            message_id TEXT PRIMARY KEY, server_id TEXT NOT NULL, local_id TEXT NOT NULL,
            sort_seq TEXT NOT NULL, message_time TEXT NOT NULL, content_sha256 TEXT NOT NULL,
            source_ref TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        history._connection.commit()

    def save(self, message_id, text, *, engine, source_ref, audio_sha256="", segments=()):
        text = text.strip()
        if not text or engine not in {"wechat_native", "local_asr", "user_corrected"} or not source_ref:
            raise ValueError("transcription needs text, supported engine and source provenance")
        row = self.history._connection.execute(
            "SELECT raw_json FROM messages WHERE id=?", (message_id,)).fetchone()
        if not row or str(json.loads(row[0]).get("type")) not in {"语音", "34"}:
            raise ValueError("transcription target must be a stable voice message ID")
        old = self.history._connection.execute(
            "SELECT version,text,engine,source_ref,audio_sha256,segments_json FROM voice_transcriptions WHERE message_id=? ORDER BY version DESC LIMIT 1",
            (message_id,)).fetchone()
        segments_json = json.dumps(list(segments), ensure_ascii=False, sort_keys=True)
        values = (text, engine, source_ref, audio_sha256, segments_json)
        if old and old[1:] == values:
            return False
        # Machine retranscription never silently replaces a user's correction.
        if old and old[2] == "user_corrected" and engine != "user_corrected":
            return False
        with self.history._connection:
            self.history._connection.execute(
                "INSERT INTO voice_transcriptions(message_id,version,text,engine,source_ref,audio_sha256,segments_json,status) VALUES(?,?,?,?,?,?,?,?)",
                (message_id, old[0]+1 if old else 1, *values, "user_corrected" if engine == "user_corrected" else "transcribed_unreviewed"))
        return True

    def _source_identities(self, chat, paths):
        """Recover omitted IDs through exact source fields; never use time alone."""
        identities = {}
        for path in paths:
            path = Path(path).resolve()
            with sqlite3.connect(path.as_uri()+"?mode=ro",uri=True) as db:
                columns = {row[1] for row in db.execute("PRAGMA table_info(messages)")}
                needed = {"username","type","sort_seq","create_time","content","server_id","local_id"}
                if not needed <= columns:
                    raise ValueError("message identity source schema is unsupported")
                for seq, stamp, content, server, local in db.execute(
                    "SELECT sort_seq,create_time,content,server_id,local_id FROM messages WHERE username=? AND type IN ('语音','34',34)", (chat,)):
                    if not server or str(server)=="0" or not seq:
                        continue
                    key=(str(seq),str(stamp),content or "")
                    identities.setdefault(key,{})[(str(server),str(local or ""))]=str(path)
        return identities

    def import_native(self, chat, media_paths=(), message_sources=()):
        """Read explicit decrypted local VoiceInfo shards; do not guess a transcript field."""
        stats = dict(voices=0, audio_saved=0, native_transcripts_saved=0, missing_audio=0,
                     unsupported_transcript_shards=0, identities_recovered=0, ambiguous_identity=0, unmatched_audio=0)
        identities=self._source_identities(chat,message_sources)
        sources=[]
        try:
            for path in media_paths:
                path=Path(path).resolve()
                db=sqlite3.connect(path.as_uri()+"?mode=ro",uri=True)
                sources.append((path,db))
                cols={r[1] for r in db.execute("PRAGMA table_info(VoiceInfo)")}
                if not {"chat_name_id", "svr_id", "voice_data"} <= cols:
                    raise ValueError("unsupported local VoiceInfo schema")
                # Absence is reported, not treated as proof that the UI cannot transcribe.
                stats["unsupported_transcript_shards"] += int(not ({"voice_text", "trans_text", "transcription"} & cols))
            rows=self.history._connection.execute(
                "SELECT id,content,raw_json,message_time FROM messages WHERE chat=?",(chat,)).fetchall()
            for mid,content,raw_json,stamp in rows:
                raw=json.loads(raw_json)
                if str(raw.get("type")) not in {"语音","34"}: continue
                stats["voices"]+=1
                transcript=embedded_transcript(content)
                if transcript:
                    stats["native_transcripts_saved"]+=int(self.save(mid,transcript,engine="wechat_native",source_ref="message_xml:"+mid))
                found=False
                server_id=str(raw.get("server_id") or "")
                if not server_id or server_id == "0":
                    matches=identities.get((str(raw.get("sort_seq") or ""),str(stamp),content or ""),{})
                    if len(matches)>1:
                        stats["ambiguous_identity"]+=1
                    elif len(matches)==1:
                        (server_id,local_id),source_ref=next(iter(matches.items()))
                        digest=hashlib.sha256((content or "").encode("utf-8")).hexdigest()
                        old=self.history._connection.execute("SELECT server_id,local_id FROM voice_message_links WHERE message_id=?",(mid,)).fetchone()
                        if old and old!=(server_id,local_id):
                            raise ValueError("voice identity repair conflicts with existing link")
                        with self.history._connection:
                            self.history._connection.execute("INSERT OR IGNORE INTO voice_message_links(message_id,server_id,local_id,sort_seq,message_time,content_sha256,source_ref,status) VALUES(?,?,?,?,?,?,?,?)",(mid,server_id,local_id,str(raw.get("sort_seq")),str(stamp),digest,source_ref,"verified_exact_source_fields"))
                        stats["identities_recovered"]+=int(old is None)
                    else:
                        old=self.history._connection.execute("SELECT server_id FROM voice_message_links WHERE message_id=?",(mid,)).fetchone()
                        if old:server_id=old[0]
                if server_id and server_id != "0":
                    for path,db in sources:
                        cols={r[1] for r in db.execute("PRAGMA table_info(VoiceInfo)")}
                        text_col=next((c for c in ("voice_text","trans_text","transcription") if c in cols),None)
                        fields="v.voice_data"+(f",v.{text_col}" if text_col else "")
                        hits=db.execute(f"SELECT {fields} FROM VoiceInfo v JOIN Name2Id n ON n.rowid=v.chat_name_id WHERE n.user_name=? AND CAST(v.svr_id AS TEXT)=?",(chat,server_id)).fetchall()
                        # Ambiguous shard matches are not silently attached to a message.
                        if len(hits)>1: raise ValueError("ambiguous voice server ID in shard")
                        if not hits: continue
                        payload=hits[0][0]
                        if payload:
                            payload=bytes(payload);digest=hashlib.sha256(payload).hexdigest()
                            before=self.history._connection.total_changes
                            with self.history._connection:
                                self.history._connection.execute("INSERT OR IGNORE INTO message_media(id,message_id,chat,kind,mime_type,original_ref,local_name,size,sha256,data) VALUES(?,?,?,?,?,?,?,?,?,?)",
                                    ("voice:"+hashlib.sha256((mid+digest).encode()).hexdigest(),mid,chat,"voice","audio/silk",str(path),"voice.silk",len(payload),digest,payload))
                            stats["audio_saved"]+=self.history._connection.total_changes-before
                            found=True
                        if text_col and isinstance(hits[0][1],str) and hits[0][1].strip():
                            stats["native_transcripts_saved"]+=int(self.save(mid,hits[0][1],engine="wechat_native",source_ref=str(path),audio_sha256=hashlib.sha256(bytes(payload)).hexdigest() if payload else ""))
                        if found: break
                if not found:
                    found=bool(self.history._connection.execute("SELECT 1 FROM message_media WHERE message_id=? AND kind IN ('voice','audio')",(mid,)).fetchone())
                stats["unmatched_audio"]+=int(not found)
                stats["missing_audio"]+=int(not found)
            stats["missing_audio_confirmed"]=False
            return stats
        finally:
            for _,db in sources:db.close()

    def transcribe_local(self, chat, model_path, *, limit=100, device="auto", retry_failed=False,
                         message_ids=None, progress=None, workers=1):
        model_path=Path(model_path).resolve()
        if not model_path.is_dir(): raise ValueError("provide an existing local ASR model directory")
        if limit < 1: raise ValueError("limit must be positive")
        if not 1 <= workers <= 8: raise ValueError("workers must be from 1 through 8")
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("local ASR requires faster-whisper and an existing model; nothing is downloaded automatically") from exc
        if device == "auto":
            import ctranslate2
            device = "cuda" if ctranslate2.get_cuda_device_count() else "cpu"
        if device not in {"cpu", "cuda"}: raise ValueError("device must be auto, cpu or cuda")
        model=WhisperModel(str(model_path),device=device,
                          compute_type="int8_float16" if device=="cuda" else "int8",local_files_only=True,
                          num_workers=workers,cpu_threads=2 if workers > 1 else 0)
        rows=self.history._connection.execute("""SELECT m.id,mm.data,mm.sha256 FROM messages m JOIN message_media mm ON mm.message_id=m.id
            WHERE m.chat=? AND mm.kind IN ('voice','audio') AND NOT EXISTS(SELECT 1 FROM voice_transcriptions t WHERE t.message_id=m.id)
            GROUP BY m.id ORDER BY m.rowid""",(chat,)).fetchall()
        selected=[]
        allowed=set(message_ids) if message_ids is not None else None
        for row in rows:
            if allowed is not None and row[0] not in allowed:continue
            previous=self.history._connection.execute("SELECT status FROM voice_transcription_attempts WHERE message_id=? AND audio_sha256=? AND model_ref=?",(row[0],row[2],str(model_path))).fetchone()
            if previous and not retry_failed:continue
            selected.append(row)
            if len(selected)>=limit:break
        def recognize(row):
            mid,payload,digest=row
            state,code="failed",""
            text="";parts=[]
            try:
                with tempfile.TemporaryDirectory(prefix="wechat-voice-") as folder:
                    audio=Path(folder)/"voice.audio";audio.write_bytes(payload)
                    if b"#!SILK_V3" in bytes(payload)[:20]:
                        try: import pilk
                        except ImportError as exc: raise RuntimeError("SILK decoding requires pilk") from exc
                        import wave
                        pcm=Path(folder)/"voice.pcm";pilk.decode(str(audio),str(pcm),pcm_rate=24000)
                        audio=Path(folder)/"voice.wav"
                        with wave.open(str(audio),'wb') as out:
                            out.setnchannels(1);out.setsampwidth(2);out.setframerate(24000);out.writeframes(pcm.read_bytes())
                    segments,_=model.transcribe(str(audio),language="zh",vad_filter=True)
                    parts=[dict(start=s.start,end=s.end,text=s.text,avg_logprob=s.avg_logprob,no_speech_prob=s.no_speech_prob) for s in segments]
                    text="".join(p["text"] for p in parts).strip()
                    if text:
                        state="transcribed"
                    else:
                        state="empty"
            except Exception as exc:
                # Store a redacted code, never exception text with private data.
                code=type(exc).__name__
            return mid,digest,state,code,text,parts
        done=failed=empty=0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for index,(mid,digest,state,code,text,parts) in enumerate(pool.map(recognize,selected)):
                if state=="transcribed":
                    done+=int(self.save(mid,text,engine="local_asr",source_ref=str(model_path),audio_sha256=digest,segments=parts))
                elif state=="empty":empty+=1
                else:failed+=1
                with self.history._connection:
                    self.history._connection.execute("INSERT INTO voice_transcription_attempts(message_id,audio_sha256,model_ref,status,error_code) VALUES(?,?,?,?,?) ON CONFLICT(message_id,audio_sha256,model_ref) DO UPDATE SET status=excluded.status,error_code=excluded.error_code,updated_at=CURRENT_TIMESTAMP",(mid,digest,str(model_path),state,code))
                if progress:progress(dict(processed=index+1,total=len(selected),transcribed=done,failed=failed,empty=empty))
        return dict(attempted=len(selected),transcribed=done,failed=failed,empty=empty,device=device)
