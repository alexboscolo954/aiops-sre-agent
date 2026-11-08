"""Teachings in the console app's API (slice 11.6a): a Contract's review queue, its
approved and past Teachings, and the Operator's approve, reject, retire and write, each
only within the Contract in the path."""

import asyncio
from typing import Any

from aiops_agent.config import Settings
from aiops_agent.models import Investigation
from aiops_agent.store import Store, connect
from aiops_agent.teachings import MAX_IN_PROMPT
from tests.test_app_investigations import SAME, hub
from tests.test_console import AS_OPERATOR, OPERATOR, VIEW

ACME = "/api/v1/contracts/acme/teachings"
CROSS = {**VIEW, "Sec-Fetch-Site": "cross-site"}
BY = f"console:{OPERATOR}"


def seed(database_url: str, approved: int = 1) -> dict[str, int]:
    """acme: two proposed (one contradicting its approved one), approved ones, one
    rejected, one retired; bank: one proposed and one approved."""

    async def go() -> dict[str, int]:
        async with connect(database_url) as pool:
            st = Store(pool)
            await st.migrate()
            await st.insert(Investigation(id="t1", contract_id="acme", title="t", started=1))
            ids = {}
            for n in range(approved):
                ids["approved"] = await st.add_teaching(
                    "acme", f"approved {n}", ["KubePodCrashLooping"], approved_by="slack:U1"
                )
            ids["rejected"] = await st.add_teaching("acme", "rejected", [])
            await st.decide_teaching(ids["rejected"], "acme", False, "slack:U1")
            ids["retired"] = await st.add_teaching("acme", "retired", [], approved_by="slack:U1")
            await st.retire_teaching(ids["retired"], "acme", "slack:U1")
            ids["proposed"] = await st.add_teaching(
                "acme", "drafted", [], source_id="t1", correction="it was the node"
            )
            ids["contradicting"] = await st.add_teaching(
                "acme", "the opposite", [], contradicts=ids["approved"]
            )
            ids["bank_proposed"] = await st.add_teaching("bank", "bank's draft", [])
            ids["bank_approved"] = await st.add_teaching(
                "bank", "bank's", [], approved_by="slack:U2"
            )
            return ids

    return asyncio.run(go())


