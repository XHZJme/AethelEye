"""
筱和灵眸(AethelEye) - 监控任务API路由

监控任务的CRUD操作、立即采集、SKU配置等
"""
from datetime import datetime, timedelta
from typing import List, Optional
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
import asyncio
import sys
import json

from app.database import get_db_session
from app.models.task import MonitorTask
from app.models.sku import SKU
from app.models.price_record import PriceRecord
from app.models.sku_change_event import SKUChangeEvent
from app.models.sku_note_memory import SKUNoteMemory
from app.models.alert import Alert
from app.models.browser import BrowserProfile
from app.models.settings_model import SystemSettings
from app.models.webhook import WebhookConfig
from app.models.user import User
from app.middleware.permission import require_login, require_operator, require_admin
from app.services.sku_note_memory_service import get_sku_note_memory_service
from app.services.engine_registry import get_engine
from app.utils.logger import get_logger
from pathlib import Path
from app.config import settings

# 日志
log = get_logger("audit")

# 路由
router = APIRouter(prefix="/api/tasks", tags=["监控任务"])


def _normalize_and_validate_product_url(raw_url: str) -> str:
    """
    商品链接安全校验 + 清洗：
    - 仅允许 http/https
    - 仅允许 taobao/tmall 相关域名
    - 剥离生意参谋/千牛/spm等商家后台跟踪参数，只保留商品核心参数
    """
    url = (raw_url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="商品链接不能为空")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="商品链接必须使用 http 或 https 协议")

    host = (parsed.hostname or "").lower()
    allowed_hosts = (
        "taobao.com",
        "tmall.com",
        "tb.cn",
    )
    if not host or not any(host == d or host.endswith(f".{d}") for d in allowed_hosts):
        raise HTTPException(status_code=400, detail="无效的商品链接，仅支持天猫/淘宝")

    # 清洗跟踪参数：剥离生意参谋/千牛/spm等商家后台参数
    _STRIP_PARAMS = {
        "spm", "b_spm", "b_spm_log", "b_s_f",
        "mi_id", "sycm", "scm", "utparam",
        "pvid", "pos", "acm", "item_id_from",
        "ns", "abbucket", "ali_refid", "ali_trackid",
        "bxsign",
    }
    if parsed.query:
        from urllib.parse import parse_qs, urlencode
        qs = parse_qs(parsed.query, keep_blank_values=True)
        cleaned_qs = {k: v for k, v in qs.items() if k not in _STRIP_PARAMS}
        cleaned_query = urlencode(cleaned_qs, doseq=True)
        parsed = parsed._replace(query=cleaned_query)

    return parsed.geturl()


def _validate_frequency_permission(frequency_minutes: int, user: User) -> None:
    """
    频率权限校验：
    - 低于30分钟仅允许超级管理员(admin)
    """
    if frequency_minutes <= 0:
        raise HTTPException(status_code=400, detail="采集频率必须大于0分钟")
    if frequency_minutes < 30 and user.role != "admin":
        raise HTTPException(status_code=403, detail="仅超级管理员可设置30分钟以下采集频率")


async def _collect_for_parse_via_engine(
    url: str,
    profile_id: int,
    headless: bool,
    trace_id: Optional[str] = None
):
    """
    通过全局单例引擎执行 parse，共享 profile 锁避免与正在进行的采集冲突。
    主事件循环已是 ProactorEventLoop，直接支持 Playwright。
    """
    engine = get_engine()
    async with engine.get_profile_lock(profile_id):
        return await engine.collect_for_parse(
            url=url,
            profile_id=profile_id,
            headless=headless,
            trace_id=trace_id
        )


# ===== Pydantic模型 =====

class TaskCreateRequest(BaseModel):
    """创建监控任务请求"""
    url: str
    frequency_minutes: int = 120
    browser_profile_id: Optional[int] = None
    webhook_config_id: Optional[int] = None
    recording_enabled: bool = False
    note: Optional[str] = None
    product_title: Optional[str] = None
    shop_name: Optional[str] = None

    # SKU配置（创建后配置）
    # skus: List[SKUConfig] = []


class SKUConfig(BaseModel):
    """配SKU配置"""
    sku_name: str
    sku_id_external: Optional[str] = None
    base_price: Optional[float] = None
    is_monitored: bool = True
    note: Optional[str] = None


