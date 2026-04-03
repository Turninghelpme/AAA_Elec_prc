#include "servo.h"
#include "tim.h" // 包含由CubeMX生成的定时器头文件

// --- 物理参数配置 ---
#define SERVO_PULSE_STEP 20     // 每次(20ms)转动的脉宽步长，控制持续转动速度，可自行调整
#define SERVO_MIN_PULSE  500.0f
#define SERVO_MAX_PULSE  2500.0f
#define PI               3.14159265f

// 记录两路舵机的当前脉宽值 (默认中位)
// 必须改为 float 才能累计微小的脉宽变化
static float current_pulse1 = 1500.0f; 
static float current_pulse2 = 1500.0f;

// V_FORWARD 决定了红光跑完一圈的时间。需要根据实际测试调整大小以卡准 30 秒
#define V_FORWARD 1.5f

// --- 状态机定义 ---
typedef enum {
    DIR_STOP = 0, // 停止
    DIR_INC,      // 脉宽增加
    DIR_DEC       // 脉宽减少
} ServoDir_t;

// 记录当前运动状态
static ServoDir_t dir1 = DIR_STOP; 
static ServoDir_t dir2 = DIR_STOP;


// ==========================================
// 基础初始化与控制
// ==========================================
void Servo_Init(void)
{
    // 开启PWM输出
    HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_1);
    HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_2);
    // 回到中位
    Servo_ReturnToCenter();
}

void Servo_ReturnToCenter(void)
{
    current_pulse1 = 1500;
    current_pulse2 = 1500;
    // 停止持续运动的指令
    Servo_Stop();
    // 强制写入中位PWM
    __HAL_TIM_SetCompare(&htim1, TIM_CHANNEL_1, current_pulse1);
    __HAL_TIM_SetCompare(&htim1, TIM_CHANNEL_2, current_pulse2);
}

// ==========================================
// 内部点动执行函数 (供 Task 调用)
// ==========================================
static void Servo1_Increase(void)
{
    if (current_pulse1 + SERVO_PULSE_STEP <= SERVO_MAX_PULSE) {
        current_pulse1 += SERVO_PULSE_STEP;
    } else {
        current_pulse1 = SERVO_MAX_PULSE;
    }
    __HAL_TIM_SetCompare(&htim1, TIM_CHANNEL_1, current_pulse1);
}

static void Servo1_Decrease(void)
{
    if (current_pulse1 - SERVO_PULSE_STEP >= SERVO_MIN_PULSE) {
        current_pulse1 -= SERVO_PULSE_STEP;
    } else {
        current_pulse1 = SERVO_MIN_PULSE;
    }
    __HAL_TIM_SetCompare(&htim1, TIM_CHANNEL_1, current_pulse1);
}

static void Servo2_Increase(void)
{
    if (current_pulse2 + SERVO_PULSE_STEP <= SERVO_MAX_PULSE) {
        current_pulse2 += SERVO_PULSE_STEP;
    } else {
        current_pulse2 = SERVO_MAX_PULSE;
    }
    __HAL_TIM_SetCompare(&htim1, TIM_CHANNEL_2, current_pulse2);
}

static void Servo2_Decrease(void)
{
    if (current_pulse2 - SERVO_PULSE_STEP >= SERVO_MIN_PULSE) {
        current_pulse2 -= SERVO_PULSE_STEP;
    } else {
        current_pulse2 = SERVO_MIN_PULSE;
    }
    __HAL_TIM_SetCompare(&htim1, TIM_CHANNEL_2, current_pulse2);
}

// ==========================================
// 持续转动状态控制 (外部调用，非阻塞)
// ==========================================
void Turn_Left_Continuous(void)  { dir1 = DIR_INC;}
void Turn_Right_Continuous(void) { dir1 = DIR_DEC;}
// 已根据要求对调上下逻辑
void Turn_Up_Continuous(void)    { dir2 = DIR_DEC;}
void Turn_Down_Continuous(void)  { dir2 = DIR_INC;}

void Servo_Stop(void)
{
    dir1 = DIR_STOP;
    dir2 = DIR_STOP; 
}

// ==========================================
// 后台任务引擎：由 TIM6 中断精准调用 (每20ms一次)
// ==========================================
void Servo_Task(void)
{
    // 删除了 HAL_GetTick 的判断，因为进这个函数就意味着 20ms 已经到了
    
    // 根据通道1的状态执行
    if (dir1 == DIR_INC)      Servo1_Increase();
    else if (dir1 == DIR_DEC) Servo1_Decrease();

    // 根据通道2的状态执行
    if (dir2 == DIR_INC)      Servo2_Increase();
    else if (dir2 == DIR_DEC) Servo2_Decrease();
}

// ==========================================
// 视觉 PID 追踪算法
// ==========================================

// 假设 OpenMV 画面分辨率为 320x240，中心点即为 (160, 120)
#define CENTER_X 160
#define CENTER_Y 120

