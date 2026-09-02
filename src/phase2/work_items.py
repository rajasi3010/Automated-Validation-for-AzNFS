"""Create or find Azure DevOps Bugs for Phase 2 unsupported verdicts."""
from __future__ import annotations

import html
import logging
import os
from dataclasses import dataclass
from urllib.parse import quote

import requests
from azure.identity import DefaultAzureCredential
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

_AZURE_DEVOPS_SCOPE = "499b84ac-1321-427f-aa17-267ca6975798/.default"


@dataclass(frozen=True)
class BugConfig:
    organization: str
    project: str
    area_path: str = ""
    assigned_to: str = ""
    tags: str = "AzNFS"
    managed_identity_client_id: str | None = None
    timeout: int = 30
    max_retries: int = 3
    phase: str = ""
    product: str = "AzNFS Validation Tool"


class AzureDevOpsBugClient:
    """Idempotently create active Azure DevOps Bug work items."""

    def __init__(
        self,
        config: BugConfig,
        credential=None,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config
        self._credential = credential or DefaultAzureCredential(
            managed_identity_client_id=config.managed_identity_client_id
        )
        self._session = session or self._retrying_session(config.max_retries)
        organization = quote(config.organization, safe="")
        project = quote(config.project, safe="")
        self._api_base = f"https://dev.azure.com/{organization}/{project}/_apis/wit"
        self._web_base = f"https://dev.azure.com/{organization}/{project}/_workitems/edit"

    @staticmethod
    def _retrying_session(max_retries: int) -> requests.Session:
        retry = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"POST"}),
            respect_retry_after_header=True,
        )
        session = requests.Session()
        session.mount("https://", HTTPAdapter(max_retries=retry))
        return session

    def _headers(self, content_type: str) -> dict[str, str]:
        token = self._credential.get_token(_AZURE_DEVOPS_SCOPE).token
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
        }

    def _title(self, label: str, arch: str) -> str:
        # Phase-independent so Phase 2 and Phase 3 reuse the same Bug.
        return (
            f"[{self.config.product}] "
            f"{label} ({arch or 'unknown arch'}) is not supported by AzNFS"
        )

    def _find_active_bug(self, title: str) -> int | None:
        escaped_title = title.replace("'", "''")
        query = (
            "SELECT [System.Id] FROM WorkItems "
            "WHERE [System.TeamProject] = @project "
            "AND [System.WorkItemType] = 'Bug' "
            f"AND [System.Title] = '{escaped_title}' "
            "AND [System.State] NOT IN ('Closed', 'Resolved', 'Removed') "
            "ORDER BY [System.ChangedDate] DESC"
        )
        response = self._session.post(
            f"{self._api_base}/wiql?api-version=7.1",
            headers=self._headers("application/json"),
            json={"query": query},
            timeout=self.config.timeout,
        )
        response.raise_for_status()
        matches = response.json().get("workItems", [])
        return int(matches[0]["id"]) if matches else None

    @staticmethod
    def _source_run_url() -> str:
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
        repository = os.environ.get("GITHUB_REPOSITORY", "").strip("/")
        run_id = os.environ.get("GITHUB_RUN_ID", "")
        if repository and run_id:
            return f"{server}/{repository}/actions/runs/{run_id}"
        return ""

    @staticmethod
    def _next_steps(outcome: str) -> list[str]:
        if outcome == "pending_publish":
            return [
                "Confirm the distro/architecture is in the AzNFS support matrix "
                "(<code>packages.csv</code> in the AZNFS-mount repo).",
                "If it should be supported, publish the AzNFS package to the PMC prod "
                "repo for this distro/architecture.",
                "If it should not be supported, close this Bug as by-design.",
            ]
        return [
            "Open the workflow run linked above and read the failure for this distro.",
            "Reproduce it on a VM of the same image and fix the AzNFS package, "
            "the repo/package availability, or the test as appropriate.",
            "Once fixed, rerun the pipeline; a passing run flips the distro back to "
            "<code>known_supported</code>.",
            "If the distro is genuinely out of scope, close this Bug as by-design.",
        ]

    def _description(self, label: str, arch: str, outcome: str, reason: str) -> str:
        phase = self.config.phase or "Automated validation"
        source_url = self._source_run_url()
        source = (
            f"<a href=\"{html.escape(source_url, quote=True)}\">{html.escape(source_url)}</a>"
            if source_url
            else "not available (run outside GitHub Actions)"
        )
        why = (
            "the AzNFS package is not published on PMC prod for this "
            "distro/architecture, so it cannot be validated"
            if outcome == "pending_publish"
            else "automated validation failed for this distro/architecture, so it is "
            "recorded as <b>known unsupported</b> in the validation database"
        )
        steps = "".join(f"<li>{step}</li>" for step in self._next_steps(outcome))
        return (
            "<p><b>What happened</b><br/>"
            f"{html.escape(phase)} of the AzNFS automated validation pipeline reported "
            f"that {why}.</p>"
            "<p><b>Details</b></p>"
            "<ul>"
            f"<li><b>Distro:</b> {html.escape(label)}</li>"
            f"<li><b>Architecture:</b> {html.escape(arch or 'unknown')}</li>"
            f"<li><b>Detected by:</b> {html.escape(phase)}</li>"
            f"<li><b>Recorded state:</b> {html.escape(outcome)}</li>"
            f"<li><b>Reason:</b> {html.escape(reason or 'not reported')}</li>"
            f"<li><b>Pipeline run:</b> {source}</li>"
            "</ul>"
            "<p><b>What to do next</b></p>"
            f"<ol>{steps}</ol>"
            "<p>This Bug is created and reused automatically by the AzNFS validation "
            "pipeline: while it stays active, later runs link to it instead of filing "
            "a duplicate.</p>"
        )

    def ensure_bug(self, label: str, arch: str, outcome: str, reason: str) -> str:
        """Return an existing active Bug URL or create a new Bug and return its URL."""
        title = self._title(label, arch)

        work_item_id = self._find_active_bug(title)
        if work_item_id is not None:
            logger.info("Using existing Azure DevOps Bug %s for %s (%s)", work_item_id, label, arch)
            return f"{self._web_base}/{work_item_id}"

        patch = [
            {"op": "add", "path": "/fields/System.Title", "value": title},
            {
                "op": "add",
                "path": "/fields/System.Description",
                "value": self._description(label, arch, outcome, reason),
            },
        ]
        if self.config.area_path:
            patch.append({"op": "add", "path": "/fields/System.AreaPath", "value": self.config.area_path})
        if self.config.assigned_to:
            patch.append({"op": "add", "path": "/fields/System.AssignedTo", "value": self.config.assigned_to})
        if self.config.tags:
            patch.append({"op": "add", "path": "/fields/System.Tags", "value": self.config.tags})

        response = self._session.post(
            f"{self._api_base}/workitems/$Bug?api-version=7.1",
            headers=self._headers("application/json-patch+json"),
            json=patch,
            timeout=self.config.timeout,
        )
        response.raise_for_status()
        work_item_id = int(response.json()["id"])
        logger.info("Created Azure DevOps Bug %s for %s (%s)", work_item_id, label, arch)
        return f"{self._web_base}/{work_item_id}"


