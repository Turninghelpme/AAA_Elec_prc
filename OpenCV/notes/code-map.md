# 代码清单

这份文档说明 `D:\OpenCV` 里当前和项目直接相关的代码、脚本、数据包分别是做什么的。

## 实时检测主脚本

### `D:\OpenCV\tools\jetson_red_laser_demo.py`

用途：

- Jetson 上 USB 摄像头取流
- 提供 MJPEG 实时网页
- 检测红激光
- 检测绿激光
- 检测黑胶布框
- 在当前版本中尝试输出黑胶布外框、内框和中线

Jetson 端对应文件：

- `/home/jetson/codex-install/jetson_red_laser_demo.py`

当前访问地址：

- `http://192.168.19.123:8091/`

当前状态：

- 正在使用
- 是本项目最重要的主脚本

## C++ 实验版

### `D:\OpenCV\tools\jetson_red_laser_demo.cpp`

用途：

- 用于验证 C++ 是否能比 Python 版更快

当前状态：

- 已编译实验过
- 目前没有作为主版本继续使用
- 主要原因不是不能用，而是当前瓶颈并不主要来自 Python 语言层

## 早期摄像头串流脚本

### `D:\OpenCV\tools\jetson_usb_mjpeg_stream.py`

用途：

- 最初用来验证 Jetson 摄像头实时 MJPEG 串流

当前状态：

- 仍可作为基础参考
- 但当前主项目已经转到 `jetson_red_laser_demo.py`

## 一键同步备份脚本

### `D:\OpenCV\tools\sync_jetson_code_backup.py`

用途：

- 连接 Jetson
- 从 `/home/jetson/codex-install` 拉取当前代码文件
- 在 `D:\OpenCV\backups\` 下生成带时间戳的本地快照
- 自动生成 `README.md`、`manifest.sha256.txt` 和 `.zip`
- 自动更新 `D:\OpenCV\backups\LATEST.txt`

### `D:\OpenCV\tools\sync_jetson_code_backup.cmd`

用途：

- Windows 下一键运行上面的同步脚本
- 适合双击执行，或在终端直接运行

## 驱动安装包

### `D:\OpenCV\peak-linux-driver-8.17.0 (1).tar.gz`

用途：

- PEAK PCAN Linux 驱动安装包

当前状态：

- 已安装到 Jetson
- 保留本地原始安装包，方便后续重装或核对版本

## 本地代码备份

### `D:\OpenCV\backups\2026-04-18-code-snapshot`

用途：

- 保存当前一轮调试后的本地代码快照
- 用于下次恢复、回退、核对

当前包含：

- `tools\jetson_red_laser_demo.py`
- `tools\jetson_red_laser_demo.cpp`
- `tools\jetson_usb_mjpeg_stream.py`
- `peak-linux-driver-8.17.0 (1).tar.gz`
- `manifest.sha256.txt`
- `README.md`

补充：

- 最新快照入口：`D:\OpenCV\backups\LATEST.txt`
- 压缩包：`D:\OpenCV\backups\2026-04-18-code-snapshot.zip`

## 主要文档

### `D:\OpenCV\notes\jetson-nano.md`

用途：

- Jetson 基础配置、网络、SSH、桌面关闭、PEAK 驱动状态说明

### `D:\OpenCV\notes\usb-camera.md`

用途：

- USB 摄像头识别和采集测试记录

### `D:\OpenCV\notes\usb-camera-stream.md`

用途：

- 早期摄像头 HTTP 串流方案记录

### `D:\OpenCV\notes\red-laser-demo.md`

用途：

- 当前视觉主项目的核心说明文档
- 包含：
  - 激光检测逻辑
  - 标定采样逻辑
  - 黑胶布检测演进过程
  - 中线方案尝试
  - 当前已知问题

### `D:\OpenCV\notes\contest-2023-e-vision.md`

用途：

- 2023 电赛 E 题视觉方案建议

### `D:\OpenCV\notes\contest-2023-e-plan.md`

用途：

- 2023 电赛 E 题实施计划

## 日志

### `D:\OpenCV\logs\2026-04-18.md`

用途：

- 今天这一轮工作的操作日志
- 适合快速回顾这次都做了什么

## 产物目录

### `D:\OpenCV\artifacts\`

用途：

- 保存抓拍图、调试截图、阶段性验证结果

如何使用：

- 当某次调试结果肉眼难描述时，优先看这里的图片
- 文件名基本按调试阶段命名，可以快速回溯算法变化
