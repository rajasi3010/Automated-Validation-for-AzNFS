"""Read-only reader for the Compute-PMC.Onboarding repo's tux-dev repo YAMLs.

Replaces the old PMC v4 ``get_repository`` call: Gate 2's repo config
(``signing_service`` / ``groups``) now comes from the per-repo YAML definitions
under ``data/tux/repos`` in the ADO git repo (msazure/One), read over the ADO
REST "Items" API with an AAD bearer token minted from the VM's managed identity
(MIscan). No PMC API and no extra secret.

Deliberately dumb: it lists YAML paths, fetches/parses them, and maps a repo
name to its config dict. All gate logic stays in the orchestrator (tests inject
a fake with the same ``get_repo_config`` surface).

REST surface (ADO REST API 7.1):
  list : GET {org}/{project}/_apis/git/repositories/{repo}/items
             ?scopePath={path}&recursionLevel=Full&versionDescriptor.version={ref}
  item : GET {org}/{project}/_apis/git/repositories/{repo}/items
             ?path={path}&includeContent=true&$format=json&versionDescriptor.version={ref}
"""
from __future__ import annotations

import logging
import os
import re

import requests
import yaml

logger = logging.getLogger(__name__)

API_VERSION = "7.1"

# AAD resource (audience) for Azure DevOps — MIscan's token must be scoped here.
ADO_RESOURCE_SCOPE = "499b84ac-1321-427f-aa17-267ca6975798/.default"


class OnboardingError(RuntimeError):
    """Raised when the onboarding repo returns an unexpected error response."""


def _norm(s: str) -> str:
    """Lowercase and strip all separators, for tolerant repo-name comparison."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _short_name(path: str) -> str:
    """'repos/microsoft-ubuntu-noble' -> 'microsoft-ubuntu-noble'."""
    parts = (path or "").strip("/").split("/", 1)
    return parts[1] if len(parts) > 1 else (path or "")


class OnboardingClient:
    """Maps a tux-dev repo name to its onboarding YAML config dict."""

    def __init__(
        self,
        org: str | None = None,
        project: str | None = None,
        repo: str | None = None,
        repos_path: str | None = None,
        ref: str | None = None,
        mi_client_id: str | None = None,
        timeout: int | None = None,
        session: requests.Session | None = None,
        credential=None,
    ) -> None:
        self.org = org or os.environ.get("ADO_ORG", "msazure")
        self.project = project or os.environ.get("ADO_PROJECT", "One")
        self.repo = repo or os.environ.get("ONBOARD_REPO", "Compute-PMC.Onboarding")
        self.repos_path = repos_path or os.environ.get("ONBOARD_REPOS_PATH", "/data/tux/repos")
        self.ref = ref or os.environ.get("ONBOARD_REF", "main")
        self.mi_client_id = (
            mi_client_id if mi_client_id is not None
            else os.environ.get("ADO_MI_CLIENT_ID", "")
        )
        self.timeout = timeout if timeout is not None else int(os.environ.get("ADO_TIMEOUT", "30"))
        self._session = session or requests.Session()
        self._credential = credential
        self._paths: list[str] | None = None
        self._docs: dict[str, dict | None] = {}
        self._by_name: dict[str, dict] | None = None

    # -- internals ---------------------------------------------------------
    def _base(self) -> str:
        org = self.org
        if not org.startswith("http"):
            org = f"https://dev.azure.com/{org}"
        return f"{org.rstrip('/')}/{self.project}/_apis/git/repositories/{self.repo}"

    def _get_token(self) -> str:
        if self._credential is None:
            from azure.identity import DefaultAzureCredential  # lazy: only for live use
            self._credential = DefaultAzureCredential(
                managed_identity_client_id=self.mi_client_id or None
            )
        return self._credential.get_token(ADO_RESOURCE_SCOPE).token

    def _headers(self) -> dict:
        token = self._get_token()
        return {"Authorization": f"Bearer {token}"} if token else {}

    def _get(self, params: dict) -> dict:
        url = f"{self._base()}/items"
        all_params = {
            **params,
            "api-version": API_VERSION,
            "versionDescriptor.versionType": "branch",
            "versionDescriptor.version": self.ref,
        }
        resp = self._session.get(url, params=all_params, headers=self._headers(), timeout=self.timeout)
        if resp.status_code == 404:
            return {}
        if not resp.ok:
            raise OnboardingError(f"ADO items GET {url} -> {resp.status_code}: {resp.text[:300]}")
        try:
            return resp.json()
        except ValueError as exc:  # pragma: no cover - defensive
            raise OnboardingError(f"ADO items GET {url}: invalid JSON: {exc}") from exc

    # -- public API --------------------------------------------------------
    def list_yaml_paths(self) -> list[str]:
        """Paths of the *.yaml repo-definition files under repos_path (cached)."""
        if self._paths is None:
            data = self._get({"scopePath": self.repos_path, "recursionLevel": "Full"})
            items = data.get("value", []) if isinstance(data, dict) else []
            self._paths = [
                it["path"]
                for it in items
                if isinstance(it, dict)
                and it.get("gitObjectType") == "blob"
                and str(it.get("path", "")).lower().endswith((".yaml", ".yml"))
            ]
        return self._paths

    def get_yaml(self, path: str) -> dict | None:
        """Parsed YAML doc for one file (cached; None on miss/parse error)."""
        if path not in self._docs:
            data = self._get({"path": path, "includeContent": "true", "$format": "json"})
            content = data.get("content") if isinstance(data, dict) else None
            doc: dict | None = None
            if content:
                try:
                    parsed = yaml.safe_load(content)
                    if isinstance(parsed, dict):
                        doc = parsed
                except yaml.YAMLError as exc:
                    logger.warning("onboarding YAML parse failed for %s: %s", path, exc)
            self._docs[path] = doc
        return self._docs[path]

    def _index_by_name(self) -> dict[str, dict]:
        """Build {normalised-repo-name: doc} from every YAML (cached).

        Indexes each doc under its ``name`` and the short-name of every
        ``repos/``|``yumrepos/`` entry in its ``paths`` list, so a repo name
        discovered from the directory listing resolves to its config.
        """
        if self._by_name is None:
            index: dict[str, dict] = {}
            for path in self.list_yaml_paths():
                doc = self.get_yaml(path)
                if not isinstance(doc, dict):
                    continue
                keys = set()
                if doc.get("name"):
                    keys.add(_norm(str(doc["name"])))
                for p in doc.get("paths") or []:
                    keys.add(_norm(_short_name(str(p))))
                for key in keys:
                    if key:
                        index.setdefault(key, doc)
            self._by_name = index
        return self._by_name

    def get_repo_config(self, repo_name: str) -> dict | None:
        """The onboarding YAML config dict for a tux-dev repo name (or None)."""
        return self._index_by_name().get(_norm(repo_name))

    def ping(self) -> bool:
        """Lightweight reachability probe (used by pre-flight if wired)."""
        try:
            self.list_yaml_paths()
            return True
        except (OnboardingError, requests.RequestException) as exc:
            logger.error("Onboarding repo unreachable: %s", exc)
            return False


def from_env() -> OnboardingClient:
    return OnboardingClient()
