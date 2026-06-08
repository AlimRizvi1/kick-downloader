
import os
import sys
import json
import glob
import re
import threading
import ctypes
import multiprocessing
from typing import Optional, Dict, Any, List
from tkinter import filedialog

import customtkinter as ctk
import yt_dlp

# =========================================================
# APP CONFIG
# =========================================================

APP_TITLE = "KICK Downloader"
APP_VERSION = "1.0.0"
DEFAULT_OUTPUT = os.path.join(os.path.expanduser("~"), "Downloads")

NEON_GREEN = "#53fc18"
NEON_PINK = "#ff007f"
NEON_ORANGE = "#ffae00"
PURE_BLACK = "#000000"
PURE_WHITE = "#ffffff"
DARK_GRAY = "#1A1A1A"
CARD_BG = "#0A0A0A"
BORDER_WIDTH = 4

os.makedirs(DEFAULT_OUTPUT, exist_ok=True)

def get_app_data_dir() -> str:
    base = os.getenv("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "Kick Downloader")
    os.makedirs(path, exist_ok=True)
    return path

APP_DATA_DIR = get_app_data_dir()
SESSION_FILE = os.path.join(APP_DATA_DIR, "session.json")

# =========================================================
# PATH HELPERS
# =========================================================

def resource_path(relative_path: str) -> str:
    """
    Works both in development and in PyInstaller builds.
    Tries both normal and _internal layouts.
    """
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except Exception:
        base_path = os.path.abspath(".")

    candidates = [
        os.path.join(base_path, relative_path),
        os.path.join(base_path, "_internal", relative_path),
        os.path.join(os.path.abspath("."), relative_path),
    ]

    for path in candidates:
        if os.path.exists(path):
            return path

    return candidates[0]

def strip_ansi(text: str) -> str:
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_escape.sub("", text)

def find_ffmpeg_dir() -> Optional[str]:
    candidates = [
        resource_path("ffmpeg"),
        resource_path(os.path.join("ffmpeg", "bin")),
    ]

    for folder in candidates:
        ffmpeg_exe = os.path.join(folder, "ffmpeg.exe")
        ffprobe_exe = os.path.join(folder, "ffprobe.exe")
        if os.path.isfile(ffmpeg_exe) and os.path.isfile(ffprobe_exe):
            return folder
    return None

def safe_filename_root(path: str) -> str:
    """
    Returns a best-effort file root without extension.
    """
    return os.path.splitext(path)[0]

# =========================================================
# DOWNLOAD TASK
# =========================================================

class DownloadTask:
    def __init__(
        self,
        url: str,
        folder: str,
        on_update_cb,
        on_finish_cb,
        task_type: str = "VOD",
        title: str = "Initializing...",
        percent: str = "0%",
        speed: str = "0 KB/s",
        eta: str = "N/A",
        progress_raw: float = 0.0,
        status: str = "PREPARING",
        output_root: Optional[str] = None,
        video_id: Optional[str] = None,
    ):
        self.url = url
        self.folder = folder
        self.on_update = on_update_cb
        self.on_finish = on_finish_cb
        self.task_type = task_type

        self.title = title
        self.percent = percent
        self.speed = speed
        self.eta = eta
        self.progress_raw = progress_raw
        self.status = status

        self.stop_requested = False
        self.pause_requested = False
        self.thread: Optional[threading.Thread] = None

        self.ffmpeg_dir = find_ffmpeg_dir()
        self.output_root = output_root
        self.video_id = video_id

    # -------------------------
    # Persistence
    # -------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "folder": self.folder,
            "task_type": self.task_type,
            "title": self.title,
            "percent": self.percent,
            "speed": self.speed,
            "eta": self.eta,
            "progress_raw": self.progress_raw,
            "status": self.status,
            "output_root": self.output_root,
            "video_id": self.video_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], on_update_cb, on_finish_cb):
        raw_status = data.get("status", "PAUSED")
        restored_status = raw_status
        if raw_status in {"DOWNLOADING", "PAUSING...", "RESUMING...", "PREPARING", "FINISHING..."}:
            restored_status = "PAUSED"

        return cls(
            url=data.get("url", ""),
            folder=data.get("folder", DEFAULT_OUTPUT),
            on_update_cb=on_update_cb,
            on_finish_cb=on_finish_cb,
            task_type=data.get("task_type", "VOD"),
            title=data.get("title", "Restored download"),
            percent=data.get("percent", "0%"),
            speed=data.get("speed", "0 KB/s"),
            eta=data.get("eta", "N/A"),
            progress_raw=float(data.get("progress_raw", 0.0) or 0.0),
            status=restored_status,
            output_root=data.get("output_root"),
            video_id=data.get("video_id"),
        )

    # -------------------------
    # Controls
    # -------------------------
    def pause(self):
        if self.status == "DOWNLOADING":
            self.pause_requested = True
            self.status = "PAUSING..."
            self.on_update(self)

    def resume(self):
        if self.status in ["PAUSED", "CANCELLED", "ERROR"]:
            self.stop_requested = False
            self.pause_requested = False
            self.status = "RESUMING..."
            self.on_update(self)
            self.run()

    def stop(self):
        self.stop_requested = True
        self.status = "STOPPING..."
        self.on_update(self)

        # Release yt-dlp hooks
        try:
            if hasattr(self, "ydl"):
                self.ydl._progress_hooks = []
        except:
            pass

        # Wait briefly for download thread to stop
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)

        self.cleanup_temp_files()

    def run(self):
        self.thread = threading.Thread(target=self._execute, daemon=True)
        self.thread.start()

    # -------------------------
    # Cleanup
    # -------------------------
    def cleanup_temp_files(self):
        """
        Delete yt-dlp temporary files:
        .part
        .ytdl
        .temp
        """

        try:
            for file in os.listdir(self.folder):
                full_path = os.path.join(self.folder, file)

                if not os.path.isfile(full_path):
                    continue

                lower = file.lower()

                if (
                    lower.endswith(".part")
                    or lower.endswith(".ytdl")
                    or ".part-frag" in lower
                    or lower.endswith(".temp")
                ):
                    try:
                        os.remove(full_path)
                    except PermissionError:
                        # Windows still locking file
                        pass
                    except Exception:
                        pass

        except Exception:
            pass


    def cleanup_artifacts(self):
        """
        Delete yt-dlp temp files for this task:
        - *.part
        - *.ytdl
        - fragment temp files
        Uses the saved output root if available.
        """
        root = self.output_root
        if not root:
            return

        folder = os.path.dirname(root)
        base = os.path.basename(safe_filename_root(root))

        patterns = [
            os.path.join(folder, f"{base}*.part"),
            os.path.join(folder, f"{base}*.part*"),
            os.path.join(folder, f"{base}*.ytdl"),
            os.path.join(folder, f"{base}*.ytdl*"),
        ]

        deleted = set()
        for pattern in patterns:
            for path in glob.glob(pattern):
                if path in deleted:
                    continue
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                        deleted.add(path)
                except Exception:
                    pass

    # -------------------------
    # yt-dlp execution
    # -------------------------
    def _make_ydl_opts(self):
        outtmpl = os.path.join(self.folder, "%(id)s_%(title)s.%(ext)s")

        class MyLogger:
            def debug(self, msg):
                pass

            def warning(self, msg):
                pass

            def error(self, msg):
                pass

        def hook(d):
            if self.stop_requested or self.pause_requested:
                raise Exception("USER_INTERRUPT")

            status = d.get("status")
            if status == "downloading":
                p_str = strip_ansi(d.get("_percent_str", "0%")).replace("%", "").strip()
                try:
                    self.progress_raw = float(p_str) / 100.0
                except Exception:
                    pass

                self.percent = f"{p_str}%"
                self.speed = strip_ansi(d.get("_speed_str", "0 KB/s"))
                self.eta = strip_ansi(d.get("_eta_str", "N/A"))
                self.status = "DOWNLOADING"
                self.on_update(self)

            elif status == "finished":
                self.progress_raw = 1.0
                self.percent = "100%"
                self.status = "FINISHING..."
                self.on_update(self)

        ydl_opts = {
            "format": "bestvideo+bestaudio/best",
            "outtmpl": outtmpl,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "logger": MyLogger(),
            "progress_hooks": [hook],
            "continuedl": True,
            "retries": 10,
            "windowsfilenames": True,
            "restrictfilenames": True,
        }

        if self.ffmpeg_dir:
            ydl_opts["ffmpeg_location"] = self.ffmpeg_dir

        return ydl_opts

    def _execute(self):
        try:
            ydl_opts = self._make_ydl_opts()
            self.ydl = yt_dlp.YoutubeDL(ydl_opts)

            with self.ydl as ydl:
                info = ydl.extract_info(self.url, download=False)

                self.video_id = info.get("id") or self.video_id
                self.title = info.get("title", "Unknown Stream")
                self.output_root = safe_filename_root(ydl.prepare_filename(info))
                self.on_update(self)

                if self.stop_requested or self.pause_requested:
                    return

                ydl.download([self.url])
                self.status = "COMPLETED"

        except Exception as e:
            if "USER_INTERRUPT" in str(e):
                self.status = "PAUSED" if self.pause_requested else "CANCELLED"
                if self.stop_requested and not self.pause_requested:
                    self.cleanup_artifacts()
            else:
                self.status = "ERROR"
                self.title = self.title or "Download failed"

        self.on_update(self)
        self.on_finish(self)

