"""The recorders' scrub (evals/scrub.py): keeps a sandbox's identity out of this public repo."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "evals"))  # its `import scrub`
spec = importlib.util.spec_from_file_location(
    "record_azure", Path(__file__).parent.parent / "evals" / "record_azure.py"
)
assert spec and spec.loader
record_azure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(record_azure)

SUB, TENANT, CLIENT = "11111111-aaaa-bbbb-cccc-000000000001", "22222222-x", "33333333-x"


def test_scrub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", SUB)
    monkeypatch.setenv("AZURE_TENANT_ID", TENANT)
    monkeypatch.setenv("AZURE_CLIENT_ID", CLIENT)
    monkeypatch.setenv("AIOPS_SCRUB", json.dumps({"jo@mail.test": "oncall@example.com", "jo": "x"}))
    fakes, scrub = record_azure.fakes_and_scrub("real-rg", "real-app-1")
    got = scrub(
        {
            "id": f"/subscriptions/{SUB.upper()}/resourceGroups/REAL-RG/sites/real-app-1",
            "caller": "jo@mail.test",
            "claims": {"upn": "jo@mail.test", "ipaddr": "198.51.100.7"},
            "httpRequest": {"clientIpAddress": "198.51.100.7"},
            "events": [{"tenantId": TENANT, "by": CLIENT}],
            "tags": {f"hidden-related:/subscriptions/{SUB}/sites/real-app-1": "Resource"},
        }
    )
    assert got == {
        "id": f"/subscriptions/{record_azure.SUBSCRIPTION}/resourceGroups/shop-prod-rg"
        "/sites/shop-web",
        "caller": "oncall@example.com",  # the email whole, before its user name
        "events": [{"tenantId": record_azure.TENANT, "by": record_azure.CLIENT}],
        "tags": {
            f"hidden-related:/subscriptions/{record_azure.SUBSCRIPTION}/sites/shop-web": "Resource"
        },
    }
    assert set(fakes) >= {SUB, TENANT, CLIENT, "real-rg", "real-app-1", "jo"}


def test_a_recording_with_a_real_value_left_is_never_written() -> None:
    import scrub  # evals/scrub.py, shared by the recorders

    fakes = {"jo@mail.test": "oncall@example.com"}
    scrub.refuse_leaks("caller: oncall@example.com", fakes)  # clean: no exit
    with pytest.raises(SystemExit, match="1 real value"):
        scrub.refuse_leaks("caller: JO@Mail.test", fakes)


def test_aws_access_key_ids_never_reach_a_recording() -> None:
    import scrub

    text = 'resources: [ASIAQWERTYUIOPASDFGH, checkout], key: "AKIAZXCVBNMLKJHGFDSA"'
    assert scrub.mask_aws_key_ids(text) == (
        'resources: [ASIAIOSFODNN7EXAMPLE, checkout], key: "AKIAIOSFODNN7EXAMPLE"'
    )
