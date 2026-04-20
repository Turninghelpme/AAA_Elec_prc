#include "uart_comm.h"
#include <string.h>

/* ── 接收状态机 ── */
typedef enum {
    STATE_WAIT_HEADER1 = 0,
    STATE_WAIT_HEADER2,
    STATE_RECV_DATA,
    STATE_WAIT_TAIL1,
    STATE_WAIT_TAIL2,
} RxState_t;

/* 接收缓冲区（完整帧长 9 字节，数据段 5 字节：x_H x_L y_H y_L sum） */
#define DATA_LEN  5U   /* x_H x_L y_H y_L sum */

static UART_HandleTypeDef *s_huart    = NULL;
static RxState_t            s_state   = STATE_WAIT_HEADER1;
static uint8_t              s_buf[DATA_LEN];
static uint8_t              s_idx     = 0U;
static TargetCoord_t        s_target  = {0, 0, false};
static volatile bool        s_new_frame = false;

/* DMA / 中断接收用单字节缓冲 */
static uint8_t s_rx_byte = 0U;

/* ── 公开接口实现 ── */

void UartComm_Init(UART_HandleTypeDef *huart)
{
    s_huart = huart;
    s_state  = STATE_WAIT_HEADER1;
    s_idx    = 0U;
    s_new_frame = false;

    /* 启动中断接收（每次接收 1 字节） */
    HAL_UART_Receive_IT(s_huart, &s_rx_byte, 1U);
}

/**
 * @brief  状态机喂字节
 *
 * 帧格式：0xAA 0xBB [x_H x_L y_H y_L sum] 0x0D 0x0A
 *                    ←──── DATA_LEN=5 ────→
 */
void UartComm_ReceiveByte(uint8_t byte)
{
    switch (s_state) {
        case STATE_WAIT_HEADER1:
            if (byte == UART_HEADER1) {
                s_state = STATE_WAIT_HEADER2;
            }
            break;

        case STATE_WAIT_HEADER2:
            if (byte == UART_HEADER2) {
                s_idx   = 0U;
                s_state = STATE_RECV_DATA;
            } else {
                /* 连续两个 0xAA 时继续等第二帧头 */
                s_state = (byte == UART_HEADER1) ? STATE_WAIT_HEADER2
                                                 : STATE_WAIT_HEADER1;
            }
            break;

        case STATE_RECV_DATA:
            /* 收集 5 字节：x_H x_L y_H y_L sum */
            s_buf[s_idx++] = byte;
            if (s_idx >= DATA_LEN) {
                s_state = STATE_WAIT_TAIL1;
            }
            break;

        case STATE_WAIT_TAIL1:
            if (byte == UART_TAIL1) {
                s_state = STATE_WAIT_TAIL2;
            } else {
                s_state = STATE_WAIT_HEADER1;
            }
            break;

        case STATE_WAIT_TAIL2:
            if (byte == UART_TAIL2) {
                /* 校验 */
                uint8_t calc_sum = (uint8_t)(UART_HEADER1 + UART_HEADER2
                                             + s_buf[0] + s_buf[1]
                                             + s_buf[2] + s_buf[3]);
                if (calc_sum == s_buf[4]) {
                    s_target.x     = ((uint16_t)s_buf[0] << 8) | s_buf[1];
                    s_target.y     = ((uint16_t)s_buf[2] << 8) | s_buf[3];
                    s_target.valid = true;
                    s_new_frame    = true;
                }
            }
            s_state = STATE_WAIT_HEADER1;
            break;

        default:
            s_state = STATE_WAIT_HEADER1;
            break;
    }
}

bool UartComm_HasNewFrame(void)
{
    return s_new_frame;
}

TargetCoord_t UartComm_GetTarget(void)
{
    s_new_frame = false;
    return s_target;
}

/* ──────────────────────────────────────────────────────────────
 * HAL UART 接收完成回调（在 stm32f4xx_it.c 或 main.c 中包含
 * HAL_UART_RxCpltCallback，并在其中调用本函数）
 *
 * 示例：
 *   void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
 *   {
 *       if (huart->Instance == USART1) {
 *           UartComm_IRQHandler();
 *       }
 *   }
 * ──────────────────────────────────────────────────────────────*/
void UartComm_IRQHandler(void)
{
    UartComm_ReceiveByte(s_rx_byte);
    /* 重新挂起中断接收 */
    HAL_UART_Receive_IT(s_huart, &s_rx_byte, 1U);
}
