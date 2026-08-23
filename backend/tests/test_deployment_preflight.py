from __future__ import annotations

from scripts import deployment_preflight


def test_deployment_preflight_launch_checklist_includes_launch_stages() -> None:
    checklist = deployment_preflight._build_launch_checklist(
        env_file=".env.staging",
        worker_mode="external",
    )

    keys = [item["key"] for item in checklist]
    assert "prelaunch_config" in keys
    assert "prelaunch_db" in keys
    assert "prelaunch_schema" in keys
    assert "launch_worker" in keys
    assert "postdeploy_public" in keys
    assert "postdeploy_auth" in keys
    assert "postdeploy_billing" in keys
    assert "postdeploy_admin" in keys

    prelaunch_schema = next(item for item in checklist if item["key"] == "prelaunch_schema")
    assert prelaunch_schema["command"] == "npm run db:migrate"
    assert "authorized" in prelaunch_schema["purpose"].lower()

    postdeploy_public = next(item for item in checklist if item["key"] == "postdeploy_public")
    assert "smoke:staging" in postdeploy_public["command"]
    assert "pricing" in postdeploy_public["purpose"].lower() or "public" in postdeploy_public["purpose"].lower()