def from_env(phase: str = "") -> AzureDevOpsBugClient | None:
    """Build the Bug client when an Azure DevOps destination is configured."""
    organization = os.environ.get("AZDO_ORGANIZATION", "").strip()
    project = os.environ.get("AZDO_PROJECT", "").strip()
    if not organization or not project:
        logger.info("Azure DevOps Bug creation disabled: AZDO_ORGANIZATION/AZDO_PROJECT not configured")
        return None
    timeout = int(os.environ.get("AZDO_HTTP_TIMEOUT", "30") or "30")
    max_retries = int(os.environ.get("AZDO_HTTP_MAX_RETRIES", "3") or "3")
    return AzureDevOpsBugClient(BugConfig(
        organization=organization,
        project=project,
        area_path=os.environ.get("AZDO_AREA_PATH", "").strip(),
        assigned_to=os.environ.get("AZDO_ASSIGNED_TO", "").strip(),
        tags=os.environ.get("AZDO_TAGS", "AzNFS").strip(),
        managed_identity_client_id=(
            os.environ.get("AZDO_MANAGED_IDENTITY_CLIENT_ID")
            or os.environ.get("AZURE_MANAGED_IDENTITY_CLIENT_ID")
            or None
        ),
        timeout=timeout,
        max_retries=max_retries,
        phase=phase or os.environ.get("AZDO_PHASE", "").strip(),
        product=os.environ.get("AZDO_PRODUCT", "AzNFS Validation Tool").strip(),
    ))