# =========================================================
# UI: TASK CARD
# =========================================================

class TaskCard(ctk.CTkFrame):
    def __init__(self, master, task, on_remove):
        super().__init__(
            master,
            fg_color=CARD_BG,
            border_width=2,
            border_color=PURE_WHITE,
            corner_radius=0,
        )
        self.task = task
        self.on_remove = on_remove

        self.pack(fill="x", pady=8, padx=5)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(12, 5))

        type_tag = f"[{task.task_type}] " if hasattr(task, "task_type") else ""
        self.lbl_title = ctk.CTkLabel(
            header,
            text=f"{type_tag}{task.title}",
            font=ctk.CTkFont(weight="bold", size=13),
            text_color=PURE_WHITE,
            anchor="w",
        )
        self.lbl_title.pack(side="left", expand=True, fill="x")

        self.btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        self.btn_frame.pack(side="right")

        self.btn_pause = ctk.CTkButton(
            self.btn_frame,
            text="‖" if task.status not in ["PAUSED"] else "▶",
            width=35,
            height=35,
            fg_color=NEON_ORANGE if task.status not in ["PAUSED"] else NEON_GREEN,
            text_color=PURE_BLACK,
            corner_radius=0,
            font=ctk.CTkFont(weight="bold"),
            hover_color="#CC8B00" if task.status not in ["PAUSED"] else "#2cbf10",
            command=self.handle_pause,
        )
        self.btn_pause.pack(side="left", padx=5)

        self.btn_stop = ctk.CTkButton(
            self.btn_frame,
            text="✕",
            width=35,
            height=35,
            fg_color=NEON_PINK,
            text_color=PURE_WHITE,
            corner_radius=0,
            font=ctk.CTkFont(weight="bold"),
            hover_color="#CC0066",
            command=self.handle_stop,
        )
        self.btn_stop.pack(side="left")

        self.prog_bar = ctk.CTkProgressBar(
            self,
            height=10,
            progress_color=NEON_GREEN,
            fg_color=DARK_GRAY,
            corner_radius=0,
        )
        self.prog_bar.set(max(0.0, min(1.0, task.progress_raw)))
        self.prog_bar.pack(fill="x", padx=15, pady=8)

        stats = ctk.CTkFrame(self, fg_color="transparent")
        stats.pack(fill="x", padx=15, pady=(0, 12))

        self.lbl_pct = ctk.CTkLabel(
            stats,
            text=task.percent,
            font=ctk.CTkFont(family="Consolas", size=18, weight="bold"),
            text_color=PURE_WHITE,
        )
        self.lbl_pct.pack(side="left")

        self.lbl_status = ctk.CTkLabel(
            stats,
            text=task.status,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=NEON_GREEN,
        )
        self.lbl_status.pack(side="left", padx=25)

        self.lbl_info = ctk.CTkLabel(
            stats,
            text=f"{task.speed} | {task.eta}",
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color=PURE_WHITE,
        )
        self.lbl_info.pack(side="right")

        self._sync_status_colors()

    def _sync_status_colors(self):
        if self.task.status == "PAUSED":
            self.btn_pause.configure(text="▶", fg_color=NEON_GREEN, hover_color="#2cbf10")
            self.lbl_status.configure(text_color=NEON_ORANGE)
        elif self.task.status == "DOWNLOADING":
            self.btn_pause.configure(text="‖", fg_color=NEON_ORANGE, hover_color="#CC8B00")
            self.lbl_status.configure(text_color=NEON_GREEN)
        elif self.task.status in ["COMPLETED", "CANCELLED", "ERROR"]:
            if self.btn_pause.winfo_ismapped():
                self.btn_pause.pack_forget()
            self.btn_stop.configure(text="CLEAN", width=60, fg_color=DARK_GRAY)

    def handle_pause(self):
        if self.task.status == "PAUSED":
            self.task.resume()
            self.btn_pause.configure(text="‖", fg_color=NEON_ORANGE, hover_color="#CC8B00")
        else:
            self.task.pause()

    def handle_stop(self):
        if self.task.status in ["COMPLETED", "CANCELLED", "ERROR"]:
            if self.task.status in ["CANCELLED", "ERROR"]:
                self.task.cleanup_artifacts()
            self.on_remove(self)
        else:
            self.task.stop()
            self.after(500, lambda: self.on_remove(self))

    def update_ui(self):
        title = self.task.title or "Unknown Stream"
        if len(title) > 65:
            title = title[:65] + "..."
        self.lbl_title.configure(text=f"[{self.task.task_type}] {title}")

        self.prog_bar.set(max(0.0, min(1.0, self.task.progress_raw)))
        self.lbl_pct.configure(text=self.task.percent)
        self.lbl_info.configure(text=f"{self.task.speed} | {self.task.eta}")
        self.lbl_status.configure(text=self.task.status)

        self._sync_status_colors()

