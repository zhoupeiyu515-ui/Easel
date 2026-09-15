#!/usr/bin/env python3
"""toutiao_publish.py — 把图文内容发布到今日头条（头条号后台 mp.toutiao.com）。

用法（CWD=项目根）：
  # 离线自检（不启浏览器）：
  python skills/openclaw/skill-toutiao-publisher/scripts/toutiao_publish.py --selftest

  # 首次登录：打开头条号后台登录页，扫码后 profile 持久化
  python skills/openclaw/skill-toutiao-publisher/scripts/toutiao_publish.py --login

  # 预览（dry-run，不真正发布）：
  python skills/openclaw/skill-toutiao-publisher/scripts/toutiao_publish.py \
      --input outputs/主题名/article.md --title "文章标题" --tags "AI,效率"

  # 存草稿 / 真正发布：
  python skills/openclaw/skill-toutiao-publisher/scripts/toutiao_publish.py \
      --input outputs/主题名/article.md --title "文章标题" --exec --draft
  python skills/openclaw/skill-toutiao-publisher/scripts/toutiao_publish.py \
      --input outputs/主题名/article.md --title "文章标题" --cover outputs/主题名/cover.png --exec

依赖：playwright + chromium（`pip install playwright && playwright install chromium`）。
登录态持久化在 ~/.easel-browser-profiles/ToutiaoProfile（与其它平台 publisher 同款方案）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# PROJECT_ROOT：优先 EASEL_ROOT env（gateway/CLI/web 注入），否则按 __file__ 上溯。
# ⚠️ 本脚本会被 openclaw/sync.sh 拍平复制到 workspace，那里相对层级会变——故 env 兜底不可省
# （与 zhihu_answer.py / manifest.py 同款）。
PROJECT_ROOT = Path(os.environ.get("EASEL_ROOT") or Path(__file__).resolve().parents[4])
_SHARED_SCRIPTS = PROJECT_ROOT / "skills" / "shared" / "scripts"
if str(_SHARED_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SHARED_SCRIPTS))

import content_guard  # noqa: E402  出站内容安全闸门
import output_paths  # noqa: E402  产物路径规约

PROFILE_DIR = Path.home() / ".easel-browser-profiles" / "ToutiaoProfile"

LOGIN_URL = "https://mp.toutiao.com/auth/page/login"
PUBLISH_URL = "https://mp.toutiao.com/profile_v4/graphic/publish"
HOME_URL = "https://mp.toutiao.com/profile_v4/index"

# 标题上限：头条图文标题 30 字（超限后台会截断/报错），正文无硬限。
TITLE_LIMIT = 30
TAG_LIMIT = 5

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
    "--disable-extensions", "--disable-background-networking",
    "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
    "--mute-audio", "--no-first-run", "--no-default-browser-check",
]

# 选择器按"从新到旧"排列，逐个尝试——头条号后台改版频繁，多策略比单点选择器耐改。
TITLE_SELECTORS = [
    "textarea[placeholder*='标题']",
    "input[placeholder*='标题']",
    ".article-title textarea",
    ".title-input textarea",
    "textarea.byte-input__textarea",
]
BODY_SELECTORS = [
    ".ProseMirror",
    "div[contenteditable='true'][data-placeholder]",
    "div.editor-content[contenteditable='true']",
    "#ueditor_0",
]
BODY_IFRAME_SELECTORS = ["iframe[id*='ueditor']", "iframe[class*='editor']"]
SUBMIT_SELECTORS = [
    "button:has-text('预览并发布')",
    "button:has-text('发布')",
    "button:has-text('存草稿')",
    "div.publish-btn",
]

# 正文输入后必须出现的确认态（发布成功页特征），用于判定是否真的发出去了。
SUCCESS_HINTS = ("发布成功", "已发布", "内容管理", "草稿箱")


def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _resolve(path_str: str) -> Path:
    """相对路径一律挂到 PROJECT_ROOT 下（CLI 从仓库根或别处跑都一致）。"""
    p = Path(path_str).expanduser()
    return p if p.is_absolute() else (PROJECT_ROOT / p)


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception as exc:  # pragma: no cover - 环境依赖，selftest 不触发
        die(f"未安装 playwright：{exc}\n→ pip install playwright && playwright install chromium")
    from playwright.sync_api import sync_playwright
    return sync_playwright


def _first_match(page, selectors: list[str], timeout_ms: int = 5000):
    """按顺序尝试选择器，返回第一个可见元素；全不中返回 None。"""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for sel in selectors:
            try:
                locator = page.locator(sel).first
                if locator.count() and locator.is_visible():
                    return locator
            except Exception:
                continue
        page.wait_for_timeout(300)
    return None


def _fill_title(page, title: str, timeout_ms: int) -> bool:
    el = _first_match(page, TITLE_SELECTORS, timeout_ms)
    if not el:
        return False
    el.click()
    el.fill("")
    el.type(title, delay=20)
    return True


def _fill_body(page, body: str, timeout_ms: int) -> bool:
    el = _first_match(page, BODY_SELECTORS, timeout_ms)
    if el is not None:
        el.click()
        # 富文本编辑器用 insert_text 逐段写入，避免 type() 在长文下过慢。
        for para in [p for p in body.split("\n") if p.strip()]:
            page.keyboard.insert_text(para)
            page.keyboard.press("Enter")
        return True
    # 回退：正文编辑器在 iframe 里（老版 ueditor）
    for frame_sel in BODY_IFRAME_SELECTORS:
        try:
            frame_el = page.locator(frame_sel).first
            if not frame_el.count():
                continue
            frame = frame_el.content_frame
            if frame:
                frame.locator("body").click()
                frame.locator("body").type(body, delay=5)
                return True
        except Exception:
            continue
    return False


def _upload_cover(page, cover: Path) -> bool:
    """封面走页面里的 file input（头条号封面弹窗内），失败只告警不阻断。"""
    if not cover.is_file():
        return False
    try:
        inputs = page.locator("input[type='file']")
        if not inputs.count():
            return False
        inputs.first.set_input_files(str(cover))
        page.wait_for_timeout(1500)
        return True
    except Exception:
        return False


def _click_submit(page, want_draft: bool) -> bool:
    selectors = ["button:has-text('存草稿')"] if want_draft else SUBMIT_SELECTORS
    btn = _first_match(page, selectors, 8000)
    if not btn:
        return False
    btn.click()
    page.wait_for_timeout(2500)
    # 发布确认弹窗（"确认发布"二次确认）
    for label in ("确认发布", "确定", "确认"):
        try:
            confirm = page.locator(f"button:has-text('{label}')").first
            if confirm.count() and confirm.is_visible():
                confirm.click()
                page.wait_for_timeout(2500)
                break
        except Exception:
            continue
    return True


def _open_browser(pw, headed: bool):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    ctx = pw.chromium.launch_persistent_context(
        str(PROFILE_DIR), headless=not headed, args=LAUNCH_ARGS,
        viewport={"width": 1440, "height": 900},
    )
    return ctx, ctx.pages[0] if ctx.pages else ctx.new_page()


def login(wait_seconds: int, headed: bool = True) -> int:
    """打开登录页等扫码，登录态写入 PROFILE_DIR。"""
    sync_playwright = _require_playwright()
    with sync_playwright() as pw:
        ctx, page = _open_browser(pw, headed)
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        print(f"请在弹出的浏览器里扫码登录头条号（{wait_seconds}s 内）…", file=sys.stderr)
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if "login" not in page.url:
                page.goto(HOME_URL, wait_until="domcontentloaded")
                print(f"登录成功，profile 已保存到 {PROFILE_DIR}", file=sys.stderr)
                ctx.close()
                return 0
            page.wait_for_timeout(2000)
        ctx.close()
    die("登录超时：未检测到登录态，请重跑 --login")


def publish_article(content: str, title: str, tags: list[str], cover: Path | None,
                    dry_run: bool, headed: bool, as_draft: bool, timeout_ms: int) -> dict:
    """把图文发到头条号。dry_run=True 时只走到编辑器填写完成，不点发布。"""
    sync_playwright = _require_playwright()
    result: dict = {"platform": "toutiao", "dry_run": dry_run, "draft": as_draft,
                    "title": title, "tags": tags,
                    "cover": str(cover) if cover else "", "steps": {}}
    with sync_playwright() as pw:
        ctx, page = _open_browser(pw, headed)
        try:
            page.goto(PUBLISH_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            if "login" in page.url or "auth" in page.url:
                result["error"] = "未登录头条号：先跑 --login 扫码"
                return result

            result["steps"]["title"] = _fill_title(page, title, timeout_ms)
            result["steps"]["body"] = _fill_body(page, content, timeout_ms)
            if cover:
                result["steps"]["cover"] = _upload_cover(page, cover)
            if tags:
                result["steps"]["tags"] = _fill_tags(page, tags, timeout_ms)

            if not result["steps"]["title"] or not result["steps"]["body"]:
                result["error"] = "编辑器定位失败（标题或正文），头条号后台可能已改版——见 references/publish-flow.md"
                return result

            if dry_run:
                result["note"] = "dry-run：内容已填入编辑器，未点击发布"
                return result

            if not _click_submit(page, as_draft):
                result["error"] = "未找到发布/存草稿按钮"
                return result
            body_text = page.inner_text("body")
            result["published"] = any(h in body_text for h in SUCCESS_HINTS)
            result["url"] = page.url
        finally:
            ctx.close()
    return result


def _fill_tags(page, tags: list[str], timeout_ms: int) -> bool:
    """话题/标签输入（头条用 # 话题，输入后回车绑定）。找不到就跳过，不阻断。"""
    el = _first_match(page, ["input[placeholder*='话题']", "input[placeholder*='标签']"], timeout_ms)
    if el is None:
        return False
    el.click()
    for tag in tags[:TAG_LIMIT]:
        el.type(tag, delay=30)
        page.wait_for_timeout(600)
        page.keyboard.press("Enter")
    return True


