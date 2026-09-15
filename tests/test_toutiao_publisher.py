"""今日头条（头条号）发布 SKILL 的契约单测。

覆盖：发布脚本离线自检、标题长度守卫、出站安全闸门、跨平台派发注册表、SKILL frontmatter 契约。
全部不启浏览器、不联网、不派生进程（直接调 main()，用 monkeypatch 顶掉浏览器阶段）。
运行：pytest tests/test_toutiao_publisher.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = PROJECT_ROOT / "skills" / "openclaw" / "skill-toutiao-publisher"
SKILL_MD = SKILL_DIR / "SKILL.md"

sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "openclaw"
                       / "skill-cross-platform-publish" / "scripts"))

import toutiao_publish as tp  # noqa: E402
import publish_dispatch  # noqa: E402


@pytest.fixture
def article(tmp_path):
    path = tmp_path / "article.md"
    path.write_text("正文第一段\n\n正文第二段", encoding="utf-8")
    return path


def test_selftest_passes_offline(capsys):
    assert tp._selftest() == 0
    assert "selftest: OK" in capsys.readouterr().out


def test_title_over_limit_is_rejected(monkeypatch, article, capsys):
    monkeypatch.setattr(sys, "argv", [
        "toutiao_publish.py", "--input", str(article), "--title", "标" * 40])

    with pytest.raises(SystemExit) as exc:
        tp.main()

    assert exc.value.code == 1
    assert "上限 30 字" in capsys.readouterr().err


def test_sensitive_content_is_blocked_before_publishing(monkeypatch, tmp_path, capsys):
    """真发（--exec）命中密钥必须退出码 7 阻止，且发生在起浏览器之前。"""
    path = tmp_path / "article.md"
    path.write_text("正文里混进了 sk-ABCDEFGHIJKLMNOPQRSTUVWX", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "toutiao_publish.py", "--input", str(path), "--title", "标题", "--exec"])

    with pytest.raises(SystemExit) as exc:
        tp.main()

    assert exc.value.code == 7
    assert "阻止本次发布" in capsys.readouterr().err


def test_dry_run_fills_editor_without_publishing(monkeypatch, article, tmp_path):
    """默认 dry-run：把内容交给编辑器但不点发布，tags 正确拆分。"""
    captured: dict = {}

    def fake_publish(content, title, tags, cover, dry_run, headed, as_draft, timeout_ms):
        captured.update(content=content, title=title, tags=tags, cover=cover,
                        dry_run=dry_run, draft=as_draft)
        return {"platform": "toutiao", "dry_run": dry_run,
                "steps": {"title": True, "body": True}}

    monkeypatch.setattr(tp, "publish_article", fake_publish)
    monkeypatch.setattr(tp, "_write_record", lambda result: tmp_path / "record.json")
    monkeypatch.setattr(sys, "argv", [
        "toutiao_publish.py", "--input", str(article), "--title", "标题",
        "--tags", "AI, 效率工具 ,"])

    assert tp.main() == 0
    assert captured["dry_run"] is True
    assert captured["draft"] is False
    assert captured["tags"] == ["AI", "效率工具"]
    assert captured["title"] == "标题"


def test_publish_dispatch_routes_toutiao_to_this_skill():
    platform = publish_dispatch.PLATFORMS["toutiao"]

    assert platform["publisher"] == "skill-toutiao-publisher"
    assert platform["title"] == 30
    assert "article" in platform["types"]


def test_publish_dispatch_plan_covers_toutiao():
    plan = publish_dispatch._check_platform(
        "toutiao", {"title": "标题", "body": "正文", "tags": ["AI"], "media_type": "article"})

    assert plan["ok"] and not plan["warnings"]


def test_skill_frontmatter_contract():
    text = SKILL_MD.read_text(encoding="utf-8")
    head = text.split("---")[1]

    assert "name: skill-toutiao-publisher" in head
    assert "layer: publish" in head
    assert len(text.splitlines()) <= 200


@pytest.mark.parametrize("placeholder", [
    "mp.toutiao.com", "ToutiaoProfile", "outputs/_publish",
])
def test_skill_documents_key_entrypoints(placeholder):
    assert placeholder in SKILL_MD.read_text(encoding="utf-8")
