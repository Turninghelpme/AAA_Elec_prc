# OpenMV 视觉识别主程序
# 功能：颜色色块检测 + AprilTag 识别，通过 UART 将目标坐标发送至 STM32
# 通信协议：AA BB [x_high] [x_low] [y_high] [y_low] [checksum] 0D 0A
#
# 接线：OpenMV P4 (TX) → STM32 RX   (波特率 115200)
#       OpenMV GND   → STM32 GND

import sensor
import image
import time
import struct
from pyb import UART, LED

# ──────────────────────────────────────────────
# 硬件初始化
# ──────────────────────────────────────────────
uart = UART(3, 115200, timeout_char=1000)   # OpenMV UART3 (P4=TX, P5=RX)

red_led   = LED(1)
green_led = LED(2)
blue_led  = LED(3)

sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)           # 320×240
sensor.set_vflip(False)
sensor.set_hmirror(False)
sensor.skip_frames(time=2000)               # 等待自动曝光稳定
sensor.set_auto_gain(False)
sensor.set_auto_whitebal(False)

clock = time.clock()

# ──────────────────────────────────────────────
# 配置：检测目标颜色阈值 (LAB 色彩空间)
# 可用 Tools → Machine Vision → Threshold Editor 标定
# ──────────────────────────────────────────────
COLOR_THRESHOLDS = [
    (30, 100, 15, 127, 15, 127),    # 红色
]

# 图像中心（用于计算偏差）
IMG_W = 320
IMG_H = 240
CX    = IMG_W // 2
CY    = IMG_H // 2

# ──────────────────────────────────────────────
# AprilTag 模式切换（True = AprilTag，False = 颜色）
# ──────────────────────────────────────────────
USE_APRILTAG = False


# ──────────────────────────────────────────────
# 通信协议打包函数
# 帧格式: 0xAA 0xBB [x_H] [x_L] [y_H] [y_L] [sum] 0x0D 0x0A
# checksum = (0xAA + 0xBB + x_H + x_L + y_H + y_L) & 0xFF
# ──────────────────────────────────────────────
def build_frame(x, y):
    """将坐标打包为串口帧并发送"""
    x = max(0, min(x, 0xFFFF))
    y = max(0, min(y, 0xFFFF))
    x_h = (x >> 8) & 0xFF
    x_l =  x       & 0xFF
    y_h = (y >> 8) & 0xFF
    y_l =  y       & 0xFF
    chk = (0xAA + 0xBB + x_h + x_l + y_h + y_l) & 0xFF
    frame = struct.pack("9B", 0xAA, 0xBB, x_h, x_l, y_h, y_l, chk, 0x0D, 0x0A)
    return frame


def send_target(x, y):
    uart.write(build_frame(x, y))


# ──────────────────────────────────────────────
# 主循环
# ──────────────────────────────────────────────
while True:
    clock.tick()
    img = sensor.snapshot()

    target_x = CX   # 默认发送图像中心（无目标时）
    target_y = CY
    found    = False

    if USE_APRILTAG:
        # ── AprilTag 识别 ──
        tags = img.find_apriltags()
        if tags:
            tag = max(tags, key=lambda t: t.w() * t.h())   # 选面积最大的标签
            target_x = tag.cx()
            target_y = tag.cy()
            found    = True
            img.draw_rectangle(tag.rect(), color=(255, 0, 0))
            img.draw_cross(tag.cx(), tag.cy(), color=(0, 255, 0))
            img.draw_string(tag.cx() + 5, tag.cy(),
                            "ID:%d" % tag.id(), color=(255, 255, 0))
    else:
        # ── 颜色色块检测 ──
        blobs = img.find_blobs(
            COLOR_THRESHOLDS,
            pixels_threshold=200,
            area_threshold=200,
            merge=True
        )
        if blobs:
            blob     = max(blobs, key=lambda b: b.pixels())  # 选面积最大色块
            target_x = blob.cx()
            target_y = blob.cy()
            found    = True
            img.draw_rectangle(blob.rect(), color=(255, 0, 0))
            img.draw_cross(blob.cx(), blob.cy(), color=(0, 255, 0))

    # ── 发送坐标 & LED 指示 ──
    if found:
        green_led.on()
        red_led.off()
        send_target(target_x, target_y)
    else:
        red_led.on()
        green_led.off()
        # 目标丢失时发送图像中心，使云台保持原位
        send_target(CX, CY)

    # 调试信息（IDE 串口监视器可见）
    # print("FPS:%0.1f  x:%d  y:%d  found:%s" % (clock.fps(), target_x, target_y, found))
