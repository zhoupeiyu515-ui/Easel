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
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "shared" / "scripts"))
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


# ---------- Web 工作台接入契约（login / whoami / --content） ----------
# 这三样是 web/app.py 的分派点依赖的接口约定：
#   login  子命令把进度写进 login_state 协议文件（Web 后端只认这个文件，不直接管浏览器）
#   whoami 子命令在 stdout 打一行 JSON（web/app.py 按行解析，取最后一个 '{' 开头的行）
#   --content 让发布页的正文不必落临时文件

import json  # noqa: E402


def test_login_subcommand_parses_web_args():
    ns = tp._login_parser().parse_args(
        ["--qr-out", "/tmp/q.png", "--status-file", "/tmp/s.json", "--timeout", "120"])

    assert ns.qr_out == "/tmp/q.png"
    assert ns.status_file == "/tmp/s.json"
    assert ns.timeout == 120


def test_login_subcommand_writes_login_state_protocol(monkeypatch, tmp_path):
    import login_state

    qr, sf = tmp_path / "q.png", tmp_path / "s.json"
    seen: list[str] = []

    def fake_qr_login(profile, qr_out, status_file, timeout_s, headed=False):
        login_state.write_status(str(status_file), "starting")
        seen.append("starting")
        qr_out.write_bytes(b"png")
        login_state.write_status(str(status_file), "qr_ready", "扫码", qr=str(qr_out))
        seen.append("qr_ready")
        return 0

    monkeypatch.setattr(tp, "_qr_login", fake_qr_login)

    assert tp.main(["login", "--qr-out", str(qr), "--status-file", str(sf)]) == 0
    data = json.loads(sf.read_text(encoding="utf-8"))
    assert seen == ["starting", "qr_ready"]
    assert data["state"] == "qr_ready"
    assert data["qr"] == str(qr)


def test_login_subcommand_defaults_to_outputs_login_dir(monkeypatch):
    """不传 --qr-out/--status-file 时落到 outputs/_login（与其它平台同款约定）。"""
    captured: dict = {}

    def fake_qr_login(profile, qr_out, status_file, timeout_s, headed=False):
        captured.update(qr_out=qr_out, status_file=status_file)
        return 0

    monkeypatch.setattr(tp, "_qr_login", fake_qr_login)

    assert tp.main(["login"]) == 0
    assert captured["qr_out"].name == "toutiao.png"
    assert captured["status_file"].name == "toutiao.json"
    assert captured["status_file"].parent.name == "_login"


def test_whoami_prints_single_json_line(monkeypatch, capsys):
    monkeypatch.setattr(tp, "_probe_identity",
                        lambda *a, **k: {"loggedIn": True, "name": "我的头条号", "avatar": ""})

    assert tp.main(["whoami"]) == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip().startswith("{")]
    assert json.loads(lines[-1]) == {"loggedIn": True, "name": "我的头条号", "avatar": ""}


def test_whoami_failure_carries_error_field(monkeypatch, capsys):
    """校验本身失败必须带 error——Web 端据此不缓存「未登录」假阴性。"""
    monkeypatch.setattr(
        tp, "_probe_identity",
        lambda *a, **k: {"loggedIn": False, "name": "", "avatar": "", "error": "浏览器起不来"})

    assert tp.main(["whoami"]) == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip().startswith("{")]
    assert json.loads(lines[-1])["error"] == "浏览器起不来"


def test_content_and_input_are_mutually_exclusive(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "toutiao_publish.py", "--content", "正文", "--input", "x.md", "--title", "标题"])

    with pytest.raises(SystemExit) as exc:
        tp.main()

    assert exc.value.code == 2


def test_missing_content_source_errors(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["toutiao_publish.py", "--title", "标题"])

    with pytest.raises(SystemExit) as exc:
        tp.main()

    assert exc.value.code == 2


def test_content_is_published_without_temp_file(monkeypatch, tmp_path):
    """--content 直接把正文送进发布流程，不读文件。"""
    captured: dict = {}

    def fake_publish(content, title, tags, cover, dry_run, headed, as_draft, timeout_ms):
        captured.update(content=content, title=title, tags=tags)
        return {"platform": "toutiao", "steps": {"title": True, "body": True}}

    monkeypatch.setattr(tp, "publish_article", fake_publish)
    monkeypatch.setattr(tp, "_write_record", lambda result: tmp_path / "r.json")
    monkeypatch.setattr(sys, "argv", [
        "toutiao_publish.py", "--content", "第一段\n\n第二段", "--title", "标题"])

    assert tp.main() == 0
    assert captured["content"] == "第一段\n\n第二段"
    assert captured["title"] == "标题"