// PID 参数结构体
typedef struct {
    float Kp;
    float Kd;
    int16_t error_last;
} PID_TypeDef;

// Kp 决定纠偏力度。由于偏差是像素(最大可能上百)，Kp 一般不用太大
static PID_TypeDef pid_line = {0.05f, 0.02f, 0};

// ==========================================
// 红光巡线核心控制算法 (由 TIM6 每 20ms 调用)
// ==========================================
void Servo_LineFollow_Task(int16_t err_d, int16_t line_angle, uint8_t corner_flag)
{
    // 1. 遇到拐点时的特殊处理 (可根据 OpenMV 的实际逻辑扩展)
    if (corner_flag == 1) {
        // 比如在拐角处降低前进速度，或者让 OpenMV 主导切换追踪的新线段
        // 此处暂不做复杂干预，依赖 OpenMV 传回新的角度
    }

    // 2. PID 计算纠偏输出量
    float pid_out = pid_line.Kp * err_d + pid_line.Kd * (err_d - pid_line.error_last);
    pid_line.error_last = err_d;

    // 3. 将角度转化为弧度制
    float rad = line_angle * PI / 180.0f;

    // 4. 向量分解：基础前进矢量 + 垂直纠偏矢量
    // 前进矢量: ( V * cos(rad), V * sin(rad) )
    // 垂直纠偏矢量: 与前进方向垂直，即 ( pid * cos(rad + 90°), pid * sin(rad + 90°) )
    // 根据三角函数化简：cos(rad + 90°) = -sin(rad), sin(rad + 90°) = cos(rad)
    
    float delta_x = V_FORWARD * cosf(rad) - pid_out * sinf(rad);
    float delta_y = V_FORWARD * sinf(rad) + pid_out * cosf(rad);

    // 5. 累计到当前脉宽
    current_pulse1 += delta_x;
    current_pulse2 += delta_y;

    // 6. 极限保护
    if (current_pulse1 > SERVO_MAX_PULSE) current_pulse1 = SERVO_MAX_PULSE;
    if (current_pulse1 < SERVO_MIN_PULSE) current_pulse1 = SERVO_MIN_PULSE;
    if (current_pulse2 > SERVO_MAX_PULSE) current_pulse2 = SERVO_MAX_PULSE;
    if (current_pulse2 < SERVO_MIN_PULSE) current_pulse2 = SERVO_MIN_PULSE;

    // 7. 转换为整数并输出驱动硬件
    __HAL_TIM_SetCompare(&htim1, TIM_CHANNEL_1, (uint32_t)current_pulse1);
    __HAL_TIM_SetCompare(&htim1, TIM_CHANNEL_2, (uint32_t)current_pulse2);
}

// 这里的 Kp 和 Kd 需要你根据实际云台的反应速度去调整
// Kp 太小：追踪慢；Kp 太大：云台来回疯狂抖动
PID_TypeDef pid_x = {0.5f, 0.1f, 0}; 
PID_TypeDef pid_y = {0.5f, 0.1f, 0};

/**
 * @brief  PID 追踪运算函数 (由 TIM6 每 20ms 调用一次)
 * @param  target_x: OpenMV 传回的 X 坐标
 * @param  target_y: OpenMV 传回的 Y 坐标
 */
void Servo_Track_PID(int16_t target_x, int16_t target_y)
{
    // 如果坐标为 0,0 (假设这是 OpenMV 没识别到目标时的默认值)，则云台保持不动
    if(target_x == 0 && target_y == 0) return;

    // 1. 计算偏差 (中心点 - 目标点)
    int16_t err_x = CENTER_X - target_x; 
    int16_t err_y = CENTER_Y - target_y;

    // 2. PD 计算输出增量
    float out_x = pid_x.Kp * err_x + pid_x.Kd * (err_x - pid_x.error_last);
    float out_y = pid_y.Kp * err_y + pid_y.Kd * (err_y - pid_y.error_last);

    // 记录本次偏差供下次微分使用
    pid_x.error_last = err_x;
    pid_y.error_last = err_y;

    // 3. 叠加到当前脉宽 (如果方向反了，把 += 改成 -= 即可)
    current_pulse1 += (int16_t)out_x;
    current_pulse2 += (int16_t)out_y;

    // 4. 严格限幅，防止打坏舵机
    if (current_pulse1 > SERVO_MAX_PULSE) current_pulse1 = SERVO_MAX_PULSE;
    if (current_pulse1 < SERVO_MIN_PULSE) current_pulse1 = SERVO_MIN_PULSE;
    if (current_pulse2 > SERVO_MAX_PULSE) current_pulse2 = SERVO_MAX_PULSE;
    if (current_pulse2 < SERVO_MIN_PULSE) current_pulse2 = SERVO_MIN_PULSE;

    // 5. 写入寄存器执行动作
    __HAL_TIM_SetCompare(&htim1, TIM_CHANNEL_1, current_pulse1);
    __HAL_TIM_SetCompare(&htim1, TIM_CHANNEL_2, current_pulse2);
}