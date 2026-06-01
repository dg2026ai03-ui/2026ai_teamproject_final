import machine
import time
import struct
import sys
import select

# 1. SCD30 센서 드라이버
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
            self.i2c.writeto(self.addr, b'\x03\x00')
            time.sleep_ms(30)
            m = self.i2c.readfrom(self.addr, 18)
            for i in range(0, 18, 3): self._check_crc(m[i:i+3])
            co2 = struct.unpack('>f', bytes([m[0],m[1],m[3],m[4]]))[0]
            temp = struct.unpack('>f', bytes([m[6],m[7],m[9],m[10]]))[0]
            hum = struct.unpack('>f', bytes([m[12],m[13],m[15],m[16]]))[0]
            return co2, temp, hum
        except: return 0.0, 0.0, 0.0

    def start(self):
        self.i2c.writeto(self.addr, b'\x00\x10\x00\x00\x81')

    def ready(self):
        try:
            self.i2c.writeto(self.addr, b'\x02\x02')
            return struct.unpack('>H', self.i2c.readfrom(self.addr, 3)[:2])[0] == 1
        except: return False

# 2. ✅ 핀 번호 수정 (0번 버스, GP8=SDA, GP9=SCL)
i2c_bus = machine.I2C(0, sda=machine.Pin(8), scl=machine.Pin(9), freq=50000)
mq2_sensor = machine.ADC(26)
LED = machine.Pin(16, machine.Pin.OUT)

sensor = SCD30(i2c_bus)
sensor.start()

# 설정값
STUDY_TIME = 50 * 60
STRETCH_TIME = 10 * 60
weather_mode = "1"
weather_names = {"1": "맑음☀️", "2": "황사😷", "3": "비☔", "4": "겨울❄️"}

is_study = True
start_time = time.time()

print("="*50)
print("당곡고 집중도 방어 시스템 가동")
print("날씨 변경 방법: Shell창에 숫자 입력 후 Enter")
print("1:맑음, 2:황사, 3:비, 4:겨울")
print("="*50)

while True:
    now_ts = time.time()
    
    # 키보드 입력 확인 (날씨 변경용)
    if select.select([sys.stdin], [], [], 0)[0]:
        ch = sys.stdin.read(1)
        if ch in ["1", "2", "3", "4"]:
            weather_mode = ch
            print(f"\n[설정 변경] 날씨가 '{weather_names[ch]}'로 변경되었습니다.")

    # 센서 데이터 수집
    temp, hum, co2, di = 0.0, 0.0, 0.0, 0.0
    if sensor.ready():
        co2, temp, hum = sensor.read_measurement()
        di = 0.81 * temp + 0.01 * hum * (0.99 * temp - 14.3) + 46.3
    gas = mq2_sensor.read_u16()

    # 타이머 로직
    elapsed = now_ts - start_time
    limit = STUDY_TIME if is_study else STRETCH_TIME
    if elapsed >= limit:
        is_study = not is_study
        start_time = now_ts
        print("\n" + "!"*30)
        print("모드가 변경되었습니다!")
        print("!"*30 + "\n")

    # 남은 시간 계산
    rem_min = (limit - elapsed) // 60
    rem_sec = (limit - elapsed) % 60
    
    print(f"\r[{'공부' if is_study else '휴식'}] {int(rem_min):02d}:{int(rem_sec):02d} | DI:{di:.1f} | CO2:{int(co2)} | 가스:{gas} | 날씨:{weather_names[weather_mode]}", end="")

    # LED 제어 및 안내 메시지
    if not is_study:
        LED.value(int(time.ticks_ms() / 100) % 2)
        if int(elapsed) % 60 == 0:
            print("\n[안내] 스트레칭 시간입니다! 자리에서 일어나 몸을 푸세요.")
    else:
        is_bad = (di >= 75.0 or co2 >= 1000 or gas >= 25000)
        if is_bad:
            LED.value(int(time.ticks_ms() / 500) % 2)
            if int(elapsed) % 10 == 0:
                print("\n" + "-"*30)
                print(f"[경고] 집중 환경이 나쁩니다! (날씨: {weather_names[weather_mode]})")
                if weather_mode == "1":
                    print("👉 창문을 활짝 열어 환기하고 불쾌지수를 낮추세요!")
                elif weather_mode == "2":
                    print("👉 창문을 1cm만 열어 살짝 환기하고 에어컨을 켜세요!")
                elif weather_mode == "3":
                    print("👉 창문을 닫고 에어컨 제습 모드를 가동하세요!")
                elif weather_mode == "4":
                    print("👉 너무 추우니 2분간만 짧게 환기하고 문을 닫으세요!")
                print("-"*30)
        else:
            LED.value(1)

    time.sleep(0.1)
