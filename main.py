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
        return "danger", "🔴 매우 나쁨", "#f87171", "즉시 환기가 필요해요!"
    elif di >= 75 or co2 >= 1000:
        return "warning", "🟡 주의", "#fbbf24", "집중력이 떨어질 수 있어요!"
    else:
        return "good", "🟢 쾌적해요!", "#34d399", "공부하기 딱 좋은 환경이에요!"

# ==========================================================
# 9. HTML 생성
# ==========================================================
def get_html(di, co2, gas, temp, hum, timer_str, guide,
             weather, pointer_px, recovery_min, is_study):

    co2_data  = str(co2_history)
    time_data = str(time_history)

    status_key, status_label, status_color, status_desc = get_status(di, co2, is_study)

    # 집중력 점수 계산
    score = 100
    if di > 70:  score -= int((di - 70) * 4)
    if co2 > 800: score -= int((co2 - 800) * 0.05)
    score = max(0, min(100, score))

    if score >= 80:
        score_color = "#34d399"
        score_emoji = "😊"
    elif score >= 50:
        score_color = "#fbbf24"
        score_emoji = "😐"
    else:
        score_color = "#f87171"
        score_emoji = "😵"

    # 회복 시간 안내
    if recovery_min == 0:
        recovery_text = "✅ 이미 쾌적한 환경이에요!"
        recovery_color = "#34d399"
    else:
        recovery_text = f"🪟 창문 열면 약 {recovery_min}분 후 쾌적해져요!"
        recovery_color = "#fbbf24"

    # 날씨 버튼
    weather_buttons = ""
    weathers = [
        ("sunny", "☀️", "맑음"),
        ("dusty", "😷", "황사"),
        ("rainy", "☔", "비"),
        ("cold",  "❄️", "겨울")
    ]
    for key, icon, label in weathers:
        if key == weather:
            weather_buttons += f'''
            <a href="/?w={key}"
               style="background:#ecfdf5; border:2px solid #34d399; color:#065f46;"
               class="flex flex-col items-center p-3 rounded-2xl font-bold text-sm cursor-pointer">
                <span class="text-2xl">{icon}</span>
                <span class="mt-1">{label}</span>
            </a>'''
        else:
            weather_buttons += f'''
            <a href="/?w={key}"
               style="background:#f8fafc; border:2px solid #e2e8f0; color:#64748b;"
               class="flex flex-col items-center p-3 rounded-2xl font-bold text-sm cursor-pointer hover:border-emerald-300">
                <span class="text-2xl">{icon}</span>
                <span class="mt-1">{label}</span>
            </a>'''

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
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
    background: linear-gradient(135deg, #f0fdf4 0%, #eff6ff 100%);
    min-height: 100vh;
    padding: 24px 16px;
  }}
  .card {{
    background: white;
    border-radius: 24px;
    padding: 24px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.06);
    border: 1px solid #f1f5f9;
  }}
  .label {{
    font-size: 11px;
    font-weight: 700;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 6px;
  }}
  .big-num {{
    font-size: 48px;
    font-weight: 900;
    line-height: 1;
  }}
  .badge {{
    display: inline-block;
    padding: 6px 14px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 700;
  }}
  .gauge-wrap {{
    background: linear-gradient(to top, #34d399, #fbbf24, #f87171);
    width: 20px;
    height: 200px;
    border-radius: 999px;
    position: relative;
  }}
  .gauge-needle {{
    position: absolute;
    right: -36px;
    width: 32px;
    height: 24px;
    display: flex;
    align-items: center;
    gap: 4px;
  }}
  .score-ring {{
    width: 120px;
    height: 120px;
    border-radius: 50%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    border: 8px solid;
    margin: 0 auto;
  }}
</style>
</head>
<body>

<!-- 헤더 -->
<div style="max-width:900px; margin:0 auto;">
  <div class="flex items-center justify-between mb-6">
    <div>
      <h1 style="font-size:22px; font-weight:900; color:#1e293b;">
        🧠 Study Shield
      </h1>
      <p style="font-size:12px; color:#94a3b8; margin-top:2px;">
        당곡고등학교 · 3초마다 자동 갱신
      </p>
    </div>
    <!-- 현재 상태 배지 -->
    <div class="badge" style="background:{status_color}22; color:{status_color}; font-size:14px;">
      {status_label}
    </div>
  </div>

  <!-- 상태 안내 배너 -->
  <div class="card mb-4" style="background:{status_color}11; border:1.5px solid {status_color}44;">
    <p style="color:{status_color}; font-weight:700; font-size:15px;">{status_desc}</p>
    <p style="color:#64748b; font-size:13px; margin-top:4px;">{guide}</p>
  </div>

  <!-- 메인 그리드 -->
  <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:16px;" class="mb-4">

    <!-- 집중력 점수 -->
    <div class="card flex flex-col items-center justify-center" style="min-height:180px;">
      <div class="label">집중력 점수</div>
      <div class="score-ring" style="border-color:{score_color};">
        <span style="font-size:36px;">{score_emoji}</span>
        <span style="font-size:22px; font-weight:900; color:{score_color};">{score}점</span>
      </div>
    </div>

    <!-- 불쾌지수 게이지 -->
    <div class="card flex flex-col items-center justify-center" style="min-height:180px;">
      <div class="label">불쾌지수 (DI)</div>
      <div style="display:flex; align-items:center; gap:16px; margin-top:12px;">
        <div style="display:flex; flex-direction:column; justify-content:space-between; height:200px; font-size:10px; color:#cbd5e1; text-align:right;">
          <span>85</span>
          <span>75</span>
          <span>68</span>
          <span>60</span>
        </div>
        <div class="gauge-wrap">
          <div class="gauge-needle" style="top:{pointer_px}px;">
            <span style="color:#1e293b; font-size:10px;">◀</span>
            <span style="font-weight:900; font-size:15px; color:#1e293b;">{di:.1f}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 타이머 -->
    <div class="card flex flex-col items-center justify-center" style="min-height:180px;">
      <div class="label">{'📚 공부 중' if is_study else '🤸 휴식 중'}</div>
      <div style="font-size:44px; font-weight:900; color:#6366f1; font-family:monospace; margin-top:8px;">
        {timer_str}
      </div>
      <div style="font-size:11px; color:#94a3b8; margin-top:8px;">
        {'남은 공부 시간' if is_study else '남은 휴식 시간'}
      </div>
    </div>
  </div>

  <!-- 센서 수치 그리드 -->
  <div style="display:grid; grid-template-columns:1fr 1fr 1fr 1fr; gap:12px;" class="mb-4">

    <!-- CO2 -->
    <div class="card">
      <div class="label">💨 CO2</div>
      <div class="big-num" style="color:{'#f87171' if co2>=1000 else '#1e293b'};">
        {int(co2)}
      </div>
      <div style="font-size:11px; color:#94a3b8; margin-top:4px;">ppm</div>
    </div>

    <!-- 온도 -->
    <div class="card">
      <div class="label">🌡️ 온도</div>
      <div class="big-num" style="color:#f97316;">{temp:.1f}</div>
      <div style="font-size:11px; color:#94a3b8; margin-top:4px;">°C</div>
    </div>

    <!-- 습도 -->
    <div class="card">
      <div class="label">💧 습도</div>
      <div class="big-num" style="color:#38bdf8;">{hum:.1f}</div>
      <div style="font-size:11px; color:#94a3b8; margin-top:4px;">%</div>
    </div>

    <!-- 가스 -->
    <div class="card">
      <div class="label">🏭 가스 MQ2</div>
      <div class="big-num" style="color:{'#f87171' if gas>=25000 else '#1e293b'}; font-size:32px;">
        {gas}
      </div>
    </div>
  </div>

  <!-- 날씨 + 환기 예측 -->
  <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px;" class="mb-4">

    <!-- 날씨 선택 -->
    <div class="card">
      <div class="label">⛅ 바깥 날씨 선택</div>
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:10px;">
        {weather_buttons}
      </div>
    </div>

    <!-- 환기 회복 예측 -->
    <div class="card" style="background:{recovery_color}11; border:1.5px solid {recovery_color}44;">
      <div class="label">⏱️ 환기 회복 예측</div>
      <p style="font-weight:700; font-size:16px; color:{recovery_color}; margin-top:10px;">
        {recovery_text}
      </p>
      <p style="font-size:11px; color:#94a3b8; margin-top:8px; line-height:1.6;">
        물질전달 1차 감쇄 공식 기반<br>
        (목표: 1,000ppm / 외부: 400ppm)
      </p>
    </div>
  </div>

  <!-- CO2 그래프 -->
  <div class="card">
    <div class="label">📈 CO2 실시간 변화 그래프</div>
    <canvas id="co2Chart" height="70" style="margin-top:12px;"></canvas>
  </div>

</div>

<script>
const co2Data  = {co2_data};
const timeData = {time_data};
const ctx = document.getElementById('co2Chart').getContext('2d');
new Chart(ctx, {{
  type: 'line',
  data: {{
    labels: timeData.map(t => t + '초'),
    datasets: [
      {{
        label: 'CO2 (ppm)',
        data: co2Data,
        borderColor: '#6366f1',
        backgroundColor: 'rgba(99,102,241,0.08)',
        borderWidth: 2.5,
        pointRadius: 4,
        pointBackgroundColor: '#6366f1',
        tension: 0.4,
        fill: true
      }},
      {{
        label: '경고 기준 (1000ppm)',
        data: Array(co2Data.length).fill(1000),
        borderColor: '#f87171',
        borderWidth: 1.5,
        borderDash: [6, 4],
        pointRadius: 0,
        fill: false
      }}
    ]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{
        labels: {{ color: '#64748b', font: {{ size: 11, weight: 'bold' }} }}
      }}
    }},
    scales: {{
      x: {{
        ticks: {{ color: '#94a3b8', maxTicksLimit: 8 }},
        grid:  {{ color: '#f1f5f9' }}
      }},
      y: {{
        ticks: {{ color: '#94a3b8' }},
        grid:  {{ color: '#f1f5f9' }},
        min: 300,
        suggestedMax: 1500
      }}
    }}
  }}
}});
</script>

</body></html>"""

# ==========================================================
# 10. 웹서버 실행
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

            pointer_px = int(200 - ((di - 60) * (200 / 25))) - 12
            pointer_px = max(-12, min(188, pointer_px))

            recovery_min = calc_recovery_time(co2)

            bad = (di >= 75.0 or co2 >= 1000 or gas >= 25000)
            if not is_study:
                guide = "자리에서 일어나 몸을 움직이세요! 10분 후 공부 시간이 시작돼요."
            elif bad:
                if   selected_weather == "sunny": guide = "창문을 활짝 열어 환기하세요!"
                elif selected_weather == "dusty": guide = "창문은 1cm만 열고 에어컨을 켜세요!"
                elif selected_weather == "rainy": guide = "창문을 닫고 에어컨 제습 모드를 켜세요!"
                else:                             guide = "2분만 짧게 환기하고 문을 닫으세요!"
            else:
                guide = "최적의 공부 환경이에요! 이 상태를 유지해보세요 😊"

            html = get_html(di, co2, gas, temp, hum, timer_str, guide,
                           selected_weather, pointer_px, recovery_min, is_study)
            conn.send("HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n")
            conn.send(html)
        except:
            pass
        conn.close()
    except:
        pass
    time.sleep_ms(100)