class TaskUpdateRequest(BaseModel):
    """更新监控任务请求"""
    frequency_minutes: Optional[int] = None
    browser_profile_id: Optional[int] = None
    webhook_config_id: Optional[int] = None
    recording_enabled: Optional[bool] = None
    note: Optional[str] = None
    status: Optional[str] = None  # active/paused


class TaskResponse(BaseModel):
    """监控任务响应"""
    id: int
    url: str
    platform: str
    product_title: Optional[str]
    shop_name: Optional[str]
    product_image: Optional[str]
    frequency_minutes: int
    status: str
    last_check_at: Optional[datetime]
    next_check_at: Optional[datetime]
    recording_enabled: bool
    last_error: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    """任务列表响应"""
    total: int
    tasks: List[TaskResponse]


class SKUResponse(BaseModel):
    """配SKU响应"""
    id: int
    sku_name: str
    sku_id_external: Optional[str]
    base_price: Optional[float]
    current_price: Optional[float]
    is_monitored: bool
    status: str
    note: Optional[str] = None
    sort_order: int = 0
    last_updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class TaskAlertItem(BaseModel):
    """任务详情内的异动记录"""
    id: int
    sku_id: int
    alert_type: str
    base_price: float
    alert_price: float
    price_diff: float
    price_diff_pct: float
    screenshot_path: Optional[str] = None
    status: str
    detected_at: Optional[datetime] = None
    sku_name: Optional[str] = None


class TaskDetailResponse(BaseModel):
    """任务详情响应"""
    task: TaskResponse
    skus: List[SKUResponse]
    sku_change_events: List[dict] = []
    alerts: List[TaskAlertItem] = []


class ParseURLResponse(BaseModel):
    """解析商品链接响应"""
    platform: str
    product_title: Optional[str]
    shop_name: Optional[str]
    product_image: Optional[str]
    skus: List[dict]


async def _parse_product_with_profile(
    *,
    url: str,
    session: Session,
    user: User,
    trace_prefix: str,
) -> ParseURLResponse:
    """复用链接解析主流程（创建前解析、已有任务重解析共用）"""
    safe_url = _normalize_and_validate_product_url(url)

    engine = get_engine()
    platform, is_valid = await engine.parse_product_url(safe_url)
    if not is_valid:
        raise HTTPException(status_code=400, detail="无效的商品链接，仅支持天猫/淘宝")

    profile = session.query(BrowserProfile).filter(BrowserProfile.is_active == True).first()
    if not profile:
        raise HTTPException(status_code=400, detail="没有可用的浏览器配置，请先在浏览器管理中添加配置")

    running_mode = "silent"
    mode_setting = session.query(SystemSettings).filter(SystemSettings.key == "running_mode").first()
    if mode_setting and mode_setting.value in ("silent", "visual"):
        running_mode = mode_setting.value

    profile_id = profile.id
    # 淘宝/天猫反爬检测 headless 指纹，解析链接必须使用非 headless 模式
    parse_headless = False

    try:
        trace_id = f"{trace_prefix}_{user.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        parsed_data = await asyncio.wait_for(
            _collect_for_parse_via_engine(
                safe_url,
                profile_id,
                parse_headless,
                trace_id,
            ),
            timeout=60,
        )

        if parsed_data.get("error"):
            log.warning(
                f"商品解析失败: {parsed_data['error']}",
                data={"url": safe_url, "running_mode": running_mode},
            )
            raise HTTPException(status_code=500, detail=f"页面解析失败: {parsed_data['error']}")

        shop_name = parsed_data.get("shop_name")
        skus = []
        memory_service = get_sku_note_memory_service()
        for sku in parsed_data.get("skus", []):
            sku_name = sku.get("name", "")
            memory_match = memory_service.match_note(
                session=session,
                platform=platform,
                shop_name=shop_name,
                sku_name=sku_name,
            )
            skus.append(
                {
                    "name": sku_name,
                    "price": sku.get("price", 0.0),
                    "sku_id": sku.get("sku_id"),
                    "note": memory_match.get("note"),
                    "note_conflict": memory_match.get("conflict", False),
                    "note_candidates": memory_match.get("candidates", []),
                }
            )

        title = parsed_data.get("title")
        valid_price_count = 0
        for sku in skus:
            try:
                if float(sku.get("price") or 0) > 0:
                    valid_price_count += 1
            except Exception:
                continue

        if not skus or (valid_price_count == 0 and not title):
            raise HTTPException(
                status_code=422,
                detail="页面可访问但未解析到有效SKU价格，请检查浏览器登录态或商品页反爬状态后重试",
            )

        log.info(
            "商品链接解析成功",
            data={
                "url": safe_url,
                "platform": platform,
                "running_mode": running_mode,
                "title": title,
                "sku_count": len(skus),
                "user": user.username,
            },
        )

        return ParseURLResponse(
            platform=platform,
            product_title=title or "未获取到标题",
            shop_name=shop_name or "未获取到店铺",
            product_image=None,
            skus=skus,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="解析超时（60秒），页面加载较慢，请稍后重试")


