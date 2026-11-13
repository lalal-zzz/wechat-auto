"""Optional adapter imports cannot take ownership of MCP streams or logging."""

import importlib.util
import io
import json
import logging
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from wechat_auto.backends.replica_import import replica_module


@pytest.mark.parametrize('fail', [False, True])
def test_import_side_effects_are_restored_even_on_failure(fail):
    stdout, stderr = sys.stdout, sys.stderr
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level

    def import_module(name):
        print('synthetic vendor initialization')
        sys.stdout = io.StringIO()
        root.handlers.clear()
        root.setLevel(logging.DEBUG)
        if fail:
            raise ImportError('synthetic missing dependency')
        return SimpleNamespace()

    with patch('wechat_auto.backends.replica_import.importlib.import_module', side_effect=import_module):
        if fail:
            with pytest.raises(ImportError):
                replica_module('synthetic_replica')
        else:
            replica_module('synthetic_replica')
    assert sys.stdout is stdout and sys.stderr is stderr
    assert root.handlers == handlers and root.level == level


def test_installed_replica_import_preserves_real_process_streams():
    if importlib.util.find_spec('wechatauto') is None:
        pytest.skip('optional adapter is not installed')
    code = """
import sys, json, logging
from wechat_auto.backends.replica_import import replica_module
stdout, stderr = sys.stdout, sys.stderr
root = logging.getLogger()
handlers, level = root.handlers[:], root.level
module = replica_module('wechatauto.db')
print(json.dumps({'stdout_preserved': sys.stdout is stdout, 'stderr_preserved': sys.stderr is stderr,
                  'logging_preserved': root.handlers == handlers and root.level == level,
                  'database_class_available': hasattr(module, 'WeChatDB')}))
"""
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0
    assert all(json.loads(result.stdout).values())
