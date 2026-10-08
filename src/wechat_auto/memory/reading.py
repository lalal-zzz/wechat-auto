"""Lossless natural-text reading helpers; never display media XML attributes."""
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timedelta, timezone

TEXT_TAGS = {'title', 'des', 'desc', 'content', 'recorditem', 'datadesc',
             'dataname', 'sourcename', 'displayname', 'text', 'voicetrans',
             'transcription', 'label', 'poiid'}
XML_START = re.compile(r'<(?:\?xml\b|(?:msg|appmsg|recordinfo|emoji|voicemsg|videomsg|img|sysmsg|location)(?=[\s/>]))')
MEDIA_TYPES = {'图片', '动画表情', '语音', '视频', '3', '34', '43', '47'}


def display_time(value):
    try:
        timestamp = float(value)
        if abs(timestamp) > 100_000_000_000:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp, timezone(timedelta(hours=8))).isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        return str(value) if value is not None else 'unknown'


def readable_message(message, *, recover_xml=False):
    readable = str(message.get('readable') or '')
    content = str(message.get('content') or '')
    parts = []
    errors = []
    raw = message.get('raw') or {}
    media = isinstance(raw, dict) and str(raw.get('type')) in MEDIA_TYPES

    def retain_prefix(prefix):
        prefix = prefix.strip()
        if (prefix and not re.search(r'<[A-Za-z_!?/]', prefix)
                and not re.search(r'\b(?:aeskey|cdnurl|encryptedkey|md5)\s*=', prefix, re.I)
                and all(c.isprintable() or c in '\n\r\t' for c in prefix)
                and prefix not in parts):
            parts.append(prefix)

    def parse_xml(value, depth=0):
        if depth > 30:
            errors.append('nested XML exceeds safe depth; must inspect separately')
            return
        try:
            tree = ET.fromstring(value)
        except ET.ParseError:
            errors.append('XML parse failure; body/quote requires separate inspection')
            if not recover_xml:
                return
            try:
                from lxml import etree
            except ImportError:
                return
            try:
                tree = etree.fromstring(value.encode('utf-8'), etree.XMLParser(
                    recover=True, resolve_entities=False, no_network=True))
            except (ValueError, etree.XMLSyntaxError):
                return
            if tree is None:
                return
            errors.append('XML recovered locally; inspect displayed whitelist text')
        for node in tree.iter():
            if not isinstance(node.tag, str):
                continue
            tag = node.tag.rsplit('}', 1)[-1].lower()
            if tag in TEXT_TAGS and node.text and node.text.strip():
                text = node.text.strip()
                if text.startswith('<') or XML_START.search(text):
                    match = XML_START.search(text)
                    if match:
                        retain_prefix(text[:match.start()])
                        text = text[match.start():]
                    parse_xml(text, depth + 1)
                elif text not in parts:
                    parts.append(text)

    # Exported media may prepend binary/transport text before its XML root.
    # Detect the root anywhere so its attributes never become ordinary text.
    for value in (readable, content):
        match = XML_START.search(value)
        if match:
            if not media:
                retain_prefix(value[:match.start()])
            parse_xml(value[match.start():])
        elif value.lstrip().startswith('<'):
            parse_xml(value)
        elif value and value not in parts:
            parts.append(value)
    transcript = message.get("transcription") or {}
    if isinstance(transcript, dict) and transcript.get("text"):
        parts.append("[语音转写 · " + str(transcript.get("engine", "unknown")) + " · " + str(transcript.get("status", "unreviewed")) + "] " + transcript["text"])
    if not parts and (readable or content):
        parts.append('[XML/媒体正文未解读]')
    return parts, list(dict.fromkeys(errors))
