# AAA_Elec_prc
电赛 — STM32 + OpenMV + 舵机云台视觉跟踪系统

## 项目简介
本项目实现了一套基于 **STM32 + OpenMV** 的视觉识别云台控制系统：
- **OpenMV** 负责目标识别（颜色色块 / AprilTag），将目标像素坐标通过 UART 发送给 STM32
- **STM32** 接收坐标后使用增量式 PID 算法驱动双轴舵机（Pan/Tilt）实时跟踪目标

## 目录结构
```
AAA_Elec_prc/
├── OpenMV/               # OpenMV MicroPython 程序
│   ├── main.py           # 视觉识别主程序（颜色 / AprilTag）
│   └── README.md         # OpenMV 模块说明
└── STM32/                # STM32 HAL 固件
    ├── Core/
    │   ├── Inc/
    │   │   ├── main.h        # 宏定义与 PID 参数
    │   │   ├── servo.h       # 舵机驱动接口
    │   │   └── uart_comm.h   # UART 帧解析接口
    │   └── Src/
    │       ├── main.c        # 主程序（外设初始化 + 主循环）
    │       ├── servo.c       # 舵机 PWM 驱动实现
    │       └── uart_comm.c   # UART 状态机帧解析实现
    └── README.md             # STM32 模块说明
```

## 通信协议
OpenMV → STM32，UART 115200 8N1，帧长 9 字节：

```
0xAA  0xBB  x_H  x_L  y_H  y_L  sum  0x0D  0x0A
```

其中 `sum = (0xAA + 0xBB + x_H + x_L + y_H + y_L) & 0xFF`

## 快速上手
1. 将 `OpenMV/main.py` 上传到 OpenMV，根据实际目标颜色调整 `COLOR_THRESHOLDS`
2. 使用 STM32CubeMX 按 `STM32/README.md` 中的外设配置生成工程骨架
3. 将 `STM32/Core/` 下的源文件加入工程并编译烧录
4. 接好电源与信号线，上电后 OpenMV 绿灯亮表示检测到目标，舵机自动跟踪