# =========================================================
# MAIN APP
# =========================================================

class KickApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("kickdownloader.pro.1")
        except Exception:
            pass

        self.title(APP_TITLE)
        self.geometry("1000x850")
        self.configure(fg_color=PURE_BLACK)

        icon_path = resource_path("assets/icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        self.output_folder = DEFAULT_OUTPUT
        self.active_tasks: Dict[DownloadTask, TaskCard] = {}
        self._save_session_pending = False
        self._restoring_session = False

        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.setup_ui()
        self.load_session()

    # -------------------------
    # UI
    # -------------------------
    def setup_ui(self):
        self.master_frame = ctk.CTkFrame(self, fg_color=PURE_BLACK, corner_radius=0)
        self.master_frame.pack(expand=True, fill="both", padx=60, pady=40)

        header = ctk.CTkFrame(self.master_frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 30))

        ctk.CTkLabel(
            header,
            text="KICK DOWNLOADER //",
            font=ctk.CTkFont(family="Impact", size=52),
            text_color=NEON_GREEN,
        ).pack(side="left")

        self.lbl_global_status = ctk.CTkLabel(
            header,
            text="● SYSTEM READY",
            font=ctk.CTkFont(weight="bold", size=12),
            text_color=PURE_WHITE,
        )
        self.lbl_global_status.pack(side="right", pady=(25, 0))

        cmd_card = ctk.CTkFrame(
            self.master_frame,
            fg_color=PURE_BLACK,
            border_width=BORDER_WIDTH,
            border_color=PURE_WHITE,
            corner_radius=0,
        )
        cmd_card.pack(fill="x", pady=(0, 25))

        f_row = ctk.CTkFrame(cmd_card, fg_color="transparent")
        f_row.pack(fill="x", padx=20, pady=(20, 10))

        ctk.CTkLabel(
            f_row,
            text="DESTINATION //",
            font=ctk.CTkFont(weight="bold", size=12),
            text_color=PURE_WHITE,
        ).pack(side="left")

        self.lbl_path = ctk.CTkLabel(
            f_row,
            text=self.output_folder,
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color=PURE_WHITE,
        )
        self.lbl_path.pack(side="left", padx=20)

        ctk.CTkButton(
            f_row,
            text="BROWSE",
            width=90,
            height=30,
            fg_color=PURE_BLACK,
            border_width=2,
            border_color=PURE_WHITE,
            text_color=PURE_WHITE,
            corner_radius=0,
            hover_color=DARK_GRAY,
            command=self.browse_folder,
        ).pack(side="right")

        u_row = ctk.CTkFrame(cmd_card, fg_color="transparent")
        u_row.pack(fill="x", padx=20, pady=(10, 20))

        self.url_entry = ctk.CTkEntry(
            u_row,
            height=50,
            fg_color=PURE_BLACK,
            border_width=2,
            border_color=NEON_GREEN,
            placeholder_text="PASTE KICK VOD LINK...",
            font=ctk.CTkFont(family="Consolas", size=15),
            text_color=PURE_WHITE,
            corner_radius=0,
        )
        self.url_entry.pack(side="left", expand=True, fill="x", padx=(0, 15))

        ctk.CTkButton(
            u_row,
            text="+ ADD TASK",
            width=140,
            height=50,
            fg_color=NEON_GREEN,
            text_color=PURE_BLACK,
            font=ctk.CTkFont(weight="bold", size=14),
            corner_radius=0,
            hover_color=PURE_WHITE,
            command=self.add_vod_task,
        ).pack(side="right")

        ctrl_frame = ctk.CTkFrame(self.master_frame, fg_color="transparent")
        ctrl_frame.pack(fill="x", pady=(0, 25))

        ctk.CTkButton(
            ctrl_frame,
            text="PAUSE ALL",
            height=55,
            fg_color=NEON_ORANGE,
            text_color=PURE_BLACK,
            font=ctk.CTkFont(weight="bold", size=13),
            corner_radius=0,
            hover_color="#CC8B00",
            command=self.pause_all,
        ).pack(side="left", expand=True, fill="x", padx=(0, 4))

        ctk.CTkButton(
            ctrl_frame,
            text="STOP ALL",
            height=55,
            fg_color=NEON_PINK,
            text_color=PURE_WHITE,
            font=ctk.CTkFont(weight="bold", size=13),
            corner_radius=0,
            hover_color="#CC0066",
            command=self.stop_all,
        ).pack(side="left", expand=True, fill="x", padx=(4, 0))

        ctk.CTkLabel(
            self.master_frame,
            text="DOWNLOAD LIST //",
            font=ctk.CTkFont(weight="bold", size=12),
            text_color=PURE_WHITE,
        ).pack(anchor="w")

        self.scroll_list = ctk.CTkScrollableFrame(
            self.master_frame,
            fg_color=PURE_BLACK,
            border_width=BORDER_WIDTH,
            border_color=PURE_WHITE,
            corner_radius=0,
            height=500,
        )
        self.scroll_list.pack(fill="both", expand=True, pady=(5, 0))

    # -------------------------
    # Session handling
    # -------------------------
    def schedule_save_session(self):
        if self._save_session_pending:
            return
        self._save_session_pending = True

        def _do_save():
            self._save_session_pending = False
            self.save_session()

        self.after(250, _do_save)

    def save_session(self):
        try:
            data = {
                "version": 1,
                "output_folder": self.output_folder,
                "tasks": [task.to_dict() for task in self.active_tasks.keys()],
            }
            tmp_file = SESSION_FILE + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, SESSION_FILE)
        except Exception:
            pass

    def load_session(self):
        self._restoring_session = True
        try:
            if not os.path.exists(SESSION_FILE):
                self._restoring_session = False
                return

            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.output_folder = data.get("output_folder", DEFAULT_OUTPUT)
            self.lbl_path.configure(text=self.output_folder)
            tasks = data.get("tasks", [])

            for task_data in tasks:
                url = task_data.get("url", "")
                if not url:
                    continue
                task = DownloadTask.from_dict(task_data, self.on_task_update, lambda t: None)
                self._create_card(task)

        except Exception:
            pass
        finally:
            self._restoring_session = False
            self.update_system_status()

    # -------------------------
    # Task management
    # -------------------------
    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_folder = folder
            self.lbl_path.configure(text=folder)
            self.schedule_save_session()

    def add_vod_task(self):
        url = self.url_entry.get().strip()
        self.url_entry.delete(0, "end")
        if not url:
            return

        task = DownloadTask(url, self.output_folder, self.on_task_update, lambda t: None, "VOD")
        self._create_card(task)
        task.run()

    def _create_card(self, task: DownloadTask):
        card = TaskCard(self.scroll_list, task, self.remove_task_card)
        self.active_tasks[task] = card
        self.schedule_save_session()

    def on_task_update(self, task: DownloadTask):
        if task in self.active_tasks:
            self.after(0, self.active_tasks[task].update_ui)
        self.after(0, self.update_system_status)
        self.schedule_save_session()

    def remove_task_card(self, card: TaskCard):
        if card.task in self.active_tasks:
            del self.active_tasks[card.task]
        card.destroy()
        self.schedule_save_session()

    def pause_all(self):
        for task in list(self.active_tasks.keys()):
            task.pause()
        self.schedule_save_session()

    def stop_all(self):
        for task in list(self.active_tasks.keys()):
            task.stop()
        self.schedule_save_session()

    def update_system_status(self):
        active_count = sum(
            1 for t in self.active_tasks.keys()
            if t.status == "DOWNLOADING"
        )
        if active_count > 0:
            self.lbl_global_status.configure(text=f"● {active_count} ACTIVE DOWNLOADS", text_color=NEON_GREEN)
        else:
            self.lbl_global_status.configure(text="● SYSTEM READY", text_color=PURE_WHITE)

    def on_close(self):
        self.save_session()
        self.destroy()

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":
    multiprocessing.freeze_support()

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    app = KickApp()
    app.mainloop()
