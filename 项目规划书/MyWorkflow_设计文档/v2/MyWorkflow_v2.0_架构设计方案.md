# MyWorkflow v2.0 架构设计方案

> 作者：基于第一版设计与多 Agent 闭环迭代（GAN-inspired）策略的深度演进版
> 状态：V2.0 Core Architecture Draft

## 1. 系统演进核心理念 (从 V1 到 V2)

MyWorkflow v2.0 的核心在于将引擎从**“单向瀑布流执行器”**跨越升级为**“带自我反思与质量门禁的智能体循环状态机”**。

| 演进维度 | V1.0 原有设计 | V2.0 进化设计 | 带来价值 |
| --- | --- | --- | --- |
| **逻辑流转** | 线性顺序执行 | 带 Evaluator 反馈的**生成-评审迭代闭环** | 显著提升大型复杂流程生成产物的成功率和健壮性 |
| **上下文管理** | 依赖 LLM 做语义摘要压缩 | 基于 SQLite 静态快照的**Context Reset (硬重置)** | 彻底消除长流程中的 LLM 上下文幻觉与注意力漂移 |
| **角色协同** | 单一全能节点 | **Planner-Generator-Evaluator** 三位一体协同 | 引入"挑剔的"对抗审查，防止模型评判自毁（Self-evaluation bias） |
| **任务编排** | 全部平铺，人工划分 | 动态路由（>7 步触发**子工作流拆解**）+ 松耦合契约 | 让引擎具备自主应对月度/季度级别巨型复杂任务的拆解能力 |
| **安全与求值** | `eval` 动态求值 + 容易落库 | **simpleeval 沙盒 + 序列化脱敏拦截** + 静态规则优先 | 提供工业级的安全保障执行环境 |

---

## 2. 核心架构重构 (Engine Layer)

引擎层需要进行结构性改造以支持循环重入和“干净的石板”启动机制。

### 2.1 引入 `Context Reset` 机制
放弃过去在 `context_manager.py` 中使用 LLM 摘要旧步骤的 `compress_cold_steps` 方案。
- **机制**：通过 `state_store.py` 导出当前的全部变量，生成一个 JSON 格式的 **Handoff Artifact（交接快照）**。
- **动作**：当启动新步骤或被 Evaluator 打回重来时，清理当前 LLM 的 Message History（完全忘掉之前的瞎掰），直接把 `Handoff Artifact` 和 `Feedback` 注入为系统级的 System Prompt。

### 2.2 状态机回退流 (`Runner Loop Logic`)
`runner.py` 成为由条件驱动的分支状态机，支持从 Evaluator 退回 Generator。
- 支持类似 `on_reject: goto Step 2` 的内部流转。
- 管理**“阶梯式重试计数器”**（见后文），防范死循环扩散。

### 2.3 子流程变量的显式映射 (Output Mapping)
避免在递归 `sub_workflow` 时发生全局命名污染，废除简单粗暴的 `state.variables.update(sub_outputs)`。
- 由 Generator 显式利用 `variable_mapper` 技能，通过映射字典注入全局域。

---

## 3. 核心元工作流设计 (META_CREATOR 三角色闭环)

母工作流 `META_CREATOR.step.md` 从线性结构更新为如下循环迭代流：

### Step 1: Planner (规划者) - 需求解构与蓝图发布
- **Persona**：资深系统分析师。
- **职责**：将用户的一句话需求转化为 `Workflow_Spec`（JSON蓝图）。
- **复杂性断言与模块化生成**：如果任务预估需要超过 **7 个独立步骤**，强制触发**子流程拆分逻辑（Clustering）**，并定义子流程间的**“交接箱（Handoff Box）”**契约。
- **子流程介入点**：如果决定拆分出若干个 Sub_Flow，母工作流将进入子循环——**优先完整生成并评审 Sub_Flow**。只有当底层零件（各个子流程）通过评审后，母工作流才会继续生成组装总成（主流程）。

### Step 2: Generator (生成者) - 全量代码实现与精准重写
- **Persona**：精通 Python/Markdown 的架构级开发工程师。
- **职责**：采用**“全量交付 (Full Artifact Delivery)”**策略，一气呵成生成完整的 `Workflow_Draft.step.md`（文件草案），确保全局变量和流程上下文的连贯性，避免一步一检带来的思维截断。针对子流程的衔接，主动编写 `[Skill: variable_mapper]` 对齐数据。
- **精准编辑（收到反馈时）**：当接收到 Evaluator 的缺陷反馈时，Generator 不再“从零重写整个文件”，而是读取草案，利用 LLM 的**Editing（局部代码修改）**能力，针对指定的错误坐标进行**点对点的精准修正**。

