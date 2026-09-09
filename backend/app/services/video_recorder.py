"""
筱和灵眸(AethelEye) - CDP Screencast 录屏器

基于 CDP Page.startScreencast + ffmpeg 管道实现 Page 级录屏
- 不需要关闭 BrowserContext 即可获取视频
- 兼容 persistent context（常驻浏览器模式）
- 使用 Playwright 内置 ffmpeg（libvpx VP8 编码）
"""
import asyncio
import base64
import subprocess
import os
from pathlib import Path
from typing import Optional
from playwright.async_api import Page, BrowserContext

from app.utils.logger import get_logger

log = get_logger("video_recorder")


def _find_ffmpeg() -> str:
    """
    查找 ffmpeg 可执行文件路径

    优先级：
    1. Playwright 内置 ffmpeg（ms-playwright 目录下）
    2. 系统 PATH 中的 ffmpeg

    Returns:
        ffmpeg 路径

    Raises:
        FileNotFoundError: 未找到 ffmpeg
    """
    import sys
    import shutil

    # Playwright 内置 ffmpeg - 扫描常见安装目录
    search_dirs = []

    # PyInstaller 打包环境
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys._MEIPASS)
        search_dirs.append(exe_dir / 'ms-playwright')

    # 用户本地 ms-playwright 目录
    if sys.platform == 'win32':
        local_app = os.environ.get("LOCALAPPDATA", "")
        if local_app:
            search_dirs.append(Path(local_app) / "ms-playwright")
    else:
        home = Path.home()
        search_dirs.append(home / ".cache" / "ms-playwright")

    # 扫描 ffmpeg 可执行文件
    ffmpeg_names = ["ffmpeg-win64.exe", "ffmpeg-linux", "ffmpeg-mac", "ffmpeg"]
    for base_dir in search_dirs:
        if not base_dir.exists():
            continue
        for item in base_dir.iterdir():
            if item.is_dir() and item.name.startswith("ffmpeg"):
                for name in ffmpeg_names:
                    candidate = item / name
                    if candidate.is_file():
                        return str(candidate)

    # 系统 PATH
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    raise FileNotFoundError(
        "未找到 ffmpeg。请运行 'python -m playwright install ffmpeg' 安装。"
    )


# 模块级缓存
_ffmpeg_path: Optional[str] = None


def _get_ffmpeg() -> str:
    global _ffmpeg_path
    if _ffmpeg_path is None:
        _ffmpeg_path = _find_ffmpeg()
    return _ffmpeg_path


