"""
筱和灵眸(AethelEye) - AI RPA Replayer

Replay 模式：回放已编译 Workflow，失败时触发自愈。

流程：
  1. 从 WorkflowStore 加载最佳 Workflow
  2. 按步骤顺序执行
  3. 步骤失败 → 调 LLM 诊断 → 尝试修复 → 或回退到 Explore
"""
import json
import traceback
import base64
from typing import Any, Dict, Optional, Tuple

from playwright.async_api import Page

from app.engines.ai_rpa.workflow import Workflow, WorkflowStep, get_workflow_store
from app.engines.ai_rpa.explorer import _execute_action, _take_screenshot_base64, _parse_llm_response, explore
from app.engines.ai_rpa.prompts.explore import SYSTEM_PROMPT, SELF_HEAL_DIAGNOSE
from app.services.llm.gateway import get_llm_gateway
from app.services.llm.service_resolver import get_service_model_or_default
from app.utils.logger import get_logger

log = get_logger("system")

DEFAULT_MODEL = "abab6.5s-chat"


async def replay(
    page: Page,
    workflow: Workflow,
    url: str,
    platform: str,
    max_heal_attempts: int = 2,
    timeout_seconds: int = 60,
    trace_id: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    """
    回放 Workflow。

    Args:
        page: Playwright Page（已导航到目标页面）
        workflow: 要回放的 Workflow
        url: 目标 URL
        platform: 平台标识
        max_heal_attempts: 最大自愈尝试次数
        timeout_seconds: 总超时
        trace_id: 日志追踪 ID

    Returns:
        (extracted_data, success) — 成功时返回提取的数据
    """
    log.info(f"[AI-RPA] Replay开始: {workflow.id}", data={
        "steps": len(workflow.steps),
        "success_rate": f"{workflow.success_rate:.0%}",
        "trace_id": trace_id,
    })

    extracted_data: Dict[str, Any] = {}
    import time
    start_time = time.time()

    for step in workflow.steps:
        # 超时检查
        if time.time() - start_time > timeout_seconds:
            log.warning(f"[AI-RPA] Replay超时", data={"trace_id": trace_id})
            workflow.record_failure()
            get_workflow_store().save(workflow)
            return None, False

        # 构造 action dict
        action = {
            "action": step.action,
            "target": step.target,
            "value": step.value,
            "timeout_ms": step.timeout_ms,
        }
        if step.extract_fields:
            action["fields"] = step.extract_fields

        log.info(f"[AI-RPA] Replay Step {step.step}: {step.action}", data={
            "target": step.target, "trace_id": trace_id,
        })

        # 执行
        result = await _execute_action(page, action)

        if result.get("success"):
            if "data" in result:
                extracted_data.update(result["data"])
            continue

        # 步骤失败 → 尝试自愈
        log.warning(f"[AI-RPA] Replay Step {step.step} 失败", data={
            "action": step.action,
            "detail": result.get("detail", ""),
            "trace_id": trace_id,
        })

        healed = await _try_self_heal(
            page=page,
            workflow=workflow,
            failed_step=step,
            error_message=result.get("detail", ""),
            platform=platform,
            max_attempts=max_heal_attempts,
            trace_id=trace_id,
        )

        if not healed:
            workflow.record_failure()
            get_workflow_store().save(workflow)
            return None, False

    # 全部步骤执行完成
    workflow.record_success()
    get_workflow_store().save(workflow)
    log.info(f"[AI-RPA] Replay成功: {workflow.id}", data={
        "extracted_fields": list(extracted_data.keys()),
        "trace_id": trace_id,
    })
    return extracted_data, True


async def _try_self_heal(
    page: Page,
    workflow: Workflow,
    failed_step: WorkflowStep,
    error_message: str,
    platform: str,
    max_attempts: int = 2,
    trace_id: Optional[str] = None,
) -> bool:
    """
    尝试自愈：调 LLM 诊断失败原因，修复 Workflow 步骤。

    Returns:
        True = 自愈成功（步骤已执行）
        False = 自愈失败（需要 fallback 到 Explore）
    """
    gateway = get_llm_gateway()
    model = get_service_model_or_default("ai_rpa", DEFAULT_MODEL)

    for attempt in range(1, max_attempts + 1):
        log.info(f"[AI-RPA] 自愈尝试 {attempt}/{max_attempts}", data={
            "workflow": workflow.id, "step": failed_step.step, "trace_id": trace_id,
        })

        try:
            screenshot_b64 = await _take_screenshot_base64(page)
        except Exception:
            return False

        # 构造诊断 prompt
        prompt = SELF_HEAL_DIAGNOSE.format(
            platform=platform,
            workflow_id=workflow.id,
            failed_step=failed_step.step,
            failed_action=f"{failed_step.action} → {failed_step.target}",
            error_message=error_message,
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT.format(max_rounds=10)},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}},
            ]},
        ]

        try:
            response = await gateway.chat(
                messages=messages,
                model=model,
                temperature=0.1,
                max_tokens=1024,
                source="ai_rpa",
            )
            llm_text = response.choices[0].message.content if response.choices else ""
            diagnosis = _parse_llm_response(llm_text)
        except Exception as e:
            log.warning(f"[AI-RPA] 自愈LLM调用失败", data={"error": str(e), "trace_id": trace_id})
            continue

        can_heal = diagnosis.get("can_heal", False)
        strategy = diagnosis.get("heal_strategy", "")

        log.info(f"[AI-RPA] 诊断结果", data={
            "diagnosis": diagnosis.get("diagnosis", "")[:200],
            "can_heal": can_heal,
            "strategy": strategy,
            "trace_id": trace_id,
        })

        if not can_heal:
            return False

        if strategy == "full_re_explore":
            return False  # 让上层触发完整 Explore

        # 尝试用修复后的选择器重新执行
        fix = diagnosis.get("suggested_fix", {})
        new_target = fix.get("new_target", failed_step.target)
        new_action = fix.get("new_action", failed_step.action)

        fixed_action = {
            "action": new_action,
            "target": new_target,
            "value": failed_step.value,
            "timeout_ms": failed_step.timeout_ms,
        }

        result = await _execute_action(page, fixed_action)
        if result.get("success"):
            # 更新 Workflow 中的步骤
            failed_step.target = new_target
            failed_step.action = new_action
            get_workflow_store().save(workflow)
            log.info(f"[AI-RPA] 自愈成功", data={
                "strategy": strategy, "new_target": new_target, "trace_id": trace_id,
            })
            return True

        error_message = result.get("detail", "修复后仍然失败")

    return False


async def replay_or_explore(
    page: Page,
    url: str,
    platform: str,
    max_explore_rounds: int = 10,
    timeout_seconds: int = 60,
    trace_id: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[Workflow]]:
    """
    先尝试 Replay，失败则 Explore。

    这是 AI RPA 引擎的主入口。

    Returns:
        (extracted_data, workflow) 或 (None, None)
    """
    store = get_workflow_store()

    # 1. 尝试找到匹配的 Workflow
    workflow = store.find_best_for_url(url, platform)

    if workflow and workflow.success_rate >= 0.3:
        log.info(f"[AI-RPA] 找到缓存Workflow: {workflow.id} (成功率 {workflow.success_rate:.0%})")

        data, success = await replay(
            page=page,
            workflow=workflow,
            url=url,
            platform=platform,
            timeout_seconds=timeout_seconds,
            trace_id=trace_id,
        )

        if success and data:
            return data, workflow

        log.info(f"[AI-RPA] Replay失败，降级到Explore模式", data={"trace_id": trace_id})

    # 2. Explore 模式
    return await explore(
        page=page,
        url=url,
        platform=platform,
        max_rounds=max_explore_rounds,
        timeout_seconds=timeout_seconds,
        trace_id=trace_id,
    )
