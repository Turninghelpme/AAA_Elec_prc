/**
 * @file  main.c
 * @brief STM32 主程序
 *        功能：接收 OpenMV 坐标帧 → PID 控制云台舵机跟踪目标
 *
 * 外设配置摘要（请在 CubeMX 中按此配置生成初始化代码）：
 *   ┌──────────────────────────────────────────────────────────┐
 *   │ USART1  PA9(TX) PA10(RX)  115200 8N1  中断接收          │
 *   │ USART2  PA2(TX) PA3(RX)   115200 8N1  调试输出           │
 *   │ TIM3    PA6(CH1=Pan) PA7(CH2=Tilt)                       │
 *   │         PSC=83  ARR=19999  → 50Hz PWM                    │
 *   │ SysTick 1ms 系统时基                                      │
 *   └──────────────────────────────────────────────────────────┘
 *
 * 注：本文件展示主控逻辑，HAL 外设初始化函数（MX_xxx_Init）
 *     由 CubeMX 自动生成，此处仅保留调用框架与业务代码。
 */

#include "main.h"
#include "servo.h"
#include "uart_comm.h"
#include <stdio.h>
#include <math.h>

/* ── HAL 外设句柄（由 CubeMX 生成） ── */
TIM_HandleTypeDef  htim3;
UART_HandleTypeDef huart1;
UART_HandleTypeDef huart2;

/* ── 内部函数声明 ── */
static void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_TIM3_Init(void);
static void MX_USART1_UART_Init(void);
static void MX_USART2_UART_Init(void);

/* ── PID 状态 ── */
typedef struct {
    float kp, ki, kd;
    float integral;
    float prev_error;
} PID_t;

static PID_t pid_pan  = {PID_KP_PAN,  PID_KI_PAN,  PID_KD_PAN,  0.0f, 0.0f};
static PID_t pid_tilt = {PID_KP_TILT, PID_KI_TILT, PID_KD_TILT, 0.0f, 0.0f};

/**
 * @brief  PID 计算（增量式输出）
 * @param  pid    PID 状态结构体指针
 * @param  error  当前误差（像素）
 * @return 角度增量（°）
 */
static float PID_Compute(PID_t *pid, float error)
{
    pid->integral += error;
    /* 积分限幅 */
    if (pid->integral >  PID_INTEGRAL_LIMIT) pid->integral =  PID_INTEGRAL_LIMIT;
    if (pid->integral < -PID_INTEGRAL_LIMIT) pid->integral = -PID_INTEGRAL_LIMIT;

    float derivative = error - pid->prev_error;
    pid->prev_error  = error;

    return pid->kp * error + pid->ki * pid->integral + pid->kd * derivative;
}

/* ── 调试输出 ── */
static void debug_printf(const char *fmt, ...)
{
#ifdef DEBUG
    char buf[128];
    va_list args;
    va_start(args, fmt);
    int len = vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    if (len > 0) {
        HAL_UART_Transmit(&huart2, (uint8_t *)buf, (uint16_t)len, 100U);
    }
#else
    (void)fmt;
#endif
}

/* ── UART 接收回调（在 stm32f4xx_it.c 中调用或直接写在此文件） ── */
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART1) {
        UartComm_IRQHandler();
    }
}

/* ──────────────────────────────────────────────────────────────
 *                          主函数
 * ──────────────────────────────────────────────────────────────*/
