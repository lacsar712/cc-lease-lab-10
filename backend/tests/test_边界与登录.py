import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["数据目录"] = _tmp
os.environ["会话密钥"] = "test-lease-key"

import pytest
from fastapi.testclient import TestClient

from app import seed
from app.factory import create_app


@pytest.fixture()
def client():
    seed.初始化库()
    return TestClient(create_app())


def test_未登录拒api(client):
    r = client.get("/api/概览")
    assert r.status_code == 401


def test_登录与会话(client):
    r = client.post("/api/登录", json={"账号": "admin", "密码": "123456"})
    assert r.status_code == 200
    assert r.json().get("ok")
    r2 = client.get("/api/概览")
    assert r2.status_code == 200


def test_登录页文案(client):
    r = client.get("/login")
    assert r.status_code == 200
    body = r.text
    assert "登录" in body
    assert "密码" in body


def test_错误密码(client):
    r = client.post("/api/登录", json={"账号": "admin", "密码": "wrong"})
    assert r.status_code == 401


def test_租约详情路由可匹配并带担保(client):
    client.post("/api/登录", json={"账号": "admin", "密码": "123456"})
    # 中文路径段 + ASCII 参数名：详情接口必须真正命中路由，而非 FastAPI 兜底 404
    r = client.get("/api/租约/ls-active-01")
    assert r.status_code == 200
    body = r.json()
    assert body["租约号"] == "ls-active-01"
    assert "担保" in body and body["担保"] is not None


def test_取消接口与担保列表(client):
    client.post("/api/登录", json={"账号": "admin", "密码": "123456"})
    client.post(
        "/api/租约/申领",
        json={"池键": "pool-net", "租户": "team-api", "租约号": "ls-api-cancel",
              "立即生效": False, "租期分钟": 30},
    )
    r = client.post("/api/租约/取消", json={"租约号": "ls-api-cancel"})
    assert r.status_code == 200
    assert r.json()["状态"] == "已取消"
    assert r.json()["担保"]["担保状态"] == "已退冻"
    担保 = client.get("/api/担保").json()
    assert any(g["租约号"] == "ls-api-cancel" and g["状态"] == "已退冻" for g in 担保)