# ===== API端点 =====

@router.get("", response_model=TaskListResponse)
def list_tasks(
    platform: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_login)
):
    """
    获取监控任务列表（支持分页）
    """
    query = session.query(MonitorTask)

    # 筛选
    if platform:
        query = query.filter(MonitorTask.platform == platform)
    if status:
        if status == "has_error":
            query = query.filter(
                (MonitorTask.last_error.isnot(None)) & (MonitorTask.last_error != "")
                | MonitorTask.status.in_(["error", "need_login"])
            )
        else:
            query = query.filter(MonitorTask.status == status)

    # 搜索
    if search:
        query = query.filter(
            (MonitorTask.product_title.contains(search)) |
            (MonitorTask.shop_name.contains(search))
        )

    # 先查询总数
    total = query.count()

    # 分页查询
    page_size = min(max(page_size, 1), 100)  # 限制每页 1-100
    offset = (max(page, 1) - 1) * page_size
    tasks = query.order_by(MonitorTask.id.desc()).offset(offset).limit(page_size).all()

    return TaskListResponse(
        total=total,
        tasks=[TaskResponse.model_validate(t) for t in tasks]
    )


@router.post("/parse-url", response_model=ParseURLResponse)
async def parse_url(
    url: str,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_operator)
):
    """
    解析商品链接

    访问商品页面，返回实际的商品信息、SKU列表和到手价
    """
    try:
        return await _parse_product_with_profile(
            url=url,
            session=session,
            user=user,
            trace_prefix="parse",
        )
    except HTTPException:
        raise
    except Exception as e:
        # 避免日志格式化二次解析异常信息导致吞错
        log.error(f"解析过程异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"解析过程异常: {str(e)}")


@router.post("/{task_id}/reparse", response_model=ParseURLResponse)
async def reparse_task(
    task_id: int,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_operator),
):
    """对已有任务重新解析商品信息与SKU，并回写任务数据"""
    task = session.query(MonitorTask).filter(MonitorTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    try:
        parsed = await _parse_product_with_profile(
            url=task.url,
            session=session,
            user=user,
            trace_prefix=f"reparse_{task_id}",
        )

        task.product_title = parsed.product_title
        task.shop_name = parsed.shop_name
        task.last_error = None

        existing_skus = session.query(SKU).filter(SKU.task_id == task_id).all()
        existing_sku_map = {sku.sku_name: sku for sku in existing_skus}
        now = datetime.now()
        created_count = 0
        updated_count = 0

        for sku_data in parsed.skus:
            sku_name = (sku_data.get("name") or "").strip()
            if not sku_name:
                continue

            parsed_price = sku_data.get("price")
            try:
                parsed_price_num = float(parsed_price) if parsed_price is not None else None
            except (TypeError, ValueError):
                parsed_price_num = None
            if parsed_price_num is not None and parsed_price_num <= 0:
                parsed_price_num = None

            sku = existing_sku_map.get(sku_name)
            if sku:
                changed = False
                parsed_external_id = sku_data.get("sku_id")
                if parsed_external_id and sku.sku_id_external != parsed_external_id:
                    sku.sku_id_external = parsed_external_id
                    changed = True
                if parsed_price_num is not None:
                    sku.current_price = parsed_price_num
                    sku.last_updated_at = now
                    changed = True
                if changed:
                    updated_count += 1
                continue

            sku = SKU(
                task_id=task_id,
                sku_name=sku_name,
                sku_id_external=sku_data.get("sku_id"),
                current_price=parsed_price_num,
                is_monitored=True,
                status="normal",
                note=sku_data.get("note"),
                last_updated_at=now if parsed_price_num is not None else None,
            )
            session.add(sku)
            created_count += 1

        session.commit()

        log.info(
            "任务重解析完成",
            data={
                "task_id": task_id,
                "updated_by": user.username,
                "created_skus": created_count,
                "updated_skus": updated_count,
                "parsed_skus": len(parsed.skus),
            },
        )

        return parsed
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"任务重解析异常: {str(e)}", data={"task_id": task_id})
        raise HTTPException(status_code=500, detail=f"重解析失败: {str(e)}")


