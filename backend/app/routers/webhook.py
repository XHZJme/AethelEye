"""
筱和灵眸(AethelEye) - Webhook配置API路由

企微Webhook配置管理
"""
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db_session
from app.models.webhook import WebhookConfig
from app.models.user import User
from app.middleware.permission import require_admin
from app.utils.encryption import decrypt_secret, encrypt_secret, is_encrypted_secret
from app.utils.logger import get_logger

# 日志
log = get_logger("audit")

# 路由
router = APIRouter(prefix="/api/webhook", tags=["Webhook配置"])


# ===== Pydantic模型 =====

class WebhookCreate(BaseModel):
    """创建Webhook请求"""
    name: str
    webhook_url: str
    webhook_type: str = "wecom"  # wecom/dingtalk/custom
    is_default: bool = False
    secret: Optional[str] = None
    mentioned_list: Optional[str] = None  # JSON数组字符串
    mentioned_mobile_list: Optional[str] = None  # JSON数组字符串
    msg_type: str = "markdown"  # text/markdown
    keyword: Optional[str] = None


class WebhookUpdate(BaseModel):
    """更新Webhook请求"""
    name: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_type: Optional[str] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    secret: Optional[str] = None
    mentioned_list: Optional[str] = None
    mentioned_mobile_list: Optional[str] = None
    msg_type: Optional[str] = None
    keyword: Optional[str] = None


class WebhookResponse(BaseModel):
    """Webhook响应"""
    id: int
    name: str
    webhook_url: str
    webhook_type: str
    is_default: bool
    is_active: bool
    created_at: datetime
    secret: Optional[str] = None
    mentioned_list: Optional[str] = None
    mentioned_mobile_list: Optional[str] = None
    msg_type: str = "markdown"
    keyword: Optional[str] = None
    webhook_url_configured: bool = False
    secret_configured: bool = False

    class Config:
        from_attributes = True


class WebhookListResponse(BaseModel):
    """Webhook列表响应"""
    total: int
    webhooks: List[WebhookResponse]


MASKED_SECRET = "••••••••（已配置）"


def _validate_webhook_url(value: str) -> str:
    """只接受结构完整的 HTTP(S) Webhook 地址。"""
    from urllib.parse import urlparse

    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Webhook URL格式无效")
    return value


def _migrate_legacy_secrets(webhook: WebhookConfig, session: Session) -> None:
    """将旧版明文配置迁移为带版本前缀的密文。"""
    changed = False
    for field in ("webhook_url", "secret"):
        value = getattr(webhook, field, None)
        if value and not is_encrypted_secret(value):
            setattr(webhook, field, encrypt_secret(value))
            changed = True
    if changed:
        session.commit()


def _webhook_response(webhook: WebhookConfig) -> WebhookResponse:
    """返回脱敏后的配置，避免机器人密钥经 API 回显。"""
    return WebhookResponse(
        id=webhook.id,
        name=webhook.name,
        webhook_url=MASKED_SECRET if webhook.webhook_url else "",
        webhook_type=webhook.webhook_type,
        is_default=webhook.is_default,
        is_active=webhook.is_active,
        created_at=webhook.created_at,
        secret=MASKED_SECRET if webhook.secret else None,
        mentioned_list=webhook.mentioned_list,
        mentioned_mobile_list=webhook.mentioned_mobile_list,
        msg_type=webhook.msg_type or "markdown",
        keyword=webhook.keyword,
        webhook_url_configured=bool(webhook.webhook_url),
        secret_configured=bool(webhook.secret),
    )


# ===== API端点 =====

@router.get("", response_model=WebhookListResponse)
def list_webhooks(
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """获取Webhook配置列表"""
    webhooks = session.query(WebhookConfig).order_by(WebhookConfig.id).all()
    for webhook in webhooks:
        _migrate_legacy_secrets(webhook, session)
    return WebhookListResponse(
        total=len(webhooks),
        webhooks=[_webhook_response(w) for w in webhooks]
    )


@router.post("", response_model=WebhookResponse)
def create_webhook(
    request: WebhookCreate,
    http_request: Request,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """创建Webhook配置"""
    # 验证类型
    if request.webhook_type not in ("wecom", "dingtalk", "custom"):
        raise HTTPException(status_code=400, detail="类型必须是 wecom/dingtalk/custom")

    webhook_url = _validate_webhook_url(request.webhook_url)

    # 如果设置为默认，取消其他默认
    if request.is_default:
        session.query(WebhookConfig).filter(WebhookConfig.is_default == True).update({"is_default": False})

    webhook = WebhookConfig(
        name=request.name,
        webhook_url=encrypt_secret(webhook_url),
        webhook_type=request.webhook_type,
        is_default=request.is_default,
        is_active=True,
        secret=encrypt_secret(request.secret.strip()) if request.secret and request.secret.strip() else None,
        mentioned_list=request.mentioned_list,
        mentioned_mobile_list=request.mentioned_mobile_list,
        msg_type=request.msg_type,
        keyword=request.keyword,
    )
    session.add(webhook)
    session.commit()

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"Webhook配置已创建",
        user_id=admin.id,
        data={
            "webhook_id": webhook.id,
            "name": webhook.name,
            "operator": admin.username,
            "ip": ip_address,
        }
    )

    return _webhook_response(webhook)


@router.get("/{webhook_id}", response_model=WebhookResponse)
def get_webhook(
    webhook_id: int,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """获取单个Webhook配置"""
    webhook = session.query(WebhookConfig).filter(WebhookConfig.id == webhook_id).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="配置不存在")
    _migrate_legacy_secrets(webhook, session)
    return _webhook_response(webhook)


@router.put("/{webhook_id}", response_model=WebhookResponse)
def update_webhook(
    webhook_id: int,
    request: WebhookUpdate,
    http_request: Request,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """更新Webhook配置"""
    webhook = session.query(WebhookConfig).filter(WebhookConfig.id == webhook_id).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="配置不存在")

    if request.name:
        webhook.name = request.name
    if request.webhook_url:
        webhook.webhook_url = encrypt_secret(_validate_webhook_url(request.webhook_url))
    if request.webhook_type:
        if request.webhook_type not in ("wecom", "dingtalk", "custom"):
            raise HTTPException(status_code=400, detail="类型必须是 wecom/dingtalk/custom")
        webhook.webhook_type = request.webhook_type
    if request.is_default:
        # 取消其他默认
        session.query(WebhookConfig).filter(
            WebhookConfig.is_default == True,
            WebhookConfig.id != webhook_id
        ).update({"is_default": False})
        webhook.is_default = True
    if request.is_active is not None:
        webhook.is_active = request.is_active
    if request.secret is not None:
        webhook.secret = encrypt_secret(request.secret.strip()) if request.secret.strip() else None
    if request.mentioned_list is not None:
        webhook.mentioned_list = request.mentioned_list
    if request.mentioned_mobile_list is not None:
        webhook.mentioned_mobile_list = request.mentioned_mobile_list
    if request.msg_type is not None:
        if request.msg_type not in ("text", "markdown"):
            raise HTTPException(status_code=400, detail="消息类型必须是 text/markdown")
        webhook.msg_type = request.msg_type
    if request.keyword is not None:
        webhook.keyword = request.keyword

    session.commit()

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"Webhook配置已更新",
        user_id=admin.id,
        data={
            "webhook_id": webhook_id,
            "operator": admin.username,
            "ip": ip_address,
        }
    )

    return _webhook_response(webhook)


