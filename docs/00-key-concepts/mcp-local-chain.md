# 实例：本地 MCP 全链路是怎么串起来的（Client → Server 容器 → 真实应用）

> 所属模块：00 关键概念 ｜ 学习日期：2026-07-07
> 承接 [MCP Client vs Server 辨析](mcp-client-vs-server.md)，这次用本机真实配置，把"配置 → 调用容器 → 容器调用真实服务"整条链路走一遍。
> ⚠️ 本机配置里含明文密码 / AWS 密钥，本笔记已全部打码（`***`），真实值只在本地 `~/.codex/config.toml`，切勿提交到仓库。

## 本机现状（探查结果）

Colima 里有 6 个运行中的 MCP 容器，镜像是 `mcp/redis`、`mcp/clickhouse`、`rustfs/mcp:main`。它们**都是 MCP Server**，由 **Codex（AI 应用 = Host）作为 MCP Client** 拉起。

- Client 配置文件：`~/.codex/config.toml` 的 `[mcp_servers.*]` 段
- 传输方式：**stdio**（容器带 `OpenStdin: true`，即 `docker run -i`）
- 三个 docker 型 server 结构完全一致，下面用 **redis** 举例。

## 完整链路图

```
┌────────────────────────────────────────────────────────────┐
│ Host = Codex（AI 应用）                                       │
│  读取 ~/.codex/config.toml → 为每个 server 起一个 MCP Client  │
│                                                              │
│   ┌───────────────┐                                          │
│   │ MCP Client:    │  ①启动子进程: docker run -i --rm mcp/redis ...  │
│   │  redis         │─────────────────────────────┐           │
│   └───────────────┘                              │           │
│         ▲  ②JSON-RPC over stdin/stdout           │           │
└─────────┼────────────────────────────────────────┼──────────┘
          │                                         ▼
          │                          ┌──────────────────────────┐
          │                          │ MCP Server 容器           │
          └──────────────────────────│  mcp/redis                │
             (工具列表/调用结果)       │  跑 redis-mcp-server      │
                                      │  暴露 Tools: get/set/...  │
                                      └───────────┬──────────────┘
                                         ③用 --url 连真实服务      │
                                                  ▼
                                      ┌──────────────────────────┐
                                      │ 真实应用：Redis 实例       │
                                      │ redis://***@10.0.181.92:  │
                                      │        26379/1            │
                                      └──────────────────────────┘
```

## 三段拆解（redis 为例）

### ① MCP Client 怎么配置
`~/.codex/config.toml` 里：

```toml
[mcp_servers.redis]
command = "/opt/homebrew/bin/docker"
args = ["run", "-i", "--rm", "mcp/redis",
        "uv", "run", "redis-mcp-server",
        "--url", "redis://:***@10.0.181.92:26379/1"]
startup_timeout_sec = 120.0
```

- `command` + `args` 就是 Client "**怎么把 Server 拉起来**"的命令。
- 这里 `command` 是 `docker`，所以 Server 以**容器**形式启动；换成本机二进制/脚本也一样（本机另有 `matlab` server 直接用 `python server.py`）。
- `-i`（interactive）是关键：保持 stdin 打开，Client 才能和容器进程用 stdio 通信。

### ② Client 如何调用容器里的 Server
- Codex 启动时读配置，对每个 server **fork 一个子进程**执行那条 `docker run -i` 命令，容器就跑起来了（就是你在 Colima 看到的那些）。
- Client 和容器之间走 **JSON-RPC 2.0**，通过容器的 **stdin/stdout** 收发（这就是 stdio 传输）。
- 握手：Client 发 `initialize` → Server 回能力 → Client 发 `tools/list` 拿到工具清单（如 redis 的 `get`/`set`/`keys`）。
- 模型要用工具时，Client 发 `tools/call`（方法名 + 参数）→ Server 执行 → 回结果。

### ③ Server 如何调用真正的应用
- `mcp/redis` 容器里跑的是 `redis-mcp-server` 进程，它拿到 `--url redis://:***@10.0.181.92:26379/1`。
- 收到 `tools/call`（比如 `get key=foo`）后，它**用普通 Redis 客户端库连到那台真实 Redis**（`10.0.181.92:26379`，第 1 号 db），执行命令，把结果按 MCP 协议格式包好回给 Client。
- 所以 Server 本质是个**翻译层/适配器**：把"MCP 协议的工具调用" ↔ "真实服务的原生协议（Redis 命令 / ClickHouse SQL / S3 API）"来回转换。

## 另外两个 server（结构相同，只换后端）

| Server | 启动方式 | 连接的真实应用 |
|--------|----------|----------------|
| redis | `docker run -i mcp/redis` | Redis @ `10.0.181.92:26379` |
| clickhouse | `docker run -i mcp/clickhouse`（用 `-e` 传一堆 `CLICKHOUSE_*` 环境变量）| ClickHouse @ `10.0.181.88:8123`，库 `dev_171` |
| rustfs | `docker run -i rustfs/mcp:main`（`-e` 传 `AWS_*`）| S3 兼容存储 @ `10.0.81.92:9000` |

> 区别只是"参数怎么传"：redis 直接写在命令行 `--url`，clickhouse/rustfs 用 `-e ENV` 从 `[mcp_servers.X.env]` 注入环境变量。链路三段完全一样。

## 一图记住

> **配置(config.toml) 告诉 Client 怎么拉 Server；Client 用 docker run -i 起容器、走 stdio JSON-RPC 调工具；Server 容器再用后端原生协议连真实的 Redis/ClickHouse/S3。** MCP 只管 Client↔Server 这一段，Server↔真实应用那段是各服务自己的协议。

## 安全备注（重要）
- 这些配置里是**明文的数据库密码和 AWS 密钥**。它们躺在本地 `~/.codex/config.toml` 尚可，但：
  - 不要把该文件或含密文的截图提交到任何仓库。
  - 更稳妥的做法：用环境变量 / 密钥管理注入，而非明文写进配置。

## 关联
- 角色概念见 [MCP Client vs Server 辨析](mcp-client-vs-server.md)
- 协议总览见 [模块 00 README](README.md)
