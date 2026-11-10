# AIFreeRadar

本机使用的免费 AI API 研究应用：通过可配置的模型与搜索服务发现线索，读取原始网页，整理官方免费政策，并保存完整资源库和带引用的增量简报。覆盖文本、图像、视频、语音、Embedding、Rerank 六类 API。

“有效 / 已核实”只表示公开免费政策符合收录条件。所有推荐均为**未实测调用**，网络访问为**未实测**；应用不会自动注册、登录、领取权益或调用候选 API。项目不会预置伪造的官方资源，首次资源清单由真实研究生成。

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

打开 <http://127.0.0.1:8765>。不必激活 `.venv`；`uv run` 使用项目环境。程序仅监听 `127.0.0.1`，不提供注册、登录、局域网或公网访问。关闭终端或按 Ctrl+C 后停止服务与调度。

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

`/settings` 页面展示合并后的生效值和每个字段的来源（数据库、`config.toml` 或默认值），并允许修改模型、模型端点、密钥变量名、搜索服务、定时开关与时间、默认范围。页面只写数据库，不改动 `config.toml`；`host`、`port`、`data_dir` 只读。保存时先整体校验，再在单个事务内写入，版本不一致返回冲突，需刷新后重试。保存与探测是两步，探测失败不会写库。正在进行的研究任务使用启动时快照，页面修改只影响之后的运行与触发点；调度时间或开关的变更不补跑当天。

密钥优先级：数据库中的加密密钥（按当前 `model_api_key_env` / `search_api_key_env` 对应的变量名匹配）> `config.toml` 中的 `model_api_key` / `search_api_key` 明文 > 同名环境变量（含 `.env`）。页面写入的密钥以 AES-256-GCM 加密后存库，主密钥来自 `AIFREERADAR_SECRET_KEY`。页面从不回传密钥明文，只返回是否已配置及来源；清空密钥请提交 `null`，空字符串不是有效值。

### 开发代理

前端开发服务器（`pnpm --dir frontend dev`，监听 `127.0.0.1:5173`）把 `/api` 与 `/health` 代理到后端，并把代理请求的 `Origin` 改写为后端地址，因此开发时默认无需任何环境变量：

```powershell
uv run aifreeradar          # 终端一：后端，默认 127.0.0.1:8765
pnpm --dir frontend dev     # 终端二：开发服务器
```

浏览器访问 <http://127.0.0.1:5173>，编辑即时热更新，写请求经代理后按同源处理。后端不在默认端口时设置 `AIFREERADAR_API_TARGET`（必须是 127.0.0.1/localhost 的 http 回环源，不允许账号、路径、查询或片段）。只有绕过代理、从浏览器直接向另一端口发写请求时，后端才需要 `AIFREERADAR_DEV_ORIGIN=http://127.0.0.1:5173`；未设置时这种跨端口直发一律 403。代理只存在于开发服务器，正式同源托管与生产构建不受影响。

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
port = 8765

# [direct_sources]
# text = ["https://platform.openai.com/docs/pricing"]
# image = ["https://platform.stability.ai/pricing"]

[default_scope]
categories = ["text", "image", "video", "speech", "embedding", "rerank"]
region = "global"
```

`region` 只能取 `global` 或 `china`，类别至少选择一项。`china` 指研究中国大陆官方注册和使用政策，不表示实际网络可达。官方未说明的线索保留为待核实。

`direct_sources` 是可选的本机配置，按类别列出官方免费政策入口页（例如 pricing 或文档首页）。它只能写在 `config.toml`，不能通过 `/settings` 编辑；键必须是上面的类别名，值必须是绝对 HTTP(S) 地址。留空或省略即关闭直连来源。

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
port = 8765

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

例如选择 Exa 就设置 `search_provider = "exa"` 和 `search_api_key_env = "EXA_API_KEY"`。请求发往 `https://api.exa.ai/search`，只要高亮片段作为发现线索，不把 Exa 摘要当作官方依据。搜索请求失败或密钥缺失时记录失败，**不会回退到 DuckDuckGo、原生模型搜索或另一搜索服务**。服务可用性、限额和费用由相应账号与提供商决定。

