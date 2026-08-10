# Workflow 编排与多智能体拓扑

> 所属模块：04 · Agent 架构 ｜ 学习日期：2026-08-10  
> 实验：`experiments/mini-agent/agent_demo.py`（§4 Plan-and-Execute + §5 Supervisor-Worker）  
> 项目桥：`projects/p3-mini-coding-agent/`（单 agent ReAct + Tool 注册表；多 agent 不必默认上）

## 一句话总结

**固定 Workflow 管确定性路径，自主 Agent 管开放探索**；多智能体是**拓扑选择**（Supervisor-Worker / Planner-Executor / Fan-out），不是「拆成越多角色越聪明」——协调税真实存在。

## 我的理解

```
                    任务形态光谱
  确定性高 ◄──────────────────────────────────► 开放探索
       │                                              │
  固定 Workflow                              自主 Agent Loop
  Sequential / Parallel / Router / Loop      ReAct / Reflection
       │                                              │
       └──── 可组合：外层 Workflow 调度，内层 Agent 执行 ──┘
```

底层逻辑：**先问「路径是否可预写」**，再决定用哪一层。路径可预写却硬上全自主 Agent = 延迟与费用无上限；路径不可预写却焊死 Sequential = 稍有分支就全挂。

### 1. 四种 Workflow 原语

| 原语 | 形态 | 适合 | 失败面 |
|------|------|------|--------|
| **Sequential** | A → B → C | 强依赖流水线（先检索再生成） | 前步错，后步全歪 |
| **Parallel** | A ∥ B ∥ C → merge | 无依赖 fan-out（多源检索、多视角评审） | 汇总策略；短板拖总时延 |
| **Router** | 条件分流 | 意图分类后走不同子图 | 路由错 = 全错；要可观测 |
| **Loop** | 直到条件 / 上限 | 重试、反思、批处理 | 必须有 **max 迭代**（同 Agent `max_turns`） |

```
Router 示例（客服）
  用户问 ──▶ 路由
              ├─ logistics  ──▶ Sequential(查单 → 回写)
              ├─ refund     ──▶ Parallel(物流∥政策) → 汇总
              └─ chitchat   ──▶ 单步回复（禁止上多 worker）
```

实验对照：`supervisor_route` + `run_supervisor` 就是 **Router +（可选）Sequential pipeline** 的最小实现——退货走 `logistics → policy` 串联，闲聊只派 `chitchat`。

### 2. 何时固定 Workflow，何时自主 Agent

| 信号 | 优先 |
|------|------|
| 步骤可列清单、依赖稳定、要可审计 SLA | **固定 Workflow** |
| 信息逐步揭露、分支多、工具结果改写下一步 | **自主 Agent（ReAct）** |
| 外层要可控成本，内层要探索 | **Workflow 包 Agent**（外层限时/限步，内层 ReAct） |
| 单步可答、无专业分工 | **单 agent / 单 worker** |

和模块内 Planning 笔记对齐：

- **ReAct** ≈ 运行时动态 workflow（每步才决定下一边）  
- **Plan-and-Execute** ≈ 先 compile 一张 DAG，再 execute（更像固定 workflow）

实验：`build_refund_plan` 的 `t1→t2∥t3→t4` 就是 **Plan 编译出的 Sequential+Parallel DAG**；`run_react` 则是边观察边长边。

### 3. 多智能体拓扑

#### 3.1 Supervisor-Worker（实验已跑通）

```
        ┌──────── Supervisor（路由/汇总，不干脏活）────────┐
        │  route(question) → worker_ids                    │
        └───────────────┬──────────────────────────────────┘
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
   logistics        policy           chitchat
   (查物流)         (查政策)          (闲聊单兵)
```

| 用户问 | route | workers | 设计意图 |
|--------|-------|---------|----------|
| 订单到哪了 | logistics | `[logistics]` | 专岗单兵 |
| 退货政策/可否退 | refund_pipeline | `[logistics, policy]` | 串联补全证据 |
| 你好 | chitchat | `[chitchat]` | **砍协调税** |

断言抓手（`demo_multi_agent`）：闲聊 `workers == ["chitchat"]`——多 agent 默认不是正确答案。

#### 3.2 Planner-Executor

```
Planner（只规划，不调工具）
   │  产出 SubTask DAG / 自然语言步骤
   ▼
Executor（只执行，不改全局目标）
   │  dispatch tools / 填 observation
   ▼
（可选）Replanner：失败或观测偏离 → 改计划
```

与单进程 Plan-and-Execute 的差别：**角色隔离**——规划者看不到工具私有状态，执行者不擅自改目标。适合「计划要人审 / 要审计」的场景；代价是多一轮 LLM + 状态同步。

