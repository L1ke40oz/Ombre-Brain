# Handoff：根路径换成 Vue SPA

写于 2026-09-16。对应提交 `eeb96c8`，已推到 `origin`（`L1ke40oz/Ombre-Brain`）。
这份文档是给下一个人（可能是几个月后的你自己）看的：做了什么、为什么这么做、
以及我在过程中踩进去又爬出来的坑。**不要读 `frontend/dashboard.html`**，
那文件大到读一次就把上下文吃光。

---

## 一、起因

`ombre-brain-galaxy-mobile` 是让 Gemini 重写的前端，Vue 3 + Vite 的多文件工程。
ob 后端当时只认一个 `frontend/dashboard.html`：

- `/` 路由写死读那一个文件；
- 唯一的静态路由是**四个文件名的硬白名单**。

Vite 产出的是 `index-dbWGaxSt.js` 这种带内容哈希的分块，名字每次构建都变，
白名单模型根本发不出去。所以不改后端的话，新前端一行都跑不起来。

当时给过两条路：

- **路 A**：让 Vite 把一切内联成单个 HTML，继续沿用老的单文件伺服；
- **路 B**：保留多文件构建，改 ob 去伺服整个 dist 目录。

选了**路 B**，理由是「主要是想方便修改」——路 A 每改一行都要重新内联，
dev 模式的 HMR 也用不上。

---

## 二、最终形态

```
浏览器  ──►  /              → Vue SPA 首页（index.html）
             /galaxy /letters /settings … → 同一份 index.html（history 模式）
             /assets/*.js   → 带哈希的分块，immutable 缓存一年
             /api/* /auth/* /mcp /static/* … → 后端原样，没被动过
             /legacy-dashboard → 老的单文件面板
             /dashboard     → 301 到 /
```

### 新增 `src/web/spa.py`

整个路由面就两条：

```python
@mcp.custom_route("/", methods=["GET"])            # → index.html
@mcp.custom_route("/{path:path}", methods=["GET"]) # 命中文件发文件，否则回 index.html
```

关键常量：

- `_DIST_SUBPATH = ("frontend", "app")` —— 构建产物落点。
- `_RESERVED_PREFIXES` —— 后端语义面的前缀清单，见下文「坑 2」。
- `_IMMUTABLE_DIRS = ("assets",)` —— 这些目录下的文件名带内容哈希，可以
  `max-age=31536000, immutable`。
- `_NEVER_CACHE` —— `index.html` / `sw.js` / `registerSW.js` /
  `manifest.webmanifest` 一律 `no-store`。这四个名字一旦被缓存，用户会卡在
  旧版本前端上，且自己刷不掉。

### 改动的文件

| 文件 | 改了什么 |
|---|---|
| `src/web/__init__.py` | 引入 `web.spa`，并把它放到 `_WEB_MODULES` **最后一项** |
| `src/web/dashboard.py` | `/` → `/legacy-dashboard` |
| `src/web/letters.py` | 删掉 `/letters` → 301 `/#letters` 那条路由 |
| `src/web/config_api.py` | 只改了 `/dashboard` → 301 `/` 的注释，路由本身保留 |
| `tests/test_public_surface_minimization.py` | 断言里的 `/` 改成 `/legacy-dashboard` |
| `tests/test_spa_app_surface.py` | 新增，18 条契约 |
| `.gitignore` | 放行 `frontend/app/`，屏蔽 `*_start.bat` 等 |

前端侧（隔壁 `ombre-brain-galaxy-mobile`）：

- `vite.config.ts`：`base = '/'`；`outDir` 直接指向 `../Ombre-Brain/frontend/app`
  （可用 `OMBRE_DIST_DIR` 覆盖）；dev proxy 指向 `http://127.0.0.1:2140`
  （可用 `OMBRE_DEV_TARGET` 覆盖）；PWA 的 `navigateFallbackDenylist` 扩充。
- `src/router/index.ts`：`createWebHistory(import.meta.env.BASE_URL)`，
  前缀只有 `vite.config.ts` 一个真源。