class CDPVideoRecorder:
    """
    CDP Screencast 录屏器

    在已有的 persistent context 中对单个 Page 进行录屏，
    不需要关闭 context 即可获取视频文件。
    """

    def __init__(self):
        self._cdp_session = None
        self._ffmpeg_proc: Optional[subprocess.Popen] = None
        self._ack_task: Optional[asyncio.Task] = None
        self._ack_queue: Optional[asyncio.Queue] = None
        self._frame_count: int = 0
        self._recording: bool = False
        self._output_path: Optional[Path] = None

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def frame_count(self) -> int:
        return self._frame_count

    async def start(
        self,
        page: Page,
        output_path: Path,
        quality: int = 80,
        max_width: int = 1280,
        max_height: int = 720,
        every_nth_frame: int = 2,
    ) -> None:
        """
        开始录屏

        Args:
            page: 要录制的页面
            output_path: 输出视频文件路径 (.webm)
            quality: JPEG 质量 (1-100)
            max_width: 最大宽度
            max_height: 最大高度
            every_nth_frame: 每 N 帧捕获一次（降低开销）
        """
        if self._recording:
            log.warning("录屏器已在运行，先停止旧录屏")
            await self.stop()

        self._output_path = Path(output_path)
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        self._frame_count = 0

        # 启动 ffmpeg 管道（带监控风格时间戳水印）
        ffmpeg_path = _get_ffmpeg()

        # drawtext 滤镜：左上角实时时间戳（白字黑底半透明，等宽字体）
        # Windows 字体路径需要用 / 或双反斜杠，且用 : 转义
        import sys as _sys
        if _sys.platform == "win32":
            _font_file = "C\\\\:/Windows/Fonts/consola.ttf"
        else:
            _font_file = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

        drawtext_filter = (
            f"drawtext=fontfile='{_font_file}'"
            f":text='%{{localtime\\:%Y-%m-%d %H\\\\\\:%M\\\\\\:%S}}'"
            f":x=10:y=10:fontsize=18:fontcolor=white"
            f":box=1:boxcolor=black@0.6:boxborderw=5"
        )

        self._ffmpeg_proc = subprocess.Popen(
            [
                ffmpeg_path,
                "-y",
                "-loglevel", "warning",
                "-an",
                "-use_wallclock_as_timestamps", "1",
                "-f", "image2pipe",
                "-c:v", "mjpeg",
                "-i", "pipe:0",
                "-vf", drawtext_filter,
                "-c:v", "libvpx",
                "-pix_fmt", "yuv420p",
                "-r", "15",
                "-b:v", "500k",
                str(self._output_path),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # 创建 CDP session
        context = page.context
        self._cdp_session = await context.new_cdp_session(page)

        # ACK 队列和协程
        self._ack_queue = asyncio.Queue()

        def on_frame(params):
            data = base64.b64decode(params["data"])
            try:
                if self._ffmpeg_proc and self._ffmpeg_proc.stdin:
                    self._ffmpeg_proc.stdin.write(data)
                    self._ffmpeg_proc.stdin.flush()
                    self._frame_count += 1
            except (BrokenPipeError, OSError):
                pass
            self._ack_queue.put_nowait(params["sessionId"])

        self._cdp_session.on("Page.screencastFrame", on_frame)

        # ACK 协程：必须 ack 帧，否则浏览器停止发送
        async def ack_loop():
            while True:
                try:
                    sid = await asyncio.wait_for(self._ack_queue.get(), timeout=0.2)
                    await self._cdp_session.send(
                        "Page.screencastFrameAck", {"sessionId": sid}
                    )
                except asyncio.TimeoutError:
                    pass
                except asyncio.CancelledError:
                    break
                except Exception:
                    break

        self._ack_task = asyncio.create_task(ack_loop())

        # 启动 screencast
        await self._cdp_session.send("Page.startScreencast", {
            "format": "jpeg",
            "quality": quality,
            "maxWidth": max_width,
            "maxHeight": max_height,
            "everyNthFrame": every_nth_frame,
        })

        self._recording = True
        log.info("CDP录屏已启动", data={
            "output": str(self._output_path),
            "quality": quality,
            "every_nth_frame": every_nth_frame,
        })

    async def stop(self, timeout: int = 60) -> Optional[str]:
        """
        停止录屏并返回视频文件路径

        Args:
            timeout: 等待 ffmpeg 编码完成的超时秒数

        Returns:
            视频文件路径，失败返回 None
        """
        if not self._recording:
            return None

        self._recording = False

        # 停止 screencast
        try:
            if self._cdp_session:
                await self._cdp_session.send("Page.stopScreencast")
        except Exception as e:
            log.warning(f"停止screencast异常: {e}")

        # 等待最后几帧
        await asyncio.sleep(0.5)

        # 取消 ack 协程
        if self._ack_task:
            self._ack_task.cancel()
            try:
                await self._ack_task
            except asyncio.CancelledError:
                pass
            self._ack_task = None

        # 关闭 CDP session
        try:
            if self._cdp_session:
                await self._cdp_session.detach()
        except Exception:
            pass
        self._cdp_session = None

        # 关闭 ffmpeg 管道并等待编码完成
        video_path = None
        if self._ffmpeg_proc:
            try:
                self._ffmpeg_proc.stdin.close()
                _, stderr_bytes = self._ffmpeg_proc.communicate(timeout=timeout)
                stderr_text = stderr_bytes.decode("utf-8", errors="replace")

                if self._ffmpeg_proc.returncode == 0:
                    if self._output_path and self._output_path.exists():
                        size_kb = self._output_path.stat().st_size / 1024
                        video_path = str(self._output_path)
                        log.info("CDP录屏完成", data={
                            "path": video_path,
                            "frames": self._frame_count,
                            "size_kb": f"{size_kb:.1f}",
                        })
                    else:
                        log.warning("ffmpeg完成但视频文件不存在")
                else:
                    log.warning(f"ffmpeg异常退出: code={self._ffmpeg_proc.returncode}",
                                data={"stderr": stderr_text[-300:]})
            except subprocess.TimeoutExpired:
                log.warning(f"ffmpeg编码超时({timeout}s)，强制终止")
                self._ffmpeg_proc.terminate()
                try:
                    self._ffmpeg_proc.wait(timeout=5)
                except Exception:
                    self._ffmpeg_proc.kill()
                # 超时也可能产生了部分可用文件
                if self._output_path and self._output_path.exists():
                    video_path = str(self._output_path)
            except Exception as e:
                log.error(f"关闭ffmpeg异常: {e}")
            finally:
                self._ffmpeg_proc = None

        return video_path