实验里的 `SubTask` + `run_plan_execute` 是 **同进程版** Planner-Executor；拆成两个 agent 只是把 policy 边界画硬。

#### 3.3 Fan-out / 评审团

- 并行多个 worker 同题异角色（正确性 / 安全 / 可复现）  
- merge：投票、加权、或 supervisor 摘要  
- 适用：高风险结论、代码评审；不适用：强实时单跳问答

### 4. 通信与状态共享

| 模式 | 做法 | 风险 |
|------|------|------|
| **共享黑板** | 公共 Memory / 状态 dict | 写冲突；要约定 owner 字段 |
| **消息传递** | A 的输出 = B 的输入 | 协议漂移；要 schema |
| **中心状态机** | Supervisor 持有唯一 truth | Supervisor 变单点；但最易审计 |

工程建议（对齐 P3 经验）：

1. **Observation 只由宿主/工具写**，worker 不互改对方记忆  
2. 跨 agent 传递用 **结构化结果**（JSON），少传长思维链  
3. 每个 agent 仍要有自己的 `max_turns`，全局再加总预算

### 5. 什么时候多 agent 反而更差

1. **协调税 > 专业增益**：闲聊、单工具查询  
2. **延迟预算紧**：串 3 个 LLM 调用 = 3× 尾延迟  
3. **目标不可分**：硬拆导致上下文割裂、互相幻觉  
4. **无清晰接口**：角色重叠 → 重复劳动或推诿  
5. **调试面爆炸**：失败时不知道是路由错、worker 错还是 merge 错

**口诀**：先单 agent 跑通闭环，再按**真实瓶颈**拆专岗——拆的是技能边界，不是为了架构图好看。

## 动手记录

```bash
cd experiments/mini-agent && python3 agent_demo.py
# §4 Plan-and-Execute：t1→t2/t3→t4 DAG，依赖未满足 skipped
# §5 Multi-Agent：退货 pipeline 双 worker；你好 → 单 chitchat
```

关键符号：

- `build_refund_plan` / `run_plan_execute` — 固定 DAG workflow  
- `supervisor_route` / `run_supervisor` / `WORKERS` — Router + Worker 注册表  
- `run_react` — 自主 loop（对照「非固定 workflow」）

P3 侧刻意保持**单 agent + 工具注册表**（read/search/edit/run）：编码任务分支多，先把 Loop/Tool/沙箱做稳，再谈多 agent——这是正确的复杂度顺序。

## 踩过的坑 / 易混淆点

- **Workflow = 多 Agent**：否。Workflow 是边的编排；Agent 是带 LLM 决策的节点。一个 Sequential 里可以全是确定性工具，零 agent。  
- **Supervisor 也下场调工具**：角色污染，失败时难归因；Supervisor 应路由/汇总，脏活给 Worker。  
- **Plan-and-Execute 一次计划永生**：环境变了要 Replan；实验里 `max_retries` 只是工具级，不是业务级重规划。  
- **并行一定更快**：merge 等最慢分支；若下游要全量结果，P95 由短板决定。  
- **照搬 AutoGen/LangGraph 默认图**：框架给的是原语，拓扑仍要按任务选；默认群聊往往过重。

## 面试问答（自测）

- **Q: Sequential / Parallel / Router / Loop 各解决什么？**  
  A: 依赖链 / 无依赖加速与多视角 / 条件分流 / 有上界的重复直到收敛。

- **Q: 何时用固定 workflow，何时用自主 agent？**  
  A: 路径可预写、要 SLA → workflow；分支随观察变化 → agent；常外层 workflow 限预算、内层 agent 探索。

- **Q: Supervisor-Worker 怎么分工？**  
  A: Supervisor 路由与汇总；Worker 专岗执行。简单题只派单 worker，避免协调税（实验：你好 → chitchat）。

- **Q: Planner-Executor 和 ReAct 区别？**  
  A: 前者先出计划再执行（可审、可并行子任务）；后者边想边做。计划错需 Replan；ReAct 错可下一步改道。

- **Q: 多 agent 一定比单 agent 好吗？**  
  A: 否。有协调、延迟、调试成本；无专业边界或单步可答时单 agent 更稳。

## 参考资料

- 实验：`experiments/mini-agent/agent_demo.py`  
- 同模块：[`agent-loop.md`](agent-loop.md)、[`memory-planning-tools.md`](memory-planning-tools.md)  
- 项目：`projects/p3-mini-coding-agent/`（单 agent 工程化）  
- LangGraph / AutoGen 架构文档（借原语，不抄默认拓扑）  
- ReAct 论文；OpenAI / Anthropic Agent 工程实践