- `src/env.d.ts`：新建，见「坑 5」。

---

## 三、踩过的坑

### 坑 1：Starlette 路由是**注册顺序**匹配，先注册者胜

一开始以为会按「具体路径优先于通配」来排。不是。我写了个 TestClient 小实验
实测：先注册的 `/{path:path}` 会把后注册的 `/api/health` 整个吃掉。

所以 `web.spa` **必须**是 `_WEB_MODULES` 的最后一项，否则整个后端 API 面全挂。
这条约束落在三个地方：

1. `web/__init__.py` 里那段承重注释；
2. `tests/test_spa_app_surface.py::test_spa_must_be_registered_last` 钉住它；
3. `_RESERVED_PREFIXES` 作为纵深防御。

### 坑 2：给等 JSON 的客户端回一篇 HTML，会炸在很远的地方

SPA 兜底的天然行为是「什么都回 index.html」。但 `/api/typo` 回 HTML 的话，
前端在 `json.parse` 处报一个跟真实原因毫无关系的错。

所以 `_RESERVED_PREFIXES` 下的未命中路径一律回 **JSON 404**：

```python
_RESERVED_PREFIXES = ("api/", "auth/", "oauth/", ".well-known/", "mcp",
                      "static/", "breath-hook", "health")
```

**新增后端路径前缀时，这里和 `vite.config.ts` 的 `navigateFallbackDenylist`
要同步改。** 前者管服务端，后者管 Service Worker——SW 也会把导航请求换成
HTML，客户端这一侧漏了同样会失效。

### 坑 3：`/letters` 路由撞车

`letters.py` 里有条 `/letters` → 301 `/#letters`。它注册在 spa 之前，
会遮住 SPA 自己的 `/letters` 页面，用户点进去被弹回首页锚点。直接删了，
原地留了注释说明为什么不能加回来。

`/dashboard` → 301 `/` 反而保留：老书签落到新前端正是想要的效果。

### 坑 4：目录穿越

`_resolve_within()` 是**唯一**的路径判定入口，做 `realpath` + `commonpath`
包含性检查。Windows 上跨盘符时 `commonpath` 会抛 `ValueError`，一律当越界。

写测试时我自己搞错过一次：给 `..%2f..%2fsecret.txt` 和 `....//....//secret.txt`
断言「结果里不能出现 secret.txt」，结果测试红了。实际探了一下——这两个串
解析后是 dist **内部**一个字面量的、不存在的文件名，本来就是安全的。
断言写错了，不是代码有问题。改成了直接比对「不等于 dist 外那个真文件的
realpath」，并在注释里写明两种可接受的安全结局。

### 坑 5：`vue-tsc` 报 `Property 'env' does not exist on type 'ImportMeta'`

`router/index.ts` 用了 `import.meta.env.BASE_URL`，但 tsconfig 里没有
`vite/client` 类型，构建直接失败。新建 `src/env.d.ts` 一行
`/// <reference types="vite/client" />` 解决。

### 坑 6：`.gitignore` 的换行符污染

HEAD 里这个文件是混合换行（97 CRLF + 19 LF，`core.autocrlf=true` 的历史遗留）。
我第一次用普通编辑改它，整个文件被统一成 CRLF，diff 里凭空多出二十行
「改动」。做法是 `git checkout -- .gitignore` 回退，然后用脚本锚定某一行、
**按那一行自己的换行风格**插入新行。

同一个坑还有个变体：bash 里 `python -c "...\`COPY frontend/\`..."` 中的反引号
被命令替换执行了，报 `COPY: command not found`。写成临时脚本文件即可。

### 坑 7：端口

`src/server.py:133` 的优先级是 **env `OMBRE_PORT` > config.yaml `host_port` > 18001**。

我一度说你 config.yaml 里的 `port: 2140` 「没生效」——对你的实际情况这话是错的：
你的 `ob _start.bat` 里有 `set OMBRE_PORT=2140`，env 优先级最高，端口一直是
2140。我补的 `host_port` 只在**不带那个 env 启动**时才起作用。

