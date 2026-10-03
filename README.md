# ZJU Study Workbench

本地课程资料与电子笔记工作台。采用苹果风格布局与纸页阅读区，连接已有 zju-scholar，并将课次、作业状态与笔记 Git 版本放在同一个界面。

这是独立项目，不复制原 ZLA 前端、不移动原课程材料，也不依赖固定盘符。学校平台的提交状态与本地 Git commit 分开保存。

## 运行

需要 Python 3.11+、Node.js 22.12+ 和 Git。构建后的界面没有前端运行依赖；Python 服务使用标准库，PDF 提取及密钥存储是两项小型依赖。

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
npm ci
npm run build
.venv/Scripts/python -m server --demo
```

访问终端显示的本地地址。Windows 构建后也可用 `./start.ps1 -Demo`；正式使用 `./start.ps1`，会自动打开浏览器。`--demo` 使用合成资料，不连接学校、不调用真实模型。正式运行去掉 `--demo`，在设置中填写笔记根目录、zju-scholar 源码路径与其 Python 路径。源码目录须保持原位，沿用原来的系统密钥环登录；账户登录仍在 zju-scholar 的私密终端里完成。

```sh
python -m server --data-dir /path/to/private-app-data --port 8765
```

默认本机状态在 `~/.zju-study-workbench/`；`--data-dir` 可替换。不要将它放入公有仓库。下载根目录、笔记根目录、AI 路由均为配置项。优先沿用 `courses/<课程>/<课次>/materials`，课次未确认的资料留在课程级。

## 设计与范围

- 资料库：扫描课程/课次、预览文本和 PDF、明确选择参考资料及页码。文件不存在、未检查、未提供是不同状态。
- 采集：通过 zju-scholar 子进程下载课程课件、单课次智云 PPT、字幕和录像；显式映射两个平台的 ID，不按同名猜课程。
- 笔记：本地提取所选文字，使用可配置的 OpenAI 兼容 API、Pi 或 Codex 单次整理；先存草稿，确认后保存。支持 Markdown 基础排版和 LaTeX；安装 XeLaTeX 后可双遍编译，失败时保留原 PDF。保存并 Git 提交按钮只提交源稿，PDF 与样式副本仍由原笔记项目的工作流管理。
- 样式：生成 LaTeX 时沿用本课已有导言区；新课次可读取笔记库的 `templates/electronic-notes-template.tex`。需要 `note-style.tex` 时从本机笔记库模板复制，不修改已有副本。PDF 成功编译后仍需本人打开核对排版。
- 进度：作业个人提交状态缺失时保留未知；笔记分为待整理、草稿、待核对、完成。
- Git：显示真实 commit 与父节点；可将当前笔记单独提交。不会混入其他暂存改动，也不会自动 push 笔记仓库。

网页版只绑定 loopback。API 密钥保存到系统密钥环；课程资料、状态和草稿不进入代码仓库。模型调用由界面明确选择的资料和操作触发。工具不会替用户向学校提交作业。

## 可迁移性

前端仅 TypeScript + Vite，后端按文件库、平台桥接、AI、Git 四个边界组织。没有数据库服务、云端账户、桌面打包或供应商 SDK 依赖。适配器不加载旧应用 UI。共享此代码不代表获得共享教师材料、账号或教材的许可。

## 验证

```sh
npm run check
npm run build
python -m unittest discover -s tests -v
```

在线登录、真实下载、模型费用和账号订阅可用性必须在对应账户上单独验证。演示与离线测试不证明学校接口或模型服务在线可用。

API 初始地址 `http://127.0.0.1:8045/v1` 和模型名 `gemini-3.8-flash` 只是可修改的配置占位，请填写自己的 Anti-Gravity Tools 实际服务与模型映射。Pi / Codex 需预先安装并登录，本版通过受限单次 CLI 调用接入，未实现持续对话。

图片、扫描 PDF 与智云图片型 PPT PDF 需要先做外部 OCR；本版不内置 OCR，不会将无法提取文字的文件当作有效参考。老式 `.ppt` 需另存 PPTX / 可提取文字的 PDF。课次与平台 ID 显式关联，资料返回的目录名仍需本人核对。首次连接空资料库时，先在根目录创建 `courses/<课程名>/`，再在界面新增课次。

验收说明与三版设计对照见 [HTML 汇报](docs/acceptance-report.html)。

设计参考：[Awesome Design MD / Apple](https://github.com/VoltAgent/awesome-design-md/blob/main/design-md/apple/DESIGN.md)。平台能力参考：[zju-scholar](https://github.com/Lucent-Snow/zju-scholar)、[ZJU Learning Assistant](https://github.com/PeiPei233/zju-learning-assistant)。本仓库不包含上述项目源码，其许可证与本仓库独立。

Windows / Linux 自动检查模板位于 `docs/ci/check.yml`。当前发布令牌缺少 workflow 权限，模板尚未放入 `.github/workflows/`，远端 CI 未运行；如需启用，使用有对应权限的账户将模板复制进去。