int main(void)
{
    /* 1. HAL 初始化 */
    HAL_Init();
    SystemClock_Config();

    /* 2. 外设初始化 */
    MX_GPIO_Init();
    MX_TIM3_Init();
    MX_USART1_UART_Init();
    MX_USART2_UART_Init();

    /* 3. 业务模块初始化 */
    Servo_Init(&htim3);         /* 舵机上电归中 */
    UartComm_Init(&huart1);     /* 启动 UART 中断接收 */

    debug_printf("STM32 OpenMV Pan-Tilt Ready\r\n");

    /* 4. 主循环 */
    while (1) {
        if (UartComm_HasNewFrame()) {
            TargetCoord_t target = UartComm_GetTarget();

            /* 计算像素误差（以图像中心为原点） */
            float err_pan  = (float)((int16_t)target.x - (int16_t)IMG_CX);
            float err_tilt = (float)((int16_t)target.y - (int16_t)IMG_CY);

            /* 死区处理 */
            if (fabsf(err_pan)  < DEAD_ZONE_PX) err_pan  = 0.0f;
            if (fabsf(err_tilt) < DEAD_ZONE_PX) err_tilt = 0.0f;

            /* PID 输出角度增量 */
            float delta_pan  = PID_Compute(&pid_pan,   err_pan);
            float delta_tilt = PID_Compute(&pid_tilt,  err_tilt);

            /* 更新舵机角度（Pan：X 偏右→顺时针，Tilt：Y 偏下→仰头） */
            int16_t new_pan  = (int16_t)Servo_GetPan()  + (int16_t)delta_pan;
            int16_t new_tilt = (int16_t)Servo_GetTilt() - (int16_t)delta_tilt;

            /* 限幅后写入舵机（Servo_Set* 内部也会限幅，双重保护） */
            if (new_pan  < 0)   new_pan  = 0;
            if (new_pan  > 180) new_pan  = 180;
            if (new_tilt < 0)   new_tilt = 0;
            if (new_tilt > 180) new_tilt = 180;

            Servo_SetPan ((uint16_t)new_pan);
            Servo_SetTilt((uint16_t)new_tilt);

            debug_printf("x:%3u y:%3u  pan:%3u tilt:%3u\r\n",
                         target.x, target.y,
                         Servo_GetPan(), Servo_GetTilt());
        }

        /* 可在此添加其他任务（按键、显示、状态机等） */
        HAL_Delay(1U);
    }
}

/* ──────────────────────────────────────────────────────────────
 *          外设初始化（CubeMX 生成的配置骨架）
 * ──────────────────────────────────────────────────────────────*/

/**
 * @brief  系统时钟配置
 *         HSE 8 MHz → PLL → SYSCLK 168 MHz（STM32F4）
 *         如使用 F1 系列，请将 PLL 参数改为 72 MHz。
 */
static void SystemClock_Config(void)
{
    RCC_OscInitTypeDef RCC_OscInitStruct = {0};
    RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

    __HAL_RCC_PWR_CLK_ENABLE();
    __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

    RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
    RCC_OscInitStruct.HSEState       = RCC_HSE_ON;
    RCC_OscInitStruct.PLL.PLLState   = RCC_PLL_ON;
    RCC_OscInitStruct.PLL.PLLSource  = RCC_PLLSOURCE_HSE;
    RCC_OscInitStruct.PLL.PLLM       = 8U;
    RCC_OscInitStruct.PLL.PLLN       = 336U;
    RCC_OscInitStruct.PLL.PLLP       = RCC_PLLP_DIV2;
    RCC_OscInitStruct.PLL.PLLQ       = 7U;
    HAL_RCC_OscConfig(&RCC_OscInitStruct);

    RCC_ClkInitStruct.ClockType      = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK
                                     | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    RCC_ClkInitStruct.SYSCLKSource   = RCC_SYSCLKSOURCE_PLLCLK;
    RCC_ClkInitStruct.AHBCLKDivider  = RCC_SYSCLK_DIV1;
    RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV4;
    RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV2;
    HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5);
}

/**
 * @brief  GPIO 初始化（LED 状态指示，PA5 = LD2 on Nucleo）
 */
static void MX_GPIO_Init(void)
{
    __HAL_RCC_GPIOA_CLK_ENABLE();

    GPIO_InitTypeDef GPIO_InitStruct = {0};
    GPIO_InitStruct.Pin   = GPIO_PIN_5;
    GPIO_InitStruct.Mode  = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull  = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);
}

/**
 * @brief  TIM3 PWM 初始化
 *         APB1 时钟 42 MHz，TIM3 倍频后 84 MHz
 *
 *         通用公式：PSC = (TIM_CLK / 1_000_000) - 1  （目标 1 MHz 计数频率）
 *                   ARR = 19999                        （20ms 周期，50Hz）
 *
 *         对于 168 MHz SYSCLK / APB1 DIV4 = 42 MHz × 2 = 84 MHz TIM_CLK：
 *             PSC = 84 - 1 = 83  → 84MHz / 84 = 1 MHz
 *             ARR = 19999        → 50 Hz
 */
