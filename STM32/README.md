# STM32 舵机控制固件

## 功能
- 通过 USART1 接收 OpenMV 发来的目标坐标帧
- 使用增量式 PID 控制算法驱动云台双轴舵机跟踪目标
- USART2 输出调试信息（接 ST-Link Virtual COM）

## 文件结构
```
STM32/
└── Core/
    ├── Inc/
    │   ├── main.h          # 宏定义、外设句柄声明、PID 参数
    │   ├── servo.h         # 舵机驱动接口
    │   └── uart_comm.h     # UART 通信接口与帧解析
    └── Src/
        ├── main.c          # 主程序（时钟/外设初始化 + 主循环）
        ├── servo.c         # 舵机 PWM 驱动实现
        └── uart_comm.c     # UART 状态机帧解析实现
```

## 硬件要求
- 开发板：STM32F4 系列（Nucleo-F401RE / F411RE 等），如使用 F1 系列需调整时钟参数
- 舵机：标准 PWM 舵机（50 Hz，500–2500 µs）
- 摄像头模块：OpenMV H7 / Cam M7

## 引脚映射
| 功能 | STM32 引脚 | 说明 |
|------|-----------|------|
| USART1_RX | PA10 | 接收 OpenMV 坐标数据 |
| USART2_TX | PA2  | 调试输出（ST-Link） |
| TIM3_CH1  | PA6  | 水平舵机 PWM（Pan） |
| TIM3_CH2  | PA7  | 垂直舵机 PWM（Tilt） |

## 定时器配置（TIM3，50 Hz PWM）
| 参数 | 值 | 说明 |
|------|----|------|
| TIM_CLK | 84 MHz | APB1 × 2（168 MHz SYSCLK） |
| Prescaler | 83 | → 1 MHz 计数频率 |
| Period (ARR) | 19999 | → 20 ms = 50 Hz |
| 脉宽范围 | 500–2500 µs | 对应 0°–180° |

## PID 参数调整
在 `Core/Inc/main.h` 中修改：
```c
#define PID_KP_PAN   0.08f
#define PID_KI_PAN   0.0f
#define PID_KD_PAN   0.02f
// Tilt 轴同理
```
建议先调 Kp 使云台能响应，再加 Kd 抑制振荡；一般不需要 Ki。

## 编译方法
1. 使用 STM32CubeMX 按上述外设配置生成工程骨架
2. 将 `Core/Src/*.c` 和 `Core/Inc/*.h` 复制到生成的工程中
3. 用 Keil MDK / STM32CubeIDE / arm-none-eabi-gcc 编译
4. 通过 ST-Link 烧录至开发板
