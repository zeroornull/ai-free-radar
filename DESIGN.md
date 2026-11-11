---
name: AIFreeRadar
description: 浅纸、深墨与酒红引文构成的期刊式界面
colors:
  paper: "#faf9f5"
  ink: "#1b1a17"
  ink-hover: "#41423e"
  wine: "#8c2f39"
  wine-hover: "#532029"
  wine-soft: "#f3e9e8"
  subtle: "#f0ede5"
  text-secondary: "#5c5e63"
  text-tertiary: "#66665f"
  border: "#d9d5cb"
  border-strong: "#aaa69b"
  success: "#3f5d4e"
  success-bg: "#edf1ec"
  success-border: "#d2ded3"
  warning: "#684719"
  warning-bg: "#f4efe2"
  warning-border: "#e2d5b7"
  error: "#792833"
  error-bg: "#f5eae7"
  error-border: "#e8ceca"
typography:
  display:
    fontFamily: '"Source Serif 4", "Songti SC", "Noto Serif CJK SC", "SimSun", serif'
    fontSize: "clamp(1.65rem, 1.4rem + 0.7vw, 2rem)"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "-0.015em"
  headline:
    fontFamily: '"Source Serif 4", "Songti SC", "Noto Serif CJK SC", "SimSun", serif'
    fontSize: "1.3rem"
    fontWeight: 600
    lineHeight: 1.3
  title:
    fontFamily: '"Source Serif 4", "Songti SC", "Noto Serif CJK SC", "SimSun", serif'
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: '"Source Serif 4", "Songti SC", "Noto Serif CJK SC", "SimSun", serif'
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: '"Libre Franklin", "Source Han Sans SC", "Microsoft YaHei", sans-serif'
    fontSize: "0.8125rem"
    fontWeight: 600
    lineHeight: 1.4
  citation:
    fontFamily: '"Roboto Mono", "Cascadia Code", Consolas, monospace'
    fontSize: "0.6875rem"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  sm: "0"
  md: "0"
  lg: "0"
  xl: "0"
  pill: "0"
spacing:
  "1": "0.5rem"
  "2": "1rem"
  "3": "1.5rem"
  "4": "2rem"
  "5": "3rem"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "0.45rem 0.85rem"
  button-primary-hover:
    backgroundColor: "{colors.ink-hover}"
  button-outline:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "0.45rem 0.85rem"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.wine}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "0.45rem 0.85rem"
  native-select:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0.45rem 0.7rem"
    width: "100%"
  navigation:
    textColor: "{colors.text-secondary}"
    padding: "0.75rem 0"
  chip:
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.sm}"
    padding: "0.1rem 0.35rem"
  flat-panel:
    backgroundColor: "transparent"
    rounded: "{rounded.sm}"
    padding: "1.25rem 0"
  message-row:
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0.65rem 0"
---

# Design System: AIFreeRadar

## Overview

**Creative North Star: "期刊目录 / Journal Issue"**

浅纸底承载深墨正文，酒红用于链接、焦点与少量事件标记。衬线题名和正文、无衬线控件、等宽引文共同形成可扫描、可追溯的阅读秩序。

界面以双线刊头、细横线和方角建立层次。内容密度来自排版与分隔，长内容保留原生展开路径；页面流程与具体首屏构图见对应 surface brief。

**Key Characteristics:**

- 浅纸、深墨、酒红的克制配色。
- 三种自托管字体按阅读、操作、数据分工。
- 方角、横线、无阴影与无光晕。
- 连续记录行与原生 disclosure。

## Colors

### Primary

酒红 `wine` 承担链接、焦点和事件强调；`wine-hover` 用于链接悬停。主要提交按钮采用深墨 `ink` 与纸色文字，悬停转为 `ink-hover`。源码中 `blue-*` 是沿用的变量名，实际对应酒红色阶，不代表蓝色视觉方向。

### Neutral

`paper` 同时用于页面与普通表面；`subtle` 用于轻提示和悬停。`ink` 用于正文，`text-secondary` 用于辅助描述，`text-tertiary` 用于元数据。`border` 分隔记录，`border-strong` 划分区块与控件边界。

### Semantic

`success`、`warning`、`error` 分别搭配同名前缀的背景与边框表达结果状态。状态徽标依靠文字与边框；提示条可以使用语义浅底。状态含义由业务数据决定，不以装饰色推导核验结论。

## Typography

