#ifndef __UART_COMM_H
#define __UART_COMM_H

#include "stm32f4xx_hal.h"
#include <stdbool.h>
#include <stdint.h>

/**
 * @file  uart_comm.h
 * @brief UART 通信驱动 —— 解析 OpenMV 发送的坐标帧
 *
 * 帧格式（共 9 字节）：
 *   [0]  0xAA  帧头1
 *   [1]  0xBB  帧头2
 *   [2]  x_H   X 坐标高字节
 *   [3]  x_L   X 坐标低字节
 *   [4]  y_H   Y 坐标高字节
 *   [5]  y_L   Y 坐标低字节
 *   [6]  sum   校验字节 = (0xAA+0xBB+x_H+x_L+y_H+y_L) & 0xFF
 *   [7]  0x0D  帧尾1 (CR)
 *   [8]  0x0A  帧尾2 (LF)
 *
 * 硬件连接：
 *   STM32 USART1_RX (PA10) → OpenMV TX (P4)
 *   STM32 GND              → OpenMV GND
 */

#define UART_FRAME_LEN    9U
#define UART_HEADER1   0xAAU
#define UART_HEADER2   0xBBU
#define UART_TAIL1     0x0DU
#define UART_TAIL2     0x0AU

/* 解析后的目标坐标 */
typedef struct {
    uint16_t x;        /* 0 – 319 */
    uint16_t y;        /* 0 – 239 */
    bool     valid;    /* true = 本次数据有效 */
} TargetCoord_t;

/**
 * @brief  初始化 UART 接收（DMA 或中断模式均可）
 * @param  huart  指向已配置好的 USART1 句柄
 */
void UartComm_Init(UART_HandleTypeDef *huart);

/**
 * @brief  在 UART 接收中断回调中调用此函数，喂入单字节
 * @param  byte  接收到的字节
 */
void UartComm_ReceiveByte(uint8_t byte);

/**
 * @brief  查询是否有新的有效帧已解析完成
 * @return true = 有新帧，false = 无新帧
 */
bool UartComm_HasNewFrame(void);

/**
 * @brief  获取最新一帧的目标坐标（调用后清除新帧标志）
 * @return TargetCoord_t
 */
TargetCoord_t UartComm_GetTarget(void);

/**
 * @brief  在 HAL_UART_RxCpltCallback 中调用，处理单字节接收并重挂中断
 *
 * 示例（stm32f4xx_it.c 或 main.c）：
 *   void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
 *   {
 *       if (huart->Instance == USART1)
 *           UartComm_IRQHandler();
 *   }
 */
void UartComm_IRQHandler(void);

#endif /* __UART_COMM_H */
