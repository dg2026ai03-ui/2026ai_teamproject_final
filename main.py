import machine
import time
import struct
import network
import socket
import math

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
        except:
            return None

    def start(self):
        try:
            self.i2c.writeto(self.addr, b'\x00\x10\x00\x00\x81')
            print("SCD30 시작!")
        except:
            print("SCD30 시작 실패")

    def ready(self):
        try:
            self.i2c.writeto(self.addr, b'\x02\x02')
            return struct.unpack('>H', self.i2c.readfrom(self.addr, 3)[:2])[0] == 1
        except:
            return False

i2c_bus    = machine.I2C(0, sda=machine.Pin(8), scl=machine.Pin(9), freq=50000)
mq2_sensor = machine.ADC(26)
sensor     = SCD30(i2c_bus)
sensor.start()

WIFI_SSID = "enhypengirl"
WIFI_PW   = "enhypengirl"

wlan = network.WLAN(network.STA_IF)
wlan.active(False)
time.sleep(3)
wlan.active(True)
time.sleep(3)
wlan.disconnect()
time.sleep(2)
wlan.connect(WIFI_SSID, WIFI_PW)

print("와이파이 연결 중...")
for _ in range(30):
    if wlan.isconnected(): break
    time.sleep(1)
    print(".", end="")

if wlan.isconnected():
    ip = wlan.ifconfig()[0]
    print("\n연결 성공!")
    print("http://" + ip)
else:
    print("\n연결 실패!")

co2, temp, hum, di, gas = 450.0, 24.0, 50.0, 0.0, 0
STUDY_TIME   = 50 * 60 * 1000
STRETCH_TIME = 10 * 60 * 1000
is_study     = True
prev_ms      = time.ticks_ms()
sel_weather  = "sunny"
co2_hist     = []

