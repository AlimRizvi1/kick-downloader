# KICK Downloader

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/downloads/)

A professional-grade, multi-threaded downloader and live-stream monitor for [KICK.com](https://kick.com), built with a striking **Neon Brutalism** interface.

---

## 🎨 Design Philosophy
KICK Downloader Pro breaks away from boring, standard UI patterns, utilizing **Neon Brutalism**—a high-contrast, bold aesthetic designed for power users who demand efficiency, symmetry, and visual impact.

## 🚀 Core Features

- **High-Performance VOD Downloads**: Fast, multi-threaded extraction via `yt-dlp`.
- **Live Stream Monitoring**: Built-in auto-record functionality to never miss a moment.
- **Persistent Queue Management**: Add multiple tasks, pause/resume individually, or stop all with one click.
- **Robust Connection Handling**: Automatic resume for interrupted downloads and high retry limits.
- **Pro Dashboard**: A unified, single-screen control panel for total visibility.
- **Native System Integration**: Saves directly to your system's "Downloads" folder with support for custom paths.

---

## 🛠️ Getting Started

### Prerequisites
- [Python 3.10+](https://www.python.org/)
- [FFmpeg](https://ffmpeg.org/download.html) (Mandatory for media merging)

### Installation
1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/kick-downloader.git
   cd kick-downloader
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **FFmpeg Setup**:
   Download `ffmpeg.exe` and `ffprobe.exe` and place them inside the `/ffmpeg` directory in the project root.

4. **Launch**:
   ```bash
   python src/download.py
   ```

---

## 📦 Building from Source (EXE)

To create a standalone Windows executable:
1.  Run the provided `build.bat` file.
2.  The application will be compiled into the `/dist` folder.
3.  The output will be named `Kick Downloader v1.0.0.exe`.

---

## ⚖️ License
This project is licensed under the **MIT License**. See the `LICENSE` file for details.

*Note: This tool uses `yt-dlp` for its core extraction logic. Please respect the copyright of content creators when downloading material.*

---
*Built for the KICK community.*
