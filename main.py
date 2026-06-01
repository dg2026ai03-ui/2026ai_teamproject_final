import machine
import time
import struct
import sys
import select

# ==========================================================
# 1. SCD30 센서 드라이버 (I2C1 통신 전용)
# ==========================================================
class SCD30:
    def __init__(self, i2c, addr=0x61):
        self.i2c = i2c
        self.addr = addr
        self.crc_table = [self._generate_crc(i) for i in range(256)]

    def _generate_crc(self, crc):
        for _ in range(8):
            if crc & 0x80: crc = (crc << 1) ^ 0x31
            else: crc = (crc << 1)
            crc &= 0xFF
        return crc

    def _check_crc(self, arr):
        crc = 0xff
        for i in range(2):
            crc ^= arr[i]
            crc = self.crc_table[crc]
        if crc != arr[2]: raise Exception("CRC Error")

    def read_measurement(self):
        try:
            # 데이터 읽기 명령 전송
            self.i2c.writeto(self.addr, b'\x03\x00')
            time.sleep_ms(30)
            m = self.i2c.readfrom(self.addr, 18)
            for i in range(0, 18, 3): self._check_crc(m[i:i+3])
            
            # 바이트 데이터를 실수형(float)으로 변환
            co2 = struct.unpack('>f', bytes([m[0],m[1],m[3],m[4]]))[0]
            temp = struct.unpack('>f', bytes([m[6],m[7],m[9],m[10]]))[0]
            hum = struct.unpack('>f', bytes([m[12],m[13],m[15],m[16]]))[0]
            return co2, temp, hum
        except: return 0.0, 0.0, 0.0

    def start(self):
        # 연속 측정 시작 명령
        self.i2c.writeto(self.addr, b'\x00\x10\x00\x00\x81')

    def ready(self):
        try:
            self.i2c.writeto(self.addr, b'\x02\x02')
            return struct.unpack('>H', self.i2c.readfrom(self.addr, 3)[:2])[0] == 1
        except: return False

# ==========================================================
# 2. 하드웨어 설정 (I2C1 판 및 요청하신 핀 적용)
# ==========================================================
# I2C1 채널 설정 (SDA=GP6, SCL=GP7)
i2c_bus = machine.I2C(1, sda=machine.Pin(6), scl=machine.Pin(7), freq=50000)

# MQ-2 가스 센서 (GP26 = A0)
mq2_sensor = machine.ADC(26)

# LED 1개 (GP16 = D16)
LED = machine.Pin(16, machine.Pin.OUT)

sensor = SCD30(i2c_bus)
sensor.start()

# 타이머 및 날씨 초기값 (50분/10분)
STUDY_MIN = 50 
STRETCH_MIN = 10
weather_mode = "1" # 1:쨍쨍, 2:황사, 3:비, 4:겨울
weather_map = {"1": "해 쨍쨍☀️", "2": "황사/먼지😷", "3": "비 내림☔", "4": "겨울❄️"}

is_study = True
start_time = time.time()

print("\n" + "="*50)
print("당곡고 지능형 집중도 방어 시스템 시작")
print(f"현재 설정: {STUDY_MIN}분 공부 / {STRETCH_MIN}분 휴식")
print("날씨 변경: Shell창에 1~4 입력 후 Enter")
print("="*50 + "\n")

# ==========================================================
# 3. 메인 로직 루프
# ==========================================================
while True:
    now_ts = time.time()
    
    # [입력] 날씨 모드 실시간 변경 (비차단 입력 처리)
    if select.select([sys.stdin], [], [], 0)[0]:
        key = sys.stdin.read(1)
        if key in weather_map:
            weather_mode = key
            print(f"\n[날씨 변경] '{weather_map[key]}' 모드로 전환되었습니다.")

    # [측정] SCD30 & MQ-2 데이터 수집
    co2, temp, hum, di = 0.0, 0.0, 0.0, 0.0
    if sensor.ready():
        co2, temp, hum = sensor.read_measurement()
        # 불쾌지수 공식 대입
        di = 0.81 * temp + 0.01 * hum * (0.99 * temp - 14.3) + 46.3
    gas = mq2_sensor.read_u16()

    # [타이머] 모드 전환 계산
    elapsed = now_ts - start_time
    limit = (STUDY_MIN if is_study else STRETCH_MIN) * 60
    
    if elapsed >= limit:
        is_study = not is_study
        start_time = now_ts
        print("\n\n" + "★" * 15 + f" {'[공부 모드]' if is_study else '[스트레칭 모드]'} 시작 " + "★" * 15 + "\n")

    rem = limit - elapsed
    
    # [출력] 실시간 모니터링 (Shell창 하단 고정)
    print(f"\r[{'공부' if is_study else '휴식'}] {int(rem//60):02d}:{int(rem%60):02d} | DI:{di:.1f} | CO2:{int(co2)}ppm | 가스:{gas} | 날씨:{weather_map[weather_mode]}", end="")

    # [제어] LED 패턴 및 상황별 해결책 출력
    if not is_study:
        # 🧘‍♂️ 스트레칭 모드: LED 매우 빠르게 깜빡임
        LED.value(int(time.ticks_ms() / 150) % 2)
        if int(elapsed) % 60 == 0:
            print("\n[알림] 50분 집중 끝! 지금 바로 일어나서 스트레칭 하세요!")
    else:
        # ✏️ 공부 모드 환경 분석
        bad_env = (di >= 75.0 or co2 >= 1000 or gas >= 25000)
        
        if bad_env:
            # 경보 상태: LED 천천히 깜빡임
            LED.value(int(time.ticks_ms() / 600) % 2)
            
            # 10초 주기로 날씨 맞춤 해결책 출력
            if int(elapsed) % 10 == 0:
                print(f"\n\n🚨 [집중력 경고] 실내 환경이 나쁩니다! (현재 날씨: {weather_map[weather_mode]})")
                if weather_mode == "1": # 쨍쨍
                    print("✅ 창문을 활짝 열어 환기하고, 선풍기로 불쾌지수를 낮추세요!")
                elif weather_mode == "2": # 황사
                    print("✅ 창문을 1cm만 열어 살짝 환기하고, 에어컨을 세게 켜세요!")
                elif weather_mode == "3": # 비
                    print("✅ 밖이 습하니 창문을 닫고, 에어컨 제습 모드를 가동하세요!")
                elif weather_mode == "4": # 겨울
                    print("✅ 추우니까 2분만 짧게 환기하고 즉시 문을 닫으세요!")
                print("-" * 50)
        else:
            # 최적 상태: LED 계속 켜짐
            LED.value(1)

    time.sleep(0.1)