config.yaml 里的 `port` 字段只被 `/api/system/deploy` 诊断接口拿来显示，
不决定监听端口，所以我把两个都写成 2140 以免误导。

### 坑 8：`frontend/dashboard.html` 曾让 90 条测试变红

你本地那份改过的 `dashboard.html` 会让 22 个测试文件里的 90 条契约测试失败
（它们都读这个文件、断言里面的结构）。你把备份恢复成原版之后，全量
**2934 passed / 111 skipped / 0 failed**，不需要任何临时替换。

---

## 四、实机验证过的东西

后端真的起在 2140 上跑过一轮：

- SPA 面：`/`、`/galaxy`、`/letters`、`/settings` → 200，都是 index.html。
- 后端面：`/health`、`/api/letters`（401）、`/api/buckets`（401）、
  `/auth/status`、`/static/icon.svg`、`/favicon.ico`（301）、
  `/legacy-dashboard`、`/dashboard`（301）全部原样。
- `POST /mcp` → 401 带 OAuth `resource_metadata`，**不是** SPA 的 HTML。
- 穿越尝试：`/config.yaml`、`/.git/config`、`/src/server.py`、`/../VERSION`、
  `/..%2fVERSION`（curl `--path-as-is`）——全都只拿到 SPA 首页，零文件泄漏。
- dev 模式：`localhost:3000/` 出 SPA，`/api/*` 真的代理到了 2140。

---

## 五、还没做的

1. **PWA 图标**：`public/pwa-192.png`、`public/pwa-512.png` 不存在，
   manifest 已经引用了。不影响页面运行，只影响「添加到主屏」的图标。
   （你说过「图标等一下」。）
2. **`ombre-brain-galaxy-mobile` 根本不是 git 仓库。** 前端的唯一真源现在
   没有任何版本控制，改坏了没法回退。建议尽快 `git init` 并推一个私有仓库。
3. **四份文档还在讲老的路由面**：`README.md`、`docs/INTERNALS.md`、
   `docs/MULTI_OWNER.md`、`docs/OPERATIONS.md`。等新前端在真实使用中稳下来
   再统一过一遍，免得来回改。
4. **部署机同步**：另一台机器（`/Users/nsmith/Desktop/Ombre-Brain`）拉代码时
   必须带上 `frontend/app/`，否则根路径只会显示
   `packaged frontend asset is missing`。

---

## 六、日常怎么改前端

```bash
cd ../ombre-brain-galaxy-mobile
npm run dev          # localhost:3000，HMR，/api 代理到 2140
npm run build        # 产物直接写进 ../Ombre-Brain/frontend/app/
```

构建产物**要跟着 ob 一起提交 git**：Dockerfile 只 `COPY frontend/`，
`deploy/gen_update_manifest.py` 也只给 git 已跟踪的文件算哈希——不提交的话
Docker 用户永远收不到新前端。这条理由写在 `.gitignore` 第 82–86 行，
别在那儿加 `frontend/app/`。

---

## 七、仓库拓扑与安全边界

- `origin` = `https://github.com/L1ke40oz/Ombre-Brain`（你的 fork，已推 `eeb96c8`）
- `upstream` = `https://github.com/P0luz/Ombre-Brain`（原仓库，这次快进合并到
  `115d831` / v3.6.14，零文件冲突）

**两个绝不能进仓库的文件**，都已在 `.gitignore` 里：

- `config.yaml`（`.gitignore:21`）——含真实 API key，从来没被跟踪过。
- `ob _start.bat`（`.gitignore:63-64`，规则 `*_start.bat`）——含
  `OMBRE_MCP_TOKEN`。它这次出现在了仓库根目录，是我在 `git add` 前拦下的。
  推之前对整个提交做过一遍凭据扫描，干净。

这份 handoff 本身没有提交，就放在工作区根目录。