每个类别的发现段在交给研究 Agent 之前，先执行 6 条固定基线查询（3 条中文、3 条英文），计入每段 16 次搜索预算，Agent 仍可在此之上追加查询；基线查询失败只记录失败，不回退搜索服务。若配置了 `direct_sources`，同一发现段还会抓取该类别的官方入口页，遵循 robots.txt 与每域约 1 秒的间隔，只跟进一跳链接，合计最多 8 个入口页，并与 Agent 共用每段 32 次抓取预算。入口页与白名单域名下的链接记为官方可核验线索，其余只作发现线索。本轮线索（来源类别、发现方式、搜索服务与查询词）写入数据库，在简报与待核实线索中标注。

## 使用与记录含义

资源库可按类别、中国大陆政策及资源状态筛选，详情展示关键政策、来源、核查时间和重要变化历史。显示筛选不改变研究配置。任务页可临时选择类别与地区，手动任务的选择不修改每日默认范围。简报历史按任务保存，可查看并下载对应 Markdown；同一天的多次任务各自保存文件。

收录门槛是领取及使用免费权益需要支付的金额为零。持续免费与零支付限时赠额分别记录；付款、充值或绑定支付方式才能获得的权益不进入正式推荐。额度保留原单位，不把 Token、请求次数、图片张数或时长混为一谈。同一平台不同 API 服务各自记录政策。

- 资源状态：`active` 有效、`pending` 待核实、`expired` 已失效。
- 本次核查结果：`success` 成功、`failed` 失败、`incomplete` 未完成，与资源状态分别记录。
- 免费形式：`ongoing` 持续免费、`limited` 限时免费、`unknown` 待核实。
- 中国大陆政策：`supported` 官方支持、`unsupported` 不支持、`unknown` 未核实。中文页面或第三方推荐不能单独证明官方支持。
- 任务状态：`running` 运行中、`success` 成功、`partial` 部分完成、`failed` 失败。
- 人工判断：`open` 未处理、`confirmed` 已确认、`rejected` 已驳回、`ignored` 已忽略；另可收藏与备注。

正式推荐需要可追溯的官方依据，关键字段关联引文及核查时间；社区内容只作为线索。应用核对引文是否出现在实际读取的网页、来源域与对应政策是否相符，模型声称“官方”不能替代来源验证。未知字段保留“未说明 / 未核实”。网页打不开、网络或模型失败时保留上次已确认政策，记录失败原因及最后成功核查时间，不能据此判定已失效。范围外资源也不会因没有被本次检查而失效。

首次简报展示本次范围内的初始清单；以后只展示新增、重要变化、失效和恢复，未变化的资源不会反复推荐。无变化时明确说明“本次无新增或变化”。待核实、核查失败与未完成事项单独列出；部分调查失败时保留已核实结果，任务标为部分完成。

简报的“待核实线索”会标注每条待核实资源的发现来源：官方目录直连、搜索查询词或目录链接；来源只是线索，官方结论仍以实际抓取的官方页面引文为准。

待核实与本次核查失败的资源汇总在“待核实线索”页，可按状态筛选并逐条处理：确认、驳回、忽略、收藏、写备注，或只重查这一条记录。资源详情新增人工判断面板，与研究得到的证据并排展示；判断状态、收藏和备注保存在独立表中，研究任务不会覆盖人工判断，判断也不会修改额度、有效期、支付条件、官方链接或资源状态等证据字段。忽略表示不再复查：该资源此后不会被手动、定时或补跑任务重新核查，不进入简报的任何栏目，也不计入未完成事项；重新打开后恢复处理。单资源重查只重新读取该资源的公开政策页面，不执行发现搜索，也不调用候选 API。

## 定时与数据目录

默认每天本地时间 `09:00` 研究全部类别和全球资源；可修改 `schedule_time`、`default_scope`，或设置 `schedule_enabled = false`。程序必须保持运行；应用不负责开机、唤醒电脑或在退出后执行。

错过执行时刻后，下次启动只针对最近一个应执行日期补跑一次，不按离线天数逐日生成历史日报。同一天已有结束的定时或补跑任务（包括部分完成和失败）不会因重启反复补跑；需要重试时可手动发起。第一次在当天计划时刻之前启动不会虚构过去的任务。手动任务不占用或修改每日默认配置。

