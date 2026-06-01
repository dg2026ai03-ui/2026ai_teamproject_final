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

##웹사이트 코드 

import machine
import time
import struct
import network
import socket

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

# ==========================================================
# 2. 하드웨어 설정
# ==========================================================
i2c_bus = machine.I2C(0, sda=machine.Pin(8), scl=machine.Pin(9), freq=50000)
mq2_sensor = machine.ADC(26)
LED = machine.Pin(16, machine.Pin.OUT)

sensor = SCD30(i2c_bus)
sensor.start()

# ==========================================================
# 3. ✏️ 여기 2줄만 학생이 직접 수정하세요!
# ==========================================================
WIFI_SSID = "senWiFi_Free_sky"   # 예시: "Danggok_WiFi"
WIFI_PW   = "sudo25sky@" # 예시: "1234abcd"

# 와이파이 연결
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
    print(f"\n✅ 연결 성공!")
    print(f"📱 브라우저에서 http://{ip} 로 접속하세요!")
else:
    print("\n❌ 연결 실패! 와이파이 이름/비밀번호를 확인하세요.")

# ==========================================================
# 4. 전역 변수
# ==========================================================
temp, hum, co2, di, gas = 0.0, 0.0, 0.0, 0.0, 0
STUDY_TIME   = 50 * 60 * 1000
STRETCH_TIME = 10 * 60 * 1000
is_study = True
prev_ms = time.ticks_ms()
selected_weather = "sunny"

