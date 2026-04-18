# USB 摄像头实时串流说明

## 当前状态

截至 `2026-04-18`，Jetson Nano 的 USB 摄像头实时串流已经可用。

## 串流访问地址

- 主页面：`http://192.168.19.123:8090/`
- MJPEG 视频流：`http://192.168.19.123:8090/stream.mjpg`
- 抓拍接口：`http://192.168.19.123:8090/snapshot.jpg`

## 当前串流参数

- 设备：`/dev/video0`
- 分辨率：`640x480`
- 帧率：`15`
- 传输方式：基于 HTTP 的 MJPEG

## 实现位置

- 本地脚本：`D:\OpenCV\tools\jetson_usb_mjpeg_stream.py`
- Jetson 端脚本副本：`/home/jetson/codex-install/jetson_usb_mjpeg_stream.py`

## 当前运行方式

串流服务目前以 Jetson 上的临时 `systemd` 单元运行：

- 单元名称：`jetson-camera-stream-user.service`

这表示：

- 服务当前正在运行
- 手动停止后会结束
- 系统重启后不会自动恢复，除非后续再补充为常驻服务

## 常用命令

查看 Jetson 上的服务状态：

```bash
systemctl status jetson-camera-stream-user
```

停止当前串流服务：

```bash
sudo systemctl stop jetson-camera-stream-user
```

## 验证结果

- 服务已经成功监听 `8090` 端口
- 远程访问 `/snapshot.jpg` 测试成功
- 验证时抓拍的图片已经保存在本地：
  - `D:\OpenCV\artifacts\usb_camera_live_snapshot.jpg`