def fmt_time(sec):
    mm = int(sec // 60)
    ss = int(sec % 60)
    ms = "0" + str(mm) if mm < 10 else str(mm)
    ss2 = "0" + str(ss) if ss < 10 else str(ss)
    return ms + ":" + ss2

def update_sensors():
    global co2, temp, hum, di, gas, is_study, prev_ms, co2_hist
    now = time.ticks_ms()
    if sensor.ready():
        r = sensor.read_measurement()
        if r:
            co2, temp, hum = r
            di = 0.81*temp + 0.01*hum*(0.99*temp-14.3) + 46.3
            co2_hist.append(int(co2))
            if len(co2_hist) > 15: co2_hist.pop(0)
    gas = mq2_sensor.read_u16()
    e = time.ticks_diff(now, prev_ms)
    if is_study and e >= STUDY_TIME:
        is_study = False; prev_ms = now
    elif not is_study and e >= STRETCH_TIME:
        is_study = True; prev_ms = now

def calc_recovery(c):
    if c <= 1000: return 0
    r = 600.0 / (c - 400.0)
    if r <= 0: return 99
    return max(1, int(-math.log(r) / 0.03))

def send_page(conn):
    if not is_study:
        sc = "#a78bfa"; sl = "휴식중"; sd = "스트레칭 타임!"
    elif di >= 80 or co2 >= 1500:
        sc = "#f87171"; sl = "나쁨"; sd = "즉시 환기하세요!"
    elif di >= 75 or co2 >= 1000:
        sc = "#fbbf24"; sl = "주의"; sd = "환기가 필요해요!"
    else:
        sc = "#34d399"; sl = "쾌적"; sd = "공부하기 좋아요!"

    score = 100
    if di > 70: score -= int((di-70)*4)
    if co2 > 800: score -= int((co2-800)*0.05)
    score = max(0, min(100, score))
    if score >= 80: skc = "#34d399"
    elif score >= 50: skc = "#fbbf24"
    else: skc = "#f87171"

    e = time.ticks_diff(time.ticks_ms(), prev_ms)
    rem = max(0, ((STUDY_TIME if is_study else STRETCH_TIME) - e) // 1000)
    tstr = fmt_time(rem)

    bad = di >= 75 or co2 >= 1000 or gas >= 25000
    if not is_study:
        guide = "10분 휴식 후 공부 시작!"
    elif bad:
        if sel_weather == "dusty": guide = "창문 1cm만 열고 에어컨 켜세요!"
        elif sel_weather == "rainy": guide = "에어컨 제습 모드 켜세요!"
        elif sel_weather == "snow": guide = "2분만 환기하고 닫으세요!"
        else: guide = "창문 활짝 열어 환기하세요!"
    else:
        guide = "최적 환경! 이 상태 유지하세요"

    rec = calc_recovery(co2)
    if rec == 0: rt = "이미 쾌적해요!"; rc = "#34d399"
    else: rt = "환기시 약 " + str(rec) + "분 후 쾌적!"; rc = "#fbbf24"

    bars = ""
    if co2_hist:
        mx = max(max(co2_hist), 1000)
        for v in co2_hist:
            h = max(2, int(v/mx*80))
            c = "#f87171" if v>=1000 else ("#fbbf24" if v>=800 else "#6366f1")
            bars += "<div style='flex:1;background:" + c + ";height:" + str(h) + "px;border-radius:2px 2px 0 0;margin:0 1px;'></div>"

    wicons = {"sunny":"☀","dusty":"😷","rainy":"🌧","snow":"❄"}
    wlist = [("sunny","맑음"),("dusty","황사"),("rainy","비"),("snow","눈")]
    wbtns = ""
    for k, lb in wlist:
        bg = "#ecfdf5" if k==sel_weather else "#f8fafc"
        bd = "#34d399" if k==sel_weather else "#e2e8f0"
        wbtns += "<a href='/?w=" + k + "' style='background:" + bg + ";border:2px solid " + bd + ";border-radius:12px;padding:8px;text-align:center;text-decoration:none;font-size:12px;font-weight:700;color:#1e293b;display:block;'>" + wicons[k] + "<br>" + lb + "</a>"

    def s(t): conn.sendall(t.encode())

    s("HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n")
    s("<!DOCTYPE html><html><head>")
    s("<meta charset='UTF-8'>")
    s("<meta http-equiv='refresh' content='5'>")
    s("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    s("<title>Study Shield</title>")
    s("<style>*{box-sizing:border-box;margin:0;padding:0;}body{font-family:sans-serif;background:#f0fdf4;padding:12px;}h1{font-size:18px;font-weight:900;color:#1e293b;}.card{background:#fff;border-radius:16px;padding:16px;margin-bottom:10px;box-shadow:0 2px 8px rgba(0,0,0,0.06);}.lbl{font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;margin-bottom:4px;}.g3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;}.g4{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px;}</style>")
    s("</head><body><div style='max-width:700px;margin:0 auto;'>")

    s("<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;'>")
    s("<div><h1>Study Shield</h1><p style='font-size:10px;color:#94a3b8;'>당곡고 5초 갱신</p></div>")
    s("<span style='background:" + sc + "22;color:" + sc + ";padding:4px 12px;border-radius:999px;font-size:12px;font-weight:700;'>" + sl + "</span></div>")

    s("<div class='card' style='background:" + sc + "11;border:1.5px solid " + sc + "44;'>")
    s("<p style='color:" + sc + ";font-weight:700;'>" + sd + "</p>")
    s("<p style='color:#64748b;font-size:12px;margin-top:4px;'>" + guide + "</p></div>")

    s("<div class='g3' style='margin-bottom:10px;'>")
    s("<div class='card' style='text-align:center;'><div class='lbl'>집중력</div>")
    s("<div style='font-size:32px;font-weight:900;color:" + skc + ";'>" + str(score) + "</div>")
    s("<div style='font-size:10px;color:#94a3b8;'>/ 100</div></div>")
    s("<div class='card' style='text-align:center;'><div class='lbl'>타이머</div>")
    s("<div style='font-size:28px;font-weight:900;color:#6366f1;font-family:monospace;'>" + tstr + "</div>")
    s("<div style='font-size:10px;color:#94a3b8;'>" + ("공부중" if is_study else "휴식중") + "</div></div>")
    s("<div class='card' style='text-align:center;'><div class='lbl'>불쾌지수</div>")
    s("<div style='font-size:32px;font-weight:900;color:#f97316;'>" + str(round(di,1)) + "</div></div>")
    s("</div>")

    c2c = "#f87171" if co2>=1000 else "#1e293b"
    gc  = "#f87171" if gas>=25000 else "#1e293b"
    s("<div class='g4' style='margin-bottom:10px;'>")
    s("<div class='card'><div class='lbl'>CO2</div><div style='font-size:26px;font-weight:900;color:" + c2c + ";'>" + str(int(co2)) + "</div><div style='font-size:10px;color:#94a3b8;'>ppm</div></div>")
    s("<div class='card'><div class='lbl'>온도</div><div style='font-size:26px;font-weight:900;color:#f97316;'>" + str(round(temp,1)) + "</div><div style='font-size:10px;color:#94a3b8;'>C</div></div>")
    s("<div class='card'><div class='lbl'>습도</div><div style='font-size:26px;font-weight:900;color:#38bdf8;'>" + str(round(hum,1)) + "</div><div style='font-size:10px;color:#94a3b8;'>%</div></div>")
    s("<div class='card'><div class='lbl'>가스</div><div style='font-size:20px;font-weight:900;color:" + gc + ";'>" + str(gas) + "</div></div>")
    s("</div>")

    s("<div class='card' style='margin-bottom:10px;'><div class='lbl'>날씨 선택</div>")
    s("<div class='g4' style='margin-top:8px;'>" + wbtns + "</div></div>")

    s("<div class='card' style='background:" + rc + "11;border:1.5px solid " + rc + "44;margin-bottom:10px;'>")
    s("<div class='lbl'>환기 예측</div>")
    s("<p style='font-weight:700;color:" + rc + ";margin-top:4px;'>" + rt + "</p>")
    s("<p style='font-size:10px;color:#94a3b8;margin-top:4px;'>1차 감쇄 공식 기반</p></div>")

    s("<div class='card'><div class='lbl'>CO2 그래프</div>")
    s("<div style='display:flex;align-items:flex-end;height:90px;margin-top:8px;'>")
    if bars: s(bars)
    else: s("<p style='color:#94a3b8;font-size:11px;'>데이터 수집 중...</p>")
    s("</div><div style='font-size:10px;color:#f87171;margin-top:4px;'>--- 1000ppm 기준</div></div>")

    s("</div></body></html>")


srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(('', 80))
srv.listen(3)
srv.setblocking(False)
print("웹서버 실행 중...")

while True:
    update_sensors()
    try:
        conn, addr = srv.accept()
        conn.settimeout(3.0)
        print("접속:", addr)
        request = ""
        try:
            request = conn.recv(1024).decode()
        except:
            pass
        if "?w=sunny" in request: sel_weather = "sunny"
        elif "?w=dusty" in request: sel_weather = "dusty"
        elif "?w=rainy" in request: sel_weather = "rainy"
        elif "?w=snow" in request: sel_weather = "snow"
        try:
            send_page(conn)
        except Exception as e:
            print("전송오류:", e)
        conn.close()
    except:
        pass
    time.sleep_ms(100)
