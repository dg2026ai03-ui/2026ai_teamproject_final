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

# ✅ 그래프용 CO2 기록 리스트 (최근 20개만 유지)
co2_history    = []
time_history   = []
start_ts       = time.time()

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

            # ✅ CO2 기록 저장 (최근 20개만 유지)
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
# 7. 환기 회복 시간 예측 함수
# ✅ 물질전달 1차 감쇄 공식 활용
# t = -ln((목표농도 - 외부농도) / (현재농도 - 외부농도)) / k
# k = 0.03 (일반 교실 환기 속도 상수 가정)
# ==========================================================
def calc_recovery_time(current_co2):
    target  = 1000.0   # 목표 CO2 농도 (ppm)
    ambient = 400.0    # 외부 대기 CO2 농도 (ppm)
    k       = 0.03     # 환기 속도 상수 (1/분)

    if current_co2 <= target:
        return 0  # 이미 쾌적한 상태

    import math
    ratio = (target - ambient) / (current_co2 - ambient)
    if ratio <= 0:
        return 99  # 계산 불가 시 최대값 반환
    t_min = -math.log(ratio) / k
    return max(1, int(t_min))

# ==========================================================
# 8. 웹페이지 HTML
# ==========================================================
def get_html(di, co2, gas, temp, hum, timer_str, guide, weather, pointer_px, recovery_min):

    # ✅ 그래프 데이터를 JavaScript 배열 문자열로 변환
    co2_data  = str(co2_history)
    time_data = str(time_history)

    # 날씨 버튼
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

    # 회복 시간 안내 문구
    if recovery_min == 0:
        recovery_text = "🟢 이미 쾌적한 환경이에요!"
        recovery_color = "#10b981"
    else:
        recovery_text = f"🪟 지금 창문 열면 약 <b>{recovery_min}분 후</b> 쾌적해져요!"
        recovery_color = "#f59e0b"

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="3">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>당곡고 Study Shield</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
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
            <h3 class="text-xs font-bold text-slate-500 mb-4 uppercase">바깥 날씨 선택</h3>
            <div class="grid grid-cols-2 gap-2">{weather_buttons}</div>
        </div>
        <div>
            <h3 class="text-xs font-bold text-emerald-500 mb-2 uppercase">맞춤 처방</h3>
            <p class="text-slate-300 font-medium leading-relaxed text-sm">{guide}</p>
        </div>
        <!-- ✅ 환기 회복 시간 예측 -->
        <div class="bg-slate-800 rounded-2xl p-4">
            <h3 class="text-xs font-bold text-slate-500 mb-2 uppercase">⏱️ 환기 회복 예측</h3>
            <p class="font-bold text-sm" style="color: {recovery_color};">{recovery_text}</p>
            <p class="text-[10px] text-slate-600 mt-1">물질전달 1차 감쇄 공식 기반 계산</p>
        </div>
    </div>

    <!-- 불쾌지수 게이지 -->
    <div class="bg-slate-900 border border-slate-800 p-8 rounded-3xl flex flex-col items-center">
        <span class="text-xs font-bold text-slate-500 mb-6 uppercase">불쾌지수(DI) 게이지</span>
        <div class="relative flex items-center h-[320px]">
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
            <span class="text-[10px] text-slate-600">ppm | 기준: 1,000ppm 초과 시 주의</span>
        </div>
        <div class="bg-slate-900 border border-slate-800 p-6 rounded-3xl">
            <span class="text-xs font-bold text-slate-500 uppercase">가스 오염도 MQ-2</span>
            <div class="text-5xl font-black mt-1">{gas}</div>
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

<!-- ✅ CO2 실시간 그래프 -->
<div class="w-full max-w-4xl mt-8 bg-slate-900 border border-slate-800 p-6 rounded-3xl">
    <h3 class="text-xs font-bold text-slate-500 mb-4 uppercase">📈 CO2 실시간 변화 그래프</h3>
    <canvas id="co2Chart" height="80"></canvas>
</div>

<script>
// 피코 W에서 넘겨준 데이터
const co2Data  = {co2_data};
const timeData = {time_data};

const ctx = document.getElementById('co2Chart').getContext('2d');
new Chart(ctx, {{
    type: 'line',
    data: {{
        labels: timeData.map(t => t + '초'),
        datasets: [{{
            label: 'CO2 (ppm)',
            data: co2Data,
            borderColor: '#4ea8de',
            backgroundColor: 'rgba(78,168,222,0.1)',
            borderWidth: 2,
            pointRadius: 3,
            pointBackgroundColor: '#4ea8de',
            tension: 0.4,
            fill: true
        }},
        {{
            label: '경고 기준 (1000ppm)',
            data: Array(co2Data.length).fill(1000),
            borderColor: '#f43f5e',
            borderWidth: 1,
            borderDash: [5, 5],
            pointRadius: 0,
            fill: false
        }}]
    }},
    options: {{
        responsive: true,
        plugins: {{
            legend: {{
                labels: {{ color: '#94a3b8', font: {{ size: 11 }} }}
            }}
        }},
        scales: {{
            x: {{
                ticks: {{ color: '#475569', maxTicksLimit: 10 }},
                grid:  {{ color: '#1e293b' }}
            }},
            y: {{
                ticks: {{ color: '#475569' }},
                grid:  {{ color: '#1e293b' }},
                min: 300,
                suggestedMax: 1500
            }}
        }}
    }}
}});
</script>

</body></html>"""

# ==========================================================
# 9. 웹서버 실행
# ==========================================================
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('', 80))
s.listen(5)
s.setblocking(False)
print("웹서버 실행 중...")

while True:
    update_sensors()
    try:
        conn, addr = s.accept()
        conn.settimeout(2.0)
        try:
            request = conn.recv(1024).decode()

            if   "?w=sunny" in request: selected_weather = "sunny"
            elif "?w=dusty" in request: selected_weather = "dusty"
            elif "?w=rainy" in request: selected_weather = "rainy"
            elif "?w=cold"  in request: selected_weather = "cold"

            elapsed   = time.ticks_diff(time.ticks_ms(), prev_ms)
            rem       = max(0, ((STUDY_TIME if is_study else STRETCH_TIME) - elapsed) // 1000)
            timer_str = f"{int(rem//60):02d}:{int(rem%60):02d}"

            pointer_px = int(320 - ((di - 60) * (320 / 25))) - 15
            pointer_px = max(-15, min(305, pointer_px))

            # ✅ 환기 회복 시간 계산
            recovery_min = calc_recovery_time(co2)

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
                           selected_weather, pointer_px, recovery_min)
            conn.send("HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n")
            conn.send(html)
        except:
            pass
        conn.close()
    except:
        pass
    time.sleep_ms(100)
