#include "servo.h"

/* ── 模块私有变量 ── */
static TIM_HandleTypeDef *s_htim = NULL;
static uint16_t s_pan_angle  = 90U;
static uint16_t s_tilt_angle = 90U;

/* ── 内部工具函数 ── */

/**
 * @brief  角度 → 定时器比较值（µs 计数）
 *         公式：pulse = SERVO_PULSE_MIN + angle * (SERVO_PULSE_MAX - SERVO_PULSE_MIN) / 180
 */
static uint32_t angle_to_pulse(uint16_t angle)
{
    uint32_t pulse = SERVO_PULSE_MIN +
                     (uint32_t)angle * (SERVO_PULSE_MAX - SERVO_PULSE_MIN) / 180U;
    return pulse;
}

/**
 * @brief  限幅函数
 */
static uint16_t clamp_u16(uint16_t val, uint16_t lo, uint16_t hi)
{
    if (val < lo) return lo;
    if (val > hi) return hi;
    return val;
}

/* ── 公开接口实现 ── */

void Servo_Init(TIM_HandleTypeDef *htim)
{
    s_htim = htim;

    /* 启动两路 PWM 输出 */
    HAL_TIM_PWM_Start(s_htim, SERVO_PAN_TIM_CH);
    HAL_TIM_PWM_Start(s_htim, SERVO_TILT_TIM_CH);

    /* 上电归中 */
    Servo_Center();
}

void Servo_SetPan(uint16_t angle)
{
    angle = clamp_u16(angle, PAN_ANGLE_MIN, PAN_ANGLE_MAX);
    s_pan_angle = angle;

    uint32_t pulse = angle_to_pulse(angle);
    __HAL_TIM_SET_COMPARE(s_htim, SERVO_PAN_TIM_CH, pulse);
}

void Servo_SetTilt(uint16_t angle)
{
    angle = clamp_u16(angle, TILT_ANGLE_MIN, TILT_ANGLE_MAX);
    s_tilt_angle = angle;

    uint32_t pulse = angle_to_pulse(angle);
    __HAL_TIM_SET_COMPARE(s_htim, SERVO_TILT_TIM_CH, pulse);
}

uint16_t Servo_GetPan(void)
{
    return s_pan_angle;
}

uint16_t Servo_GetTilt(void)
{
    return s_tilt_angle;
}

void Servo_Center(void)
{
    Servo_SetPan(90U);
    Servo_SetTilt(90U);
}
