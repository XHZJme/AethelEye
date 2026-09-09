"""
筱和灵眸(AethelEye) - 采集引擎抽象基类

可插拔引擎架构：
  - BaseCollectionEngine 定义统一接口
  - 具体引擎（Playwright / AI-RPA / 第三方）继承并实现
  - CollectionResult 为各引擎共享的数据结构
  - engine_registry 管理引擎注册与切换

引擎合约：
  1. collect()        → 执行完整采集，返回 CollectionResult
  2. collect_for_parse() → 轻量解析，返回 dict
  3. parse_product_url() → 识别 URL 平台
  4. get_profile_lock()  → 并发控制锁
"""
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple


@dataclass
class CollectionResult:
    """
    采集结果（所有引擎共享）

    Attributes:
        success: 是否成功
        product_title: 商品标题
        shop_name: 店铺名称
        skus: SKU列表 [{"name": ..., "price": ..., "sku_id": ...}, ...]
        screenshot_path: 截图文件名（相对路径）
        recording_path: 录屏文件名（相对路径）
        error: 错误信息
        duration_ms: 采集耗时（毫秒）
    """
    success: bool = False
    product_title: Optional[str] = None
    shop_name: Optional[str] = None
    skus: List[Dict[str, Any]] = field(default_factory=list)
    screenshot_path: Optional[str] = None
    recording_path: Optional[str] = None
    error: Optional[str] = None
    duration_ms: int = 0


class BaseCollectionEngine(ABC):
    """
    采集引擎抽象基类

    所有采集引擎必须实现此接口。
    系统通过 engine_registry 选择当前活跃引擎。
    """

    # 引擎标识（子类覆盖）
    ENGINE_NAME: str = "base"
    ENGINE_DISPLAY_NAME: str = "基础引擎"

    def __init__(self):
        self._profile_locks: Dict[int, asyncio.Lock] = {}

    def get_profile_lock(self, profile_id: int) -> asyncio.Lock:
        """获取指定 profile 的异步锁（惰性创建，确保同 profile 串行）"""
        if profile_id not in self._profile_locks:
            self._profile_locks[profile_id] = asyncio.Lock()
        return self._profile_locks[profile_id]

    @abstractmethod
    async def collect(
        self,
        task,
        profile_id: int,
        headless: bool = True,
        record_video: bool = False,
        trace_id: Optional[str] = None,
    ) -> CollectionResult:
        """
        执行采集任务

        Args:
            task: MonitorTask 或兼容对象（需有 id, url, platform 属性）
            profile_id: 浏览器配置ID
            headless: 是否静默模式
            record_video: 是否录屏
            trace_id: 日志追踪ID

        Returns:
            CollectionResult
        """
        ...

    @abstractmethod
    async def collect_for_parse(
        self,
        url: str,
        profile_id: int,
        headless: bool = True,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        轻量解析（创建任务前预览商品信息）

        Args:
            url: 商品URL
            profile_id: 浏览器配置ID
            headless: 是否静默模式
            trace_id: 日志追踪ID

        Returns:
            {"success": bool, "title": str, "shop_name": str, "skus": [...], "error": str}
        """
        ...

    @abstractmethod
    async def parse_product_url(self, url: str) -> Tuple[str, bool]:
        """
        解析商品URL，识别平台

        Returns:
            (platform, is_valid) — platform 如 "tmall"/"taobao"/"jd"/"unknown"
        """
        ...

    def get_engine_info(self) -> Dict[str, Any]:
        """返回引擎元信息"""
        return {
            "name": self.ENGINE_NAME,
            "display_name": self.ENGINE_DISPLAY_NAME,
        }
