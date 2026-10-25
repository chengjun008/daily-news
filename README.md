# GitHub 免费运行版：每天九点发新闻到微信

运行方式：GitHub Actions 定时启动 → 读取中新网公开 RSS → 整理24小时内国内、国际新闻 → Server酱投递到你的微信。个人电脑关机不影响运行，不需要小程序 AppID、独立服务器或大模型 API。

仓库：https://github.com/chengjun008/daily-news

**代码部署和微信绑定是两个步骤。只有保存有效密钥、绑定接收通道，并实际收到首次测试早报后，才算配置完成。** 本地源码测试通过不能替代 GitHub 上的实际运行与微信送达验证。

## 1. 绑定微信接收通道

1. 打开 https://sct.ftqq.com/ ，用自己的微信扫码登录 Server酱 Turbo。
2. 进入通道配置，按平台指引绑定当前可用的微信接收通道，并完成关注或授权。
3. 在 SendKey 页面复制 **SCT 开头**的密钥。本脚本不支持 SC3 的 sctp 密钥。
4. 保存到下面的 GitHub Secret，不要填入源代码、README、Issue 或聊天里。

Server酱当前免费额度为每天5条，本程序每天合并发送1条简报。免费 API 额度不代表所有通道都永久免费，具体可用的微信通道及其要求以账号后台显示为准。先验证试用期结束后仍可用的免费通道。

## 2. 保存 GitHub Secret

打开仓库：

https://github.com/chengjun008/daily-news/settings/secrets/actions

选择 **New repository secret**，填写：

| 输入框 | 填写内容 |
| --- | --- |
| Name | `SERVERCHAN_SENDKEY` |
| Secret | 第1步复制的 SCT 开头密钥 |

点击 **Add secret**。名称必须完全一致。这是仓库级 Secret，不要误建成 Repository variable 或仅绑定某个 Environment 的 Secret。设置成功后只能看到名称，看不到密钥明文，这是正常的。

## 3. 第一次手动测试

打开：

https://github.com/chengjun008/daily-news/actions/workflows/daily-news.yml

1. 如果提示启用 Actions，先点击启用。
2. 点击 **Run workflow**，分支选择 `main`。
3. `mode` 先选 `preview`，再点击绿色的 **Run workflow**。
4. 等运行结束，点击本次任务，在 Summary 中查看生成的早报。preview 只抓取和预览，不读取微信密钥，不发送消息。
5. 再运行一次，`mode` 选 **send**。此次会实际发送今天的早报。
6. 检查微信是否收到。任务成功只说明接口接受消息，微信实际收到才表示接收通道验证通过。

更新主分支的脚本或工作流时也会自动运行一次 preview，用于验证 GitHub 运行器能正常抓取新闻；代码提交本身不会发送微信消息。

`send` 默认每个北京时间日期只提交一次；第一次成功后，当天再次运行会跳过，所以不会反复推送同一份早报。想查看内容可使用 preview。

## 4. 每天9点自动运行

只要工作流文件存在于默认分支 `main` 且工作流启用，就按下面规则调度：

```yaml
schedule:
  - cron: '0 1 * * *'
```

GitHub 默认用 UTC，01:00 UTC 对应北京时间09:00。代码也明确使用 UTC+8 计算日期。任务在 GitHub 托管的 Ubuntu 上运行，你的电脑关机也能工作。

**GitHub 是尽力调度，不保证整点送达。** 整点高负载可能延迟，极端情况下可能漏跑。若超过预期仍未收到，可查看 Actions 中当天是否出现任务。不要把它当作必须准点到达的通知服务。

当前仓库为公开仓库：连续60天没有仓库活动时，GitHub 可能自动暂停定时工作流。建议每月检查一次；若被暂停，在 Actions 中重新启用，并根据 GitHub 提示更新计划。单纯收到新闻不等于仓库活动。本项目没有自动制造提交来绕过暂停机制。

## 5. 如何保持免费

- 当前公开仓库使用标准 `ubuntu-latest` 托管运行器，属于 GitHub Actions 免费使用范围。
- 如果以后改成私有仓库，会消耗账户每月免费额度。GitHub Free 当前含2000分钟，额度由账号下私有仓库共享。每天一次、每次最长5分钟，本任务31天的执行时间上限约155分钟，另外加上手动测试；实际通常更短。
- 不需要升级 GitHub 套餐。本工作流不上传构建产物，仅缓存一个不含密钥的发送状态文件，体积极小。
- 如果账号已绑定支付方式，请在个人 Settings → Billing & licensing → Budgets and alerts 中检查 Actions 预算，按后台支持的方式限制额外付费用量；若没有有效支付方式，GitHub 官方说明为免费额度用尽后阻止继续使用。
- 第三方免费规则可能调整，应以 GitHub 与 Server酱后台为准。

## 6. 没收到消息时

| 现象 | 检查方法 |
| --- | --- |
| Actions 中没有 Daily WeChat News | 确认 `.github/workflows/daily-news.yml` 位于默认分支的正确路径；不要把代码放在额外一层文件夹中 |
| 没有 Run workflow 按钮 | 确认文件已提交到默认分支，刷新页面；检查是否启用 Actions |
| 测试显示未配置 SCT 密钥 | 检查仓库 Secret 是否名为 `SERVERCHAN_SENDKEY`、内容是否为 SCT 开头，且没有误建为 Variable |
| 所有新闻源均无有效新闻 | 查看任务日志；可能是 GitHub 运行器访问新闻源失败或 RSS 没有24小时内条目，程序会报错，不发送空消息 |
| preview 成功但微信没消息 | preview 设计为不发送，需要选择 send |
| 显示今天已经提交过 | 当日去重已生效；查看之前的成功运行和微信历史消息 |
| 接口成功但微信没收到 | 到 Server酱查看投递日志，并检查通道授权、关注状态与免费额度 |
| 任务失败 | 点开该次运行中的红色步骤，按错误信息排查；不要公开粘贴密钥 |

发送超时可能表示服务端已接受但响应丢失，程序不会自动重试。请先查微信及 Server酱日志再手动重跑。同日去重依赖 GitHub Cache：缓存被删除/淘汰，或发送成功后保存缓存前任务中断，都可能导致后续手动重跑重复投递，不保证绝对恰好一次。

临时停止：仓库 Actions → Daily WeChat News → 右上角菜单 → Disable workflow。恢复时选择 Enable workflow。更换微信接收账号：更新 Secret 和对应的服务接收通道。

## 7. 文件说明

```text
.github/workflows/daily-news.yml  每日调度、手动运行、当日状态缓存
news_digest.py                  新闻抓取与微信发送（仅Python标准库）
test_news_digest.py             不发送真实消息的自动化测试
README.md                       本指南
.gitignore                      忽略本地凭据与运行状态
```

如果用下载包手动上传：解压 `github-free-news.zip`，进入 `github-free-news` 文件夹，把里面的内容上传到仓库根目录。不要只上传ZIP，也不要多套一层 `github-free-news/`。上传后确认仓库中有 `.github/workflows/daily-news.yml`。

新闻简报各取国内和国际最新最多6条，原摘要前两句，附来源和链接。并非大模型综合分析，也不保证覆盖所有重大新闻。国内与国际当前均来自中新网，分类指报道主题，不表示多家独立媒体。

官方参考：

- [GitHub Actions 定时规则、延迟与60天暂停说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [GitHub 免费额度与计费](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [GitHub Secret 设置](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)
- [Server酱密钥与微信接入](https://sct.ftqq.com/docs/getting-started/sendkey/)
- [Server酱额度与消息排查](https://sct.ftqq.com/docs/getting-started/faq/)
