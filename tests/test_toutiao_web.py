"""今日头条接入 Web 工作台的契约测试。

覆盖 web/app.py 里为头条新增的接触点。全部不启浏览器、不联网（subprocess 被替身顶掉）：
  1) /api/accounts 出现 toutiao 卡片（账号页的卡片完全由这个接口驱动）
  2) /api/login/toutiao 分派到 toutiao_publish.py 的 login 子命令
  3) /api/accounts/toutiao/whoami 分派到 whoami 子命令并透传 JSON
  4) /api/publish/toutiao 分派到发布（正文走 --content 直传，不落临时文件）

运行：pytest tests/test_toutiao_web.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web"))
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "shared" / "scripts"))

import app as web  # noqa: E402

SCRIPT_SUFFIX = "skill-toutiao-publisher/scripts/toutiao_publish.py"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """把登录目录与产物目录换到沙箱，避免测试污染 outputs/ 与用户配置。"""
    login_dir = tmp_path / "_login"
    login_dir.mkdir()
    monkeypatch.setattr(web, "LOGIN_DIR", login_dir)
    monkeypatch.setattr(web, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(web, "LOGIN_PROCESSES", {})
    with web._WHOAMI_LOCK:
        web._WHOAMI_CACHE.clear()
    # TrustedHostMiddleware 只放行 localhost/127.0.0.1（TestClient 默认的 testserver 会被判
    # Invalid host header），local_write_guard 又会把非本机来源的写请求判 403——三件套都要给。
    local = "http://127.0.0.1:7860"
    with TestClient(web.app, base_url=local, client=("127.0.0.1", 51234),
                    headers={"Origin": local}) as c:
        yield c


def test_accounts_lists_toutiao(client):
    """账号页卡片由 /api/accounts 驱动——注册表加了头条，卡片就该出现。"""
    data = client.get("/api/accounts").json()
    platforms = [a["platform"] for a in data]

    assert "toutiao" in platforms, f"缺 toutiao，实际返回：{platforms}"
    toutiao = next(a for a in data if a["platform"] == "toutiao")
    assert toutiao["name"] == "今日头条"
    assert toutiao["supported"] is True
    assert len(data) == 8, f"应为 8 个平台，实际 {len(data)}"


def test_login_dispatch_uses_toutiao_login_subcommand(monkeypatch, client):
    """登录分派：起 toutiao_publish.py 的 login 子命令，二维码/状态文件指向登录目录。"""
    captured: dict = {}

    class FakePopen:
        def __init__(self, cmd, **kw):
            captured["cmd"] = cmd
            # 模拟 runner 立刻写好状态与二维码，免得 api_login_start 等满轮询窗口
            (web.LOGIN_DIR / "toutiao.png").write_bytes(b"fake-png")
            (web.LOGIN_DIR / "toutiao.json").write_text(
                json.dumps({"state": "qr_ready", "message": "请扫码", "qr": "", "ts": 0}),
                encoding="utf-8")

        def poll(self):
            return None  # 进程还活着

    monkeypatch.setattr(web.subprocess, "Popen", FakePopen)

    r = client.post("/api/login/toutiao")

    assert r.status_code == 200, r.text
    assert r.json()["state"] == "qr_ready"
    cmd = captured["cmd"]
    assert Path(cmd[1]).as_posix().endswith(SCRIPT_SUFFIX), cmd
    assert cmd[2] == "login", cmd
    assert "--qr-out" in cmd and "--status-file" in cmd, cmd
    assert str(web.LOGIN_DIR / "toutiao.png") in cmd, cmd
    assert str(web.LOGIN_DIR / "toutiao.json") in cmd, cmd


def test_whoami_dispatch_passes_through_json(monkeypatch, client):
    """whoami 分派到头条脚本，并把脚本 stdout 的 JSON 透传给前端。"""
    captured: dict = {}

    class FakeCompleted:
        returncode = 0
        stdout = json.dumps({"loggedIn": True, "name": "我的头条号", "avatar": ""})
        stderr = ""

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return FakeCompleted()

    monkeypatch.setattr(web.subprocess, "run", fake_run)

    r = client.get("/api/accounts/toutiao/whoami")

    assert r.status_code == 200, r.text
    assert r.json() == {"loggedIn": True, "name": "我的头条号", "avatar": ""}
    cmd = captured["cmd"]
    assert Path(cmd[1]).as_posix().endswith(SCRIPT_SUFFIX), cmd
    assert cmd[2] == "whoami", cmd


def test_whoami_script_error_is_not_cached(monkeypatch, client):
    """脚本自报 error（浏览器起不来）时，后端不能把它当「可信的未登录」写缓存。"""
    class FakeCompleted:
        returncode = 0
        stdout = json.dumps({"loggedIn": False, "name": "", "avatar": "",
                             "error": "浏览器起不来"})
        stderr = ""

    monkeypatch.setattr(web.subprocess, "run", lambda cmd, **kw: FakeCompleted())

    r = client.get("/api/accounts/toutiao/whoami")

    assert r.status_code == 200
    assert r.json()["loggedIn"] is False
    with web._WHOAMI_LOCK:
        assert "toutiao" not in web._WHOAMI_CACHE, "error 结论不应进缓存"


def test_publish_dispatch_uses_toutiao_script(monkeypatch, client):
    """发布分派：正文走 --content 直传，不落临时文件；标题/话题一并带上。"""
    captured: dict = {}

    class FakeCompleted:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return FakeCompleted()

    monkeypatch.setattr(web.subprocess, "run", fake_run)

    r = client.post("/api/publish/toutiao",
                    json={"title": "标题", "body": "正文内容", "tags": "AI"})

    assert r.status_code == 200, r.text
    cmd = captured["cmd"]
    assert Path(cmd[1]).as_posix().endswith(SCRIPT_SUFFIX), cmd
    assert "--content" in cmd and "正文内容" in cmd, cmd
    assert "--title" in cmd and "标题" in cmd, cmd
