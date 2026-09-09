"""
筱和灵眸(AethelEye) - Explore 模式 Prompt 模板

所有 Prompt 集中管理，方便迭代优化。
LLM 返回 JSON 格式的操作指令。
"""

# ── 系统级 Prompt ─────────────────────────────────

SYSTEM_PROMPT = """你是筱和灵眸(AethelEye)的 AI RPA 引擎。你的任务是通过观察电商页面截图，推理出提取 SKU 到手价的操作步骤。

你必须以 JSON 格式回复，不要输出任何额外文本。

## 你能执行的操作类型：

| action | 说明 | 必需字段 |
|--------|------|----------|
| wait | 等待元素出现 | target(CSS选择器), timeout_ms |
| click | 点击元素 | target(CSS选择器) |
| scroll | 滚动页面 | direction(up/down), pixels |
| type | 输入文本 | target(CSS选择器), value |
| extract | 提取数据 | targets(CSS选择器列表), fields(字段名列表) |
| done | 采集完成 | data(提取到的数据) |
| fail | 无法完成 | reason(失败原因) |

## 关键约束：
- 每次只返回**一个**操作（单步执行，逐步推进）
- CSS选择器应尽量具体，优先用 data 属性或唯一 class
- 提取价格时注意区分原价、促销价、到手价
- 如果页面有 SKU 选择器（颜色/尺码），需要遍历所有组合
- 超过 {max_rounds} 轮仍未完成，返回 fail
"""

# ── 探索首轮 Prompt ───────────────────────────────

EXPLORE_FIRST_ROUND = """## 当前状态
- 平台: {platform}
- URL: {url}
- 目标: 提取所有 SKU 的到手价（含 SKU 名称）
- 当前轮次: 1/{max_rounds}

## 页面截图
[见图片]

## 任务
观察截图，判断当前页面状态，输出下一步操作。

回复格式（严格JSON）:
```json
{{
  "reasoning": "观察到xxx，判断需要xxx",
  "action": "操作类型",
  "target": "CSS选择器（如适用）",
  "value": "值（如适用）",
  "timeout_ms": 10000
}}
```"""

# ── 探索后续轮 Prompt ─────────────────────────────

EXPLORE_NEXT_ROUND = """## 当前状态
- 平台: {platform}
- URL: {url}
- 目标: 提取所有 SKU 的到手价
- 当前轮次: {round}/{max_rounds}
- 已执行操作: {history}
- 已提取数据: {extracted_data}

## 上一步操作结果
- 操作: {last_action}
- 结果: {last_result}

## 页面截图（操作后）
[见图片]

## 任务
根据操作结果和当前截图，判断下一步。如果已提取到足够数据，返回 done。

回复格式（严格JSON）:
```json
{{
  "reasoning": "基于上一步结果xxx，判断需要xxx",
  "action": "操作类型",
  "target": "CSS选择器（如适用）",
  "value": "值（如适用）",
  "data": {{}}
}}
```"""

# ── 结果验证 Prompt ───────────────────────────────

VALIDATE_RESULT = """## 验证采集结果
- 平台: {platform}
- URL: {url}
- 提取到的数据:
```json
{extracted_data}
```

## 页面截图（最终状态）
[见图片]

## 任务
验证提取到的数据是否完整、准确：
1. 是否包含所有可见的 SKU 选项？
2. 价格格式是否正确？
3. 是否遗漏了到手价（如满减/优惠券后价格）？

回复格式（严格JSON）:
```json
{{
  "valid": true/false,
  "confidence": 0.0-1.0,
  "issues": ["问题描述（如有）"],
  "corrected_data": {{}}
}}
```"""

# ── 自愈诊断 Prompt ───────────────────────────────

SELF_HEAL_DIAGNOSE = """## 回放失败诊断
- 平台: {platform}
- Workflow ID: {workflow_id}
- 失败步骤: Step {failed_step}
- 失败操作: {failed_action}
- 错误信息: {error_message}

## 页面截图（失败时）
[见图片]

## 任务
分析回放失败原因，判断是否可以修复：
1. 页面结构是否发生变化？
2. 目标元素是否存在但选择器变了？
3. 是否需要新增/删除步骤？

回复格式（严格JSON）:
```json
{{
  "diagnosis": "原因分析",
  "can_heal": true/false,
  "heal_strategy": "repair_selector / insert_step / remove_step / full_re_explore",
  "suggested_fix": {{
    "step": 步骤编号,
    "new_target": "新CSS选择器（如适用）",
    "new_action": "新操作（如适用）"
  }}
}}
```"""