def update_sensors():
    global temp, hum, co2, di, gas, is_study, prev_ms
    now = time.ticks_ms()
    if sensor.ready():
        try:
            co2, temp, hum = sensor.read_measurement()
            di = 0.81 * temp + 0.01 * hum * (0.99 * temp - 14.3) + 46.3
        except: pass
    gas = mq2_sensor.read_u16()

    elapsed = time.ticks_diff(now, prev_ms)
    if is_study and elapsed >= STUDY_TIME:
        is_study = False; prev_ms = now
    elif not is_study and elapsed >= STRETCH_TIME:
        is_study = True; prev_ms = now

    if not is_study:
        LED.value((now // 150) % 2)
    elif di >= 75.0 or co2 >= 1000 or gas >= 25000:
        LED.value((now // 600) % 2)
    else:
        LED.value(1)

# ==========================================================
# 5. 웹페이지 HTML (온도계 게이지 + 날씨 선택 포함)
# ==========================================================
def get_html(di, co2, gas, temp, hum, timer_str, guide, weather, pointer_px):
    weather_buttons = ""
    weathers = [("sunny","☀️ 쨍쨍"),("dusty","😷 황사"),("rainy","☔ 비옴"),("cold","❄️ 겨울")]
    for key, label in weathers:
        if key == weather:
            weather_buttons += f'<a href="/?w={key}" class="p-3 rounded-xl bg-emerald-900 border-2 border-emerald-400 font-bold text-center text-sm text-emerald-300">{label}</a>'
        else:
            weather_buttons += f'<a href="/?w={key}" class="p-3 rounded-xl bg-slate-800 font-bold text-center text-sm hover:bg-slate-700">{label}</a>'

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="3">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>당곡고 Study Shield</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
body {{ font-family: sans-serif; }}
.gauge-bar {{
    background: linear-gradient(to top, #10b981 0%, #facc15 50%, #f43f5e 100%);
    width: 36px; height: 320px; border-radius: 18px;
    box-shadow: inset 0 2px 8px rgba(0,0,0,0.5);
    position: relative;
}}
#pointer {{ position: absolute; left: 46px; }}
</style>
</head>
<body class="bg-slate-950 text-slate-200 min-h-screen flex flex-col items-center p-6">

<header class="w-full max-w-4xl flex justify-between items-center mb-8">
    <h1 class="text-2xl font-black text-emerald-400">🧠 STUDY SHIELD</h1>
    <span class="text-xs text-slate-500 font-bold">3초마다 자동 갱신</span>
</header>

<div class="grid grid-cols-1 md:grid-cols-3 gap-8 w-full max-w-4xl">

    <!-- 날씨 선택 + 가이드 -->
    <div class="bg-slate-900 border border-slate-800 p-6 rounded-3xl flex flex-col gap-6">
        <div>
            <h3 class="text-xs font-bold text-slate-500 mb-4 uppercase">⛅ 바깥 날씨 선택</h3>
            <div class="grid grid-cols-2 gap-2">
                {weather_buttons}
            </div>
        </div>
        <div>
            <h3 class="text-xs font-bold text-emerald-500 mb-2 uppercase">💡 맞춤 처방</h3>
            <p class="text-slate-300 font-medium leading-relaxed text-sm">{guide}</p>
        </div>
    </div>

    <!-- 온도계 게이지 -->
    <div class="bg-slate-900 border border-slate-800 p-8 rounded-[3rem] flex flex-col items-center">
        <span class="text-xs font-bold text-slate-500 mb-6 uppercase">불쾌지수(DI) 게이지</span>
        <div class="relative flex items-center h-[320px]">
            <div class="absolute -left-12 flex flex-col justify-between h-full text-[9px] text-slate-600 font-bold py-1">
                <span>위험(85)</span>
                <span>높음(75)</span>
                <span>보통(68)</span>
                <span>쾌적(60)</span>
            </div>
            <div class="gauge-bar"></div>
            <div id="pointer" style="top: {pointer_px}px;">
                <div class="flex items-center gap-2">
                    <span class="text-white text-xl">◀</span>
                    <div class="bg-slate-800 border border-slate-700 px-3 py-1 rounded-xl shadow-xl">
                        <span class="text-2xl font-black">{di:.1f}</span>
                    </div>
                </div>
            </div>
        </div>
        <div class="mt-8 text-5xl font-mono font-black text-emerald-400">{timer_str}</div>
    </div>

    <!-- 기타 수치 -->
    <div class="flex flex-col gap-4">
        <div class="bg-slate-900 border border-slate-800 p-6 rounded-3xl">
            <span class="text-xs font-bold text-slate-500 uppercase">이산화탄소(CO2)</span>
            <div class="text-5xl font-black mt-1">{int(co2)}</div>
            <span class="text-[10px] text-slate-600">ppm | 기준: 1,000ppm</span>
        </div>
        <div class="bg-slate-900 border border-slate-800 p-6 rounded-3xl">
            <span class="text-xs font-bold text-slate-500 uppercase">가스 오염도(MQ-2)</span>
            <div class="text-5xl font-black mt-1">{gas}</div>
            <span class="text-[10px] text-slate-600">기준: 25,000 초과 시 주의</span>
        </div>
        <div class="flex gap-3">
            <div class="flex-1 bg-slate-900 border border-slate-800 p-4 rounded-2xl text-center">
                <span class="text-[10px] text-slate-500 font-bold">온도</span>
                <div class="font-black text-lg mt-1">{temp:.1f}°C</div>
            </div>
            <div class="flex-1 bg-slate-900 border border-slate-800 p-4 rounded-2xl text-center">
                <span class="text-[10px] text-slate-500 font-bold">습도</span>
                <div class="font-black text-lg mt-1">{hum:.1f}%</div>
            </div>
        </div>
    </div>

</div>
</body></html>"""

# ==========================================================
# 6. 소켓 웹서버 실행
# ==========================================================
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('', 80))
s.listen(5)
s.setblocking(False)
print("🌐 웹서버 실행 중...")

while True:
    # 센서 업데이트
    update_sensors()

    # 브라우저 요청 처리
    try:
        conn, addr = s.accept()
        conn.settimeout(2.0)
        try:
            request = conn.recv(1024).decode()

            # 날씨 버튼 클릭 처리
            if "?w=sunny" in request: selected_weather = "sunny"
            elif "?w=dusty" in request: selected_weather = "dusty"
            elif "?w=rainy" in request: selected_weather = "rainy"
            elif "?w=cold"  in request: selected_weather = "cold"

            # 타이머 계산
            elapsed = time.ticks_diff(time.ticks_ms(), prev_ms)
            rem = max(0, ((STUDY_TIME if is_study else STRETCH_TIME) - elapsed) // 1000)
            timer_str = f"{int(rem//60):02d}:{int(rem%60):02d}"

            # 화살표 포인터 위치 계산
            pointer_px = int(320 - ((di - 60) * (320 / 25))) - 15
            pointer_px = max(-15, min(305, pointer_px))

            # 날씨별 가이드 결정
            bad = (di >= 75.0 or co2 >= 1000 or gas >= 25000)
            if not is_study:
                guide = "🧘‍♂️ 스트레칭 시간! 자리에서 일어나 몸을 움직이세요."
            elif bad:
                if selected_weather == "sunny": guide = "☀️ 맑으니 창문을 활짝 열어 환기하세요!"
                elif selected_weather == "dusty": guide = "😷 황사가 심하니 창문은 1cm만 열고 에어컨을 켜세요!"
                elif selected_weather == "rainy": guide = "☔ 비가 오니 창문을 닫고 제습 모드를 가동하세요!"
                else: guide = "❄️ 추우니 2분만 짧게 환기하고 문을 닫으세요!"
            else:
                guide = "🟢 집중하기 아주 좋은 환경입니다!"

            # HTML 생성 및 전송
            html = get_html(di, co2, gas, temp, hum, timer_str, guide, selected_weather, pointer_px)
            conn.send("HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n")
            conn.send(html)
        except: pass
        conn.close()
    except: pass

    time.sleep_ms(100)