### Step 3: Evaluator (评审者) - 整体评审与四维质量门禁
- **Persona**：极度挑剔、严格把控风险的首席安全架构师。
- **职责**：对 Generator 提交的**完整文件草案进行全身扫描（整体评审）**，先进行**纯底层的静态安全检查**（寻找危险关键词 `rm`、`git push` 等），然后调用 LLM 进行四维结构化打分。
- **“点对点”反馈输出要求 (Feedback Taxonomy)**：
  ```json
  {
    "status": "REJECTED",
    "score": 65,
    "defects": [
      {
        "type": "LOGIC_ERROR",
        "location": "Step 4",
        "reason": "变量 `report_data` 未在前面任意步骤中声明过",
        "suggestion": "请在 Step 3 新增一个读取文件技能来初始化该变量"
      }
    ],
    "overall_feedback": "逻辑闭环严重断裂，请根据上述 defect 的错误坐标进行局部点对点修复。"
  }
  ```

### Step 4: 引擎自动分支 (Engine Routing)与一步一检的真正战场
由 `runner.py` 根据 Step 3 输出的 `status` 自动切换流转：
- `IF APPROVED`: 进行物理落地并注册 (`registry_manager`)。
- `IF REJECTED`: 触发 **Jump Back** 回到 Generator，并将带有精准错漏坐标的 feedback 交由它执行“局部修正”。
- **注意：“一步一检”战场在哪？**：一步一检（小步快跑、副作用停机监控）并不发生在母工作流的生成期，而是发生在**业务工作流真正被投入引擎执行的阶段**。当具体的业务步骤携带了 `[CONFIRM]` flag 或者抛出失败时，Runner 才需要停下来呼叫干预。
---

## 4. 阶梯式降级策略 (Escalation Ladder)

为防止 Generator 和 Evaluator 在高难度任务上陷入死循环“互掐”，规定同一节点的退回计数器策略：

| 轮次 | 机制 | Evaluator & Engine 处理动作 |
| --- | --- | --- |
| **Round 1** | 标准重试 | 给出完整 JSON 反馈，直接发回给 Generator。 |
| **Round 2** | CoT 强化 | Generator 附加强制词：`"You failed previously. Think step by step to solve the Defect list."` |
| **Round 3** | 标准下调 (Relaxation) | Evaluator 关闭对 `eng_quality` (工程健壮性) 和 `persona_fit` (风格) 的卡控，**保底只要逻辑闭合且无安全缺陷即放行**。 |
| **Round 4** | 强制挂起 (Human-in-the-loop)| 触发引擎底层的 `[CONFIRM]`，输出“已连续 3 次失败”，将最高评分版本呈递给用户，求取干预（手动改、强穿、或者放弃）。 |

---

## 5. 评审者的四维修真量表 (Scoring Rubric)

所有经过 `Evaluator` 评估的产出，按照以下结构化比重进行算分（前两项具有一票否决权）：

1. **逻辑完备性 (Logic Closure / 40%) - 必须 100 分** 
   - [闭环检查] 所有使用到的 `{{var}}` 必须具有确定的源头。
   - [契约对齐] 子工作流的输入输出声明类型必须准确符合对接。
2. **安全与副作用控制 (Safety Gate / 30%) - 必须 100 分**
   - [规则优先] 静态代码扫描如果命中敏感命令（`DROP`, `rm`），绝对不允许 LLM 将其降级，必须持有 `[DANGER]` 或 `[CONFIRM]` flag。
   - [越权防控] 不得出现不可控的 Shell 环境游离脚本。
3. **工程健壮性 (Engineering Quality / 20%) - 阈值 70 分 (第三轮可忽略)**
   - [步骤粒度] 是否因为将过多行为塞在了一个 Skill Parameter 中造成耦合。
4. **角色约束度 (Persona Adherence / 10%) - 阈值 60 分 (第三轮可忽略)**
   - [风格对齐] 注释、变量命名等是否符合 Pythonic 或指定的专家规范。

---
## 6. 关于版本管理：优胜劣汰 vs. 错误学习
“保留评分最高版本”是最高效的，但为了让系统具有“学习能力”

保留“当前最佳” (Champion)：即评分最高的 .step.md。

保留“最近失败反馈” (Last Failure Context)：在执行下一次生成时，必须带上上一次失败的原因。

存档历史 (Archive)：在物理存储上（.agent/logs/），保留所有的尝试记录。这样当用户最终介入人工干预时，他能看到 Agent 是怎么一步步挣扎并失败的，这有助于用户快速定位是需求太模糊还是模型能力不足。

## 7. 底层安全与隔离总结

在落地的实施细节中，这几项工程底线必须被贯彻：
1. **脱敏拦截 (Secret Scrubber)**：`sqlite` 落盘持久化 `input_json` 和 `output_json` 前，对 `required_secrets` 声明的变量抹除为 `***`，严禁真实 Token 进入磁盘长久保存。
2. **执行隔离 (Sandbox)**：条件求值 (`step.condition`) 的判断严禁使用 python 内置 `eval`，通过 `simpleeval` 进行 AST 拦截。
3. **类型安全解析**：变量插值 `{{var}}` 使用严格的数据类型深度递归检测拼接，杜绝生成非法 JSON 字符串。