@router.post("", response_model=TaskResponse)
async def create_task(
    request: TaskCreateRequest,
    http_request: Request,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_operator)
):
    """
    创建监控任务
    """
    safe_url = _normalize_and_validate_product_url(request.url)
    request.url = safe_url

    _validate_frequency_permission(request.frequency_minutes, user)

    # 解析平台
    platform = "tmall"  # 默认
    if "taobao.com" in request.url:
        platform = "taobao"

    # 检查浏览器配置是否存在
    if request.browser_profile_id:
        profile = session.query(BrowserProfile).filter(BrowserProfile.id == request.browser_profile_id).first()
        if not profile:
            raise HTTPException(status_code=400, detail="浏览器配置不存在")
    else:
        # 使用默认配置
        profile = session.query(BrowserProfile).filter(BrowserProfile.id == 1).first()
        if not profile:
            raise HTTPException(status_code=400, detail="没有可用的浏览器配置")

    # 优先使用前端parse-url阶段拿到的信息，避免创建任务时再次重解析导致阻塞
    product_title = request.product_title
    shop_name = request.shop_name

    # 若前端未传，尝试短超时兜底解析（不影响任务创建）
    if not product_title and not shop_name:
        try:
            parsed_data = await asyncio.wait_for(
                _collect_for_parse_via_engine(
                    request.url,
                    profile.id,
                    True,
                    None
                ),
                timeout=8
            )
            if parsed_data.get("success"):
                product_title = parsed_data.get("title")
                shop_name = parsed_data.get("shop_name")
                log.info(f"创建任务时自动解析成功", data={"title": product_title, "shop": shop_name})
        except TimeoutError:
            log.warning("创建任务时自动解析超时，已降级为仅保存URL")
        except Exception as e:
            log.warning(f"创建任务时自动解析失败: {e}")

    # 检查Webhook配置是否存在
    if request.webhook_config_id:
        webhook = session.query(WebhookConfig).filter(WebhookConfig.id == request.webhook_config_id).first()
        if not webhook:
            raise HTTPException(status_code=400, detail="Webhook配置不存在")

    # 计算下次采集时间
    next_check_at = datetime.now() + timedelta(minutes=request.frequency_minutes)

    # 创建任务
    task = MonitorTask(
        url=request.url,
        platform=platform,
        product_title=product_title,
        shop_name=shop_name,
        frequency_minutes=request.frequency_minutes,
        browser_profile_id=request.browser_profile_id or profile.id,
        webhook_config_id=request.webhook_config_id,
        recording_enabled=request.recording_enabled,
        note=request.note,
        status="active",
        next_check_at=next_check_at,
        created_by=user.id,
    )

    session.add(task)
    session.commit()
    session.refresh(task)

    # 任务创建后立即同步到调度器，避免“新增任务不被定时执行”
    from app.services.scheduler_service import get_scheduler_service
    scheduler = get_scheduler_service()
    scheduler.register_task(task)

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"监控任务已创建",
        user_id=user.id,
        data={
            "task_id": task.id,
            "url": request.url,
            "platform": platform,
            "operator": user.username,
            "ip": ip_address,
        }
    )

    return TaskResponse.model_validate(task)


