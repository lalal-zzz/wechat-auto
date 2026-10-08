"""Import local WeChat voice data/native text, or transcribe with an offline model."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from wechat_auto.storage.history_store import HistoryStore
from wechat_auto.storage.voice_transcription import VoiceTranscriptions
from wechat_auto.memory.store import MemoryStore
from wechat_auto.memory.analysis import AnalysisService
from wechat_auto.memory.markdown import MarkdownMemory
from wechat_auto.memory.indexer import message_period


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-db",type=Path,required=True)
    parser.add_argument("--memory-db",type=Path,default=Path("data/wechat_memory.sqlite3"))
    parser.add_argument("--memory-root",type=Path,default=Path("data/memory"))
    parser.add_argument("--conversation-id",required=True)
    parser.add_argument("--media-db",type=Path,action="append",default=[],help="explicit decrypted local media shard; read only")
    parser.add_argument("--message-source",type=Path,action="append",default=[],help="local original message export for exact ID repair")
    parser.add_argument("--native-results",type=Path,help="local JSON list: message_id,text,source_ref; verified WeChat UI results")
    parser.add_argument("--model-path",type=Path,help="existing offline faster-whisper model directory")
    parser.add_argument("--limit",type=int,default=100)
    parser.add_argument("--device",choices=["auto","cpu","cuda"],default="auto")
    parser.add_argument("--retry-failed",action="store_true")
    parser.add_argument("--progress",action="store_true")
    parser.add_argument("--workers",type=int,default=1)
    args=parser.parse_args()
    if not args.history_db.is_file() or not args.memory_db.is_file():parser.error("existing archive and Memory databases required")
    with MemoryStore(args.memory_db) as memory, HistoryStore(args.history_db) as history:
        conversation=memory.get_conversation(args.conversation_id)
        if not conversation:parser.error("unknown conversation ID")
        chat=conversation["source_chat_id"]
        transcriptions=VoiceTranscriptions(history)
        def versions():return {r[0]:r[1] for r in history._connection.execute("SELECT t.message_id,max(t.version) FROM voice_transcriptions t JOIN messages m ON m.id=t.message_id WHERE m.chat=? GROUP BY t.message_id",(chat,))}
        before=versions()
        summary=transcriptions.import_native(chat,args.media_db,args.message_source)
        if args.native_results:
            for item in json.loads(args.native_results.read_text(encoding="utf-8")):
                row=history._connection.execute("SELECT chat FROM messages WHERE id=?",(item["message_id"],)).fetchone()
                if not row or row[0]!=chat:raise ValueError("native result belongs to another conversation")
                transcriptions.save(item["message_id"],item["text"],engine="wechat_native",source_ref=item["source_ref"])
        if args.model_path:summary["asr"]=transcriptions.transcribe_local(chat,args.model_path,limit=args.limit,device=args.device,retry_failed=args.retry_failed,workers=args.workers,
            progress=(lambda value: print(json.dumps(value),flush=True) if value["processed"] % 50 == 0 or value["processed"] == value["total"] else None) if args.progress else None)
        service=AnalysisService(memory,MarkdownMemory(args.memory_root,memory),args.history_db)
        changed=0
        for mid,version in versions().items():
            if before.get(mid)==version:continue
            row=history._connection.execute("SELECT message_time FROM messages WHERE id=?",(mid,)).fetchone()
            period=message_period(row[0])
            if period:service.mark_message_delta(args.conversation_id,period,mid);changed+=1
        summary["changed_transcripts"]=changed
        summary["analysis_updated"]=False
        print(json.dumps(summary,ensure_ascii=False))


if __name__=="__main__":main()
