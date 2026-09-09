"""
筱和灵眸(AethelEye) - SKU备注记忆服务

提供跨任务、跨链接的SKU备注匹配与记忆更新
"""
from typing import Optional, List, Dict
from sqlalchemy.orm import Session

from app.models.sku_note_memory import SKUNoteMemory


class SKUNoteMemoryService:
    """SKU备注记忆服务（保守匹配）"""

    @staticmethod
    def normalize_text(value: Optional[str]) -> str:
        if not value:
            return ""
        return " ".join(value.strip().lower().split())

    def match_note(
        self,
        session: Session,
        platform: str,
        shop_name: Optional[str],
        sku_name: str,
    ) -> Dict:
        """
        备注匹配（保守）：平台 + 店铺 + 规格名 精确归一化匹配

        返回:
            {
                "note": str | None,
                "conflict": bool,
                "candidates": List[str]
            }
        """
        shop_key = self.normalize_text(shop_name)
        sku_key = self.normalize_text(sku_name)
        if not sku_key:
            return {"note": None, "conflict": False, "candidates": []}

        rows = (
            session.query(SKUNoteMemory)
            .filter(
                SKUNoteMemory.platform == platform,
                SKUNoteMemory.shop_name_normalized == shop_key,
                SKUNoteMemory.sku_name_normalized == sku_key,
            )
            .all()
        )

        if not rows:
            return {"note": None, "conflict": False, "candidates": []}

        notes = sorted(list({(r.note or "").strip() for r in rows if (r.note or "").strip()}))
        if len(notes) == 1:
            return {"note": notes[0], "conflict": False, "candidates": notes}

        return {"note": None, "conflict": True, "candidates": notes}

    def upsert_note(
        self,
        session: Session,
        platform: str,
        shop_name: Optional[str],
        sku_name: str,
        note: str,
        user_id: Optional[int],
        task_id: Optional[int],
    ) -> Dict:
        """
        人工备注写入记忆（人工输入优先，可覆盖旧值）
        """
        note_clean = (note or "").strip()
        if not note_clean:
            return {"updated": False, "old_note": None, "new_note": None, "reason": "empty_note"}

        shop_key = self.normalize_text(shop_name)
        sku_key = self.normalize_text(sku_name)
        if not sku_key:
            return {"updated": False, "old_note": None, "new_note": None, "reason": "empty_sku"}

        memory = (
            session.query(SKUNoteMemory)
            .filter(
                SKUNoteMemory.platform == platform,
                SKUNoteMemory.shop_name_normalized == shop_key,
                SKUNoteMemory.sku_name_normalized == sku_key,
            )
            .first()
        )

        if not memory:
            memory = SKUNoteMemory(
                platform=platform,
                shop_name_normalized=shop_key,
                sku_name_normalized=sku_key,
                shop_name_display=(shop_name or "")[:200] or None,
                sku_name_display=sku_name[:500],
                note=note_clean,
                created_by=user_id,
                updated_by=user_id,
                last_task_id=task_id,
            )
            session.add(memory)
            return {"updated": True, "old_note": None, "new_note": note_clean, "reason": "created"}

        old_note = (memory.note or "").strip()
        if old_note == note_clean:
            memory.last_task_id = task_id
            memory.updated_by = user_id
            return {"updated": False, "old_note": old_note, "new_note": note_clean, "reason": "unchanged"}

        memory.note = note_clean
        memory.shop_name_display = (shop_name or "")[:200] or memory.shop_name_display
        memory.sku_name_display = sku_name[:500] or memory.sku_name_display
        memory.last_task_id = task_id
        memory.updated_by = user_id
        return {"updated": True, "old_note": old_note, "new_note": note_clean, "reason": "updated"}

    def delete_note(
        self,
        session: Session,
        platform: str,
        shop_name: Optional[str],
        sku_name: str,
    ) -> bool:
        """删除备注记忆（用户主动清除备注时调用）"""
        shop_key = self.normalize_text(shop_name)
        sku_key = self.normalize_text(sku_name)
        if not sku_key:
            return False
        deleted = (
            session.query(SKUNoteMemory)
            .filter(
                SKUNoteMemory.platform == platform,
                SKUNoteMemory.shop_name_normalized == shop_key,
                SKUNoteMemory.sku_name_normalized == sku_key,
            )
            .delete()
        )
        return deleted > 0


_service: Optional[SKUNoteMemoryService] = None


def get_sku_note_memory_service() -> SKUNoteMemoryService:
    global _service
    if _service is None:
        _service = SKUNoteMemoryService()
    return _service
