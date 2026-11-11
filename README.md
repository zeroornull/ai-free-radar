# AIFreeRadar

本机使用的免费 AI API 消息雷达：每日或手动轻量收集有来源的免费机会，首页展示增量消息，资源库保存各服务与活动的持续记录，需要时再核验官方政策。覆盖文本、图像、视频、语音、Embedding、Rerank 六类 API，不收录仅能网页交互的工具。

官方页面、社区帖子、GitHub 和搜索结果摘要均可作为收集来源：只要有安全、可追溯的 HTTP(S) 链接提到免费 AI API 权益，即可收录，不要求逐字段官方原文证据。额度、有效期、领取或支付条件未知时显示“未说明”；允许要求绑卡，排除明确要求付款、购买或充值的权益。收录只表示发现了一条消息，不保证来源准确，也不代表政策已核验。所有资源均为**未实测调用**，网络访问为**未实测**；应用不会自动注册、登录、领取权益或调用候选 API，也不会预置伪造的官方资源。

## 安装与启动

需要 Python 3.12 或以上、[uv](https://docs.astral.sh/uv/) 以及 Node 24 与 pnpm（仅源码运行时的前端构建需要）。在项目目录打开 PowerShell：

```powershell
uv sync --locked
Copy-Item config.example.toml config.toml
Copy-Item .env.example .env
```

编辑 `config.toml` 选择模型及搜索服务，再编辑同目录的 `.env` 填入相应真实密钥。删除不用的占位项，`replace-with-...` 不能作为有效密钥。启动后也可以在 `/settings` 页面修改配置并保存密钥，页面写入的值优先于文件；保存密钥需要先配置主密钥：

```powershell
python -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

将输出写入 `.env` 的 `AIFREERADAR_SECRET_KEY=`。该值必须是 urlsafe base64 编码的 32 字节随机数；数据库中已有加密密钥而缺少主密钥（或格式错误）时，启动直接失败。

从源码运行前需要先构建一次前端产物：

```powershell
pnpm --dir frontend build
```

然后启动：

```powershell
uv run aifreeradar
```

打开 <http://127.0.0.1:18765>。不必激活 `.venv`；`uv run` 使用项目环境。程序仅监听 `127.0.0.1`，不提供注册、登录、局域网或公网访问。关闭终端或按 Ctrl+C 后停止服务与调度。

默认端口选在 15000 以上，降低与 Windows 动态端口及保留区间冲突的概率。若端口仍被占用，修改 `config.toml` 的 `port`，开发代理同步设置 `AIFREERADAR_API_TARGET`。

已构建的发布包（wheel/sdist）运行只依赖 Python 与打包时包含的产物，不再需要 Node 或前端构建步骤；`hatch build` 会校验 `index.html` 与 JS/CSS 资产存在并拒绝缺失产物的包。前端的 `index.html` 与 JS/CSS 资产由应用同源托管。

配置默认从启动目录的 `config.toml` 读取。指定其他配置可在 PowerShell 设置：

```powershell
$env:AIFREERADAR_CONFIG = "D:/MyRadar/config.toml"
uv run aifreeradar
```

明确指定但不存在的配置文件会报错。`.env` 从配置文件所在目录读取，已有进程环境变量优先；`data_dir` 相对于配置文件所在目录解析，不随当前工作目录变化。

### 配置真源与密钥

配置按三层合并，后者覆盖前者：

1. 代码内置默认值。
2. 启动时读取的 `config.toml`（或 `AIFREERADAR_CONFIG` 指定的路径）。每次启动都会重新读取它作为默认值，程序从不写回。
3. 数据库中的覆盖：某字段一旦存在覆盖行就以它为准；写入 `null` 会删除该覆盖并回落到 `config.toml`。覆盖在重启后继续生效。

`/settings` 页面展示合并后的生效值和每个字段的来源（数据库、`config.toml` 或默认值），并允许修改模型、模型端点、密钥变量名、搜索服务、定时开关与时间、默认范围。页面只写数据库，不改动 `config.toml`；`host`、`port`、`data_dir` 只读。保存时先整体校验，再在单个事务内写入，版本不一致返回冲突，需刷新后重试。保存与探测是两步，探测失败不会写库。正在进行的收集任务使用启动时快照，页面修改只影响之后的运行与触发点；调度时间或开关的变更不补跑当天。

密钥优先级：数据库中的加密密钥（按当前 `model_api_key_env` / `search_api_key_env` 对应的变量名匹配）> `config.toml` 中的 `model_api_key` / `search_api_key` 明文 > 同名环境变量（含 `.env`）。页面写入的密钥以 AES-256-GCM 加密后存库，主密钥来自 `AIFREERADAR_SECRET_KEY`。页面从不回传密钥明文，只返回是否已配置及来源；清空密钥请提交 `null`，空字符串不是有效值。

### 开发代理

前端开发服务器（`pnpm --dir frontend dev`，监听 `127.0.0.1:15173`）把 `/api` 与 `/health` 代理到后端，并把代理请求的 `Origin` 改写为后端地址，因此开发时默认无需任何环境变量：

```powershell
uv run aifreeradar          # 终端一：后端，默认 127.0.0.1:18765
pnpm --dir frontend dev     # 终端二：开发服务器
```

浏览器访问 <http://127.0.0.1:15173>，编辑即时热更新，写请求经代理后按同源处理。后端不在默认端口时设置 `AIFREERADAR_API_TARGET`（必须是 127.0.0.1/localhost 的 http 回环源，不允许账号、路径、查询或片段）。只有绕过代理、从浏览器直接向另一端口发写请求时，后端才需要 `AIFREERADAR_DEV_ORIGIN=http://127.0.0.1:15173`；未设置时这种跨端口直发一律 403。代理只存在于开发服务器，正式同源托管与生产构建不受影响。

## 配置示例

下列是 `config.toml` 支持的 TOML 字段，全部作为启动默认值，可在 `/settings` 覆盖。密钥可以直接写在 `model_api_key` 和 `search_api_key`（该文件已被 git 忽略），但常规做法是写入 `/settings` 页面或 `.env`，优先级见上一节。不要把真实密钥写进会提交的示例文件，页面也不会显示密钥：

```toml
data_dir = "data"
model = "openai:gpt-4.1-mini"
model_api_key_env = "OPENAI_API_KEY"
search_provider = "duckduckgo"
search_api_key_env = ""
schedule_enabled = true
schedule_time = "09:00"
host = "127.0.0.1"
port = 18765

# [direct_sources]
# text = ["https://platform.openai.com/docs/pricing"]
# image = ["https://platform.stability.ai/pricing"]

[default_scope]
categories = ["text", "image", "video", "speech", "embedding", "rerank"]
region = "global"
```

`region` 只能取 `global` 或 `china`，类别至少选择一项。`china` 是中国大陆相关政策的研究范围，不表示实际网络可达；中国大陆条件未知的免费消息仍可收集并明确标注未知。只有官方依据才能支持“官方支持中国大陆注册及使用 API”的核验结论。

`direct_sources` 是可选的本机配置，按类别列出官方免费政策入口页（例如 pricing 或文档首页），用于补充发现，并不限制收集只能来自官方。它只能写在 `config.toml`，不能通过 `/settings` 编辑；键必须是上面的类别名，值必须是绝对 HTTP(S) 地址。留空或省略即关闭直连来源。

模型示例（替换顶层相应字段，放在 `[default_scope]` **之前**）：

| 服务 | `model` | `model_api_key_env` | `.env` 中的变量 |
|---|---|---|---|
| OpenAI | `openai:gpt-4.1-mini` | `OPENAI_API_KEY` | `OPENAI_API_KEY=实际密钥` |
| Claude / Anthropic | `anthropic:claude-sonnet-4-5` | `ANTHROPIC_API_KEY` | `ANTHROPIC_API_KEY=实际密钥` |
| DeepSeek | `deepseek:deepseek-chat` | `DEEPSEEK_API_KEY` | `DEEPSEEK_API_KEY=实际密钥` |
| OpenAI 兼容端点，例如 Grok | `grok-4.7` | `XAI_API_KEY` | `XAI_API_KEY=实际密钥`，并设置 `model_base_url = "https://api.x.ai/v1"` |

以 Grok 为例，三项要成套填写，`config.toml` 可直接改成：

```toml
data_dir = "data"

model = "grok-4.7"                        # 网关返回的模型名，原样发送
model_base_url = "https://api.x.ai/v1"     # 兼容服务的 Chat Completions 地址
model_api_key_env = "XAI_API_KEY"          # 只写环境变量名，不写密钥

search_provider = "exa"
search_api_key_env = "EXA_API_KEY"

schedule_enabled = true
schedule_time = "09:00"
host = "127.0.0.1"
port = 18765

[default_scope]
categories = ["text", "image", "video", "speech", "embedding", "rerank"]
region = "global"
```

同目录 `.env`：

```dotenv
XAI_API_KEY=你的 xAI 密钥
EXA_API_KEY=你的 Exa 密钥
```

换用其他兼容服务时，只替换这三处：`model` 的模型名、`model_base_url` 的服务地址、`model_api_key_env` 指向的变量名（`.env` 里同名赋值）。`model_base_url` 不要带查询串、片段或账号密码。

没有 `openai:`、`anthropic:`、`deepseek:` 这类官方前缀时，`model` 整段都是模型名，原样发给 `model_base_url`。因此网关里的 `grok/grok-4.7-build-fast@500k` 就照写，不必再加 `compatible:`。`compatible:` 仍然可用，只是会去掉这个前缀。不填 `model_base_url` 时配置直接失败，不会默认连到 `api.openai.com`，也不会改用 `OPENAI_API_KEY`。

模型名称示例不保证账号已获权限或服务长期提供该型号。另支持 `openai-chat:` 与 `openai-responses:` 前缀；后者只用于 OpenAI Responses API 或其透明代理，不用于任意兼容端点。OpenAI 与 Anthropic 可以直接使用 `model_base_url`。已安装的 `DeepSeekProvider` 没有 `base_url` 参数；DeepSeek 的 `model_base_url` 会传给 `AsyncOpenAI`，再交给 `DeepSeekProvider(openai_client=...)`。未填写时使用 `https://api.deepseek.com`。配置错误、权限不足、缺密钥或模型不兼容都会明确失败，不会静默替换模型。真实模型请求可能产生所选提供商的费用；应用不会根据价格自动切换服务。

搜索服务**只使用显式选定的一种**：

| `search_provider` | `search_api_key_env` | `.env` 配置 |
|---|---|---|
| `duckduckgo` | `""` | 不需要搜索密钥；仍需要模型密钥 |
| `tavily` | `"TAVILY_API_KEY"` | `TAVILY_API_KEY=实际密钥` |
| `brave` | `"BRAVE_API_KEY"` | `BRAVE_API_KEY=实际密钥` |
| `exa` | `"EXA_API_KEY"` | `EXA_API_KEY=实际密钥` |

例如选择 Exa 就设置 `search_provider = "exa"` 和 `search_api_key_env = "EXA_API_KEY"`。请求发往 `https://api.exa.ai/search`，使用高亮片段发现消息；保留的摘要必须标注为搜索摘要，不能冒充已读取的网页或已核验官方政策。搜索请求失败或密钥缺失时记录失败，**不会回退到 DuckDuckGo、原生模型搜索或另一搜索服务**。服务可用性、限额和费用由相应账号与提供商决定。

每个类别的发现段在交给研究 Agent 之前，先执行 6 条固定基线查询（3 条中文、3 条英文），计入每段 16 次搜索预算，Agent 仍可在此之上追加查询；基线查询失败只记录失败，不回退搜索服务。若配置了 `direct_sources`，同一发现段还会抓取该类别的官方入口页，遵循 robots.txt 与每域约 1 秒的间隔，只跟进一跳链接，合计最多 8 个入口页，并与 Agent 共用每段 32 次抓取预算。实际搜索结果及实际读取的页面分别记录来源；抓取失败时可保留本次真实观察到的搜索摘要，并注明其来源与访问方式。

## 使用与记录含义

首页“消息动态”展示当前免费机会的新增、重要变化和恢复消息，可按类别筛选并切换查看已结束历史。消息展示免费摘要、已知条件与未知项、绑卡要求、来源类型及页面/摘要标识；有发布时间时显示发布时间，否则明确显示发现时间。日期较旧仅表示消息年龄，不自动判定结束。

资源库维护提供商及具体 API 服务，每个服务可有多个独立活动。有来源消息的资源以“已收录”为主状态，未知条件不阻止正常展示；没有可追溯消息的旧记录标为“历史线索·来源待补”。详情优先展示最新消息、来源及活动历史，官方政策核验是可选操作，未执行或未通过时附加“未经核验”。内部政策状态 `pending`、`active`、`expired` 仍分别表示未核验、政策已核验及有失效结论，不能当作消息收录门槛。收集不会覆盖既有核验证据或最后成功核验时间，额度保留原单位。

同一服务、同一活动的转发或重复报道合并来源，不因标题改写、时间或链接变化重复发消息。额度、模型、领取条件、支付条件、地区或有效期等实质变化产生新事件；不同活动分别保留。新报告中的未知值不抹掉此前已知内容。只有来源明确结束或明确的到期日期已过才结束活动；抓取失败、长期没更新或本次未搜到均不构成结束证据。当前列表默认隐藏已结束活动，历史仍可查看；资源全部活动已结束时默认从当前资源库隐藏。

每日、补跑和普通手动任务按所选类别及地区轻量收集新消息和更新，不自动逐条严格复核旧资源。资源详情或线索工作台的“按需核验”只针对指定资源读取公开政策页面，不执行发现搜索，也不调用候选 API。严格核验仍要求关键事实与实际读取的官方原文相符；绑卡本身不代表付费，实际付款条件仍排除。失败保留上次政策与成功时间，并展示原因。

简报按任务保存，可查看并下载 Markdown，同日多次任务各自保留。收集简报只列本次新增、实质变化、结束或恢复事件，包含来源、页面/摘要标识、时间含义和未核验说明；不每天重列所有待核验资源。无变化时明确说明。缺少额度或有效期不算收集失败；真实搜索、模型或存储失败仍如实记录，部分失败保留已收集结果。

资源、历史线索工作台保留确认、驳回、忽略、收藏和备注。“历史线索”只汇总尚无可追溯消息来源且人工判断仍为待处理的记录，已收录但未经核验的资源不计入来源待补数量。人工判断独立保存，不覆盖收集报告或核验证据；确认不等于政策核验。忽略的资源不参与后续收集、复核、消息流或简报，也不计入未完成事项，可重新打开。页面筛选只改变显示，任务页的临时类别和地区不修改每日默认范围。

“补齐存量消息”（`POST /api/messages/backfill`）先从已保存证据和历史工具结果恢复来源，仅对仍缺来源的资源使用当前配置的搜索与模型补找消息，不要求补齐额度、期限或逐字段官方证据。任务与收集、译文回填共用单写锁，重复运行跳过已收录资源；仍找不到来源的保留为“历史线索·来源待补”。从历史资料恢复的消息保留原首次发现时间，不包装成今天的新发现。旧记录、人工判断和核验信息均保留。

### 中文译文（机器翻译）

英文线索与消息的描述文本（标题、摘要、结束原因，以及消息内的额度、额度单位、刷新周期、限速、领取条件、有效期说明与地区限制）在收集后附加一份简体中文机器翻译，线索的失败原因同样处理；已是中文或“未说明”等占位的内容不再翻译。译文只附加、不替换：原文永久保留，页面上可展开对照。译文只读，统一标注“机器翻译，未经核验”；核验与证据一律以原文为准。提供商/服务品牌名、资源详情的政策字段、来源标题与证据引文、人工备注不翻译。

翻译复用已配置的唯一模型（`model`、`model_api_key_env`、`model_base_url`），不新增服务、密钥或设置项；按原文缓存，原文未变不重译。翻译失败或返回为空时保留原文、译文留空，收集任务照常成功。译文不参与去重与实质变化判定。

译文覆盖线索页、首页“消息动态”与简报：页面上有译文时中文在前、原文折叠可展开；简报双语自包含，译文在前、原文紧随，已核验政策段保持原文。线索页提供“回填译文”按钮，对已保存的英文内容发起幂等回填任务（`POST /api/translations/backfill`），进度在任务详情查看；回填与收集共用单任务约束，忙碌时拒绝并说明原因。

## 定时与数据目录

默认每天本地时间 `09:00` 轻量收集全部类别和全球资源；可修改 `schedule_time`、`default_scope`，或设置 `schedule_enabled = false`。程序必须保持运行；应用不负责开机、唤醒电脑或在退出后执行。

错过执行时刻后，下次启动只针对最近一个应执行日期补跑一次，不按离线天数逐日生成历史日报。同一天已有结束的定时或补跑任务（包括部分完成和失败）不会因重启反复补跑；需要重试时可手动发起。第一次在当天计划时刻之前启动不会虚构过去的任务。手动任务不占用或修改每日默认配置。

手动、定时与补跑共用跨进程单写锁；研究运行时新的任务会得到忙碌原因，调度延后尝试。应用另持有进程生命周期锁，防止第二实例同时恢复未完成任务或写入同一目录。请勿让外部脚本直接并发修改资源库或 Memory。

默认 `data_dir = "data"`，业务数据保存在该目录下：

- `radar.sqlite3`：资源、收集消息及活动事件、核验证据、重要变化、任务及定时执行记录；人工判断另存于 `resource_reviews`、`user_actions` 表，发现线索存于 `lead_discoveries` 表。
- `briefings/<任务标识>.md`：每次任务独立的 Markdown 简报。
- Harness Memory 与工具输出目录：研究笔记、来源线索与受控工具输出，均限制在配置的数据目录内。
- `application.lock`、`research.lock`：应用实例与研究写入锁；锁文件存在本身不表示任务仍在运行。

数据库以 `PRAGMA user_version` 记录结构版本，打开时按顺序执行幂等迁移步骤。已有的 `radar.sqlite3` 会就地升级，不需要删除或重建；追加消息与活动历史存储，保留既有资源、原始证据、任务、变化、人工判断、设置及简报。旧记录优先从已保存的真实来源恢复消息，缺失部分可用“补齐存量消息”定向补搜；不为无来源线索编造出处，也不把历史研究笔记的转述冒充网页原文。

业务资源身份和历史比较使用结构化数据库，不能只靠 Memory 是否“记得”。重启后仍可查询已经保存的资源与简报。运行中异常终止的任务在独占启动恢复时标为失败；不会伪造成功。

## 单实例部署（k3s）

应用是单实例、单写者程序，只能以单个 Pod 运行：使用 `Recreate` 更新策略，副本数为 1，不要让滚动更新或水平扩容同时启动两份进程。`/data`（即 `data_dir`）挂在一个 `local-path` 的 `ReadWriteOnce` PVC 上；SQLite 数据库与锁文件都要求本地卷，不能把该目录放在 NFS 或其他网络文件系统上。Pod 重启会中断服务并由启动恢复处理，属于预期行为。

备份使用 SQLite 的 backup API 获取运行时一致副本，例如 `sqlite3 data/radar.sqlite3 ".backup 'backup.sqlite3'"`，不要直接复制正在写入的数据库文件。备份要与 `AIFREERADAR_SECRET_KEY` 分开保存：数据库中的设置密钥没有主密钥无法解密，两者放在一起等于把明文密钥一并备份。恢复时同时提供数据库与主密钥。

访问只通过 `kubectl port-forward` 转发到本机回环地址。Ingress 或公网暴露必须先有身份认证，当前版本未实现，不要直接暴露。

## 框架与安全边界

依赖固定为 `pydantic-ai-harness[researcher,anthropic]==0.66.0` 与 `pydantic-ai-slim[openai]==2.66.0`，完整解析版本见 `uv.lock`。实施环境实际安装 Python 3.12.13，并检查了上述版本的本地 API。

这一版本的 stock `Researcher` 会自行组合搜索与回退；本项目使用同一框架的实际 Agent 与 Harness Memory 组合，加入显式搜索、原文读取和结构化输出，保证只使用配置的搜索服务。研究 Agent 不具备通用 Shell、任意代码执行或项目源码编辑工具。

Windows 上该版本的 `LocalWorkspaceBackend` 依赖 POSIX 命令，不能作为本机 FileStore 后端。应用使用限制在 `data_dir/memory` 的文件型工作区：虚拟 POSIX 路径，拒绝目录穿越和符号链接逃逸，并且没有 `run` 命令，因此不是可执行命令的工作区，FileStore 不会调用 `mv`。写入仍用临时文件加 `os.replace` 在同一卷上替换。每个 Memory 目录只允许一个写入者，不能当作资源库或多写者数据库。

原文读取仅接受公开 HTTP(S) 来源，拒绝本地、私有地址和指向这些地址的重定向；研究工具不会访问本机管理端点。Web 固定本机监听，并校验 Host / 写入请求 Origin。响应使用 `Referrer-Policy: same-origin`，同源表单会带上真实 Origin；`no-referrer` 会让浏览器把 Origin 发成 `null`，从而误拒本机提交。跨站来源、字面量 `null` 和 `Sec-Fetch-Site: cross-site` 仍会拒绝。模型内容在页面中转义。不要通过端口转发或反向代理把本应用公开到网络。

直连来源复用同一个抓取器，继承上述地址、端口与内容类型限制，并额外遵守 robots.txt 与每域约 1 请求/秒的限速。

## 验证命令

需求说明第 10 节列出本次产品行为的验收条件。以下为开发验证命令，不表示本次改动已执行或通过；实际结果以运行记录为准。验证应使用隔离临时数据，不修改个人资源库，也不需要付费模型研究。

```powershell
uv run pytest
uv run ruff check .
uv run pyright
pnpm --dir frontend api:check
pnpm --dir frontend typecheck
pnpm --dir frontend build
```

覆盖率评测（可选，真实模型与真实网络，只读）：先运行 `uv run python scripts/coverage_eval.py --dry-run` 校验 `benchmark/seed_targets.json` 与配置，再运行 `uv run python scripts/coverage_eval.py` 生成 `data/tmp-stats/coverage-<时间>.md`；评测不写入资源库，也不触发正式任务。真实模型与搜索服务可能收费，正常开发验收无需运行此评测。搜索不保证穷尽，来源报告与官方政策都可能随后变化。
