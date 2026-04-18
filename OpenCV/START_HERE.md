# OpenCV / Jetson Nano 快速开始

这份文档用于下次快速接手当前项目，目标是不翻聊天记录也能在几分钟内恢复工作。

## 当前重点

- 开发板：`Jetson Nano`
- 固定 IP：`192.168.19.123`
- SSH 用户：`jetson`
- SSH 密码：`jetson`
- 开发方式：`SSH + 命令行`
- 图形界面：已关闭
- 实时检测页面：`http://192.168.19.123:8091/`

当前主要在做两件事：

1. Jetson 上的 USB 摄像头实时取流
2. 红激光 / 绿激光 / 黑胶布框中线 的实时检测

## 最重要的代码

- 主脚本：`D:\OpenCV\tools\jetson_red_laser_demo.py`
- Jetson 端副本：`/home/jetson/codex-install/jetson_red_laser_demo.py`
- 主说明文档：`D:\OpenCV\notes\red-laser-demo.md`
- 代码清单：`D:\OpenCV\notes\code-map.md`
- 本地备份入口：`D:\OpenCV\backups\LATEST.txt`

## 当前服务状态

当前实时检测服务不是通过 `systemd-run` 启动的，而是以 `jetson` 用户后台常驻进程运行。

原因：

- 当前脚本在 `systemd-run` 下会触发 `Illegal Instruction`
- 直接前台运行或 `nohup` 后台运行是正常的

## 重新连接 Jetson

Windows 终端：

```powershell
ssh jetson@192.168.19.123
```

## 启动实时检测服务

在 Jetson 上执行：

```bash
nohup /usr/bin/python3 -u /home/jetson/codex-install/jetson_red_laser_demo.py --device /dev/video0 --port 8091 --width 640 --height 480 --fps 30 > /home/jetson/codex-install/jetson_red_laser_demo.log 2>&1 < /dev/null &
```

## 停止实时检测服务

在 Jetson 上执行：

```bash
pkill -f jetson_red_laser_demo.py
```

## 查看当前是否运行

```bash
ps -ef | grep jetson_red_laser_demo.py | grep -v grep
```

## 查看日志

```bash
tail -n 50 /home/jetson/codex-install/jetson_red_laser_demo.log
```

## 打开实时页面

- 主页面：`http://192.168.19.123:8091/`
- 视频流：`http://192.168.19.123:8091/stream.mjpg`
- 抓拍：`http://192.168.19.123:8091/snapshot.jpg`
- 状态：`http://192.168.19.123:8091/status.json`
- 标定：`http://192.168.19.123:8091/calibration.json`

## 当前算法状态

### 激光检测

- 红绿激光检测已经接入实时页面
- 绿激光偶尔会误检成红激光，后续还需要继续收紧

### 黑胶布中线

- 当前代码已经切到“外框 + 内框 + 中线”的版本
- `status.json` 会尝试返回：
  - `outer_corners`
  - `inner_corners`
  - `corners`
- 其中：
  - `outer_corners`：黑胶布外边界
  - `inner_corners`：内白框边界
  - `corners`：内外边界平均得到的中线

### 已知问题

- 当画面中只出现黑框的一部分，或者大面积白纸压过目标时，`inner_corners` 还会跳到错误白区
- 因此当前黑框中线算法是“可运行但还需要继续收紧”的状态

## 本地代码备份

当前已经完成一份本地代码快照：

- 最新备份指针：`D:\OpenCV\backups\LATEST.txt`
- 快照目录：`D:\OpenCV\backups\2026-04-18-code-snapshot`
- 压缩包：`D:\OpenCV\backups\2026-04-18-code-snapshot.zip`

快照内包含：

- `tools\jetson_red_laser_demo.py`
- `tools\jetson_red_laser_demo.cpp`
- `tools\jetson_usb_mjpeg_stream.py`
- `peak-linux-driver-8.17.0 (1).tar.gz`
- `manifest.sha256.txt`

如果要从 Jetson 再拉一次最新代码到本地备份，直接运行：

```powershell
D:\OpenCV\tools\sync_jetson_code_backup.cmd
```

或者：

```powershell
python D:\OpenCV\tools\sync_jetson_code_backup.py
```

## 建议的下一步

最推荐的继续调试方式：

1. 把黑胶布框完整放进画面中央
2. 保证外部白纸不要占满整张画面
3. 观察 `outer_corners / inner_corners / corners` 是否三者一致
4. 继续调内框筛选逻辑，而不是先去动激光检测

## 下次优先看这些文档

1. `D:\OpenCV\START_HERE.md`
2. `D:\OpenCV\notes\code-map.md`
3. `D:\OpenCV\notes\red-laser-demo.md`
4. `D:\OpenCV\logs\2026-04-18.md`