static void MX_TIM3_Init(void)
{
    __HAL_RCC_TIM3_CLK_ENABLE();
    __HAL_RCC_GPIOA_CLK_ENABLE();

    /* GPIO：PA6 PA7 复用为 TIM3_CH1 TIM3_CH2 */
    GPIO_InitTypeDef GPIO_InitStruct = {0};
    GPIO_InitStruct.Pin       = GPIO_PIN_6 | GPIO_PIN_7;
    GPIO_InitStruct.Mode      = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull      = GPIO_NOPULL;
    GPIO_InitStruct.Speed     = GPIO_SPEED_FREQ_LOW;
    GPIO_InitStruct.Alternate = GPIO_AF2_TIM3;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    /* TIM3 基础配置 */
    htim3.Instance               = TIM3;
    htim3.Init.Prescaler         = 83U;     /* 84 MHz / 84 = 1 MHz */
    htim3.Init.CounterMode       = TIM_COUNTERMODE_UP;
    htim3.Init.Period            = 19999U;  /* 20 ms → 50 Hz */
    htim3.Init.ClockDivision     = TIM_CLOCKDIVISION_DIV1;
    htim3.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;
    HAL_TIM_PWM_Init(&htim3);

    /* OC（PWM）通道配置 */
    TIM_OC_InitTypeDef sConfigOC = {0};
    sConfigOC.OCMode       = TIM_OCMODE_PWM1;
    sConfigOC.Pulse        = 1500U;         /* 初始 1.5ms → 90° */
    sConfigOC.OCPolarity   = TIM_OCPOLARITY_HIGH;
    sConfigOC.OCFastMode   = TIM_OCFAST_DISABLE;
    HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_1);
    HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_2);
}

/**
 * @brief  USART1 初始化（接收 OpenMV 数据）
 */
static void MX_USART1_UART_Init(void)
{
    __HAL_RCC_USART1_CLK_ENABLE();
    __HAL_RCC_GPIOA_CLK_ENABLE();

    /* PA9=TX  PA10=RX */
    GPIO_InitTypeDef GPIO_InitStruct = {0};
    GPIO_InitStruct.Pin       = GPIO_PIN_9 | GPIO_PIN_10;
    GPIO_InitStruct.Mode      = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull      = GPIO_PULLUP;
    GPIO_InitStruct.Speed     = GPIO_SPEED_FREQ_VERY_HIGH;
    GPIO_InitStruct.Alternate = GPIO_AF7_USART1;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    huart1.Instance          = USART1;
    huart1.Init.BaudRate     = 115200U;
    huart1.Init.WordLength   = UART_WORDLENGTH_8B;
    huart1.Init.StopBits     = UART_STOPBITS_1;
    huart1.Init.Parity       = UART_PARITY_NONE;
    huart1.Init.Mode         = UART_MODE_RX;
    huart1.Init.HwFlowCtl    = UART_HWCONTROL_NONE;
    huart1.Init.OverSampling = UART_OVERSAMPLING_16;
    HAL_UART_Init(&huart1);

    /* 使能 USART1 中断 */
    HAL_NVIC_SetPriority(USART1_IRQn, 0U, 0U);
    HAL_NVIC_EnableIRQ(USART1_IRQn);
}

/**
 * @brief  USART2 初始化（调试输出，接 ST-Link Virtual COM）
 */
static void MX_USART2_UART_Init(void)
{
    __HAL_RCC_USART2_CLK_ENABLE();
    __HAL_RCC_GPIOA_CLK_ENABLE();

    /* PA2=TX  PA3=RX */
    GPIO_InitTypeDef GPIO_InitStruct = {0};
    GPIO_InitStruct.Pin       = GPIO_PIN_2 | GPIO_PIN_3;
    GPIO_InitStruct.Mode      = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull      = GPIO_PULLUP;
    GPIO_InitStruct.Speed     = GPIO_SPEED_FREQ_VERY_HIGH;
    GPIO_InitStruct.Alternate = GPIO_AF7_USART2;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    huart2.Instance          = USART2;
    huart2.Init.BaudRate     = 115200U;
    huart2.Init.WordLength   = UART_WORDLENGTH_8B;
    huart2.Init.StopBits     = UART_STOPBITS_1;
    huart2.Init.Parity       = UART_PARITY_NONE;
    huart2.Init.Mode         = UART_MODE_TX;
    huart2.Init.HwFlowCtl    = UART_HWCONTROL_NONE;
    huart2.Init.OverSampling = UART_OVERSAMPLING_16;
    HAL_UART_Init(&huart2);
}

/**
 * @brief  错误处理
 */
void Error_Handler(void)
{
    __disable_irq();
    while (1) {
        /* 调试时在此处打断点 */
    }
}
