import flet as ft
import socket
import json
import threading
import time
import datetime
import traceback

# --- 設定値 (config.pyの内容を統合) ---
UDP_PORT = 5005
BUFFER_SIZE = 1024
SENSOR_TIMEOUT = 5.0
MIN_LAP_TIME = 5.0 
MAX_HISTORY_COUNT = 20
MULTI_GOAL_DISPLAY_TIME = 3.0

# --- UI部品の関数 ---
def create_wifi_info():
    return ft.Container(
        content=ft.Row([
            ft.Text("SSID: motogym", color="white", weight="bold"),
            ft.Text("PASS: 12345678", color="white", weight="bold"),
        ], alignment="center", spacing=20, wrap=True),
        padding=10, bgcolor="grey900", border_radius=10
    )

def create_sensor_status(label):
    return ft.Container(
        content=ft.Text(f"{label}\n--", color="white", weight="bold", size=12, text_align="center"),
        padding=5, border_radius=5, bgcolor="grey800", width=120, alignment=ft.alignment.center
    )

class GymkhanaApp:
    def __init__(self):
        self.running = True
        # 共通センサー状態
        self.last_start_sensor_time = 0.0
        self.last_stop_sensor_time = 0.0
        self.start_sensor_detail = {"rssi": None, "proto": ""}
        self.stop_sensor_detail = {"rssi": None, "proto": ""}
        
        self.current_mode = None # 'MULTI', 'SOLO', 'CALC'
        
        # SOLOモード用状態
        self.solo_running = False
        self.solo_start_time = 0.0
        
        # MULTIモード用状態
        self.active_runners = [] 
        self.history_count = 0
        self.multi_hold_runner = None 
        self.multi_hold_expire_time = 0.0
        
        # 計算機用状態
        self.calc_target = "top" 

    def main(self, page: ft.Page):
        self.page = page
        page.title = "Gymkhana Timer"
        page.bgcolor = "#1a1a1a"
        page.theme_mode = "dark"
        page.padding = 10
        page.scroll = ft.ScrollMode.AUTO

        try:
            # センサー表示UIの初期化
            self.start_sensor_status = create_sensor_status("START")
            self.stop_sensor_status = create_sensor_status("GOAL")
            self.sensor_row = ft.Row(
                [ft.Text("Sensor:", color="grey400"), self.start_sensor_status, self.stop_sensor_status],
                alignment="center", spacing=10
            )

            # 通信とタイマーの開始
            threading.Thread(target=self.udp_listener, daemon=True).start()
            threading.Thread(target=self.timer_loop, daemon=True).start()

            self.show_mode_selection()
        except Exception as e:
            self.show_error(e)

    def show_error(self, e):
        self.page.clean()
        self.page.add(
            ft.Text("⚠️ Fatal Error", color="red", size=20, weight="bold"),
            ft.Text(traceback.format_exc(), color="white", font_family="monospace", size=10)
        )
        self.page.update()

    def show_mode_selection(self):
        self.current_mode = None
        self.page.clean()
        
        def create_btn(icon, title, subtitle, color, click_fn):
            return ft.Container(
                content=ft.Column([
                    ft.Icon(name=icon, size=40, color=color),
                    ft.Text(title, size=18, weight="bold", color=color),
                    ft.Text(subtitle, size=12, color="grey"),
                ], alignment="center", horizontal_alignment="center"),
                padding=15, bgcolor="grey900", border_radius=10,
                border=ft.Border(top=ft.BorderSide(1, color), bottom=ft.BorderSide(1, color), left=ft.BorderSide(1, color), right=ft.BorderSide(1, color)),
                on_click=click_fn, ink=True
            )

        btn_multi = create_btn("people", "MULTI MODE", "複数人追走 (2センサー)", "cyan", lambda _: self.show_multi_mode())
        btn_solo = create_btn("timer", "SOLO MODE", "単独計測 (1センサー)", "orange", lambda _: self.show_solo_mode())
        btn_calc = create_btn("calculate", "TIME CALC", "タイム比計算機", "green", lambda _: self.show_calc_mode())

        self.page.add(
            create_wifi_info(),
            ft.Container(height=10),
            self.sensor_row,
            ft.Container(height=20),
            ft.Text("モードを選択してください", size=14, color="white", text_align="center"),
            ft.Container(height=10),
            btn_multi,
            ft.Container(height=10),
            btn_solo,
            ft.Container(height=10),
            btn_calc
        )
        self.page.update()

    # --- MULTI MODE ---
    def show_multi_mode(self):
        self.current_mode = "MULTI"
        self.page.clean()
        self.multi_main_time = ft.Text("0.000", size=60, color="yellow", weight="bold", font_family="monospace")
        self.multi_main_name = ft.Text("---", size=24, color="white", weight="bold")
        self.multi_main_status = ft.Text("READY", size=16, color="grey")
        self.multi_history_list = ft.ListView(expand=True, spacing=5, height=200)
        self.multi_queue_text = ft.Text("No other runners", color="grey", size=12)

        self.page.add(
            ft.Row([
                ft.IconButton(icon="arrow_back", on_click=lambda _: self.show_mode_selection()),
                ft.Text("MULTI MODE", size=20, weight="bold", color="cyan"),
            ], alignment="spaceBetween"),
            self.sensor_row,
            ft.Container(
                content=ft.Column([
                    self.multi_main_name, self.multi_main_time, self.multi_main_status
                ], horizontal_alignment="center"),
                padding=20, bgcolor="grey900", border_radius=15, alignment=ft.alignment.center,
                border=ft.Border(top=ft.BorderSide(2, "grey800"), bottom=ft.BorderSide(2, "grey800"), left=ft.BorderSide(2, "grey800"), right=ft.BorderSide(2, "grey800"))
            ),
            ft.Text("ON COURSE:", size=12, color="cyan", weight="bold"),
            self.multi_queue_text,
            ft.Divider(color="grey800"),
            ft.Text("HISTORY:", size=12, color="white"),
            self.multi_history_list
        )
        self.page.update()

    # --- SOLO MODE ---
    def show_solo_mode(self):
        self.current_mode = "SOLO"
        self.solo_running = False
        self.page.clean()
        self.solo_time_display = ft.Text("0.000", size=80, color="yellow", weight="bold", font_family="monospace")
        self.solo_status_text = ft.Text("READY", size=20, color="grey")

        self.page.add(
            ft.Row([
                ft.IconButton(icon="arrow_back", on_click=lambda _: self.show_mode_selection()),
                ft.Text("SOLO MODE", size=20, weight="bold", color="orange"),
            ], alignment="spaceBetween"),
            self.sensor_row,
            ft.Container(height=40),
            ft.Column([
                self.solo_status_text,
                self.solo_time_display,
                ft.Container(height=20),
                ft.ElevatedButton("RESET", color="white", bgcolor="red900", on_click=lambda _: self.reset_solo())
            ], horizontal_alignment="center")
        )
        self.page.update()

    def reset_solo(self):
        self.solo_running = False
        self.solo_time_display.value = "0.000"
        self.solo_time_display.color = "yellow"
        self.solo_status_text.value = "RESET"
        self.page.update()

    # --- CALC MODE ---
    def show_calc_mode(self):
        self.current_mode = "CALC"
        self.page.clean()
        
        self.txt_top = ft.Text("", size=30, color="yellow")
        self.txt_ratio = ft.Text("105", size=30, color="cyan")
        self.txt_my = ft.Text("", size=30, color="white")
        self.lbl_target = ft.Text("Target: 0.000", color="grey")
        self.calc_result = ft.Text("0.00 %", size=50, weight="bold", color="green")

        def select(t):
            self.calc_target = t
            self.con_top.border = self._b("cyan" if t=="top" else "transparent")
            self.con_ratio.border = self._b("cyan" if t=="ratio" else "transparent")
            self.con_my.border = self._b("cyan" if t=="my" else "transparent")
            self.page.update()

        self.con_top = ft.Container(self.txt_top, padding=10, bgcolor="grey900", border_radius=5, border=self._b("cyan"), on_click=lambda _: select("top"), width=150, height=60, alignment=ft.alignment.center_right)
        self.con_ratio = ft.Container(self.txt_ratio, padding=10, bgcolor="grey900", border_radius=5, border=self._b("transparent"), on_click=lambda _: select("ratio"), width=100, height=60, alignment=ft.alignment.center_right)
        self.con_my = ft.Container(self.txt_my, padding=10, bgcolor="grey900", border_radius=5, border=self._b("transparent"), on_click=lambda _: select("my"), width=150, height=60, alignment=ft.alignment.center_right)

        def k(val, col="grey800", w=80):
            return ft.Container(ft.Text(val, size=20, weight="bold"), width=w, height=50, bgcolor=col, border_radius=8, alignment=ft.alignment.center, on_click=lambda _: self.on_key(val))

        keypad = ft.Column([
            ft.Row([k("7"), k("8"), k("9")], alignment="center"),
            ft.Row([k("4"), k("5"), k("6")], alignment="center"),
            ft.Row([k("1"), k("2"), k("3")], alignment="center"),
            ft.Row([k("C", "red900"), k("0"), k(".")], alignment="center"),
        ])

        self.page.add(
            ft.Row([ft.IconButton(icon="arrow_back", on_click=lambda _: self.show_mode_selection()), ft.Text("CALC", size=20, weight="bold", color="green")]),
            ft.Row([ft.Text("Top:"), self.con_top], alignment="center"),
            ft.Row([ft.Text("Ratio%:"), self.con_ratio, self.lbl_target], alignment="center"),
            ft.Row([ft.Text("My:"), self.con_my], alignment="center"),
            ft.Divider(),
            ft.Column([self.calc_result], horizontal_alignment="center"),
            keypad
        )
        self.page.update()

    def _b(self, color):
        return ft.Border(top=ft.BorderSide(2, color), bottom=ft.BorderSide(2, color), left=ft.BorderSide(2, color), right=ft.BorderSide(2, color))

    def on_key(self, val):
        target = self.txt_top if self.calc_target=="top" else (self.txt_ratio if self.calc_target=="ratio" else self.txt_my)
        if val == "C": target.value = ""
        elif val == ".":
            if "." not in target.value: target.value += "."
        else: target.value += val
        
        try:
            top = float(self.txt_top.value or 0)
            ratio = float(self.txt_ratio.value or 0)
            my = float(self.txt_my.value or 0)
            if top > 0 and ratio > 0: self.lbl_target.value = f"Target: {top / (ratio/100):.3f}"
            if top > 0 and my > 0:
                res = (my / top) * 100
                self.calc_result.value = f"{res:.2f} %"
                self.calc_result.color = "green" if res < 105 else ("yellow" if res < 110 else "red")
        except: pass
        self.page.update()

    # --- LOGIC ---
    def udp_listener(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('0.0.0.0', UDP_PORT))
            sock.settimeout(1.0)
            while self.running:
                try:
                    data, _ = sock.recvfrom(BUFFER_SIZE)
                    msg = data.decode('utf-8').strip()
                    
                    if msg.startswith("{"):
                        try:
                            j = json.loads(msg)
                            if j.get("status") == "alive":
                                if j.get("sensor") == "START": self.last_start_sensor_time = time.time()
                                else: self.last_stop_sensor_time = time.time()
                        except: pass
                        continue

                    # 計測信号の処理
                    if self.current_mode == "MULTI":
                        if msg == "START": self.handle_multi_start()
                        if msg == "STOP": self.handle_multi_stop()
                    elif self.current_mode == "SOLO":
                        if msg == "START" or msg == "STOP": self.handle_solo_signal()
                except socket.timeout: continue
        except: pass

    def handle_multi_start(self):
        self.history_count += 1
        self.active_runners.append({'num': self.history_count, 'name': 'Rider', 'start_time': time.time()})
        self.update_multi_ui()

    def handle_multi_stop(self):
        if not self.active_runners: return
        runner = self.active_runners.pop(0)
        res = time.time() - runner['start_time']
        self.multi_hold_runner = {'num': runner['num'], 'name': runner['name'], 'time': res}
        self.multi_hold_expire_time = time.time() + MULTI_GOAL_DISPLAY_TIME
        # 履歴へ追加
        self.multi_history_list.controls.insert(0, ft.Text(f"#{runner['num']} Rider: {res:.3f}s", color="yellow", size=16))
        if len(self.multi_history_list.controls) > MAX_HISTORY_COUNT: self.multi_history_list.controls.pop()
        self.update_multi_ui()

    def update_multi_ui(self):
        if not self.multi_main_time: return
        now = time.time()
        if self.multi_hold_runner and now < self.multi_hold_expire_time:
            self.multi_main_name.value = f"#{self.multi_hold_runner['num']} FINISH"
            self.multi_main_time.value = f"{self.multi_hold_runner['time']:.3f}"
            self.multi_main_time.color = "red"
        elif self.active_runners:
            r = self.active_runners[0]
            self.multi_main_name.value = f"#{r['num']} RUNNING"
            self.multi_main_time.color = "yellow"
        else:
            self.multi_main_name.value = "---"
            self.multi_main_time.value = "0.000"
            self.multi_main_time.color = "grey"
        
        others = [f"#{r['num']}" for r in self.active_runners[1:]]
        self.multi_queue_text.value = f"Following: {', '.join(others)}" if others else "No other runners"
        self.page.update()

    def handle_solo_signal(self):
        now = time.time()
        if not self.solo_running:
            self.solo_running = True
            self.solo_start_time = now
            self.solo_status_text.value = "RUNNING!"
            self.solo_time_display.color = "green"
        else:
            if now - self.solo_start_time < MIN_LAP_TIME: return
            self.solo_running = False
            res = now - self.solo_start_time
            self.solo_time_display.value = f"{res:.3f}"
            self.solo_time_display.color = "red"
            self.solo_status_text.value = "FINISH"
        self.page.update()

    def timer_loop(self):
        while self.running:
            try:
                now = time.time()
                # SOLOモードの更新
                if self.current_mode == "SOLO" and self.solo_running:
                    self.solo_time_display.value = f"{now - self.solo_start_time:.3f}"
                
                # MULTIモードの更新
                if self.current_mode == "MULTI":
                    if self.multi_hold_runner and now > self.multi_hold_expire_time:
                        self.multi_hold_runner = None
                    if not self.multi_hold_runner and self.active_runners:
                        self.multi_main_time.value = f"{now - self.active_runners[0]['start_time']:.3f}"
                    self.update_multi_ui()

                # センサー表示更新
                def up(c, t, l):
                    if now - t < SENSOR_TIMEOUT:
                        c.bgcolor = "green"
                        c.content.value = f"{l}: OK"
                    else:
                        c.bgcolor = "grey800"
                        c.content.value = f"{l}\n--"
                up(self.start_sensor_status, self.last_start_sensor_time, "START")
                up(self.stop_sensor_status, self.last_stop_sensor_time, "GOAL")
                
                if self.page: self.page.update()
            except: pass
            time.sleep(0.1)

if __name__ == "__main__":
    app = GymkhanaApp()
    ft.app(target=app.main)