@router.delete("/{webhook_id}")
def delete_webhook(
    webhook_id: int,
    http_request: Request,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """删除Webhook配置"""
    webhook = session.query(WebhookConfig).filter(WebhookConfig.id == webhook_id).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="配置不存在")

    session.delete(webhook)
    session.commit()

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"Webhook配置已删除",
        user_id=admin.id,
        data={
            "webhook_id": webhook_id,
            "operator": admin.username,
            "ip": ip_address,
        }
    )

    return {"message": "配置已删除"}


@router.post("/{webhook_id}/test")
async def test_webhook(
    webhook_id: int,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """测试Webhook推送"""
    import httpx

    webhook = session.query(WebhookConfig).filter(WebhookConfig.id == webhook_id).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="配置不存在")

    _migrate_legacy_secrets(webhook, session)
    webhook_url = decrypt_secret(webhook.webhook_url)
    if not webhook_url:
        raise HTTPException(status_code=400, detail="Webhook 地址无法解密，请重新保存配置")

    # 构建测试消息（使用配置的消息类型和@人设置）
    import json as _json
    test_content = f"【筱和灵眸测试消息】\n时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n由 {admin.username} 发送测试"

    # 关键词前缀
    keyword = webhook.keyword or ''
    if keyword and keyword not in test_content:
        test_content = f"{keyword}\n{test_content}"

    msg_type = webhook.msg_type or 'markdown'

    if webhook.webhook_type == "wecom":
        if msg_type == "text":
            test_message: dict = {
                "msgtype": "text",
                "text": {"content": test_content}
            }
            # @人
            if webhook.mentioned_list:
                try:
                    test_message["text"]["mentioned_list"] = _json.loads(webhook.mentioned_list)
                except Exception:
                    pass
            if webhook.mentioned_mobile_list:
                try:
                    test_message["text"]["mentioned_mobile_list"] = _json.loads(webhook.mentioned_mobile_list)
                except Exception:
                    pass
        else:
            at_suffix = ""
            if webhook.mentioned_list:
                try:
                    uids = _json.loads(webhook.mentioned_list)
                    at_suffix = "\n" + " ".join(f"<@{uid}>" for uid in uids if uid != "@all")
                    if "@all" in uids:
                        at_suffix += " @所有人"
                except Exception:
                    pass
            test_message = {
                "msgtype": "markdown",
                "markdown": {"content": test_content + at_suffix}
            }
    elif webhook.webhook_type == "dingtalk":
        test_message = {
            "msgtype": "markdown",
            "markdown": {"title": "筱和灵眸测试", "text": test_content}
        }
        if webhook.mentioned_mobile_list:
            try:
                mobiles = _json.loads(webhook.mentioned_mobile_list)
                test_message["at"] = {"atMobiles": mobiles, "isAtAll": "@all" in mobiles}
            except Exception:
                pass
    else:
        test_message = {
            "msgtype": "text",
            "text": {"content": test_content}
        }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, json=test_message)

            if response.status_code == 200:
                result = response.json()
                if result.get("errcode") == 0:
                    log.info(f"Webhook测试成功", data={"webhook_id": webhook_id})
                    return {"success": True, "message": "推送成功"}
                else:
                    return {"success": False, "message": f"企微返回错误: {result.get('errmsg')}"}
            else:
                return {"success": False, "message": f"HTTP错误: {response.status_code}"}

    except Exception as e:
        log.error("Webhook测试失败", data={"webhook_id": webhook_id, "error_type": type(e).__name__})
        return {"success": False, "message": "推送失败，请检查地址、网络和机器人配置"}
