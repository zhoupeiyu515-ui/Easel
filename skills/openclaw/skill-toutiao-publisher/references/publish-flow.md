# 头条号发布链路与选择器维护

> 本文件是领域知识，`scripts/toutiao_publish.py` 改动选择器时对照本表。

## 一、链路

```
mp.toutiao.com/auth/page/login          扫码登录（登录态存 ToutiaoProfile）
        ↓
mp.toutiao.com/profile_v4/graphic/publish   图文发布页
        ├── 标题输入框
        ├── 正文富文本编辑器
        ├── 封面设置（弹窗内 file input）
        ├── 话题/标签输入
        └── 「预览并发布」→ 确认弹窗「确认发布」｜「存草稿」
```

## 二、选择器表（脚本里的常量，按顺序回退）

| 元素 | 脚本常量 | 候选选择器 | 备注 |
|---|---|---|---|
| 标题 | `TITLE_SELECTORS` | `textarea[placeholder*='标题']` / `input[placeholder*='标题']` / `.article-title textarea` / `.title-input textarea` / `textarea.byte-input__textarea` | 头条用的是自研组件库（byte-*），占位符匹配最稳 |
| 正文 | `BODY_SELECTORS` | `.ProseMirror` / `div[contenteditable='true'][data-placeholder]` / `div.editor-content[contenteditable='true']` / `#ueditor_0` | 老版页面正文在 iframe 里，见 `BODY_IFRAME_SELECTORS` |
| 发布 | `SUBMIT_SELECTORS` | `button:has-text('预览并发布')` / `button:has-text('发布')` / `button:has-text('存草稿')` / `div.publish-btn` | 存草稿模式只匹配「存草稿」 |
| 话题 | 内联 | `input[placeholder*='话题']` / `input[placeholder*='标签']` | 找不到就跳过，不阻断发布 |
| 成功判定 | `SUCCESS_HINTS` | `发布成功` / `已发布` / `内容管理` / `草稿箱` | 点完按钮后读 `body` 全文匹配 |

## 三、改版了怎么修

1. **先跑 dry-run 定位失败点**：`steps` 字段会告诉你 `title` 还是 `body` 没填上。
   ```bash
   python skills/openclaw/skill-toutiao-publisher/scripts/toutiao_publish.py \
     --input outputs/主题名/article.md --title "标题" --headed
   ```
   `--headed` 能直接看到浏览器停在哪一步。
2. **在浏览器 DevTools 里取新选择器**：优先用**语义稳定**的属性（placeholder 文本、按钮可见文字），避免 `class` 哈希 / `:nth-child` 这类易变定位。
3. **加进候选列表的末尾**，保留旧选择器——头条灰度发布期间不同账号页面版本可能不同。
4. **改完跑自检 + dry-run**：
   ```bash
   python skills/openclaw/skill-toutiao-publisher/scripts/toutiao_publish.py --selftest
   python scripts/validate_skill_commands.py
   ```

## 四、登录态

- profile 目录：`~/.easel-browser-profiles/ToutiaoProfile`
- 失效表现：访问发布页被跳回 `auth/page/login`，脚本返回 `未登录头条号：先跑 --login 扫码`
- 头条登录常要求短信验证，`--login` 时留意手机；同一 profile 长期复用可显著降低二次验证概率
- 别把 profile 目录提交进仓库（`.gitignore` 已排除 `~/.easel-browser-profiles` 这类 home 目录）

## 五、发布留痕

每次 `--exec` 成功都会写 `outputs/_publish/toutiao_<时间戳>.json`（系统目录，经 `skills/shared/scripts/output_paths.py` 校验）。内容库不展示该系统目录，它是给归因层和排障用的。
