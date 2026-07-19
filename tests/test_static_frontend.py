from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from starlette.routing import Mount

import bag_doctor.main as main


def test_root_selects_committed_react_build():
    response = main.index()
    assert Path(response.path) == main.FRONTEND_DIST / "index.html"
    assert Path(response.path).is_file()


def test_assets_mount_uses_only_production_dist_and_does_not_shadow_api():
    mounts = [route for route in main.app.routes if isinstance(route, Mount)]
    assets = next(route for route in mounts if route.path == "/assets")
    assert isinstance(assets.app, StaticFiles)
    assert Path(assets.app.directory) == main.FRONTEND_DIST / "assets"

    api_paths = {route.path for route in main.app.routes if isinstance(route, APIRoute)}
    assert "/api/analyze/local" in api_paths
    assert "/api/analyze/jobs/{job_id}" in api_paths
    assert not any(path == "/{path:path}" for path in api_paths)


def test_missing_build_is_controlled_and_does_not_fall_back(monkeypatch, tmp_path):
    missing = tmp_path / "dist" / "index.html"
    monkeypatch.setattr(main, "FRONTEND_INDEX", missing)
    with pytest.raises(HTTPException) as caught:
        main.index()
    assert caught.value.status_code == 503
    assert caught.value.detail == "Frontend production build is unavailable"
    assert str(missing) not in caught.value.detail
