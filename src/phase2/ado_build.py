"""Trigger an AzNFS Azure DevOps pipeline run and poll its status.

This is the Gate-4 "build" client for Phase 2: when a new distro/arch is in the
build matrix but not yet published on tux-dev, the orchestrator queues the AzNFS
build/sign/publish pipeline in ``targetEnv=tuxdev`` mode and polls until it
finishes. Auth is an AAD bearer token minted from the VM's managed identity
(MIscan) -- the same identity used for the onboarding-YAML reads. No PAT/secret.

Deliberately dumb: it holds no gate logic (tests inject a fake with the same
``trigger_run`` / ``get_run_status`` / ``ping`` surface).

REST surface (ADO REST API 7.1):
  trigger : POST {org}/{project}/_apis/pipelines/{pipelineId}/runs
  status  : GET  {org}/{project}/_apis/pipelines/{pipelineId}/runs/{runId}
  reach   : GET  {org}/{project}/_apis/pipelines/{pipelineId}
"""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

API_VERSION = "7.1"

# AAD resource (audience) for Azure DevOps -- MIscan's token must be scoped here.
ADO_RESOURCE_SCOPE = "499b84ac-1321-427f-aa17-267ca6975798/.default"

# Default MIscan (user-assigned managed identity) client id on the VM runner.
# Not a secret; override with ADO_MI_CLIENT_ID (empty = let DefaultAzureCredential
# auto-select system-assigned MI or `az login` during local dev).
MISCAN_CLIENT_ID = "ea2ea2c0-c588-498a-984e-a12e390743b5"

# ADO run "result" values once state == "completed".
RESULT_SUCCEEDED = "succeeded"
RESULT_FAILED = "failed"
RESULT_CANCELED = "canceled"


class AdoError(RuntimeError):
    """Raised when ADO returns an unexpected error response."""


class AdoBuildClient:
    """Queues an AzNFS pipeline run and reports its state/result."""

    def __init__(
        self,
        org: str | None = None,
        project: str | None = None,
        pipeline_id: str | None = None,
        mi_client_id: str | None = None,
        branch: str | None = None,
        timeout: int | None = None,
        session: requests.Session | None = None,
        credential=None,
    ) -> None:
        self.org = org or os.environ.get("ADO_ORG", "msazure")
        self.project = project or os.environ.get("ADO_PROJECT", "One")
        self.pipeline_id = pipeline_id or os.environ.get("AZNFS_PIPELINE_ID", "407942")
        self.mi_client_id = (
            mi_client_id if mi_client_id is not None
            else os.environ.get("ADO_MI_CLIENT_ID", MISCAN_CLIENT_ID)
        )
        self.branch = branch if branch is not None else os.environ.get("ADO_PIPELINE_BRANCH", "refs/heads/main")
        self.timeout = timeout if timeout is not None else int(os.environ.get("ADO_TIMEOUT", "30"))
        self._session = session or requests.Session()
        self._credential = credential

    # -- internals ---------------------------------------------------------
    def _base(self) -> str:
        org = self.org
        if not org.startswith("http"):
            org = f"https://dev.azure.com/{org}"
        return f"{org.rstrip('/')}/{self.project}/_apis/pipelines/{self.pipeline_id}"

    def _get_token(self) -> str:
        if self._credential is None:
            from azure.identity import DefaultAzureCredential  # lazy: only for live use
            self._credential = DefaultAzureCredential(
                managed_identity_client_id=self.mi_client_id or None
            )
        return self._credential.get_token(ADO_RESOURCE_SCOPE).token

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        token = self._get_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _request(self, method: str, url: str, json_body: dict | None = None) -> dict:
        resp = self._session.request(
            method, url,
            params={"api-version": API_VERSION},
            json=json_body,
            headers=self._headers(),
            timeout=self.timeout,
        )
        if not resp.ok:
            raise AdoError(f"ADO {method} {url} -> {resp.status_code}: {resp.text[:300]}")
        try:
            return resp.json()
        except ValueError as exc:  # pragma: no cover - defensive
            raise AdoError(f"ADO {method} {url}: invalid JSON: {exc}") from exc

    # -- public API --------------------------------------------------------
    def get_pipeline(self) -> dict:
        """GET the pipeline definition -- used by pre-flight reachability."""
        return self._request("GET", self._base())

    def ping(self, client_id: str | None = None) -> bool:
        """Pre-flight reachability probe (``client_id`` accepted for protocol parity)."""
        try:
            self.get_pipeline()
            return True
        except (AdoError, requests.RequestException) as exc:
            logger.error("ADO pipeline unreachable: %s", exc)
            return False

    def trigger_run(self, params: dict) -> str:
        """Queue a pipeline run with template parameters; return the run id (str).

        ``params`` becomes ``templateParameters`` (e.g. versionName, targetEnv).
        The run is queued on the configured branch.
        """
        body: dict = {"templateParameters": params}
        if self.branch:
            body["resources"] = {"repositories": {"self": {"refName": self.branch}}}
        data = self._request("POST", f"{self._base()}/runs", json_body=body)
        run_id = str(data.get("id", ""))
        if not run_id:
            raise AdoError(f"ADO trigger_run: no run id in response: {data}")
        logger.info("ADO run %s queued (params=%s)", run_id, params)
        return run_id

    def get_run_status(self, run_id: str) -> tuple[str, str | None]:
        """Return (state, result).

        state  e.g. 'inProgress' | 'completed';
        result e.g. 'succeeded' | 'failed' | 'canceled' (None until completed).
        """
        data = self._request("GET", f"{self._base()}/runs/{run_id}")
        return data.get("state", ""), data.get("result")


def from_env() -> AdoBuildClient:
    return AdoBuildClient()
