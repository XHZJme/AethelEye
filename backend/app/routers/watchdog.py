"""
筱和灵眸(AethelEye) - AI Watchdog API

端点：
  GET    /api/watchdog/status           — 看门狗状态
  GET    /api/watchdog/reports          — 最近报告
  GET    /api/watchdog/memory           — AI 三层记忆摘要
  GET    /api/watchdog/memory/search    — 跨层语义搜索
  POST   /api/watchdog/memory/promote   — 短期→长期提升
  DELETE /api/watchdog/memory/{id}      — 删除记忆条目
  POST   /api/watchdog/memory/short     — 添加短期记忆
  POST   /api/watchdog/memory/entity    — 创建/更新实体
  POST   /api/watchdog/start            — 启动看门狗
  POST   /api/watchdog/stop             — 停止看门狗
"""
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.services.ai_watchdog import get_watchdog
from app.middleware.permission import require_admin
from app.utils.logger import get_logger

log = get_logger("system")
router = APIRouter(prefix="/api/watchdog", tags=["watchdog"])


# ── 请求体模型 ──────────────────────────────────

class PromoteRequest(BaseModel):
    memory_id: str

class ShortTermRequest(BaseModel):
    content: str
    source: str = "user"
    ttl: str = "2h"

class EntityRequest(BaseModel):
    name: str
    entity_type: str
    properties: Optional[Dict] = None
    relations: Optional[List[Dict]] = None


# ── 基础端点 ────────────────────────────────────

@router.get("/status")
def watchdog_status(current_user=Depends(require_admin)):
    """获取看门狗状态"""
    wd = get_watchdog()
    return {
        "is_running": wd.is_running,
        "autonomy_level": wd.autonomy_level,
        "recent_reports_count": len(wd.recent_reports),
    }


@router.get("/reports")
def watchdog_reports(current_user=Depends(require_admin)):
    """获取最近报告"""
    wd = get_watchdog()
    return {"reports": wd.recent_reports}


@router.post("/start")
def start_watchdog(current_user=Depends(require_admin)):
    """启动看门狗"""
    wd = get_watchdog()
    if wd.is_running:
        return {"message": "看门狗已在运行中"}
    wd.start()
    return {"message": "看门狗已启动"}


@router.post("/stop")
def stop_watchdog(current_user=Depends(require_admin)):
    """停止看门狗"""
    wd = get_watchdog()
    if not wd.is_running:
        return {"message": "看门狗未运行"}
    wd.stop()
    return {"message": "看门狗已停止"}


# ── 三层记忆端点 ────────────────────────────────

@router.get("/memory")
def watchdog_memory(current_user=Depends(require_admin)):
    """获取 AI 三层记忆摘要"""
    wd = get_watchdog()
    return {"memory": wd.memory_summary}


@router.get("/memory/search")
def memory_search(q: str = Query("", description="搜索关键词"),
                  current_user=Depends(require_admin)):
    """跨层语义搜索记忆"""
    wd = get_watchdog()
    if not q.strip():
        return {"results": []}
    results = wd.memory.search(q.strip())
    return {"results": results}


@router.post("/memory/promote")
def memory_promote(body: PromoteRequest, current_user=Depends(require_admin)):
    """将短期记忆提升为长期记忆"""
    wd = get_watchdog()
    ok = wd.memory.promote(body.memory_id)
    if ok:
        return {"message": "已提升为长期记忆"}
    return {"message": "未找到该短期记忆", "success": False}


@router.delete("/memory/{memory_id}")
def memory_delete(memory_id: str, current_user=Depends(require_admin)):
    """删除任意层级的记忆条目"""
    wd = get_watchdog()
    ok = wd.memory.delete(memory_id)
    if ok:
        return {"message": "已删除"}
    return {"message": "未找到该记忆条目", "success": False}


@router.post("/memory/short")
def memory_add_short(body: ShortTermRequest, current_user=Depends(require_admin)):
    """添加短期记忆条目"""
    wd = get_watchdog()
    entry = wd.memory.add_short_term(body.content, source=body.source, ttl=body.ttl)
    return {"entry": entry}


@router.post("/memory/entity")
def memory_upsert_entity(body: EntityRequest, current_user=Depends(require_admin)):
    """创建或更新实体"""
    wd = get_watchdog()
    entity = wd.memory.upsert_entity(
        name=body.name,
        entity_type=body.entity_type,
        properties=body.properties,
        relations=body.relations,
    )
    return {"entity": entity}
