"""Model selection and shared inference must be deterministic across workers."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock, RLock
from time import sleep
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from wechat_auto.config import WeChatConfig
from wechat_auto.primitives import vision


def test_ocr_warning_excludes_exception_details(monkeypatch, caplog):
    monkeypatch.setattr(vision, '_OCR_FAIL_WARNED', False)
    vision._warn_ocr_failure(RuntimeError('synthetic private payload'))

    assert 'RuntimeError' in caplog.text
    assert 'synthetic private payload' not in caplog.text


def test_paddle_cache_tracks_both_model_names_and_configuration_snapshot(monkeypatch):
    monkeypatch.setattr(vision, '_OCR_ENGINES', {})
    config = WeChatConfig()
    with patch.object(vision, '_PaddleOCRAdapter', side_effect=lambda config: object()) as create:
        first = vision._get_ocr_engine(config)
        assert vision._get_ocr_engine(config) is first
        config.paddle_recognition_model = 'synthetic-recognition'
        second = vision._get_ocr_engine(config)
        assert second is not first
        config.paddle_detection_model = 'synthetic-detection'
        assert vision._get_ocr_engine(config) is not second
    assert create.call_count == 3
    assert create.call_args_list[0].args[0].paddle_recognition_model != config.paddle_recognition_model


def test_strict_paddle_cannot_reuse_cached_rapid_fallback(monkeypatch):
    monkeypatch.setattr(vision, '_OCR_ENGINES', {})
    with (
        patch.object(vision, '_PaddleOCRAdapter', side_effect=ImportError('synthetic missing package')),
        patch.object(vision, '_RapidOCRAdapter') as rapid,
    ):
        assert vision._get_ocr_engine(WeChatConfig()) is rapid.return_value
        with pytest.raises(ImportError):
            vision._get_ocr_engine(WeChatConfig(ocr_allow_rapid_fallback=False))
    assert rapid.call_count == 1


def test_failed_model_initialization_is_not_cached_or_silently_replaced(monkeypatch):
    monkeypatch.setattr(vision, '_OCR_ENGINES', {})
    engine = object()
    with (
        patch.object(vision, '_PaddleOCRAdapter', side_effect=[RuntimeError('synthetic model failure'), engine]),
        patch.object(vision, '_RapidOCRAdapter') as rapid,
    ):
        with pytest.raises(RuntimeError):
            vision._get_ocr_engine(WeChatConfig())
        assert vision._get_ocr_engine(WeChatConfig()) is engine
    rapid.assert_not_called()


def test_concurrent_ocr_initialization_loads_one_shared_instance(monkeypatch):
    monkeypatch.setattr(vision, '_OCR_ENGINES', {})
    started, release, duplicate = Event(), Event(), Event()
    calls = []
    engine = object()

    def load(config):
        calls.append(config)
        if len(calls) > 1:
            duplicate.set()
        started.set()
        assert release.wait(timeout=5)
        return engine

    with patch.object(vision, '_PaddleOCRAdapter', side_effect=load), ThreadPoolExecutor(2) as workers:
        first = workers.submit(vision._get_ocr_engine, WeChatConfig())
        assert started.wait(timeout=5)
        second = workers.submit(vision._get_ocr_engine, WeChatConfig())
        try:
            assert not duplicate.wait(timeout=.1)
        finally:
            release.set()
        assert first.result(timeout=5) is second.result(timeout=5) is engine
    assert len(calls) == 1


@pytest.mark.parametrize('adapter_type', [vision._PaddleOCRAdapter, vision._RapidOCRAdapter])
def test_shared_adapter_serializes_underlying_inference(adapter_type):
    adapter = adapter_type.__new__(adapter_type)
    adapter._inference_lock = RLock()
    state = {'active': 0, 'maximum': 0}
    counter = Lock()

    def inference(*args, **kwargs):
        with counter:
            state['active'] += 1
            state['maximum'] = max(state['maximum'], state['active'])
        try:
            sleep(.01)
            return []
        finally:
            with counter:
                state['active'] -= 1

    adapter.engine = MagicMock(predict=inference) if adapter_type is vision._PaddleOCRAdapter else inference
    with ThreadPoolExecutor(4) as workers:
        results = list(workers.map(adapter, [np.zeros((8, 8, 3), dtype=np.uint8)] * 8))
    assert len(results) == 8 and state['maximum'] == 1