def test_a_contracts_teachings_are_its_own_in_three_lists(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    with hub(settings, fake_cluster, database_url) as c:
        seed(database_url)
        acme = c.get(ACME, headers=VIEW).json()
        bank = c.get("/api/v1/contracts/bank/teachings", headers=VIEW).json()
        unknown = c.get("/api/v1/contracts/nope/teachings", headers=VIEW).status_code
        no_cookie = c.get(ACME, headers=AS_OPERATOR).status_code
    assert [t["text"] for t in acme["proposed"]] == ["the opposite", "drafted"]  # newest first
    drafted = acme["proposed"][1]
    assert (drafted["source_id"], drafted["correction"]) == ("t1", "it was the node")
    assert [(t["text"], t["alerts"]) for t in acme["approved"]] == [
        ("approved 0", ["KubePodCrashLooping"])
    ]
    assert acme["proposed"][0]["contradicts"] == acme["approved"][0]["id"]
    assert [(t["text"], t["status"]) for t in acme["past"]] == [
        ("retired", "retired"),
        ("rejected", "rejected"),
    ]
    assert acme["limit"] == 500 and acme["left_out"] == 0
    assert [t["text"] for t in bank["proposed"] + bank["approved"]] == ["bank's draft", "bank's"]
    assert unknown == 404 and no_cookie == 401


def test_it_counts_the_approved_teachings_that_dont_fit_in_a_prompt(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    with hub(settings, fake_cluster, database_url) as c:
        seed(database_url, approved=MAX_IN_PROMPT + 2)
        acme = c.get(ACME, headers=VIEW).json()
        bank = c.get("/api/v1/contracts/bank/teachings", headers=VIEW).json()
    assert len(acme["approved"]) == MAX_IN_PROMPT + 2 and acme["left_out"] == 2
    assert bank["left_out"] == 0  # another Contract's never count


def test_approving_takes_the_edited_text_once_and_retires_what_it_contradicts(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    with hub(settings, fake_cluster, database_url) as c:
        ids = seed(database_url)
        path = f"{ACME}/{ids['contradicting']}/decision"
        yes = {"approve": True, "text": "  the opposite, edited  "}
        refused = [
            c.post(path, json=yes, headers=CROSS).status_code,
            c.post(path, json={"approve": True, "text": " "}, headers=SAME).status_code,
            c.post(path, json={"approve": True, "text": "x" * 501}, headers=SAME).status_code,
            c.post(f"{ACME}/{ids['bank_proposed']}/decision", json=yes, headers=SAME).status_code,
            c.post(f"{ACME}/999/decision", json=yes, headers=SAME).status_code,
        ]
        shown = c.post(path, json=yes, headers=SAME).json()
        again = c.post(path, json=yes, headers=SAME)
        bank = c.get("/api/v1/contracts/bank/teachings", headers=VIEW).json()
    assert refused == [403, 422, 422, 404, 404]  # bank's Teaching through acme's path: 404
    assert [(t["text"], t["decided_by"]) for t in shown["approved"]] == [
        ("the opposite, edited", BY)
    ]
    assert [t["text"] for t in shown["proposed"]] == ["drafted"]
    retired = [t for t in shown["past"] if t["text"] == "approved 0"]
    assert retired and retired[0]["status"] == "retired"
    assert again.status_code == 409 and again.json()["detail"] == "already decided"
    assert [t["text"] for t in bank["proposed"]] == ["bank's draft"]  # untouched


def test_rejecting_needs_no_text_and_keeps_the_drafted_one(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    with hub(settings, fake_cluster, database_url) as c:
        ids = seed(database_url)
        shown = c.post(
            f"{ACME}/{ids['proposed']}/decision", json={"approve": False}, headers=SAME
        ).json()
    rejected = [t for t in shown["past"] if t["id"] == ids["proposed"]]
    assert [(t["status"], t["text"], t["decided_by"]) for t in rejected] == [
        ("rejected", "drafted", BY)
    ]
    assert [t["text"] for t in shown["approved"]] == ["approved 0"]


def test_retiring_is_for_an_approved_teaching_of_this_contract(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    with hub(settings, fake_cluster, database_url) as c:
        ids = seed(database_url)
        refused = [
            c.post(f"{ACME}/{ids['approved']}/retire", headers=CROSS).status_code,
            c.post(f"{ACME}/{ids['bank_approved']}/retire", headers=SAME).status_code,
            c.post(f"{ACME}/{ids['proposed']}/retire", headers=SAME).status_code,
        ]
        shown = c.post(f"{ACME}/{ids['approved']}/retire", headers=SAME).json()
        again = c.post(f"{ACME}/{ids['approved']}/retire", headers=SAME)
        bank = c.get("/api/v1/contracts/bank/teachings", headers=VIEW).json()
    assert refused == [403, 404, 409]
    assert shown["approved"] == []
    past = [(t["status"], t["decided_by"]) for t in shown["past"] if t["id"] == ids["approved"]]
    assert past == [("retired", BY)]
    assert again.status_code == 409 and again.json()["detail"] == "not an approved Teaching"
    assert [t["text"] for t in bank["approved"]] == ["bank's"]


def test_the_operator_writes_one_approved_at_once_for_this_contract_only(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    with hub(settings, fake_cluster, database_url) as c:
        seed(database_url)
        one = {"text": "  check the node first  ", "alerts": [" KubeNodeNotReady ", " "]}
        refused = [
            c.post(ACME, json=one, headers=CROSS).status_code,
            c.post(ACME, json={"text": "  "}, headers=SAME).status_code,
            c.post(ACME, json={"text": "x" * 501}, headers=SAME).status_code,
            c.post("/api/v1/contracts/nope/teachings", json=one, headers=SAME).status_code,
        ]
        shown = c.post(ACME, json=one, headers=SAME).json()
        general = c.post(ACME, json={"text": "x" * 500}, headers=SAME).json()
        bank = c.get("/api/v1/contracts/bank/teachings", headers=VIEW).json()
    assert refused == [403, 422, 422, 404]
    mine = shown["approved"][0]
    assert (mine["text"], mine["alerts"], mine["decided_by"]) == (
        "check the node first",
        ["KubeNodeNotReady"],
        BY,
    )
    assert general["approved"][0]["alerts"] == []  # every alert
    assert [t["text"] for t in bank["approved"]] == ["bank's"]
