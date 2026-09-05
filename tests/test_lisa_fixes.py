"""Tests for the LISA engine patch loaded as a runbook extension.

The module patches LISA internals at import time, so it is imported against a
stub of ``lisa.sut_orchestrator.azure.features`` -- the engine is not a test
dependency, and stubbing keeps these tests honest about what the wrapper does
rather than what the real function happens to accept.
"""
from __future__ import annotations

import importlib
import sys
import types

import pytest


def _install_stub_engine(monkeypatch):
    """Put a fake LISA features module in sys.modules and return it."""
    calls: list[dict] = []

    def check_or_create_storage_account(name, *, allow_shared_key_access=False):
        """Original docstring."""
        calls.append({"name": name, "allow_shared_key_access": allow_shared_key_access})
        return name

    features = types.ModuleType("lisa.sut_orchestrator.azure.features")
    features.check_or_create_storage_account = check_or_create_storage_account
    for name in ("lisa", "lisa.sut_orchestrator", "lisa.sut_orchestrator.azure"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "lisa.sut_orchestrator.azure.features", features)
    monkeypatch.syspath_prepend("phase3/testsuites")
    monkeypatch.delitem(sys.modules, "_lisa_fixes", raising=False)
    return features, calls, check_or_create_storage_account


@pytest.fixture
def engine(monkeypatch):
    features, calls, original = _install_stub_engine(monkeypatch)
    module = importlib.import_module("_lisa_fixes")
    return features, calls, original, module


def test_shared_key_access_is_enabled_by_default(engine):
    # Without this, Nfs.create_share cannot list the account keys and every NFS
    # test dies before it mounts anything.
    features, calls, _, _ = engine
    features.check_or_create_storage_account("acct")
    assert calls[-1]["allow_shared_key_access"] is True


def test_explicit_argument_is_not_overridden(engine):
    features, calls, _, _ = engine
    features.check_or_create_storage_account("acct", allow_shared_key_access=False)
    assert calls[-1]["allow_shared_key_access"] is False


def test_positional_arguments_still_reach_the_original(engine):
    features, calls, _, _ = engine
    assert features.check_or_create_storage_account("acct") == "acct"
    assert calls[-1]["name"] == "acct"


def test_patch_is_idempotent_across_reimports(engine):
    # LISA may import the extension more than once; wrapping a wrapper would
    # still work but makes tracebacks harder to read.
    features, _, _, module = engine
    first = features.check_or_create_storage_account
    importlib.reload(module)
    importlib.reload(module)
    assert features.check_or_create_storage_account is first


def test_reload_does_not_make_the_wrapper_call_itself(engine):
    # Re-executing the module reuses its namespace, so reading the patched
    # function back as "the original" would recurse until the stack blew up.
    features, calls, original, module = engine
    importlib.reload(module)
    features.check_or_create_storage_account("acct")
    assert calls[-1]["allow_shared_key_access"] is True
    assert features.check_or_create_storage_account.__wrapped__ is original


def test_original_metadata_is_preserved(engine):
    features, _, _, _ = engine
    patched = features.check_or_create_storage_account
    assert patched.__name__ == "check_or_create_storage_account"
    assert patched.__doc__ == "Original docstring."