@router.get("/{task_id}", response_model=TaskDetailResponse)
def get_task(
    task_id: int,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_login)
):
    """
    获取监控任务详情（含SKU列表）
    """
    task = session.query(MonitorTask).filter(MonitorTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 获取SKU列表
    skus = session.query(SKU).filter(SKU.task_id == task_id).order_by(SKU.sort_order).all()

    events = (
        session.query(SKUChangeEvent)
        .filter(SKUChangeEvent.task_id == task_id)
        .order_by(SKUChangeEvent.changed_at.desc())
        .limit(50)
        .all()
    )

    event_data = []
    for event in events:
        event_data.append({
            "id": event.id,
            "task_id": event.task_id,
            "sku_id": event.sku_id,
            "sku_name": event.sku_name,
            "source": event.source,
            "change_type": event.change_type,
            "changed_fields": [f for f in (event.changed_fields or "").split(",") if f],
            "old_values": json.loads(event.old_values) if event.old_values else {},
            "new_values": json.loads(event.new_values) if event.new_values else {},
            "changed_by": event.changed_by,
            "changed_at": event.changed_at,
        })

    # 查询异动记录（降序，最新50条）
    alerts_raw = (
        session.query(Alert)
        .filter(Alert.task_id == task_id)
        .order_by(Alert.detected_at.desc())
        .limit(50)
        .all()
    )

    # 查 sku 名称映射
    sku_id_set = {a.sku_id for a in alerts_raw}
    sku_name_map = {}
    if sku_id_set:
        for s in session.query(SKU).filter(SKU.id.in_(sku_id_set)).all():
            sku_name_map[s.id] = s.sku_name

    alert_items = []
    for a in alerts_raw:
        alert_items.append(TaskAlertItem(
            id=a.id,
            sku_id=a.sku_id,
            alert_type=a.alert_type,
            base_price=float(a.base_price),
            alert_price=float(a.alert_price),
            price_diff=float(a.price_diff),
            price_diff_pct=float(a.price_diff_pct),
            screenshot_path=a.screenshot_path,
            status=a.status,
            detected_at=a.detected_at,
            sku_name=sku_name_map.get(a.sku_id),
        ))

    return TaskDetailResponse(
        task=TaskResponse.model_validate(task),
        skus=[SKUResponse.model_validate(s) for s in skus],
        sku_change_events=event_data,
        alerts=alert_items,
    )


@router.put("/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: int,
    request: TaskUpdateRequest,
    http_request: Request,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_operator)
):
    """
    更新监控任务
    """
    task = session.query(MonitorTask).filter(MonitorTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 更新字段
    if request.frequency_minutes is not None:
        _validate_frequency_permission(request.frequency_minutes, user)
        task.frequency_minutes = request.frequency_minutes
        # 更新下次采集时间
        if task.status == "active":
            task.next_check_at = datetime.now() + timedelta(minutes=request.frequency_minutes)

    if request.browser_profile_id:
        profile = session.query(BrowserProfile).filter(BrowserProfile.id == request.browser_profile_id).first()
        if not profile:
            raise HTTPException(status_code=400, detail="浏览器配置不存在")
        task.browser_profile_id = request.browser_profile_id

    if request.webhook_config_id:
        task.webhook_config_id = request.webhook_config_id

    if request.recording_enabled is not None:
        task.recording_enabled = request.recording_enabled

    if request.note is not None:
        task.note = request.note

    if request.status:
        if request.status not in ("active", "paused"):
            raise HTTPException(status_code=400, detail="状态必须是 active/paused")
        task.status = request.status
        if request.status == "active":
            task.next_check_at = datetime.now() + timedelta(minutes=task.frequency_minutes)
            # 恢复为活跃时清除旧的错误信息和风控状态，避免右上角状态指示器残留异常
            task.last_error = None
            task.risk_control_retries = 0
            if task.original_browser_profile_id:
                task.original_browser_profile_id = None
        else:
            task.next_check_at = None

    session.commit()

    # 任务更新后同步调度器（状态/频率/配置变更）
    from app.services.scheduler_service import get_scheduler_service
    scheduler = get_scheduler_service()
    if task.status == "active":
        scheduler.register_task(task)
    else:
        scheduler.remove_task(task.id)

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"监控任务已更新",
        user_id=user.id,
        data={
            "task_id": task_id,
            "operator": user.username,
            "ip": ip_address,
        }
    )

    return TaskResponse.model_validate(task)