手动、定时与补跑共用跨进程单写锁；研究运行时新的任务会得到忙碌原因，调度延后尝试。应用另持有进程生命周期锁，防止第二实例同时恢复未完成任务或写入同一目录。请勿让外部脚本直接并发修改资源库或 Memory。

默认 `data_dir = "data"`，业务数据保存在该目录下：

- `radar.sqlite3`：资源、证据、重要变化、任务及定时执行记录；人工判断另存于 `resource_reviews`、`user_actions` 表，发现线索存于 `lead_discoveries` 表。
- `briefings/<任务标识>.md`：每次任务独立的 Markdown 简报。
- Harness Memory 与工具输出目录：研究笔记、来源线索与受控工具输出，均限制在配置的数据目录内。
- `application.lock`、`research.lock`：应用实例与研究写入锁；锁文件存在本身不表示任务仍在运行。

数据库以 `PRAGMA user_version` 记录结构版本，打开时按顺序执行幂等迁移步骤。已有的 `radar.sqlite3` 会就地升级到当前版本，不需要删除或重建；升级只追加人工判断与发现线索相关表，不改变既有资源、任务与简报记录。

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

## 验收与验证范围

需求说明第 10 节有 17 个验收场景。2026-11-10 在本机执行 `uv run ruff check .`、`uv run pyright` 和 `uv run pytest -q`：Ruff 与 Pyright 均无错误；pytest 为 299 通过、1 跳过。跳过的是 Windows 上无法创建符号链接时的 Memory 路径逃逸测试，不是功能未实现。下表是场景与测试的对应关系。

