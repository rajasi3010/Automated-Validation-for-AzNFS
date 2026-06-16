from src.phase2.orchestrator import gate2_evaluate as evaluate


def test_gate2_selects_repo_with_esrp_and_shared():
    matched = ["microsoft-ubuntu-2204-jammy", "microsoft-ubuntu-jammy"]
    repo_objects = {
        "microsoft-ubuntu-2204-jammy": {
            "signing_service": "other",
            "repo_groups": ["shared"],
        },
        "microsoft-ubuntu-jammy": {
            "signing_service": "esrp",
            "repo_groups": ["shared", "tux-dev"],
        },
    }

    r = evaluate(matched, repo_objects)
    assert r.passed
    assert r.resolved_repo == "microsoft-ubuntu-jammy"


def test_gate2_fails_when_shared_missing():
    matched = ["microsoft-ubuntu-jammy"]
    repo_objects = {
        "microsoft-ubuntu-jammy": {
            "signing_service": "esrp",
            "repo_groups": ["test"],
        }
    }

    r = evaluate(matched, repo_objects)
    assert not r.passed
    assert r.reason == "repo config mismatch"


def test_gate2_fails_when_signing_not_esrp():
    matched = ["microsoft-ubuntu-jammy"]
    repo_objects = {
        "microsoft-ubuntu-jammy": {
            "signing_service": "esrp_500207",
            "repo_groups": ["shared"],
        }
    }

    r = evaluate(matched, repo_objects)
    assert not r.passed
    assert "signing_service" in r.details