@router.delete("/{task_id}")
def delete_task(
    task_id: int,
    http_request: Request,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_admin)
):
    """
    删除监控任务（仅管理员）
    """
    task = session.query(MonitorTask).filter(MonitorTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 先从调度器移除，避免删除后仍被触发
    from app.services.scheduler_service import get_scheduler_service
    scheduler = get_scheduler_service()
    scheduler.remove_task(task_id)

    # 删除关联的价格记录（避免孤儿数据）
    session.query(PriceRecord).filter(PriceRecord.task_id == task_id).delete()

    # 删除关联的异动记录与SKU变更节点（避免孤儿数据）
    session.query(Alert).filter(Alert.task_id == task_id).delete()
    session.query(SKUChangeEvent).filter(SKUChangeEvent.task_id == task_id).delete()

    # 删除最近由该任务写入的备注记忆（按last_task_id兜底清理）
    session.query(SKUNoteMemory).filter(SKUNoteMemory.last_task_id == task_id).delete()

    # 删除关联的SKU
    session.query(SKU).filter(SKU.task_id == task_id).delete()

    # 删除任务
    session.delete(task)
    session.commit()

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"监控任务已删除",
        user_id=user.id,
        data={
            "task_id": task_id,
            "operator": user.username,
            "ip": ip_address,
        }
    )

    return {"message": "任务已删除"}


@router.post("/{task_id}/run")
async def run_task_now(
    task_id: int,
    background_tasks: BackgroundTasks,
    http_request: Request,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_operator)
):
    """
    立即执行采集任务
    """
    task = session.query(MonitorTask).filter(MonitorTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status != "active":
        raise HTTPException(status_code=400, detail="任务已暂停，无法执行")

    # 获取浏览器配置
    profile = None
    if task.browser_profile_id:
        profile = session.query(BrowserProfile).filter(BrowserProfile.id == task.browser_profile_id).first()

    if not profile:
        raise HTTPException(status_code=400, detail="任务未配置浏览器，无法采集")

    # 通过调度器的并发控制派发（自动去重 + 信号量限流）
    from app.services.scheduler_service import get_scheduler_service
    scheduler = get_scheduler_service()
    import asyncio
    asyncio.create_task(scheduler._enqueue_collection_task(task.id))

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"手动触发采集",
        user_id=user.id,
        data={
            "task_id": task_id,
            "operator": user.username,
            "ip": ip_address,
        }
    )

    return {"message": "采集任务已启动", "task_id": task_id}