| 场景 | 对应测试 |
|---|---|
| 首次发现 | `test_official_zero_payment_policy_is_active_with_units_sources_and_times`、`test_real_agent_fetches_and_validates_official_policy`、`test_manual_http_flow_repeated_categories_unique_downloads_and_restart` |
| 免费门槛 | `test_paid_binding_or_unknown_payment_is_not_formal_recommendation`、`test_unknown_key_conditions_are_not_inferred_free_from_evidence`、`test_limited_relative_validity_is_active_without_inventing_absolute_expiry`、`test_limited_offer_preserves_source_validity_without_invented_date` |
| 多类别 | `test_all_six_categories_preserve_their_quota_units`、`test_same_provider_has_six_distinct_api_policies_even_with_shared_name_and_links`、`test_failed_category_preserves_other_real_agent_result` |
| 重复研究 | `test_checked_time_and_evidence_order_do_not_duplicate_history_or_recommendation`、`test_names_and_links_can_change_without_losing_stable_resource_identity`、`test_empty_increment_briefing_explicitly_reports_no_change` |
| 政策变化 | `test_substantive_changes_keep_before_after_time_and_field_evidence`、`test_confirmed_expiry_and_restoration_have_ordered_durable_history` |
| 核查失败 | `test_failed_or_incomplete_recheck_preserves_last_confirmed_policy`、`test_failure_preserves_confirmed_policy_and_persists_report_after_reopen`、`test_fetch_failure_never_creates_verified_policy`、`test_missing_matching_recheck_is_explicit_and_scoped` |
| 待核实 | `test_unverified_or_thirdparty_evidence_stays_pending`、`test_each_official_key_fact_requires_its_own_evidence`、`test_real_agent_rejects_unproven_official_evidence`、`test_documentation_link_must_itself_be_fetched` |
| 人工判断 | `test_leads_filter_sort_default_review_and_open_leads_count`、`test_resource_review_round_trip_audit_and_idempotency`、`test_single_resource_scope_skips_discovery_and_rechecks_only_target`、`test_recheck_starts_single_resource_run_and_appears_in_openapi` |
| 忽略语义 | `test_ignored_resource_is_never_researched_or_marked_missing`、`test_failed_run_does_not_mark_ignored_resource_incomplete`、`test_scheduled_run_honors_ignored_resources`、`test_ignored_resource_does_not_mask_missing_peer_or_scope_isolation` |
| 地区证据 | `test_china_conclusion_requires_official_region_evidence`、`test_official_china_policy_does_not_claim_network_testing`、`test_china_briefing_keeps_unclear_official_region_as_separate_lead`、`test_mainland_support_requires_registration_and_api_use_in_fetched_text` |
| 范围隔离 | `test_category_scope_preserves_outside_records_even_if_returned_or_not_rechecked`、`test_manual_scope_loads_only_scoped_history_without_changing_defaults`、`test_resource_filters_cover_all_categories_policies_and_statuses_without_changing_defaults`、`test_missing_expected_rechecks_marks_partial_and_preserves_outside_scope` |
| Web 使用 | `test_manual_http_flow_repeated_categories_unique_downloads_and_restart`、`test_resource_detail_shows_evidence_changes_previous_success_and_failure`、`test_model_strings_and_markdown_never_create_executable_html_or_unsafe_links`、`test_foreign_host_or_origin_cannot_trigger_research` |
| 定时执行 | `test_startup_after_due_catches_up_once_and_same_day_restart_is_idle`、`test_finished_schedule_statuses_do_not_rerun_on_restart`、`test_fresh_start_before_due_waits_for_normal_local_due_time`、`test_multiple_offline_days_catch_up_only_latest_due_day`、`test_custom_schedule_and_default_scope_are_used`、`test_disabled_schedule_never_runs_even_after_due_or_offline_gap`、`test_manual_busy_defers_schedule_without_consuming_due_day` |
| 写入互斥 | `test_start_is_nonblocking_persisted_and_same_manager_rejects_overlap`、`test_separate_managers_share_one_writer_lock`、`test_external_process_filelock_blocks_without_creating_a_run`、`test_close_cancels_research_persists_failure_and_releases_writer`、`test_busy_http_task_returns_conflict_and_does_not_spawn_another_run`、`test_second_app_lifespan_cannot_recover_another_apps_running_task` |
| 持久化 | `test_reopening_database_retains_resources_runs_evidence_history_and_same_day_reports`、`test_same_day_runs_have_unique_briefings_and_survive_reopen`、`test_real_harness_memory_roundtrip_survives_new_researcher`、`test_lifespan_recovers_interrupted_record_with_schedule_disabled`、`test_legacy_database_upgrades_in_place_and_second_open_is_a_noop`、`test_reopening_a_migrated_database_keeps_review_state_and_audit` |
| 配置遵从 | `test_selected_model_requires_its_own_credential`、`test_compatible_model_uses_named_endpoint_not_openai`、`test_selected_search_requires_explicit_credential`、`test_exa_search_calls_only_exa`、`test_missing_model_key_fails_before_external_research`、`test_missing_selected_search_key_fails_with_real_testmodel`、`test_configured_search_failure_is_reported_by_real_tool_loop`、`test_selected_search_http_failure_never_calls_another_provider` |
| 部分完成 | `test_mixed_category_failure_keeps_verified_records_and_partial_status`、`test_failed_category_preserves_other_real_agent_result`、`test_failed_and_partial_http_tasks_have_readable_downloadable_reports` |

另有技术边界测试，不属于第 10 节的 17 行：本地与私有地址、重定向 SSRF、符号链接逃逸，以及 Windows 上真实 Harness FileStore 的读写隔离。测试使用隔离临时目录；外部模型与 HTTP 只在传输边界替换，Agent、Memory 和 FileStore 使用实际实现。

```powershell
uv run pytest
uv run ruff check .
uv run pyright
```

覆盖率评测（可选，真实模型与真实网络，只读）：先运行 `uv run python scripts/coverage_eval.py --dry-run` 校验 `benchmark/seed_targets.json` 与配置，再运行 `uv run python scripts/coverage_eval.py` 生成 `data/tmp-stats/coverage-<时间>.md`；评测不写入资源库，也不触发正式任务。

同一环境用 Chrome 在 320px 宽度打开 `http://127.0.0.1:8765`：资源库类别筛选只改变地址，任务页仍显示全部默认类别；只选文本生成的手动任务进入任务详情，范围是“文本生成 · 全球资源”，每日默认计划仍是六类和全球。未配置 `OPENAI_API_KEY` 时任务状态为失败，原因写明缺少该变量，并生成可查看、可下载的 Markdown。任务详情页的 WCAG 2.2 A/AA 自动检查为 0 项违规。带真实密钥的外部模型研究**尚未执行**；上述失败只证明缺密钥时不会静默换服务。搜索不保证穷尽，政策也可能在核查后变化。
