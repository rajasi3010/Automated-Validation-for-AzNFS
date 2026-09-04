"""Runtime fixes applied to the LISA engine, loaded as a runbook extension.

LISA imports every module under ``phase3/testsuites`` (the runbook's
``extension:`` entry), so this runs inside the LISA process before any test
does. That is what lets the engine be installed as an ordinary pinned package
instead of a source checkout: nothing on disk is edited, and the fix is in
version control where it can be reviewed.
"""
from __future__ import annotations

import functools
import logging
from typing import Any

from lisa.sut_orchestrator.azure import features as _features

logger = logging.getLogger(__name__)

_installed = _features.check_or_create_storage_account
# Re-executing this module reuses its namespace, so reading the patched function
# back would make the wrapper call itself. Unwrap to the pristine one instead.
_original_check_or_create_storage_account = getattr(_installed, "__wrapped__", _installed)


@functools.wraps(_original_check_or_create_storage_account)
def _check_or_create_storage_account(*args: Any, **kwargs: Any) -> Any:
    """Create LISA's storage accounts with shared-key auth enabled.

    ``Nfs.create_share`` creates the file share through the data plane
    (``ShareServiceClient``), which needs the account key, but account creation
    defaults shared-key access OFF -- so ``list_keys`` fails with "Key based
    authentication is not permitted on this storage account" and every NFS test
    dies before it mounts anything. The NFS mount itself uses sec=sys, not keys.

    Only fills in the default; an explicit argument still wins.
    """
    kwargs.setdefault("allow_shared_key_access", True)
    return _original_check_or_create_storage_account(*args, **kwargs)


# functools.wraps copies __module__ from the original, so the patch cannot be
# recognised by module; tag it explicitly instead.
_check_or_create_storage_account._aznfs_patched = True  # type: ignore[attr-defined]

# Idempotent: LISA may import this module more than once, and wrapping a wrapper
# would still work but makes tracebacks harder to read.
if not getattr(_features.check_or_create_storage_account, "_aznfs_patched", False):
    _features.check_or_create_storage_account = _check_or_create_storage_account
    logger.debug("Patched check_or_create_storage_account to allow shared-key access")
