"""
筱和灵眸(AethelEye) - 录屏回放API

录屏文件管理
- 文件列表
- 关联查询
- 删除清理
"""
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path

from app.config import settings
from app.models.user import User
from app.middleware.permission import require_admin
from app.utils.logger import get_logger

# 日志
log = get_logger("system")

# 路由
router = APIRouter(prefix="/api/recordings", tags=["录屏回放"])


# ===== Pydantic模型 =====

class RecordingFile(BaseModel):
    """录屏文件"""
    filename: str
    path: str
    size_mb: float
    created_at: str
    task_id: Optional[int] = None


class RecordingListResponse(BaseModel):
    """录屏列表响应"""
    total: int
    recordings: List[RecordingFile]
    total_size_mb: float


# ===== API端点 =====

def _resolve_recording_path(filename: str) -> Path:
    """
    安全解析录屏文件路径，防止路径穿越。
    """
    if not filename or filename != Path(filename).name or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="非法文件名")
    if not filename.lower().endswith(".webm"):
        raise HTTPException(status_code=400, detail="仅支持webm录屏文件")

    root = settings.recordings_dir.resolve()
    target = (root / filename).resolve()
    if target.parent != root:
        raise HTTPException(status_code=400, detail="非法文件路径")
    return target

@router.get("", response_model=RecordingListResponse)
def list_recordings(
    task_id: Optional[int] = None,
    days: Optional[int] = None,
    user: User = Depends(require_admin)
):
    """获取录屏文件列表"""
    recordings_dir = settings.recordings_dir

    if not recordings_dir.exists():
        return RecordingListResponse(total=0, recordings=[], total_size_mb=0)

    recordings = []
    total_size = 0

    # 遍历录屏文件
    for file in recordings_dir.glob("*.webm"):
        # 获取文件信息
        stat = file.stat()
        size_mb = stat.st_size / (1024 * 1024)
        created_at = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

        # 时间筛选
        if days:
            file_date = datetime.fromtimestamp(stat.st_mtime)
            if file_date < datetime.now() - timedelta(days=days):
                continue

        # 解析文件名获取task_id
        task_id_from_file = None
        try:
            # 文件名格式: task_123_20260412_143000.webm
            parts = file.stem.split("_")
            if len(parts) >= 2 and parts[0] == "task":
                task_id_from_file = int(parts[1])
        except Exception:
            pass

        # 任务ID筛选
        if task_id and task_id_from_file != task_id:
            continue

        recordings.append(RecordingFile(
            filename=file.name,
            path=str(file),
            size_mb=round(size_mb, 2),
            created_at=created_at,
            task_id=task_id_from_file,
        ))

        total_size += size_mb

    # 按创建时间排序（最新的在前）
    recordings.sort(key=lambda x: x.created_at, reverse=True)

    return RecordingListResponse(
        total=len(recordings),
        recordings=recordings,
        total_size_mb=round(total_size, 2)
    )


@router.get("/storage-info")
def get_storage_info(
    user: User = Depends(require_admin)
):
    """获取录屏存储信息"""
    recordings_dir = settings.recordings_dir

    if not recordings_dir.exists():
        return {
            "exists": False,
            "total_files": 0,
            "total_size_mb": 0,
        }

    total_files = 0
    total_size = 0

    for file in recordings_dir.glob("*.webm"):
        total_files += 1
        total_size += file.stat().st_size

    return {
        "exists": True,
        "path": str(recordings_dir),
        "total_files": total_files,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
    }


@router.post("/cleanup")
def cleanup_old_recordings(
    days: int = 7,
    http_request: Request = None,
    user: User = Depends(require_admin)
):
    """清理旧录屏文件"""
    recordings_dir = settings.recordings_dir

    if not recordings_dir.exists():
        return {"message": "录屏目录不存在", "deleted_count": 0}

    deleted_count = 0
    cutoff_date = datetime.now() - timedelta(days=days)

    for file in recordings_dir.glob("*.webm"):
        file_date = datetime.fromtimestamp(file.stat().st_mtime)
        if file_date < cutoff_date:
            file.unlink()
            deleted_count += 1

    ip_address = http_request.client.host if http_request and http_request.client else "unknown"
    log.info(
        f"旧录屏文件已清理",
        data={
            "days": days,
            "deleted_count": deleted_count,
            "cleaned_by": user.username,
            "ip": ip_address,
        }
    )

    return {
        "message": f"已清理{deleted_count}个录屏文件",
        "deleted_count": deleted_count,
        "cutoff_days": days
    }


@router.get("/{filename}")
def get_recording(
    filename: str,
    user: User = Depends(require_admin)
):
    """获取录屏文件（用于播放）"""
    file_path = _resolve_recording_path(filename)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="录屏文件不存在")

    return FileResponse(
        file_path,
        media_type="video/webm",
        filename=filename
    )


@router.delete("/{filename}")
def delete_recording(
    filename: str,
    http_request: Request,
    user: User = Depends(require_admin)
):
    """删除录屏文件"""
    file_path = _resolve_recording_path(filename)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="录屏文件不存在")

    # 删除文件
    file_path.unlink()

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"录屏文件已删除",
        data={
            "filename": filename,
            "deleted_by": user.username,
            "ip": ip_address,
        }
    )

    return {
        "message": "录屏已删除"
    }
