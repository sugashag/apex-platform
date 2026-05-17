"""Pipeline-stage tests — defaults seeded at registration, reorder, isolation."""

from httpx import AsyncClient

from tests.helpers import register_workspace

API = "/api/v1"


async def test_default_stages_seeded_on_registration(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    resp = await client.get(f"{API}/pipeline-stages", headers=ws.headers)
    assert resp.status_code == 200
    stages = resp.json()
    assert [s["name"] for s in stages] == [
        "New Lead", "Qualified", "Proposal Sent",
        "Negotiation", "Closed Won", "Closed Lost",
    ]
    closed_won = next(s for s in stages if s["name"] == "Closed Won")
    assert closed_won["is_won"] is True
    assert closed_won["probability_default"] == 100

    closed_lost = next(s for s in stages if s["name"] == "Closed Lost")
    assert closed_lost["is_lost"] is True


async def test_create_and_reorder_stage(client: AsyncClient) -> None:
    ws = await register_workspace(client)
    create = await client.post(
        f"{API}/pipeline-stages",
        headers=ws.headers,
        json={
            "name": "Custom Review",
            "position": 7,
            "probability_default": 80,
        },
    )
    assert create.status_code == 201
    new_id = create.json()["id"]

    # Reorder: swap the two trailing positions.
    listed = await client.get(f"{API}/pipeline-stages", headers=ws.headers)
    by_name = {s["name"]: s for s in listed.json()}
    reorder_payload = {
        "stages": [
            {"id": by_name["Closed Lost"]["id"], "position": 7},
            {"id": new_id, "position": 6},
        ],
    }
    reordered = await client.put(
        f"{API}/pipeline-stages/reorder",
        headers=ws.headers,
        json=reorder_payload,
    )
    assert reordered.status_code == 200
    after_reorder = {s["name"]: s for s in reordered.json()}
    assert after_reorder["Custom Review"]["position"] == 6
    assert after_reorder["Closed Lost"]["position"] == 7


async def test_workspace_isolation(client: AsyncClient) -> None:
    ws_a = await register_workspace(client, slug_prefix="iso-a")
    ws_b = await register_workspace(client, slug_prefix="iso-b")

    a_stages = await client.get(f"{API}/pipeline-stages", headers=ws_a.headers)
    b_stages = await client.get(f"{API}/pipeline-stages", headers=ws_b.headers)
    a_ids = {s["id"] for s in a_stages.json()}
    b_ids = {s["id"] for s in b_stages.json()}
    assert a_ids.isdisjoint(b_ids)

    a_custom = await client.post(
        f"{API}/pipeline-stages",
        headers=ws_a.headers,
        json={"name": "A-only", "position": 99, "probability_default": 50},
    )
    assert a_custom.status_code == 201
    a_custom_id = a_custom.json()["id"]

    # B cannot patch A's stage.
    b_patch = await client.patch(
        f"{API}/pipeline-stages/{a_custom_id}",
        headers=ws_b.headers,
        json={"name": "Hijacked"},
    )
    assert b_patch.status_code == 404
