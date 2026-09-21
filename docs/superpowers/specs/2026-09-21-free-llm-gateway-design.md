# 免费大模型接入系统 — 设计文档

日期:2026-09-21
状态:待评审

## 1. 背景与目标

构建一个 HTTP 服务,接入多家**国内免费 LLM API**,批量执行低时效(时延不敏感)任务。
任务类型:批量文本处理、内容生成、数据提取/结构化、评测/打分。

**明确排除 DeepSeek**(及任何 DeepSeek 系列模型)。

### 核心原则(优先级从上到下)

1. **稳定可靠 > 速度**。慢不要紧,不丢任务、不崩、可续跑。
2. **防止被封号**。严格保守限速、不突发、遇限流退避,始终给服务商留足余量,避免触发风控/封 key。
3. 免费额度下跑,不引入付费依赖与重型基础设施。

## 2. 非目标(YAGNI)

- 不做多机分布式、不做 Celery/Redis/消息队列中间件。
- 不做 Web UI 前端。
- 不做流式输出(streaming)。
- 不做账号/鉴权体系(单机内网服务)。
- 不做海外 provider(第一期)。
- 不做自定义微调/训练。

## 3. 技术选型

| 项 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.11+ | asyncio + httpx 高并发调多 API |
| Web 框架 | FastAPI + uvicorn | 异步原生,自动文档 |
| 持久化 | SQLite(WAL 模式) | 单文件、断点续跑、零依赖 |
| HTTP 客户端 | httpx(AsyncClient) | 异步、连接池、超时可控 |
| 配置 | YAML | 人可读,provider/限速集中管理 |
| Provider SDK | 直接 REST 调用 | 各国内 SDK 质量参差,统一走 HTTP 可控性更强 |

## 4. 架构分层

```
┌─────────────────────────────────────────────┐
│ API 层 (FastAPI)                            │
│  POST /jobs           提交批量任务           │
│  GET  /jobs/{id}      查任务状态             │
│  GET  /jobs/{id}/result 查结果              │
│  GET  /health         健康检查               │
└──────────────────┬──────────────────────────┘
                   │ 写入 jobs + items (status=pending)
┌──────────────────▼──────────────────────────┐
│ Worker 池 (asyncio, 进程内)                 │
│  轮询 pending items → 渲染模板 → 调 LLM     │
│  写回 result / 重试 / 失败                  │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│ Router 路由层                                │
│  - 选 provider(加权 + 熔断状态)             │
│  - 每 provider 限速闸门(令牌桶)             │
│  - 429/5xx 退避 + 熔断冷却 + 自动降级        │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│ Provider 适配层                              │
│  glm / qwen / kimi / (可插拔新增)           │
│  统一接口 chat(messages, model, **opts)     │
└─────────────────────────────────────────────┘
```

## 5. Provider 适配层

统一接口:

```python
class Provider(ABC):
    name: str

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],      # [{"role": "system"|"user"|"assistant", "content": str}]
        model: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:  # 返回文本内容,异常上抛 ProviderError
        ...
```

第一期接入三家(每个一个 adapter 文件 `providers/<name>.py`):

| Provider | 免费模型 | API 端点风格 |
|---|---|---|
| 智谱 GLM (BigModel) | `glm-4-flash` / `glm-4.5-flash` | OpenAI 兼容 `/chat/completions` |
| 通义千问 (DashScope/百炼) | `qwen-turbo` / `qwen-flash` | OpenAI 兼容 |
| Moonshot Kimi | `moonshot-v1-8k` | OpenAI 兼容 |

三者均走 OpenAI 兼容 `/chat/completions` 协议,`base_url` + `api_key` + `model` 差异仅在配置。
适配层做:base_url 拼接、请求体构造、错误码分类(429/403/5xx/超时)、响应文本提取。

> 后续加新 provider:新增一个 adapter 文件 + 配置文件加一段,不改 Router/Worker。

## 6. 防封号:限速与降级(Router 核心)

每 provider 配置以下参数(保守默认):

```yaml
providers:
  glm:
    concurrency: 1        # 每 provider 并发(默认 1 = 串行,不突发)
    rpm: 20               # 每分钟上限,远低于官方免费额度
    min_interval: 3.0     # 相邻两次请求最小间隔(秒)
    jitter: 1.0           # 间隔随机抖动幅度(秒,±)
    max_retries: 3        # 单 item 在该 provider 上的最大重试
    cooldown: 120         # 熔断冷却时长(秒)
    keys: ["sk-xxx"]      # 支持多 key 轮换
```

限速机制(令牌桶 + 间隔抖动):

1. **令牌桶** 控 `rpm`;桶容量 = rpm,每请求消耗 1 令牌。
2. **间隔闸** 控 `min_interval`:距上次请求不足 `min_interval + random(-jitter, +jitter)` 时 sleep。
3. **串行优先**:默认 `concurrency=1`,天然无突发。
4. **多 key 轮换**:配置多个 key 时 round-robin,分摊单 key 风险。

错误处理与降级:

| 现象 | 动作 |
|---|---|
| 429(限流) | 指数退避 `2^n * 1s + jitter`,重试;连续失败触发熔断 |
| 403/401(key 失效) | 标记该 key 停用,切下一个 key/provider |
| 5xx / 超时 | 退避重试,随后切下一 provider |
| 连续 N 次失败 | **熔断**:provider 进入 cooldown 冷却,期间路由跳过;冷却结束半开试探 |

