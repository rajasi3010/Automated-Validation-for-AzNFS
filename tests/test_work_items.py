from __future__ import annotations

from src.phase2.work_items import AzureDevOpsBugClient, BugConfig


class _Token:
    token = "test-token"


class _Credential:
    def get_token(self, scope):
        assert scope == "499b84ac-1321-427f-aa17-267ca6975798/.default"
        return _Token()


class _Response:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def _config():
    return BugConfig(
        organization="msazure",
        project="One",
        area_path=r"One\Xstore\XSMB",
        assigned_to="Shyam Prasad",
        tags="AzNFS",
        phase="Phase 2",
    )


def test_ensure_bug_reuses_existing_active_bug():
    session = _Session([_Response({"workItems": [{"id": 1234}]})])
    client = AzureDevOpsBugClient(_config(), credential=_Credential(), session=session)

    url = client.ensure_bug("Ubuntu 24.04", "x86_64", "known_unsupported", "failed")

    assert url == "https://dev.azure.com/msazure/One/_workitems/edit/1234"
    assert len(session.calls) == 1
    query = session.calls[0][1]["json"]["query"]
    assert "[System.WorkItemType] = 'Bug'" in query
    assert "[AzNFS Validation Tool] Ubuntu 24.04 (x86_64)" in query


def test_ensure_bug_creates_requested_bug_fields(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "99")
    session = _Session([
        _Response({"workItems": []}),
        _Response({"id": 5678}),
    ])
    client = AzureDevOpsBugClient(_config(), credential=_Credential(), session=session)

    url = client.ensure_bug("Ubuntu 24.04", "arm64", "pending_publish", "package missing")

    assert url.endswith("/5678")
    create_url, create_args = session.calls[1]
    assert create_url.endswith("/workitems/$Bug?api-version=7.1")
    assert create_args["headers"]["Content-Type"] == "application/json-patch+json"
    fields = {item["path"]: item["value"] for item in create_args["json"]}
    assert fields["/fields/System.Title"] == \
        "[AzNFS Validation Tool] Ubuntu 24.04 (arm64) is not supported by AzNFS"
    assert fields["/fields/System.AreaPath"] == r"One\Xstore\XSMB"
    assert fields["/fields/System.AssignedTo"] == "Shyam Prasad"
    assert fields["/fields/System.Tags"] == "AzNFS"
    description = fields["/fields/System.Description"]
    assert "package missing" in description
    assert "owner/repo/actions/runs/99" in description
    assert "What happened" in description
    assert "What to do next" in description
    assert "Detected by:</b> Phase 2" in description
    assert "publish the AzNFS package" in description


def test_default_session_retries_transient_post_failures():
    client = AzureDevOpsBugClient(_config(), credential=_Credential())

    retry = client._session.get_adapter("https://").max_retries

    assert retry.total == 3
    assert retry.backoff_factor == 1
    assert retry.allowed_methods == frozenset({"POST"})
    assert 429 in retry.status_forcelist
    assert 503 in retry.status_forcelist


def test_phase_3_reuses_the_phase_independent_title():
    config = BugConfig(organization="msazure", project="One", phase="Phase 3")
    session = _Session([_Response({"workItems": []}), _Response({"id": 7})])
    client = AzureDevOpsBugClient(config, credential=_Credential(), session=session)

    client.ensure_bug("Rocky 9", "x86_64", "known_unsupported", "mount failed")

    fields = {item["path"]: item["value"] for item in session.calls[1][1]["json"]}
    assert fields["/fields/System.Title"] == \
        "[AzNFS Validation Tool] Rocky 9 (x86_64) is not supported by AzNFS"
    description = fields["/fields/System.Description"]
    assert "Detected by:</b> Phase 3" in description
    assert "mount failed" in description
    assert "known_supported" in description