Source Serif 4 负责题名与正文，Libre Franklin 负责导航、按钮、标签和表单，Roboto Mono 负责序位、引文与来源标识。三者均由 `/fonts/` 的 WOFF2 文件自托管；中文使用 frontmatter 中的回退栈。

`display` 是页面标题；`headline` 是区块标题；`title` 是消息行题名，普通记录标题另用 1.1875rem / 1.4。`body` 是全局正文，消息摘要使用 0.875rem / 1.55。`label` 表达操作层级，`citation` 表达来源层级。时间与数值使用等宽数字特性，不要求所有正文数字改成等宽字体。

## Layout

全局壳居中，宽度为 `min(100%, 96rem)`，横向留白使用 `clamp(1rem, 2.78vw, 2.5rem)`。刊头为粘性定位，以双线下边界分隔内容；主区上下留白为 1.25rem 与 2rem。基础间距采用 frontmatter 的五步尺度，组件保留源码中的紧凑局部间距。

75rem 以下刊头换行并隐藏副标；48rem 以下导航独占一行并自然换行，事实表转为单列。筛选表格通过 `repeat(auto-fit, minmax(min(100%, 11rem), 1fr))` 自适应。消息目次行的专用断点是 1099px 与 599px：状态移到正文上方，窄屏事实纵排；这不是其他页面必须照搬的构图。

## Elevation & Depth

所有阴影 token 均为 `none`。纸面、细边界、留白与字重承担层级；悬停通过底色或文字变化表达，焦点使用清晰轮廓，不使用发光效果。全局 `:focus-visible` 为酒红 3px 实线，偏移 3px。状态过渡为 `150ms ease-out`；减少动态偏好下过渡与动画时长降至 0.01ms。

## Shapes

所有圆角 token 均为零，包括名称仍为 `pill` 的 token。按钮、徽标、表单和容器均为方角；刊头使用 3px 双线，记录与普通分隔使用 1px 细线。容器以开放横线表达章节，不依靠悬浮卡片轮廓。

## Components

### Buttons

主要、描边、幽灵按钮共享紧凑无衬线标签与方角。页面 `.button` 高度至少 2.5rem，内距见 frontmatter；主要按钮深墨填充，描边按钮透明底，幽灵按钮酒红文字且边框透明。悬停轻改底色，禁用透明度为 0.5；键盘焦点沿用全局轮廓。底层 Button 还提供 secondary、destructive、link 等 API 及尺寸，按既有使用场景保留，不把所有页面按钮强制改成同一高度。

### Inputs / Fields

原生选择框保持原生交互。页面 `.native-select` 使用纸底、1px 控件边框、至少 2.5rem 高和 0.875rem 无衬线字体；标签为 0.8125rem、600 字重。底层 NativeSelect 默认高 2.25rem，带内联下箭头；页面类可覆盖尺寸。焦点沿用清晰外轮廓。

### Navigation

横向文字导航以酒红底线和深墨字重标识当前页，`aria-current="page"` 保留语义。默认辅助色文字，悬停酒红。窄屏自然换行，不隐藏导航项。

### Chips

小型方角文字标记使用细边框、辅助色与紧凑内距；成功、待处理和失败采用语义文字与边框，不使用胶囊外形。引文条中的标记去掉边框和内距并继承引文排版。

### Cards / Containers

平面区块使用上方细线与垂直留白。页面 panel 使用 1.25rem 垂直内距；底层 Card 为透明背景、方角、无阴影，header/content 横向内距归零。两者按既有结构使用，不叠加视觉外壳。

### Signature Row

消息目录行由序位、正文与状态构成，桌面网格为 `2.5rem minmax(0, 1fr) 7rem`，间隔 1rem。题名、摘要、事实与等宽引文依次展开；长摘要、条件与原文保留可访问的原生 details/summary。不要把示例短文行高固定为真实内容高度。

## Do's and Don'ts

### Do:

- **Do** 使用纸底、深墨正文和酒红链接，并保留语义状态文字。
- **Do** 按阅读、操作、数据角色分配三种自托管字体。
- **Do** 使用细横线、方角和留白区分层级。
- **Do** 保留键盘焦点、原文和完整内容的展开入口。

### Don't:

- **Don't** 添加圆角、阴影或光晕。
- **Don't** 因 `blue-*` 变量名而重新引入蓝色主题。
- **Don't** 以固定行高或截断移除来源、条件和原文的阅读路径。
