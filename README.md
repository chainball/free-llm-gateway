# free-llm-gateway

一个 OpenAI 兼容的 LLM 网关，把多个提供免费额度的大模型 API 聚合成一个标准 OpenAI 接口。

任何 OpenAI SDK（Go / Python / Node 等）只要把 `base_url` 指到本服务，就能像调用 OpenAI 一样使用这些上游，无需分别对接各家 API。网关负责路由、限速和故障转移。

## 特性

- **OpenAI 兼容**：`/v1/chat/completions`（同步 + SSE 流式）、`/v1/models`、`/v1/batches`
- **多上游聚合**：自动加权路由，单家失败自动熔断降级到下一家
- **遵循免费额度**：按上游限速策略（令牌桶 RPM/TPM + 并发闸），429 指数退避
- **批量任务**：SQLite 持久化、断点续跑、崩溃后孤儿任务自动重置
- **Web 管理台**：运行时启停上游、调整限速、查看任务与结果
- **单机零重依赖**：FastAPI + aiosqlite，无需 Redis / Celery

## 支持的上游

| 上游 | 免费模型 | 环境变量 |
|---|---|---|
| 智谱 BigModel | `glm-4-flash` | `GLM_API_KEY` |
| 硅基流动 SiliconFlow | `THUDM/GLM-4-9B-0414` | `SILICONFLOW_API_KEY` |

新增上游只需继承 `app/providers/base.py` 的 `OpenAICompatProvider` 并在 `app/providers/__init__.py` 注册。

## 快速开始

```bash
# 1. 创建虚拟环境并安装
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. 配置 API key（二选一）
cp .env.example .env && vim .env    # a) .env 文件（推荐，不入 git）
export GLM_API_KEY=sk-xxx           # b) 环境变量
export SILICONFLOW_API_KEY=sk-xxx

# 3. 启动（默认 127.0.0.1:8000）
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 使用

### 同步对话

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"你好"}]}'
```

流式响应在请求体中加 `"stream": true`。

### 批量（OpenAI Batch 风格，内联 JSONL）

```bash
curl http://127.0.0.1:8000/v1/batches \
  -H "Content-Type: application/json" \
  -d '{"input":"{\"custom_id\":\"1\",\"method\":\"POST\",\"url\":\"/v1/chat/completions\",\"body\":{\"model\":\"auto\",\"messages\":[{\"role\":\"user\",\"content\":\"你好\"}]}}\n{\"custom_id\":\"2\",\"method\":\"POST\",\"url\":\"/v1/chat/completions\",\"body\":{\"model\":\"glm-4-flash\",\"messages\":[{\"role\":\"user\",\"content\":\"1+1=?\"}]}}"}'

# 查询状态
curl http://127.0.0.1:8000/v1/batches/{batch_id}

# 下载结果
curl http://127.0.0.1:8000/v1/batches/{batch_id}/content
```

### Go SDK

```go
cfg := openai.DefaultConfig(os.Getenv("GATEWAY_KEY")) // key 任意非空即可
cfg.BaseURL = "http://127.0.0.1:8000/v1"
client := openai.NewClientWithConfig(cfg)
resp, err := client.CreateChatCompletion(ctx, openai.ChatCompletionRequest{
    Model:    "auto",
    Messages: []openai.ChatCompletionMessage{{Role: "user", Content: "你好"}},
})
```

### 模型选择

- `model: "auto"` — 自动加权选择可用上游（跳过熔断中的）
- 指定模型名（`glm-4-flash`、`THUDM/GLM-4-9B-0414`）或上游名（`glm`、`siliconflow`）
- `GET /v1/models` 列出可用模型

## 管理台

浏览器打开 `http://127.0.0.1:8000/`，可管理上游的启用状态、限速（RPM/TPM/并发），查看批量任务与结果。

## 配置

### 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `GLM_API_KEY` / `SILICONFLOW_API_KEY` | 上游 API key | — |
| `GATEWAY_ENV` | `.env` 文件路径 | `.env` |
| `GATEWAY_CONFIG` | 配置文件路径 | `config.yaml` |
| `GATEWAY_DB` | SQLite 路径 | `./data/tasks.db` |
| `GATEWAY_WORKERS` | 批量 worker 数 | `4` |

### config.yaml

`config.example.yaml` 提供了可覆盖的默认配置：上游的 base_url、模型列表、限速（concurrency/rpm/tpm）、熔断参数和多 key 轮换。API key 只通过环境变量提供，不写入配置文件。

## 架构

```
客户端（OpenAI SDK）
      │  /v1/chat/completions
      ▼
   FastAPI 网关
      ├── Router      模型 → 上游解析、加权路由、熔断降级
      ├── RateLimiter 并发闸 + RPM/TPM 令牌桶
      ├── Worker      批量任务消费（异步）
      └── SQLite      任务持久化 + 运行时设置
      │
      ▼
  glm ──┬── 智谱 BigModel
        └── 硅基流动 SiliconFlow
```

## 测试

```bash
pytest -q
```

测试全部离线，用 `httpx.MockTransport` 伪造上游响应，不发起真实网络请求。

## License

[MIT](LICENSE)
