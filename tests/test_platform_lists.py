"""工作台里各处「平台清单」的一致性契约测试。

今日头条接入工作台后，散落在前端的几处平台清单最容易漏改——它们各自硬编码
平台名，编译器不会替你发现。这里把它们钉住：

  1) 画像向导的「运营平台」多选（OnboardingWizard.tsx）
  2) 内容日历新建日程的「平台」胶囊（CalendarPage.tsx）
  3) 发布页的平台表与可发布集合（PublishPage.tsx）
  4) 后端承接：表单勾了今日头条 → platforms.md 真写出 «## 今日头条» 段

后端本身对平台名没有白名单（`web/app.py:4074` 直接展开 `form.platforms`），
所以 4) 是确认「链路真的支持」，1)~3) 是防漏改。

注：skill 文档里另有若干「面向 小红书/抖音/B站…」的示例性描述，那些是说明
文字而不是可选项来源，不在本测试范围内。

运行：pytest tests/test_platform_lists.py -q
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

FE = PROJECT_ROOT / "web" / "frontend" / "src" / "components"
WIZARD = FE / "OnboardingWizard.tsx"
CALENDAR = FE / "CalendarPage.tsx"
PUBLISH = FE / "PublishPage.tsx"

TOUTIAO = "今日头条"


def _array_items(path: Path, const_name: str) -> list[str]:
    """从 TSX 源码里取出 `const <name> = [...]` 的字符串项。"""
    src = path.read_text(encoding="utf-8")
    m = re.search(rf"const {const_name} = \[(.*?)\];", src, re.S)
    assert m, f"{path.name} 里没找到 {const_name} 定义"
    return re.findall(r"'([^']+)'", m.group(1))


def test_wizard_platform_options_include_toutiao():
    """画像向导的「运营平台」多选。"""
    platforms = _array_items(WIZARD, "PLATFORMS")

    assert TOUTIAO in platforms, f"画像向导缺今日头条，实际：{platforms}"


def test_calendar_platform_options_include_toutiao():
    """内容日历新建日程的「平台」胶囊。"""
    platforms = _array_items(CALENDAR, "PLATFORMS")

    assert TOUTIAO in platforms, f"内容日历缺今日头条，实际：{platforms}"


def test_publish_page_lists_toutiao():
    """发布页的平台表（key 用小写 id）与可发布集合。"""
    src = PUBLISH.read_text(encoding="utf-8")

    assert "key: 'toutiao'" in src, "PublishPage 的 PLATFORMS 缺 toutiao 条目"
    publishable = re.search(r"const PUBLISHABLE = new Set\(\[(.*?)\]\)", src, re.S)
    assert publishable, "没找到 PUBLISHABLE 定义"
    assert "'toutiao'" in publishable.group(1), "PUBLISHABLE 里应含 toutiao"


LIB = PROJECT_ROOT / "web" / "frontend" / "src" / "lib"
SKILL_NAMES = LIB / "skillDisplayNames.ts"
CAPABILITY = LIB / "capabilityMenu.ts"


def test_skill_display_name_includes_toutiao():
    """技能库 / 搜索里的中文名（缺了会显示英文 id skill-toutiao-publisher）。"""
    src = SKILL_NAMES.read_text(encoding="utf-8")

    assert "'skill-toutiao-publisher': '今日头条'" in src, "技能库缺头条中文名"


def test_capability_menu_lists_toutiao_publisher():
    """「笔」能力菜单的「发布分发」组里要能选到头条（它不随技能库自动生成）。"""
    src = CAPABILITY.read_text(encoding="utf-8")

    assert '"skill": "skill-toutiao-publisher"' in src, "能力菜单缺头条条目"
    assert '"label": "今日头条"' in src, "能力菜单缺头条中文标签"


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
            "platforms": [TOUTIAO, "小红书"],
            "accountStage": "已有账号",
            "links": {TOUTIAO: home},
        },
    })
    assert r.status_code == 200, r.text

    md = (client.profiles_dir / "pytest-toutiao-profile"
          / "platforms.md").read_text(encoding="utf-8")
    assert f"## {TOUTIAO}" in md, md
    assert home in md, md
    assert "## 小红书" in md, md
