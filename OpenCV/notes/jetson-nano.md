# Jetson Nano 配置说明

## 设备基础信息

- 主机名：`nano`
- IP 地址：`192.168.19.123`
- SSH 用户：`jetson`
- SSH 密码：`jetson`
- 操作系统：Ubuntu 20.04.6 LTS
- 内核版本：`4.9.253-tegra`

## 远程访问方式

当前建议通过 SSH 进行开发和维护：

```bash
ssh jetson@192.168.19.123
```

## 网络配置

- 当前活动网卡：`wlan0`
- 当前 Wi-Fi 配置文件：`iQOO Neo9`
- IP 模式：静态地址
- 静态 IP：`192.168.19.123/24`
- 网关：`192.168.19.223`
- DNS：`192.168.19.223`

### 说明

- 静态 IP 于 `2026-04-18` 通过 NetworkManager 完成配置
- 当前实时路由表中已经显示 `proto static`
- 这项配置仅绑定在当前 Wi-Fi 配置文件 `iQOO Neo9` 上
- 如果 Jetson 以后连接到其他 Wi-Fi，需要为新网络单独配置 IP

## 当前开发模式

为了节省系统资源，设备目前已经切换为以命令行为主的工作模式。

- 默认启动目标：`multi-user.target`
- 桌面管理器状态：已停止
- SSH 服务状态：运行中

## 当前视觉服务

当前 Jetson 上正在跑的视觉主服务是：

- 进程命令：`/usr/bin/python3 -u /home/jetson/codex-install/jetson_red_laser_demo.py --device /dev/video0 --port 8091 --width 640 --height 480 --fps 30`
- 日志文件：`/home/jetson/codex-install/jetson_red_laser_demo.log`
- 页面地址：`http://192.168.19.123:8091/`

### 说明

- 这项服务当前使用 `nohup` 后台常驻方式启动
- 截至 `2026-04-18`，这版脚本在 `systemd-run` 下会触发 `Illegal Instruction`
- 因此后续如需重启，优先使用 `SSH + nohup` 方式

## 图形界面恢复方法

临时启动图形界面：

```bash
sudo systemctl start graphical.target
```

将图形界面恢复为默认启动模式：

```bash
sudo systemctl set-default graphical.target
```

## PEAK 驱动信息

- 使用安装包：`peak-linux-driver-8.17.0 (1).tar.gz`
- 已安装驱动版本：`8.17.0`
- PCAN-Basic 版本：`4.8.0.5`
- 内核模块：`pcan`

### Jetson 端安装位置

- 上传后的压缩包：`/home/jetson/codex-install/peak-linux-driver-8.17.0.tar.gz`
- 解压后的源码目录：`/home/jetson/codex-install/peak-linux-driver-8.17.0`

### 安装结果

- 驱动已针对当前 Jetson 内核头文件成功编译
- 模块安装完成
- `pcan` 内核模块已成功加载
- 相关共享库和测试工具已一并安装

### 当前测试结论

截至 `2026-04-18`：

- 驱动在软件层面工作正常
- 测试时未连接到 PEAK 硬件设备
- `pcaninfo` 返回结果为 `No device found!`

## 建议的后续检查项

- 将 PEAK 硬件连接到 Jetson 后，再次检查 `lsusb` 和 `dmesg`
- 如后续需要长期远程开发，可配置 SSH 密钥登录
- 如后续网络环境会频繁变化，可进一步规划更稳定的地址管理方式
