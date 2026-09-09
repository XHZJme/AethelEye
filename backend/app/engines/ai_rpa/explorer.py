"""
筱和灵眸(AethelEye) - AI RPA Explorer

Explore 模式核心循环：
  截图 → LLM 推理 → 执行动作 → 截图验证 → 循环 → 编译 Workflow

⚠️ 参考 Skyvern 逻辑自行实现，未使用任何 AGPL 代码。
"""
import base64
import json
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import Page

from app.engines.ai_rpa.workflow import Workflow, WorkflowStep, WorkflowValidation, get_workflow_store
from app.engines.ai_rpa.prompts.explore import (
    SYSTEM_PROMPT,
    EXPLORE_FIRST_ROUND,
    EXPLORE_NEXT_ROUND,
    VALIDATE_RESULT,
)
from app.services.llm.gateway import get_llm_gateway
from app.services.llm.service_resolver import get_service_model_or_default
from app.utils.logger import get_logger

log = get_logger("system")

# 默认 fallback 模型
DEFAULT_MODEL = "abab6.5s-chat"


async def _take_screenshot_base64(page: Page) -> str:
    """截图并转 base64"""
    buf = await page.screenshot(type="png", full_page=False)
    return base64.b64encode(buf).decode("utf-8")


def _parse_llm_response(text: str) -> Dict[str, Any]:
    """
    解析 LLM 返回的 JSON。
    兼容 markdown 代码块包裹。
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # 去掉首行 ```json 和末行 ```
        json_lines = []
        started = False
        for line in lines:
            if not started and line.strip().startswith("```"):
                started = True
                continue
            if started and line.strip() == "```":
                break
            if started:
                json_lines.append(line)
        cleaned = "\n".join(json_lines)
    return json.loads(cleaned)


async def _execute_action(page: Page, action: Dict[str, Any]) -> Dict[str, Any]:
    """
    在 Playwright Page 上执行 LLM 返回的操作指令。
    返回执行结果。
    """
    act = action.get("action", "")
    target = action.get("target", "")
    value = action.get("value", "")
    timeout = action.get("timeout_ms", 10000)
    result: Dict[str, Any] = {"action": act, "success": False}

    try:
        if act == "wait":
            await page.wait_for_selector(target, timeout=timeout)
            result["success"] = True
            result["detail"] = f"元素已出现: {target}"

        elif act == "click":
            elem = await page.wait_for_selector(target, timeout=timeout)
            if elem:
                await elem.click()
                await page.wait_for_timeout(500)  # 等待页面响应
                result["success"] = True
                result["detail"] = f"已点击: {target}"
            else:
                result["detail"] = f"元素未找到: {target}"

        elif act == "scroll":
            direction = action.get("direction", "down")
            pixels = action.get("pixels", 500)
            delta = pixels if direction == "down" else -pixels
            await page.mouse.wheel(0, delta)
            await page.wait_for_timeout(500)
            result["success"] = True
            result["detail"] = f"已滚动 {direction} {pixels}px"

        elif act == "type":
            elem = await page.wait_for_selector(target, timeout=timeout)
            if elem:
                await elem.fill(value)
                result["success"] = True
                result["detail"] = f"已输入: {value}"
            else:
                result["detail"] = f"输入框未找到: {target}"

        elif act == "extract":
            targets = action.get("targets", [target] if target else [])
            fields = action.get("fields", [])
            extracted = {}
            for i, sel in enumerate(targets):
                try:
                    elements = await page.query_selector_all(sel)
                    texts = []
                    for el in elements:
                        t = await el.text_content()
                        if t:
                            texts.append(t.strip())
                    field_name = fields[i] if i < len(fields) else f"field_{i}"
                    extracted[field_name] = texts
                except Exception:
                    pass
            result["success"] = True
            result["data"] = extracted
            result["detail"] = f"已提取 {len(extracted)} 个字段"

        elif act == "done":
            result["success"] = True
            result["data"] = action.get("data", {})
            result["detail"] = "采集完成"

        elif act == "fail":
            result["success"] = False
            result["detail"] = action.get("reason", "LLM判定无法完成")

        else:
            result["detail"] = f"未知操作类型: {act}"

    except Exception as e:
        result["detail"] = f"执行失败: {str(e)}"
        result["traceback"] = traceback.format_exc()

    return result


async def explore(
    page: Page,
    url: str,
    platform: str,
    max_rounds: int = 10,
    timeout_seconds: int = 60,
    trace_id: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[Workflow]]:
    """
    Explore 模式主循环。

    Args:
        page: Playwright Page（已导航到目标页面）
        url: 目标 URL
        platform: 平台标识
        max_rounds: 最大探索轮数
        timeout_seconds: 总超时（秒）
        trace_id: 日志追踪 ID

    Returns:
        (extracted_data, compiled_workflow) — 成功时返回数据和编译的 Workflow
        (None, None) — 失败时
    """
    gateway = get_llm_gateway()
    model = get_service_model_or_default("ai_rpa", DEFAULT_MODEL)
    system_prompt = SYSTEM_PROMPT.format(max_rounds=max_rounds)

    history: List[Dict[str, Any]] = []
    extracted_data: Dict[str, Any] = {}
    compiled_steps: List[WorkflowStep] = []
    start_time = time.time()

    log.info(f"[AI-RPA] Explore开始", data={
        "url": url, "platform": platform, "model": model,
        "max_rounds": max_rounds, "trace_id": trace_id,
    })

    for round_num in range(1, max_rounds + 1):
        # 超时检查
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            log.warning(f"[AI-RPA] Explore超时 ({elapsed:.0f}s)", data={"trace_id": trace_id})
            break

        # 1. 截图
        try:
            screenshot_b64 = await _take_screenshot_base64(page)
        except Exception as e:
            log.error(f"[AI-RPA] 截图失败", data={"error": str(e), "trace_id": trace_id})
            break

        # 2. 构造 prompt
        if round_num == 1:
            user_prompt = EXPLORE_FIRST_ROUND.format(
                platform=platform, url=url, max_rounds=max_rounds,
            )
        else:
            user_prompt = EXPLORE_NEXT_ROUND.format(
                platform=platform, url=url,
                round=round_num, max_rounds=max_rounds,
                history=json.dumps(history[-3:], ensure_ascii=False),  # 最近3步
                extracted_data=json.dumps(extracted_data, ensure_ascii=False),
                last_action=history[-1].get("action", "") if history else "",
                last_result=history[-1].get("result", "") if history else "",
            )

        # 3. 调用 LLM（多模态：文本 + 截图）
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [
                {"type": "text", "text": user_prompt},
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
            llm_text = ""
            if response.choices and response.choices[0].message:
                llm_text = response.choices[0].message.content
        except Exception as e:
            log.error(f"[AI-RPA] LLM调用失败 (round {round_num})", data={
                "error": str(e), "trace_id": trace_id,
            })
            break

        # 4. 解析 LLM 返回
        try:
            action = _parse_llm_response(llm_text)
        except (json.JSONDecodeError, Exception) as e:
            log.warning(f"[AI-RPA] LLM返回解析失败", data={
                "raw": llm_text[:500], "error": str(e), "trace_id": trace_id,
            })
            # 给 LLM 一次修正机会
            history.append({"round": round_num, "action": "parse_error", "result": str(e)})
            continue

        act_type = action.get("action", "")
        log.info(f"[AI-RPA] Round {round_num}: {act_type}", data={
            "reasoning": action.get("reasoning", "")[:200],
            "target": action.get("target", ""),
            "trace_id": trace_id,
        })

        # 5. 检查终止条件
        if act_type == "done":
            extracted_data.update(action.get("data", {}))
            history.append({"round": round_num, "action": "done", "result": "success"})
            log.info(f"[AI-RPA] Explore成功完成 ({round_num}轮)", data={"trace_id": trace_id})

            # 编译 Workflow
            workflow = _compile_workflow(platform, url, compiled_steps, extracted_data)
            return extracted_data, workflow

        if act_type == "fail":
            log.warning(f"[AI-RPA] LLM判定无法完成", data={
                "reason": action.get("reason", ""), "trace_id": trace_id,
            })
            return None, None

        # 6. 执行操作
        exec_result = await _execute_action(page, action)
        history.append({
            "round": round_num,
            "action": act_type,
            "target": action.get("target", ""),
            "result": exec_result.get("detail", ""),
            "success": exec_result.get("success", False),
        })

        # 记录编译步骤
        compiled_steps.append(WorkflowStep(
            step=round_num,
            action=act_type,
            target=action.get("target"),
            value=action.get("value"),
            timeout_ms=action.get("timeout_ms", 10000),
            metadata={"reasoning": action.get("reasoning", "")},
        ))

        # 提取数据累积
        if "data" in exec_result:
            extracted_data.update(exec_result["data"])

    # 超时或轮数耗尽
    log.warning(f"[AI-RPA] Explore未在限制内完成", data={
        "rounds": max_rounds, "elapsed": time.time() - start_time, "trace_id": trace_id,
    })
    return None, None


def _compile_workflow(
    platform: str,
    url: str,
    steps: List[WorkflowStep],
    data: Dict[str, Any],
) -> Workflow:
    """将探索步骤编译为可回放 Workflow"""
    import re
    import time as _time

    # 生成 workflow ID
    ts = _time.strftime("%Y%m%d%H%M%S")
    wf_id = f"wf_{platform}_sku_price_{ts}"

    # 从 URL 生成匹配模式
    url_pattern = None
    if "tmall.com" in url:
        url_pattern = r"detail\.tmall\.com/item\.htm"
    elif "taobao.com" in url:
        url_pattern = r"item\.taobao\.com/item\.htm"
    elif "jd.com" in url:
        url_pattern = r"item\.jd\.com/\d+"

    wf = Workflow(
        id=wf_id,
        platform=platform,
        task_type="sku_price_collection",
        url_pattern=url_pattern,
        steps=steps,
        validation=WorkflowValidation(
            min_skus=1,
            must_have_title=True,
        ),
    )
    wf.record_success()

    # 持久化
    store = get_workflow_store()
    store.save(wf)

    log.info(f"[AI-RPA] Workflow已编译: {wf_id}", data={
        "platform": platform, "steps": len(steps),
    })
    return wf
