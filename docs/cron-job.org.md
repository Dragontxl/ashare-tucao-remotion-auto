# cron-job.org 定时任务配置

本项目使用 cron-job.org 在**每周一至周五 17:25（Asia/Shanghai）**调用 GitHub Actions 的 `workflow_dispatch` 接口。

当前任务：`jobId=8943709`，下次执行 `2026-11-26 17:25:00 +08:00`。

> cron-job.org 只负责发 HTTP 请求；视频生成、渲染和 B站上传都在 GitHub Actions 中执行。

---

## 一、推荐方式：脚本自动创建

项目已提供 `scripts/setup_cron.py`：

```bash
# 创建或更新
python scripts/setup_cron.py

# 只预览，不调用 cron-job.org API
python scripts/setup_cron.py --dry-run

# 只生成，不上传 B站（调试）
python scripts/setup_cron.py --no-upload
```

配置读取顺序：

| 配置 | 来源 |
|---|---|
| cron-job.org API Key | `--api-key` → `CRONJOB_API_KEY` → `config.cronjob.api_key` |
| GitHub PAT | `--github-token` → `GH_PAT` → `config.github.pat` |
| 仓库 | `--repo` → `GH_OWNER` + `GH_REPO` → `config.github.owner` + `repo` |

脚本会按标题查找已有任务：存在则更新，不存在则创建。

---

## 二、手动创建（cron-job.org 控制台）

| 字段 | 值 |
|---|---|
| Title | `A股盘面吐槽 17:25 生成并上传B站` |
| URL | `https://api.github.com/repos/Dragontxl/ashare-tucao-remotion-auto/actions/workflows/generate.yml/dispatches` |
| Method | `POST` |
| Schedule | 周一至周五 17:25 |
| Timezone | `Asia/Shanghai` |
| Request body | `{"ref":"main","inputs":{"upload":"true"}}` |
| Header | `Accept: application/vnd.github+json` |
| Header | `Authorization: Bearer <GitHub PAT>` |
| Header | `Content-Type: application/json` |
| Header | `X-GitHub-Api-Version: 2022-11-28` |

> ⚠️ `inputs` 的值必须是**字符串**。写成 `{"upload":true}`（布尔值）会被 GitHub 拒绝：
> `422 Invalid request. For 'additionalProperties', true is not a string.`
> 正确写法是 `{"upload":"true"}`。

---

## 三、API 创建

```http
PUT https://api.cron-job.org/jobs
Authorization: Bearer <cron-job.org API Key>
Content-Type: application/json
```

```json
{
  "job": {
    "title": "A股盘面吐槽 17:25 生成并上传B站",
    "url": "https://api.github.com/repos/Dragontxl/ashare-tucao-remotion-auto/actions/workflows/generate.yml/dispatches",
    "enabled": true,
    "saveResponses": true,
    "requestMethod": 1,
    "requestTimeout": 30,
    "redirectSuccess": false,
    "folderId": 0,
    "type": 0,
    "schedule": {
      "timezone": "Asia/Shanghai",
      "hours": [17],
      "minutes": [25],
      "mdays": [-1],
      "months": [-1],
      "wdays": [1, 2, 3, 4, 5],
      "expiresAt": 0
    },
    "extendedData": {
      "headers": {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer <GitHub PAT>",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28"
      },
      "body": "{\"ref\":\"main\",\"inputs\":{\"upload\":\"true\"}}"
    }
  }
}
```

`requestMethod`：`0=GET`、`1=POST`、`2=PUT`、`3=DELETE`。
`wdays`：`0=周日`、`1=周一` … `6=周六`，`[1,2,3,4,5]` 即周一至周五。
`mdays`/`months` 为 `-1` 表示不限制。

---

## 四、验证

```bash
# 查看任务列表
curl -H "Authorization: Bearer <cron-job.org API Key>" \
  https://api.cron-job.org/jobs
```

重点看：

- `enabled`：`true`
- `schedule.timezone`：`Asia/Shanghai`
- `schedule.hours` / `minutes`：`[17]` / `[25]`
- `schedule.wdays`：`[1,2,3,4,5]`
- `nextExecution`：下一次执行时间（Unix 时间戳）
- `lastStatus`：最近一次 HTTP 状态

也可以手动触发一次验证全链路：

```bash
python scripts/trigger_workflow.py --wait
```

---

## 五、GitHub PAT 说明

cron-job.org 的请求头里保存的是 GitHub PAT。建议使用 **fine-grained PAT** 或 **classic PAT**，至少需要：

- `repo`：访问私有仓库
- `workflow`：触发 GitHub Actions

如果只触发本仓库，也可以使用仅授权该仓库的 fine-grained PAT。

PAT 过期或撤销后，cron-job.org 会收到 `401`，此时：

1. 生成新的 PAT；
2. 运行 `python scripts/setup_cron.py` 更新任务；
3. 或在 cron-job.org 控制台修改 Header。

---

## 六、常见问题

### 1. cron-job.org 显示成功，但 GitHub 没有运行？

检查：

- PAT 是否有 `workflow` 权限；
- 仓库名、分支名是否正确；
- workflow 文件名是否为 `generate.yml`；
- cron-job.org 的 `saveResponses` 是否开启，查看响应体。

### 2. GitHub Actions 运行了，但没有上传 B站？

查看「预检 B站 Cookie」步骤。Cookie 失效时：

```bash
python scripts/refresh_bili_cookie.py
```

然后重新运行 Actions，或使用「手动从R2补传B站」。

### 3. 非交易日会怎样？

会正常触发，但流水线检测到非交易日后直接退出，Actions 显示成功。

### 4. 可以改成 17:20 或 17:30 吗？

可以。建议不要早于 17:20，因为当日复盘 docx 通常在 17:16–17:25 之间发布。
`fetch_article.py` 已内置重试，17:25 触发比较稳妥。
