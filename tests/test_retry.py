"""Tests for wechat_auto.utils.retry module."""

from unittest.mock import MagicMock

import pytest

from wechat_auto.utils.retry import retry_on_failure


class TestRetryOnFailure:
    def test_success_no_retry(self):
        func = MagicMock(return_value=42)

        @retry_on_failure(max_retries=3, delay=0)
        def wrapped():
            return func()

        result = wrapped()
        assert result == 42
        assert func.call_count == 1

    def test_retry_on_exception(self):
        call_count = 0

        @retry_on_failure(max_retries=3, delay=0, exceptions=(ValueError,))
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temporary")
            return "ok"

        result = flaky()
        assert result == "ok"
        assert call_count == 3

    def test_exhausted_retries_raises(self):
        @retry_on_failure(max_retries=2, delay=0, exceptions=(RuntimeError,))
        def always_fails():
            raise RuntimeError("permanent")

        with pytest.raises(RuntimeError, match="permanent"):
            always_fails()

    def test_on_retry_callback(self):
        callback = MagicMock()

        @retry_on_failure(max_retries=3, delay=0, exceptions=(ValueError,), on_retry=callback)
        def flaky():
            raise ValueError("fail")

        with pytest.raises(ValueError):
            flaky()

        assert callback.call_count == 3
