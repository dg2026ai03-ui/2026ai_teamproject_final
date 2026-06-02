import machine
import time
import struct
import network
import socket
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
            for i in range(0, 18, 3): self._check_crc(m[i:i+3])
            co2  = struct.unpack('>f', bytes([m[0],m[1],m[3],m[4]]))[0]
            temp = struct.unpack('>f', bytes([m[6],m[7],m[9],m[10]]))[0]
            hum  = struct.unpack('>f', bytes([m[12],m[13],m[15],m[16]]))[0]
            return co2, temp, hum
        except:
            return None

    def start(self):
        self.i2c.writeto(self.addr, b'\x00\x10\x00\x00\x81')

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

# ✅ 네오픽셀 LED 설정 (10개)
NUM_LEDS = 10
np = NeoPixel(machine.Pin(16), NUM_LEDS)

sensor = SCD30(i2c_bus)
sensor.start()

# ==========================================================
# 3. 와이파이 설정
# ==========================================================
WIFI_SSID = "여기에 와이파이이름"
WIFI_PW   = "여기에 비밀번호"

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
    print("=" * 40)
    print(f"👉 http://{ip}")
    print("=" * 40)
else:
    print("\n❌ 연결 실패!")
    ip = "0.0.0.0"

# ==========================================================
# 4. 전역 변수
# ==========================================================
# ✅ 루프 바깥에서 초기화 → 이전 값 유지 가능
co2, temp, hum, di, gas = 450.0, 24.0, 50.0, 0.0, 0

STUDY_TIME   = 50 * 60 * 1000  # 밀리초
STRETCH_TIME = 10 * 60 * 1000
is_study         = True
prev_ms          = time.ticks_ms()
selected_weather = "sunny"

# ==========================================================
# 5. ✅ 네오픽셀 LED 색깔 제어 함수
# ==========================================================
def update_led(di, co2, gas, is_study):
    now = time.ticks_ms()

    if not is_study:
        # 휴식 시간 → 파란색 깜빡임
        val = 150 if (now // 300) % 2 == 0 else 0
        for i in range(NUM_LEDS):
            np[i] = (0, 0, val)

    elif di >= 80 or co2 >= 1500 or gas >= 25000:
        # 매우 나쁨 → 빨간색 빠르게 깜빡임
        val = 150 if (now // 150) % 2 == 0 else 0
        for i in range(NUM_LEDS):
            np[i] = (val, 0, 0)

    elif di >= 75 or co2 >= 1000:
        # 경고 → 노란색 천천히 깜빡임
        val = 120 if (now // 500) % 2 == 0 else 0
        for i in range(NUM_LEDS):
            np[i] = (val, val, 0)

    else:
        # 쾌적 → 초록색 계속 켜짐
        for i in range(NUM_LEDS):
            np[i] = (0, 100, 0)

    np.write()

# ==========================================================
# 6. 센서 업데이트 함수
# ==========================================================
def update_sensors():
    # ✅ global 선언 추가 → 함수 안에서 전역변수 제대로 업데이트
    global co2, temp, hum, di, gas, is_study, prev_ms

    now = time.ticks_ms()

    if sensor.ready():
        result = sensor.read_measurement()
        if result is not None:
            co2, temp, hum = result
            di = 0.81 * temp + 0.01 * hum * (0.99 * temp - 14.3) + 46.3

    gas = mq2_sensor.read_u16()

    # 타이머 전환
    elapsed = time.ticks_diff(now, prev_ms)
    if is_study and elapsed >= STUDY_TIME:
        is_study = False
        prev_ms  = now
        print("\n🧘 휴식 시간 시작!")
    elif not is_study and elapsed >= STRETCH_TIME:
        is_study = True
        prev_ms  = now
        print("\n📚 공부 시간 시작!")

    # ✅ LED 색깔 업데이트
    update_led(di, co2, gas, is_study)

# ==========================================================
# 7. 웹페이지 HTML
# ==========================================================
def get_html(di, co2, gas, temp, hum, timer_str, guide, weather, pointer_px):
    weather_buttons = ""
    weathers = [
        ("sunny", "☀️ 쨍쨍"),
        ("dusty", "😷 황사"),
        ("rainy", "☔ 비옴"),
        ("cold",  "❄️ 겨울")
    ]
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
            <div class="grid grid-cols-2 gap-2">{weather_buttons}</div>
        </div>
        <div>
            <h3 class="text-xs font-bold text-emerald-500 mb-2 uppercase">💡 맞춤 처방</h3>
            <p class="text-slate-300 font-medium leading-relaxed text-sm">{guide}</p>
        </div>
    </div>

    <!-- 불쾌지수 게이지 -->
    <div class="bg-slate-900 border border-slate-800 p-8 rounded-3xl flex flex-col items-center">
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

    <!-- 센서 수치 -->
    <div class="flex flex-col gap-4">
        <div class="bg-slate-900 border border-slate-800 p-6 rounded-3xl">
            <span class="text-xs font-bold text-slate-500 uppercase">이산화탄소 CO2</span>
            <div class="text-5xl font-black mt-1">{int(co2)}</div>
            <span class="text-[10px] text-slate-600">ppm | 기준: 1,000ppm</span>
        </div>
        <div class="bg-slate-900 border border-slate-800 p-6 rounded-3xl">
            <span class="text-xs font-bold text-slate-500 uppercase">가스 오염도 MQ-2</span>
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
# 8. 소켓 웹서버 실행
# ==========================================================
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('', 80))
s.listen(5)
s.setblocking(False)
print("🌐 웹서버 실행 중...")

while True:
    update_sensors()

    try:
        conn, addr = s.accept()
        conn.settimeout(2.0)
        try:
            request = conn.recv(1024).decode()

            # 날씨 버튼 처리
            if   "?w=sunny" in request: selected_weather = "sunny"
            elif "?w=dusty" in request: selected_weather = "dusty"
            elif "?w=rainy" in request: selected_weather = "rainy"
            elif "?w=cold"  in request: selected_weather = "cold"

            # 타이머 계산
            elapsed   = time.ticks_diff(time.ticks_ms(), prev_ms)
            rem       = max(0, ((STUDY_TIME if is_study else STRETCH_TIME) - elapsed) // 1000)
            timer_str = f"{int(rem//60):02d}:{int(rem%60):02d}"

            # 포인터 위치 계산
            pointer_px = int(320 - ((di - 60) * (320 / 25))) - 15
            pointer_px = max(-15, min(305, pointer_px))

            # 날씨별 맞춤 가이드
            bad = (di >= 75.0 or co2 >= 1000 or gas >= 25000)
            if not is_study:
                guide = "🧘 스트레칭 시간! 자리에서 일어나 몸을 움직이세요."
            elif bad:
                if   selected_weather == "sunny": guide = "☀️ 창문을 활짝 열어 환기하세요!"
                elif selected_weather == "dusty": guide = "😷 창문은 1cm만 열고 에어컨을 켜세요!"
                elif selected_weather == "rainy": guide = "☔ 창문을 닫고 에어컨 제습 모드를 켜세요!"
                else:                             guide = "❄️ 2분만 짧게 환기하고 문을 닫으세요!"
            else:
                guide = "🟢 집중하기 아주 좋은 환경입니다!"

            html = get_html(di, co2, gas, temp, hum, timer_str, guide,
                           selected_weather, pointer_px)
            conn.send("HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n")
            conn.send(html)
        except:
            pass
        conn.close()
    except:
        pass

    time.sleep_ms(100)
