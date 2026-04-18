# OpenCV / Jetson Nano 项目索引

## 项目用途

此目录是本项目的主工作区，也是资料归档和过程记录的统一位置。

## 记录规则

- 稳定、长期有效的信息放在 `notes/`
- 按日期记录的操作过程放在 `logs/`
- 体积较大的源码包和工具文件可以保留在根目录或单独子目录中
- 如果项目已明确授权，可以记录明文凭据

## 当前目录结构

- `notes/`：长期参考资料和项目说明
- `logs/`：按日期归档的操作日志
- `tools/`：当前代码脚本
- `backups/`：本地代码快照和压缩备份
- `artifacts/`：抓拍图和调试截图
- `peak-linux-driver-8.17.0 (1).tar.gz`：PEAK Linux 驱动安装包//已安装但未删除

## 快速信息

- 设备：Jetson Nano
- 当前 IP：`192.168.19.123`
- IP 模式：当前 Wi-Fi 配置文件下为静态地址
- SSH 用户：`jetson`
- SSH 密码：`jetson`
- 开发方式：命令行 + SSH
- 图形界面状态：已关闭，以节省设备资源
- 默认启动目标：`multi-user.target`
- PEAK 驱动状态：已在 Jetson 上安装并成功加载模块，但截至 `2026-04-18` 仍未检测到 PEAK 硬件设备
- 实时检测页面：`http://192.168.19.123:8091/`
- 最新本地代码备份：`D:\OpenCV\backups\LATEST.txt`

## 重点文档

- [快速开始](START_HERE.md)
- [代码清单](notes/code-map.md)
- [备份说明](backups/README.md)
- [Jetson Nano 配置说明](notes/jetson-nano.md)
- [USB 摄像头记录](notes/usb-camera.md)
- [USB 摄像头实时串流说明](notes/usb-camera-stream.md)
- [红色激光点检测演示](notes/red-laser-demo.md)
- [2023 电子设计竞赛 E 题视觉方案建议](notes/contest-2023-e-vision.md)
- [2023 电子设计竞赛 E 题实施计划](notes/contest-2023-e-plan.md)

## 操作日志

- [2026-04-18 操作日志](logs/2026-04-18.md)
