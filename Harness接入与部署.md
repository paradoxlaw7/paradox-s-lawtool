# 约定 × DeepSeek Harness：接入、部署与使用

本次新增v2.8质量核验流程，配套插件0.3.0、桥接1.2；以 [Agent升级说明_v2.8.md](Agent升级说明_v2.8.md) 为最新部署与使用说明。下方v2.6/v2.7验证记录为历史留存。

## 现在的运行方式

这版复用 Harness 当前会话的模型。选择你已登录并充值的 DeepSeek 账号模型后，分析、起草和修订使用该账号的额度。插件不读取账号凭据、不另建模型客户端、不向硅基流动发请求。网页负责材料、编辑、人工确认与版本归档。

不能把 Harness 登录转给普通网页作为模型服务。原有普通网页项目仍使用工作台原来的模型配置；在网页中授权改用 Harness 的项目，会阻止网页单独发起模型任务，避免重复调用和费用来源混淆。

## 已完成的本机安装

插件源目录为 `C:/Users/paradox/Desktop/[约定]/dsh-yueding-law`。已经通过官方 CLI 离线安装到当前 `desktop` profile，不需要再创建另一套 profile。当前安装使用本地链接，暂时保留此目录；本机已验证的 Harness 版本为 **0.2.1-rc.2**，本插件 manifest 锁定该版本。重启 Harness 后确认插件启用。

本机连接文件为 `C:/Users/paradox/.yueding-harness/connection.json`。已生成工作台专用随机访问凭证，未读取 DeepSeek 凭据，也未更改默认模型或会话。

## 你需要完成的上线操作

1. 先备份重要档案，确认 Render 的 DATA_DIR 位于持久化磁盘内。保留原有数据磁盘和工作台环境配置。
2. 解压 `约定_Render更新包_v2.8_Agent质量核验版.zip`，在 GitHub 仓库 `paradoxlaw7/paradox-s-lawtool` 的现有部署分支、仓库首页 Upload files，上传解压后的全部内容。尤其不要遗漏 **harness_bridge.py**、**knowledge.py**、**knowledge_seed.json** 和更新后的 **Dockerfile**；仅替换 server.py 会因为缺少模块而无法启动。
3. 在本机打开 `C:/Users/paradox/.yueding-harness/Render环境变量.txt`，复制里面的变量值。到 Render 的现有服务 → Environment，添加 **HARNESS_ACCESS_TOKEN**，填入同一值。它只是约定连接凭证，不是模型 API key，也不是网站口令。不要把这个文件上传 GitHub或发到聊天。
4. 保留原有 APP_PASSWORD、PUBLIC_ORIGIN 和存储配置。PUBLIC_ORIGIN 保持当前正式 HTTPS 网址。只使用 Harness 项目时可以不配置 SILICONFLOW_API_KEY；为了原有普通网页项目继续使用，不需要删除已有密钥。
5. 保存并部署。若 GitHub 提交后已自动开始部署，等待；否则选择 Manual Deploy → Deploy latest commit，等待状态 Live。
6. 重启 Harness，确认 `dsh-yueding-law` 已安装且启用，模型选择你已充值账号下的模型。先让它调用 `yueding_status` 检查连接。

本轮没有推送 GitHub，也没有更新 Render；无需购买新的服务器或更改域名解析。账户是否有余额及实际推理是否成功由 Harness 服务判断，本轮没有实际消耗你的模型余额来试跑。

## 处理新材料

在 Harness 输入：

> 请使用约定插件处理这份 PRD。先检查连接，导入材料，分析业务并列出需要确认的问题；我确认事实后，再起草服务协议和隐私政策。生成使用当前 Harness 会话模型。

当前插件提供 18 个原生工具。新版阶段顺序以Agent升级说明为准。模型先拿到阶段说明和 JSON 结构，再按分析、服务协议、隐私政策分别提交结果。中间失败时只修复本阶段，不把半份协议保存为成功。提交不确定时先查询任务，不自动重复推理。

业务事实须在插件返回的工作台链接中填写并由本人确认。起草后在网页编辑、逐项审阅并归档。插件不能替你确认、采纳或归档。后续在 Harness 提供业务变化和来源，生成基于最近定稿的候选修订，再到工作台审阅。

网页审阅清单的“讨论此项”会给出可复制到 Harness 的问题，不再从网页额外调用模型。Word 可从网页导出，也可以让插件导出到本机 `.yueding-harness/exports`。

## 继续已有项目

打开原有真实项目 → 设置 → **改用 Harness 账号模型** → 勾选授权并确认。材料、当前稿与历史定稿保留。然后回到 Harness 让插件列出项目或读取该项目编号。没有经过网页授权的旧项目不会对插件开放。

不要在有生成任务运行时切换。已归档项目的后续变化仍走候选修订，不覆盖旧定稿。连接凭证轮换会改变插件访问范围，因此应保留或备份本机连接配置，不要随意生成另一个值覆盖现有服务器值。

## 历史接入版验证记录与限制

- 69 项后端回归通过：外部结果结构校验、无服务器模型密钥流程、逐份生成、部分失败、并发修订检查、重试幂等、数据库提交失败回滚、唯一原文匹配、不可变定稿、人工授权和插件权限等。
- 9 项插件测试通过；已用本机真实 Harness SDK 验证 13 个工具及配置格式，并通过真实本机 HTTP 创建项目、导入长 PRD、提交受控分析结果和导出真正的 DOCX。
- 浏览器验证长 PRD、人工事实确认、两阶段起草、审阅问题转交、旧项目授权切换；没有网页模型任务请求，页面无脚本错误。
- 模型输出使用受控测试样例，不将这些测试称为真实账号推理或法律质量评测。现网仍需部署后用一个真实案例完成首轮验收。

目前网页仍是单工作区：持有网页口令的人可看到同一工作台的项目。插件令牌只限已创建或已授权的 Harness 项目，不等于企业多租户权限系统。材料和输出会进入你的 Harness 会话日志，并保存在工作台服务器中。

参考：[官方插件打包](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/publish.md)、[官方工具开发](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/tool.md)、[官方账号模型适配器](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/llm/llm-deepseek-account/README.md)。

## v2.7 知识库增量

本次新增知识库检索、候选审核和依据快照；部署与使用见 [知识库建设与采集指南.md](知识库建设与采集指南.md)。上面的69项及9项是v2.6历史接入版记录，本次增量测试见 test-results/knowledge-validation.json（本机报告，不打入生产包）。新版共16个工具，不需要新的模型密钥或连接凭证。
