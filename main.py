import machine
import time
import struct
import network
import socket
import math
from neopixel import NeoPixel

# ==========================================================
# 1. SCD30 드라이버
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
            self.i2c.writeto(self.addr, b'\x03\x00')
            time.sleep_ms(30)
            m = self.i2c.readfrom(self.addr, 18)
            for i in range(0, 18, 3):
                self._check_crc(m[i:i+3])
            co2  = struct.unpack('>f', bytes([m[0],m[1],m[3],m[4]]))[0]
            temp = struct.unpack('>f', bytes([m[6],m[7],m[9],m[10]]))[0]
            hum  = struct.unpack('>f', bytes([m[12],m[13],m[15],m[16]]))[0]
            return co2, temp, hum
        except OSError as e:
            print(f"I2C 오류: {e}")
            return None
        except Exception as e:
            print(f"센서 오류: {e}")
            return None

    def start(self):
        try:
            self.i2c.writeto(self.addr, b'\x00\x10\x00\x00\x81')
            print("SCD30 시작!")
        except OSError as e:
            print(f"SCD30 시작 실패: {e}")

    def ready(self):
        try:
            self.i2c.writeto(self.addr, b'\x02\x02')
            return struct.unpack('>H', self.i2c.readfrom(self.addr, 3)[:2])[0] == 1
        except:
            return False

# ==========================================================
# 2. 하드웨어 설정
# ==========================================================
i2c_bus    = machine.I2C(0, sda=machine.Pin(8), scl=machine.Pin(9), freq=50000)
mq2_sensor = machine.ADC(26)
NUM_LEDS   = 10
np         = NeoPixel(machine.Pin(16), NUM_LEDS)
sensor     = SCD30(i2c_bus)
sensor.start()

# ==========================================================
# 3. 와이파이 설정
# ==========================================================
WIFI_SSID = "senWiFi_Free_sky"
WIFI_PW   = "sudo25sky@"

wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(WIFI_SSID, WIFI_PW)

print("와이파이 연결 중...")
for _ in range(20):
    if wlan.isconnected(): break
    time.sleep(1)
    print(".", end="")

if wlan.isconnected():
    ip = wlan.ifconfig()[0]
    print(f"\n연결 성공!")
    print("=" * 40)
    print(f"👉 http://{ip}")
    print("=" * 40)
else:
    print("\n연결 실패!")
    ip = "0.0.0.0"

# ==========================================================
# 4. 전역 변수
# ==========================================================
co2, temp, hum, di, gas = 450.0, 24.0, 50.0, 0.0, 0
STUDY_TIME       = 50 * 60 * 1000
STRETCH_TIME     = 10 * 60 * 1000
is_study         = True
prev_ms          = time.ticks_ms()
selected_weather = "sunny"
co2_history      = []
time_history     = []
start_ts         = time.time()

# ==========================================================
# 5. LED 제어
# ==========================================================
def update_led(di, co2, gas, is_study):
    now = time.ticks_ms()
    if not is_study:
        val = 150 if (now // 300) % 2 == 0 else 0
        for i in range(NUM_LEDS):
            np[i] = (0, 0, val)
    elif di >= 80 or co2 >= 1500 or gas >= 25000:
        val = 150 if (now // 150) % 2 == 0 else 0
        for i in range(NUM_LEDS):
            np[i] = (val, 0, 0)
    elif di >= 75 or co2 >= 1000:
        val = 120 if (now // 500) % 2 == 0 else 0
        for i in range(NUM_LEDS):
            np[i] = (val, val, 0)
    else:
        for i in range(NUM_LEDS):
            np[i] = (0, 100, 0)
    np.write()

# ==========================================================
# 6. 센서 업데이트
# ==========================================================
def update_sensors():
    global co2, temp, hum, di, gas, is_study, prev_ms
    global co2_history, time_history

    now = time.ticks_ms()
    if sensor.ready():
        result = sensor.read_measurement()
        if result is not None:
            co2, temp, hum = result
            di = 0.81 * temp + 0.01 * hum * (0.99 * temp - 14.3) + 46.3
            elapsed_sec = time.time() - start_ts
            co2_history.append(int(co2))
            time_history.append(int(elapsed_sec))
            if len(co2_history) > 20:
                co2_history.pop(0)
                time_history.pop(0)

    gas = mq2_sensor.read_u16()
    elapsed = time.ticks_diff(now, prev_ms)
    if is_study and elapsed >= STUDY_TIME:
        is_study = False
        prev_ms  = now
        print("휴식 시간!")
    elif not is_study and elapsed >= STRETCH_TIME:
        is_study = True
        prev_ms  = now
        print("공부 시간!")
    update_led(di, co2, gas, is_study)

# ==========================================================
# 7. 환기 회복 시간 예측
# ==========================================================
def calc_recovery_time(current_co2):
    target  = 1000.0
    ambient = 400.0
    k       = 0.03
    if current_co2 <= target:
        return 0
    ratio = (target - ambient) / (current_co2 - ambient)
    if ratio <= 0:
        return 99
    t_min = -math.log(ratio) / k
    return max(1, int(t_min))

# ==========================================================
# 8. 환경 상태 판단
# ==========================================================
def get_status(di, co2, is_study):
    if not is_study:
        return "stretch", "🤸 스트레칭 타임!", "#a78bfa", "자리에서 일어나 몸을 쭉 펴세요!"
    elif di >= 80 or co2 >= 1500:
        return "danger", "
