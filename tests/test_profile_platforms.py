"""画像「运营平台」的契约测试。

背景：今日头条接入工作台后，画像向导的「运营平台」多选也要能选它，
否则用户建画像时没法标注「我在头条运营」。

后端对平台名没有白名单（`web/app.py:4074` 直接 `for p in platforms` 展开成
platforms.md 的各节），所以这里锁两件事：
  1) 前端多选项里确实有今日头条（读源码，防漏改）
  2) 后端拿到含今日头条的表单后，platforms.md 真写出 «## 今日头条» 段并带上主页链接

运行：pytest tests/test_profile_platforms.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web"))
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "shared" / "scripts"))

import app as web  # noqa: E402

WIZARD = (PROJECT_ROOT / "web" / "frontend" / "src"
          / "components" / "OnboardingWizard.tsx")


def test_wizard_platform_options_include_toutiao():
    """画像向导的「运营平台」多选必须有今日头条。"""
    src = WIZARD.read_text(encoding="utf-8")
    m = re.search(r"const PLATFORMS = \[(.*?)\];", src, re.S)
    assert m, "OnboardingWizard.tsx 里没找到 PLATFORMS 定义"
    platforms = re.findall(r"'([^']+)'", m.group(1))

    assert "今日头条" in platforms, f"画像向导缺今日头条，实际：{platforms}"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """画像目录换到沙箱；后台 AI 增强打桩（否则测试会真起 agent）。"""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    monkeypatch.setattr(web, "PROFILES_DIR", profiles)
    monkeypatch.setattr(web, "PROFILE_BUILD_DIR", tmp_path / "_profile_build")
    monkeypatch.setattr(web, "run_agent_sync", lambda *a, **k: "测试桩：不真跑 agent")
    local = "http://127.0.0.1:7860"
    with TestClient(web.app, base_url=local, client=("127.0.0.1", 51234),
                    headers={"Origin": local}) as c:
        c.profiles_dir = profiles
        yield c


def test_build_writes_toutiao_section(client):
    """表单勾了今日头条 → platforms.md 必须写出这一节，且带主页链接。"""
    home = "https://mp.toutiao.com/profile/v4/index"
    r = client.post("/api/profile/build", json={
        "name": "pytest-toutiao-profile",
        "form": {
            "platforms": ["今日头条", "小红书"],
            "accountStage": "已有账号",
            "links": {"今日头条": home},
        },
    })
    assert r.status_code == 200, r.text

    md = (client.profiles_dir / "pytest-toutiao-profile"
          / "platforms.md").read_text(encoding="utf-8")
    assert "## 今日头条" in md, md
    assert home in md, md
    assert "## 小红书" in md, md
