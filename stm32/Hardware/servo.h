#ifndef __SERVO_H
#define __SERVO_H

#include "main.h"
#include <math.h> // 引入数学库用于三角函数计算

// 1. 基础控制
void Servo_Init(void);           // 初始化定时器并回中
void Servo_ReturnToCenter(void); // 一键归零（回到1500us）

// 2. 非阻塞式持续转动指令 (仅下达指令改变状态，瞬间返回)
void Turn_Left_Continuous(void);
void Turn_Right_Continuous(void);
void Turn_Up_Continuous(void);
void Turn_Down_Continuous(void);

// 3. 停止指令
void Servo_Stop(void);

// 4. 后台任务引擎（!!! 必须放在主循环 while(1) 中 !!!）
void Servo_Task(void);

void Servo_Track_PID(int16_t target_x, int16_t target_y);

void Servo_LineFollow_Task(int16_t err_d, int16_t line_angle, uint8_t corner_flag);

#endif