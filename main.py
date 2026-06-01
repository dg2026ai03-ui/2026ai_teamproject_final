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
        except: return None

    def start(self):
        self.i2c.writeto(self.addr, b'\x00\x10\x00\x00\x81')

    def ready(self):
        try:
            self.i2c.writeto(self.addr, b'\x02\x02')
            return struct.unpack('>H', self.i2c.readfrom(self.addr, 3)[:2])[0] == 1
        except: return False

# 2. 하드웨어 설정
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
last_warning_time = 0  # 마지막 경고 출력 시간

# ⭐ 버그 수정 핵심!
# 루프 바깥에서 초기화 → 센서 미준비 시 이전 값 유지