def _write_record(result: dict) -> Path:
    """发布留痕写 outputs/_publish/（系统目录，需 allow_system）。"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = output_paths.validate_output_path(
        f"outputs/_publish/toutiao_{stamp}.json", allow_system=True, create_parent=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _selftest() -> int:
    """轻量自测（不启浏览器）：校验选择器常量、标题上限与路径解析。"""
    assert TITLE_LIMIT == 30, "头条图文标题上限应为 30 字"
    assert TITLE_SELECTORS and BODY_SELECTORS and SUBMIT_SELECTORS, "选择器表不应为空"
    assert "--disable-blink-features=AutomationControlled" in LAUNCH_ARGS, "反检测参数缺失"
    assert PUBLISH_URL.startswith("https://mp.toutiao.com/"), "发布地址应为头条号后台"
    # 相对路径必须挂到 PROJECT_ROOT，且产物只能落 outputs/<主题> 或注册系统目录
    assert _resolve("outputs/x/a.md") == PROJECT_ROOT / "outputs/x/a.md"
    assert _resolve(str(Path.home())).is_absolute()
    try:
        output_paths.validate_output_path("outputs/toutiao-app-upgrade/note.md")
        ok = True
    except output_paths.OutputPathError:
        ok = False
    assert ok, "outputs/<主题>/ 下的产物路径应被接受"
    try:
        output_paths.validate_output_path("outputs/_publish/toutiao.json", allow_system=True)
        ok = True
    except output_paths.OutputPathError:
        ok = False
    assert ok, "outputs/_publish/ 应被接受为注册系统目录"
    # 出站闸门在 dry-run 下不拦、只告警
    content_guard.guard_or_die(["正常正文，无敏感信息"], exec_mode=False, label="自检")
    try:
        import playwright  # noqa: F401
        pw_state = "yes"
    except Exception:
        pw_state = "MISSING（需 pip install playwright && playwright install chromium）"
    print(f"toutiao_publish.py selftest: OK (playwright={pw_state})")
    return 0


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return _selftest()

    parser = argparse.ArgumentParser(description="今日头条（头条号）图文发布工具")
    parser.add_argument("--selftest", action="store_true", help="离线自检")
    parser.add_argument("--login", action="store_true", help="打开登录页等扫码，持久化登录态")
    parser.add_argument("--login-wait", type=int, default=180, help="扫码等待秒数（默认 180）")
    parser.add_argument("--input", help="正文 Markdown/文本文件路径")
    parser.add_argument("--title", help="文章标题（≤30 字）")
    parser.add_argument("--cover", help="封面图路径（可选，头条可自动选正文首图）")
    parser.add_argument("--tags", default="", help="话题标签，逗号分隔（≤5 个）")
    parser.add_argument("--draft", action="store_true", help="存草稿而不是直接发布")
    parser.add_argument("--exec", action="store_true", dest="execute",
                        help="真正发布（默认 dry-run，只填编辑器）")
    parser.add_argument("--allow-unsafe", action="store_true",
                        help="放行内容安全闸门（检出内部设置泄露也照发，谨慎）")
    parser.add_argument("--headed", action="store_true", help="有头浏览器模式（调试用）")
    parser.add_argument("--timeout", type=int, default=15000, help="编辑器元素等待毫秒数")
    args = parser.parse_args()

    if args.login:
        return login(args.login_wait, headed=True)

    if not args.input or not args.title:
        parser.error("发布需要 --input 与 --title（或用 --login / --selftest）")

    src = _resolve(args.input)
    if not src.is_file():
        die(f"内容文件不存在：{src}")
    content = src.read_text(encoding="utf-8").strip()
    if not content:
        die("内容文件为空")

    title = args.title.strip()
    if len(title) > TITLE_LIMIT:
        die(f"标题 {len(title)} 字超过头条图文上限 {TITLE_LIMIT} 字，请精简后再发")
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    cover = _resolve(args.cover) if args.cover else None
    if cover and not cover.is_file():
        die(f"封面图不存在：{cover}")

    dry_run = not args.execute
    # 出站内容安全闸门：真发前扫描标题/正文/话题，检出内部设置泄露即阻止发布（dry-run 只告警）。
    content_guard.guard_or_die([title, content, *tags], exec_mode=not dry_run,
                               allow_unsafe=args.allow_unsafe, label="今日头条图文")

    print(f"[{'DRY-RUN' if dry_run else 'EXEC'}] 今日头条图文发布", file=sys.stderr)
    print(f"  标题: {title}（{len(title)} 字）", file=sys.stderr)
    print(f"  正文: {src}（{len(content)} 字）· 话题 {len(tags)} 个"
          f"{' · 存草稿' if args.draft else ''}", file=sys.stderr)

    result = publish_article(content, title, tags, cover, dry_run,
                             args.headed, args.draft, args.timeout)
    if result.get("error"):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        die(result["error"])
    record = _write_record(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"留痕: {record}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