**路由选择顺序**:按配置权重,跳过熔断中的 provider,取可用且未超 rpm 的。单 item 失败后自动降级到下一家(见 §9)。

## 7. Worker 池

- 进程内 `asyncio` worker,数量 = 全局并发上限(默认 4,可配)。
- 每 worker 循环:取一个 `pending` item → 渲染 prompt → 选 provider → 过限速闸 → 调 LLM → 写结果。
- **优雅停机**:收到 SIGTERM/SIGINT 时,停止取新 item,等在途请求完成,持久化状态后退出。
- **启动恢复**:把 `running` 的孤儿 item(上次未完成)重置为 `pending` 重跑;`pending` 保留继续。

## 8. 持久化(SQLite)

WAL 模式,两表结构:

```sql
CREATE TABLE jobs (
    job_id          TEXT PRIMARY KEY,
    prompt_template TEXT NOT NULL,
    model           TEXT NOT NULL DEFAULT 'auto',
    provider_pref   TEXT NOT NULL DEFAULT 'auto',   -- 指定/自动
    status          TEXT NOT NULL DEFAULT 'pending',-- pending/running/done/failed/partial
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE items (
    item_id      TEXT PRIMARY KEY,
    job_id       TEXT NOT NULL REFERENCES jobs(job_id),
    input_json   TEXT NOT NULL,                     -- 单个输入(渲染进模板)
    status       TEXT NOT NULL DEFAULT 'pending',   -- pending/running/done/failed
    result       TEXT,                              -- LLM 输出文本
    provider     TEXT,
    model        TEXT,
    error        TEXT,
    retry_count  INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL
);
CREATE INDEX idx_items_status ON items(status);
CREATE INDEX idx_items_job ON items(job_id);
```

- `job.status` 由 `items` 聚合:全 done → done;有 failed → partial(或 failed);全 pending → pending。
- 每次 item 状态变更走事务提交,崩溃不丢中间态。

## 9. 任务模型与数据流

提交:

```json
POST /jobs
{
  "prompt_template": "请将以下文本分类:{{text}}",
  "inputs": [{"text": "..."}, {"text": "..."}, ...],
  "model": "auto",
  "provider_pref": "auto"       // 或 "glm" / "qwen:glm" 指定优先级
}
```

- 每个 `input` 展开为一个 `item`,用 Jinja2/`str.format` 渲染进 `prompt_template` 的 `{{key}}` 占位。
- 返回 `{"job_id": "..."}`。

单 item 执行流:

```
pending → running
  → 选 provider(跳过熔断)
  → 过限速闸(令牌桶 + 间隔抖动)
  → chat()
     ├─ 成功 → status=done, result=输出
     ├─ 可重试错误(429/5xx/超时) → retry_count++ → 退避 → pending(留待重试)
     │     └─ 超过 max_retries → 降级到下一 provider 重跑(重试计数重置)
     │           └─ 无 provider 可用 → status=failed, error=原因
     └─ 不可重试错误(输入非法/内容被拒) → status=failed
```

## 10. 配置示例

```yaml
global:
  worker_concurrency: 4
  db_path: ./data/tasks.db
  default_model: auto

providers:
  glm:
    enabled: true
    base_url: https://open.bigmodel.cn/api/paas/v4
    model: glm-4-flash
    keys: ["${GLM_API_KEY}"]     # 支持环境变量占位
    concurrency: 1
    rpm: 20
    min_interval: 3.0
    jitter: 1.0
    cooldown: 120
    weight: 1
  qwen:
    enabled: true
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    model: qwen-turbo
    keys: ["${QWEN_API_KEY}"]
    # ... 同 glm
  kimi:
    enabled: true
    base_url: https://api.moonshot.cn/v1
    model: moonshot-v1-8k
    keys: ["${MOONSHOT_API_KEY}"]
    # ... 同 glm
```

API key 从环境变量读取,不落盘明文。

## 11. 测试策略

| 层 | 测试 |
|---|---|
| 模板渲染 | 单测:占位替换、缺失字段报错 |
| Provider 适配 | 用 `httpx.MockTransport` 伪造响应/429/5xx/超时,验证解析与错误分类 |
| 限速闸 | 单测:令牌桶扣减、间隔 sleep 逻辑(注入假时钟)、jitter 边界 |
| Router | 单测:熔断触发/恢复、降级顺序、跳过热 provider |
| Worker | 单测:item 状态机流转、重试次数、孤儿恢复 |
| API | FastAPI `TestClient` + 假 provider,端到端提交→查结果 |
| 集成(手动) | 真 key 跑小批量,验证免费额度内稳定 |

CI 无外部依赖,全部可离线跑(provider 层用 mock)。

## 12. 里程碑

1. **M1 骨架**:FastAPI + SQLite 表 + Worker 状态机 + 模板渲染 + mock provider 端到端。
2. **M2 Provider**:智谱 + 通义 + Kimi 三个 adapter + Router 限速/熔断/降级。
3. **M3 加固**:优雅停机、孤儿恢复、多 key 轮换、日志、README + 配置样例。

## 13. 待确认项

- provider 三期只接三家(glm/qwen/kimi),如需豆包/百炼/硅基流动后续追加。
- 无鉴权,默认仅监听 `127.0.0.1`(内网)。
