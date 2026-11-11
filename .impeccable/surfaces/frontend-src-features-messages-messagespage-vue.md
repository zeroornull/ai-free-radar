---
version: 1
slug: "frontend-src-features-messages-messagespage-vue"
primary_target: "frontend/src/features/messages/MessagesPage.vue"
related_targets: ["frontend/src/features/resources/ResourcesPage.vue","frontend/src/features/resources/ResourceDetailPage.vue","frontend/src/features/leads/LeadsPage.vue","frontend/src/features/tasks/TasksPage.vue","frontend/src/features/tasks/TaskDetailPage.vue","frontend/src/features/briefings/BriefingsPage.vue","frontend/src/features/briefings/BriefingDetailPage.vue","frontend/src/features/settings/SettingsPage.vue"]
---

# AIFreeRadar 全站期刊目录

Mode: Operate（消息、资源、线索、任务、设置）；Read（简报正文）。
Scope: 替换所有现有页面的视觉语言；保留业务行为、原文、来源证据、未核验状态和本机数据边界。

## Direction contract

THESIS: 将免费 API 消息组织为可扫描、可追溯的期刊目录；每条消息以题名、摘要、事实和引文形成目次行。

OWN-WORLD: 浅纸底、深墨字、酒红链接；衬线正文搭配无衬线控件及等宽时间与标识。双线刊头、细横线、方角，无阴影或光晕。Source Serif 4、Libre Franklin、Roboto Mono 均自托管。

STORY: 先看最近收集与事件数，按类别筛选，读题名和免费条件，再展开全文、原文与来源；资源登记、任务记录、简报和设置延续同一体系。

FIRST VIEWPORT: 顶部刊头与横向导航；收集时间及数量紧随其后，页标题和筛选位于目录上方。桌面消息采用序位、正文、状态三列；长内容通过原生 disclosure 保留完整阅读路径。

FORM: 选择第二手 assigned 方案「期刊目录 / Journal Issue」。seed:8eb3105ba118cb94。决策草图 .impeccable/mocks/decision/v2-assigned.html 为代码构建的视觉参考；正式页面使用真实数据，完整条件与证据优先于草图的短样例行高。

SIGNATURE: 引文与正文共用目次行，全文、译文原文和来源证据逐层展开；移动端状态移至标题上方，事实纵向排列，导航自然换行。

## Verification evidence

六个主页面已在 1440、1280、390px 检查，无文档横向溢出；资源、任务、简报详情在 1440 与 390px 检查。截图位于 .impeccable/review/final-*.webp。浏览器连接本机真实数据库：33 条消息、36 项资源。typecheck 和生产 build 通过。

设计检测仅报告 Roboto 名称的通用字体警告；Roboto Mono 是所选草图已明确使用的数据字体，因此保留。
