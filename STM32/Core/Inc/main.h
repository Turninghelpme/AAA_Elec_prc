#ifndef __MAIN_H
#define __MAIN_H

#include "stm32f4xx_hal.h"

/* ── 外设句柄（由 CubeMX 生成，在 main.c 中定义） ── */
extern TIM_HandleTypeDef  htim3;
extern UART_HandleTypeDef huart1;

/* ── 调试串口（可通过 USART2 + ST-Link Virtual COM 输出） ── */
extern UART_HandleTypeDef huart2;

/* ── PID 控制器参数（可根据实际机械结构调整） ── */
#define PID_KP_PAN    0.08f
#define PID_KI_PAN    0.0f
#define PID_KD_PAN    0.02f

#define PID_KP_TILT   0.08f
#define PID_KI_TILT   0.0f
#define PID_KD_TILT   0.02f

/* 积分项限幅，防止积分饱和 */
#define PID_INTEGRAL_LIMIT  30.0f

/* ── 图像分辨率（与 OpenMV 端保持一致） ── */
#define IMG_WIDTH   320U
#define IMG_HEIGHT  240U
#define IMG_CX      (IMG_WIDTH  / 2U)   /* 160 */
#define IMG_CY      (IMG_HEIGHT / 2U)   /* 120 */

/* ── 死区：误差在此范围内不动舵机，避免抖动 ── */
#define DEAD_ZONE_PX  5

void Error_Handler(void);

#endif /* __MAIN_H */
