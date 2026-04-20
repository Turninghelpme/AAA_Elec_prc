# OpenMV 视觉识别模块

## 功能
- 颜色色块检测（默认识别红色目标）
- AprilTag 二维码识别（将 `USE_APRILTAG` 置为 `True` 切换）
- 通过 UART 将目标像素坐标发送至 STM32

## 文件说明
| 文件 | 说明 |
|------|------|
| `main.py` | OpenMV 主程序，直接烧录至 OpenMV 运行 |

## 硬件接线
| OpenMV 引脚 | STM32 引脚 | 说明 |
|------------|-----------|------|
| P4 (TX)    | PA10 (USART1_RX) | 数据线 |
| GND        | GND       | 共地  |

## 通信协议
帧长度：**9 字节**

```
[0xAA] [0xBB] [x_H] [x_L] [y_H] [y_L] [sum] [0x0D] [0x0A]
```

- `x_H:x_L`：目标 X 像素坐标（0–319）
- `y_H:y_L`：目标 Y 像素坐标（0–239）
- `sum`：校验字节 = `(0xAA + 0xBB + x_H + x_L + y_H + y_L) & 0xFF`

## 颜色阈值调整
1. 打开 OpenMV IDE
2. 菜单 → Tools → Machine Vision → Threshold Editor
3. 对准目标颜色标定 LAB 范围
4. 将结果填入 `main.py` 中 `COLOR_THRESHOLDS` 列表
