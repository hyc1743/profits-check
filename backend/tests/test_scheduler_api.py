from __future__ import annotations


def test_scheduler_configuration_endpoint_exposes_registered_job(client) -> None:
    response = client.get("/api/system/scheduler")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["snapshot_schedule_times"] == "08:00"
    assert payload["timezone"] == "Asia/Shanghai"
    assert payload["jobs"][0]["id"] == "scheduled-snapshot"


def test_scheduler_can_be_stopped_and_started_from_api(client) -> None:
    stop_response = client.put("/api/system/scheduler", json={"enabled": False})

    assert stop_response.status_code == 200
    stopped = stop_response.json()
    assert stopped["enabled"] is False
    assert stopped["jobs"] == []

    status_after_stop = client.get("/api/system/scheduler")
    assert status_after_stop.json()["enabled"] is False
    assert status_after_stop.json()["jobs"] == []

    start_response = client.put("/api/system/scheduler", json={"enabled": True})

    assert start_response.status_code == 200
    started = start_response.json()
    assert started["enabled"] is True
    assert started["snapshot_schedule_times"] == "08:00"
    assert started["jobs"][0]["id"] == "scheduled-snapshot"
