# USB 摄像头记录

## 当前检测结论

截至 `2026-04-18`，Jetson Nano 已连接一台 USB 摄像头，系统能够正常识别并使用。

## 已识别设备

- 设备名称：`icspring camera`
- USB ID：`32e6:9211`
- 视频节点：`/dev/video0`
- 媒体节点：`/dev/media1`
- 驱动路径：`uvcvideo`

## 检测依据

- `lsusb` 能看到设备 `32e6:9211`
- `v4l2-ctl --list-devices` 能看到：
  - `icspring camera`
  - `/dev/video0`
- `dmesg` 显示该 UVC 设备已被识别并完成注册

## 测试中看到的支持格式

- `MJPG`
  - `1280x720`，最高 `30 fps`
  - `800x600`，最高 `30 fps`
  - `640x480`，最高 `30 fps`
- `YUYV`
  - `1280x720`，最高 `10 fps`
  - `800x600`，最高 `15 fps`
  - `640x480`，最高 `30 fps`

## 功能测试结果

已在 Jetson 上通过 OpenCV 完成实际采集测试，结果成功。

- 测试后端：OpenCV + V4L2
- 测试设备：`/dev/video0`
- 采集结果：成功
- 保存的图像分辨率：`640x480`
- 识别到的帧率：`30.0`

## 测试图像保存位置

- Jetson 端：`/home/jetson/codex-install/usb_camera_test_2026-04-18.jpg`
- 本地副本：`D:\OpenCV\artifacts\usb_camera_test_2026-04-18.jpg`

## 实际结论

这台 USB 摄像头不仅已经被系统正确识别，而且在无桌面、仅通过 SSH 的开发环境下，也能够稳定返回图像帧，可直接用于后续 OpenCV 视觉实验。
