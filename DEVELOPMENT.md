# 本仓库的开发说明（fork 工作流）

> 这是 **fork 本地文档**，记录"怎么在上游持续更新的同时开发自己的功能"。
> 给上游提 PR 时请勿带上本文件与 `sync-upstream.sh`（上游有自己的 `CONTRIBUTING.md`）。

## 一、仓库关系

| 远程 | 指向 | 用途 |
|---|---|---|
| `origin`（fetch） | `https://ghproxy.net/https://github.com/zhoupeiyu515-ui/Easel.git` | 镜像拉取（本机直连 github.com 会被重置） |
| `origin`（push） | `https://github.com/zhoupeiyu515-ui/Easel.git` | 你自己的 fork，push 走直连 |
| `upstream` | `https://github.com/ZJU-REAL/Easel.git` | 原项目，只读，用来拉更新 |

> 本机实测：`api.github.com` 通，`github.com` 的 git 协议被重置，所以 fetch 走镜像、push 走直连。
> 如果哪天 push 也被挡，可以换 SSH（`git@github.com:zhoupeiyu515-ui/Easel.git`）或在能直连的网络里推。

```
upstream/main ──fetch──► 本地 main ──你的功能分支──► origin/feat/xxx ──(可选)PR──► upstream
```

## 二、日常同步上游

```bash
./sync-upstream.sh            # 拉上游 + rebase 当前分支
./sync-upstream.sh --check    # 只看上游有没有新提交，不动任何东西
./sync-upstream.sh --merge    # 冲突多、想保留合并记录时用 merge 代替 rebase
```

网络说明：国内直连 `github.com` 常被重置，脚本直连失败会自动切镜像（`EASEL_GIT_MIRROR` 可覆盖，默认 `https://ghproxy.net/`）。

**习惯**：每次开工前先 `./sync-upstream.sh --check`，有更新就同步完再动手。冲突窗口小，解决起来也简单。

## 三、分支策略

| 分支 | 内容 | 规则 |
|---|---|---|
| `main` | 与上游保持一致 + **fork 本地工具**（本文件、`sync-upstream.sh`） | 不在这里写功能代码 |
| `feat/xxx` | 你的功能，从 `main` 切出 | 一个分支一件事，方便给上游提 PR |
| `chore/xxx` | 杂项/工具 | 同上 |

功能分支只包含"能提给上游的改动"，fork 本地工具留在 `main`，这样功能分支随时可以干净地开 PR。

## 四、本机克隆的特殊之处（重要）

因为仓库体积大（`assets/` 235 MB + `web/static` 202 MB 演示视频）而国内拉取慢，**这份本地克隆是「部分克隆 + 稀疏检出」**：

- 克隆参数：`git clone --filter=blob:none --sparse` —— 只下载提交与目录树，文件按需取
- 已检出目录：`docs/ scripts/ profiles/ .github/ easel/ openclaw/ tests/ skills/ web/frontend/ outputs/`
- 未检出：`assets/`、`web/static/`、`web/app.py`（`web/app.py` 已在本地补出，但不在稀疏规则里）
- `core.autocrlf=false`：保持与上游字节一致，避免 Windows 换行符把整仓库标成 modified

**要补齐其它目录**（例如跑 Web 后端需要 `web/app.py`、看演示素材需要 `assets/`）：

```bash
# 直接补单个文件
git cat-file blob HEAD:web/app.py > web/app.py

# 把某个目录加进稀疏规则（注意：Git Bash 会把 /dir/ 转成 C:/Program Files/Git/dir/，
# 所以用 python 写规则文件，别用 git sparse-checkout set --no-cone /dir/）
python - <<'PY'
p = '.git/info/sparse-checkout'
lines = open(p, encoding='utf-8').read().splitlines()
lines.insert(lines.index('/tests/') + 1, '/web/static/')
open(p, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
PY
git sparse-checkout reapply     # 直连慢时先 export EASEL_GIT_MIRROR

# 彻底放弃稀疏（会拉 assets/ + web/static，约 400+ MB）
git sparse-checkout disable
```

如果哪天想重来一份干净的完整克隆：

```bash
git clone https://ghproxy.net/https://github.com/zhoupeiyu515-ui/Easel.git
```

## 五、提交前必跑

```bash
python scripts/validate_skills.py           # SKILL frontmatter、目录结构、发布安全契约
python scripts/validate_skill_commands.py   # 文档里的 python 命令与脚本真实 argparse 对齐
python -m pytest tests/ -q                  # 核心单测（不调用真实模型/平台）
```

三条全绿再提交。第一条对"发布类脚本必须接 `content_guard` + 提供 `--exec`"是硬校验，新增发布脚本记得同时把脚本路径加进 `scripts/validate_skills.py` 的 `PUBLISH_SCRIPT_CONTRACTS`。

## 六、当前 fork 上的自研功能

### 今日头条图文发布（`feat/toutiao-publisher`）

上游此前没有头条的原生发布链路（只在公众号 SKILL 的"阶段七"里通过 Wechatsync 浏览器扩展间接支持）。本 fork 补了一个原生 SKILL：

| 位置 | 内容 |
|---|---|
| `skills/openclaw/skill-toutiao-publisher/SKILL.md` | 技能说明与执行步骤 |
| `skills/openclaw/skill-toutiao-publisher/scripts/toutiao_publish.py` | 发布脚本（Playwright + 登录态持久化，默认 dry-run） |
| `skills/openclaw/skill-toutiao-publisher/references/` | 平台约束、选择器维护手册 |
| `skills/openclaw/skill-cross-platform-publish/scripts/publish_dispatch.py` | 注册 `toutiao` 平台与格式约束 |
| `tests/test_toutiao_publisher.py` | 契约单测（离线，不启浏览器） |

自己验一遍：

```bash
python skills/openclaw/skill-toutiao-publisher/scripts/toutiao_publish.py --selftest
python skills/openclaw/skill-cross-platform-publish/scripts/publish_dispatch.py platforms
python -m pytest tests/test_toutiao_publisher.py -q
```

真实发布需要头条号账号：

```bash
# 1) 首次扫码登录（登录态存 ~/.easel-browser-profiles/ToutiaoProfile）
python skills/openclaw/skill-toutiao-publisher/scripts/toutiao_publish.py --login

# 2) dry-run：内容填进编辑器但不点发布，用 --headed 看浏览器停在哪一步
python skills/openclaw/skill-toutiao-publisher/scripts/toutiao_publish.py \
  --input outputs/<主题>/article.md --title "标题" --headed

# 3) 确认无误后真发（--draft 先存草稿）
python skills/openclaw/skill-toutiao-publisher/scripts/toutiao_publish.py \
  --input outputs/<主题>/article.md --title "标题" --exec --draft
```

> 状态：脚本与约束层已完成并通过离线校验；**真实发布链路未端到端验证**（需要已登录的头条号）。首次跑务必用 `--headed` 观察，若头条号后台改版按 `references/publish-flow.md` 补选择器。