@router.post("/{task_id}/skus")
def configure_skus(
    task_id: int,
    skus: List[SKUConfig],
    http_request: Request,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_operator)
):
    """
    配置任务的SKU

    设置基准价格、是否监控等
    """
    task = session.query(MonitorTask).filter(MonitorTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    ip_address = http_request.client.host if http_request.client else "unknown"
    memory_service = get_sku_note_memory_service()

    # 更新SKU配置
    for sku_config in skus:
        sku = session.query(SKU).filter(SKU.task_id == task_id, SKU.sku_name == sku_config.sku_name).first()

        if sku:
            changed_fields = []
            old_values = {}
            new_values = {}

            if sku_config.base_price is not None:
                old_base_price = float(sku.base_price) if sku.base_price is not None else None
                sku.base_price = sku_config.base_price
                if old_base_price != sku_config.base_price:
                    changed_fields.append("base_price")
                    old_values["base_price"] = old_base_price
                    new_values["base_price"] = sku_config.base_price

            old_is_monitored = bool(sku.is_monitored)
            sku.is_monitored = sku_config.is_monitored
            if old_is_monitored != sku_config.is_monitored:
                changed_fields.append("is_monitored")
                old_values["is_monitored"] = old_is_monitored
                new_values["is_monitored"] = sku_config.is_monitored

            old_note = (sku.note or "").strip()
            if sku_config.note is not None:
                # 空字符串视为清除备注，存 None 保持数据干净
                sku.note = sku_config.note.strip() or None
            new_note = (sku.note or "").strip()
            if old_note != new_note:
                changed_fields.append("note")
                old_values["note"] = old_note
                new_values["note"] = new_note

                log.info(
                    "SKU备注已更新",
                    task_id=task_id,
                    sku_id=sku.id,
                    user_id=user.id,
                    ip=ip_address,
                    data={
                        "sku_name": sku.sku_name,
                        "old_note": old_note,
                        "new_note": new_note,
                        "action": "update",
                    }
                )

            if new_note:
                upsert_result = memory_service.upsert_note(
                    session=session,
                    platform=task.platform,
                    shop_name=task.shop_name,
                    sku_name=sku.sku_name,
                    note=new_note,
                    user_id=user.id,
                    task_id=task_id,
                )
                if upsert_result.get("updated"):
                    log.info(
                        "SKU备注记忆已更新",
                        task_id=task_id,
                        sku_id=sku.id,
                        user_id=user.id,
                        ip=ip_address,
                        data={
                            "sku_name": sku.sku_name,
                            "old_note": upsert_result.get("old_note"),
                            "new_note": upsert_result.get("new_note"),
                            "reason": upsert_result.get("reason"),
                        }
                    )
            elif old_note and not new_note:
                # 备注被清除，同步删除备注记忆
                memory_service.delete_note(
                    session=session,
                    platform=task.platform,
                    shop_name=task.shop_name,
                    sku_name=sku.sku_name,
                )

            if changed_fields:
                event = SKUChangeEvent(
                    task_id=task_id,
                    sku_id=sku.id,
                    sku_name=sku.sku_name,
                    source="manual",
                    change_type="config_update",
                    changed_fields=",".join(changed_fields),
                    old_values=json.dumps(old_values, ensure_ascii=False),
                    new_values=json.dumps(new_values, ensure_ascii=False),
                    changed_by=user.id,
                    changed_at=datetime.now(),
                )
                session.add(event)
        else:
            # 创建新SKU
            sku = SKU(
                task_id=task_id,
                sku_name=sku_config.sku_name,
                sku_id_external=sku_config.sku_id_external,
                base_price=sku_config.base_price,
                is_monitored=sku_config.is_monitored,
                note=sku_config.note,
            )
            session.add(sku)
            session.flush()

            event = SKUChangeEvent(
                task_id=task_id,
                sku_id=sku.id,
                sku_name=sku.sku_name,
                source="manual",
                change_type="created",
                changed_fields="base_price,is_monitored,note",
                old_values=json.dumps({}, ensure_ascii=False),
                new_values=json.dumps(
                    {
                        "base_price": sku_config.base_price,
                        "is_monitored": sku_config.is_monitored,
                        "note": (sku_config.note or "").strip(),
                    },
                    ensure_ascii=False,
                ),
                changed_by=user.id,
                changed_at=datetime.now(),
            )
            session.add(event)

            new_note = (sku_config.note or "").strip()
            if new_note:
                upsert_result = memory_service.upsert_note(
                    session=session,
                    platform=task.platform,
                    shop_name=task.shop_name,
                    sku_name=sku_config.sku_name,
                    note=new_note,
                    user_id=user.id,
                    task_id=task_id,
                )
                if upsert_result.get("updated"):
                    log.info(
                        "SKU备注记忆已创建",
                        task_id=task_id,
                        user_id=user.id,
                        ip=ip_address,
                        data={
                            "sku_name": sku_config.sku_name,
                            "new_note": upsert_result.get("new_note"),
                            "reason": upsert_result.get("reason"),
                            "action": "create",
                        }
                    )
    session.commit()
    log.info(
        f"SKU配置已更新",
        user_id=user.id,
        data={
            "task_id": task_id,
            "sku_count": len(skus),
            "operator": user.username,
            "ip": ip_address,
        }
    )

    return {"message": "SKU配置已更新"}


# ---------- 任务截图列表 ----------

@router.get("/{task_id}/screenshots")
def list_task_screenshots(
    task_id: int,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_login),
):
    """获取指定任务的截图列表（按时间倒序）"""
    task = session.query(MonitorTask).filter(MonitorTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    screenshots_dir = settings.screenshots_dir
    pattern = f"task_{task_id}_*.png"
    files = sorted(screenshots_dir.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)

    result = []
    for f in files[:20]:
        stat = f.stat()
        result.append({
            "filename": f.name,
            "size_kb": round(stat.st_size / 1024, 1),
            "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return {"screenshots": result}
