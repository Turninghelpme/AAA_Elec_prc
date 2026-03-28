#ifndef __SERVO_H
#define __SERVO_H

#include "stm32f4xx_hal.h"

/**
 * @file  servo.h
 * @brief PWM 舵机控制驱动（支持云台 Pan / Tilt 双路）
 *
 * 硬件连接（示例，可在 CubeMX 中调整）：
 *   TIM3_CH1 (PA6)  → 水平舵机 (Pan)
 *   TIM3_CH2 (PA7)  → 垂直舵机 (Tilt)
 *
 * 定时器配置（84 MHz TIM_CLK，PSC=83 → 1 MHz 计数频率）：
 *   Prescaler = 83  (84 分频 → 1 MHz 计数频率)
 *   Period    = 19999 (20 ms 周期 → 50 Hz)
 *   脉宽范围：500 µs – 2500 µs → 对应角度 0° – 180°
 */

/* ── 舵机脉宽配置（单位：µs，等于定时器计数值） ── */
#define SERVO_PULSE_MIN   500U    /* 0°   对应脉宽 */
#define SERVO_PULSE_MID  1500U    /* 90°  对应脉宽（归中） */
#define SERVO_PULSE_MAX  2500U    /* 180° 对应脉宽 */

/* ── 云台软限位（° × 10，保留小数精度可按需修改为整度） ── */
#define PAN_ANGLE_MIN     0U
#define PAN_ANGLE_MAX   180U
#define TILT_ANGLE_MIN   30U      /* 向下限位，防止舵机过度受力 */
#define TILT_ANGLE_MAX  150U      /* 向上限位 */

/* ── TIM 通道映射（与 CubeMX 保持一致） ── */
#define SERVO_PAN_TIM_CH   TIM_CHANNEL_1
#define SERVO_TILT_TIM_CH  TIM_CHANNEL_2

/**
 * @brief  初始化舵机，启动 PWM 输出并将云台归中
 * @param  htim  指向已配置好的 TIM 句柄（TIM3）
 */
void Servo_Init(TIM_HandleTypeDef *htim);

/**
 * @brief  设置水平舵机角度
 * @param  angle  0 – 180 (°)
 */
void Servo_SetPan(uint16_t angle);

/**
 * @brief  设置垂直舵机角度
 * @param  angle  0 – 180 (°)
 */
void Servo_SetTilt(uint16_t angle);

/**
 * @brief  获取当前水平舵机角度
 */
uint16_t Servo_GetPan(void);

/**
 * @brief  获取当前垂直舵机角度
 */
uint16_t Servo_GetTilt(void);

/**
 * @brief  将云台恢复至中位（Pan=90°，Tilt=90°）
 */
void Servo_Center(void);

#endif /* __SERVO_H */
