# free-llm-gateway

OpenAI 兼容网关,把国内**永久免费**大模型 API 包装成标准 OpenAI 接口。客户端(Go/Python 等任意 OpenAI SDK)把 `base_url` 指到本服务,像接 DeepSeek 一样直接调用;后端自动路由到免费 provider 并套用其免费限速政策。**不接入 DeepSeek 作为上游。**

## 上游(永久免费不限量)

| Provider | 免费模型 | 环境变量 |
|---|---|---|
| 智谱 GLM | `glm-4-flash` | `GLM_API_KEY` |
| 硅基流动 SiliconFlow | `THUDM/GLM-4-9B-0414` | `SILICONFLOW_API_KEY` |

## 快速开始

```bash
# 1. 创建虚拟环境并安装
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. 配置 API key(二选一)
#    a) .env 文件:复制 .env.example -> .env,填入 key(推荐,.env 不入 git)
cp .env.example .env && vim .env
#    b) 环境变量:
export GLM_API_KEY=sk-xxx
export SILICONFLOW_API_KEY=sk-xxx
# 可选:复制并编辑 config.example.yaml -> config.yaml

# 3. 启动(默认 127.0.0.1:8000)
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 使用

### 同步对话

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"你好"}]}'
```

流式:`"stream": true`。

### 批量(OpenAI Batch,内联 JSONL)

```bash
curl http://127.0.0.1:8000/v1/batches \
  -H "Content-Type: application/json" \
  -d '{"input":"{\"custom_id\":\"1\",\"method\":\"POST\",\"url\":\"/v1/chat/completions\",\"body\":{\"model\":\"auto\",\"messages\":[{\"role\":\"user\",\"content\":\"你好\"}]}}\n{\"custom_id\":\"2\",\"method\":\"POST\",\"url\":\"/v1/chat/completions\",\"body\":{\"model\":\"glm-4-flash\",\"messages\":[{\"role\":\"user\",\"content\":\"1+1=?\"}]}}"}'

# 查询状态
curl http://127.0.0.1:8000/v1/batches/{batch_id}

# 下载结果
curl http://127.0.0.1:8000/v1/batches/{batch_id}/content
```

### Go SDK(drop-in)

```go
cfg := openai.DefaultConfig(os.Getenv("GATEWAY_KEY")) // key 任意非空即可
cfg.BaseURL = "http://127.0.0.1:8000/v1"
client := openai.NewClientWithConfig(cfg)
resp, err := client.CreateChatCompletion(ctx, openai.ChatCompletionRequest{
    Model: "auto",
    Messages: []openai.ChatCompletionMessage{{Role: "user", Content: "你好"}},
})
```

### 模型选择

- `model: "auto"` — 自动加权选可用 provider(跳过熔断)。
- 指定模型名(`glm-4-flash` / `THUDM/GLM-4-9B-0414`)或 provider 名(`glm` / `siliconflow`)。
- `GET /v1/models` 列出可用模型。

## 管理台

浏览器打开 `http://127.0.0.1:8000/`,可管理 provider 启用/限速(RPM/TPM/并发),查看批量任务与结果。

## 设计要点

- **稳定可靠 > 速度**:批量任务 SQLite 持久,断点续跑,崩溃后 `running` 孤儿自动重置。
- **遵循官方免费额度**:每 provider 令牌桶(rpm/tpm)+ 并发闸,429 指数退避,连续失败熔断降级到下一家。
- **单机零重依赖**:FastAPI + aiosqlite,无 Redis/Celery。

## 测试

```bash
pytest -q
```

全部离线(用 `httpx.MockTransport` 伪造上游响应,无真实网络调用)。

## 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `GLM_API_KEY` / `SILICONFLOW_API_KEY` | 上游 API key | — |
| `GATEWAY_ENV` | .env 文件路径 | `.env` |
| `GATEWAY_CONFIG` | 配置文件路径 | `config.yaml` |
| `GATEWAY_DB` | SQLite 路径 | `./data/tasks.db` |
| `GATEWAY_WORKERS` | 批量 worker 数 | `4` |
