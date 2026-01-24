import flet as ft
import socket
import json
import threading
import time
import traceback

# --- 設定値 ---
UDP_PORT = 5005
BUFFER_SIZE = 1024
SENSOR_TIMEOUT = 5.0
MIN_LAP_TIME = 5.0 
MAX_HISTORY_COUNT = 20
MULTI_GOAL_DISPLAY_TIME = 3.0

def create_wifi_info():
    """Wi-Fi情報表示ヘッダー (文字列指定でAttributeErrorを回避)"""
    return ft.Container(
        content=ft.Row([
            ft.Text("SSID: motogym", color="white", weight="bold"),
            ft.Text("PASS: password123", color="white", weight="bold"),
        ], alignment="center", spacing=20, wrap=True),
        padding=10, bgcolor="grey900", border_radius=10
    )

def create_sensor_status(label):
    """センサー状態表示用ボックス (文字列指定)"""
    return ft.Container(
        content=ft.Text(
            f"{label}\n--", 
            color="white", 
            weight="bold", 
            size=12, 
            text_align="center"
        ),
        padding=5, border_radius=5, bgcolor="grey800", width=120,
        alignment=ft.alignment.center
    )

class GymkhanaApp:
    def __init__(self):
        self.running = True
        self.sock = None
        self.page = None
        
        # --- 共通状態 ---
        self.last_start_sensor_time = 0.0
        self.last_stop_sensor_time = 0.0
        self.start_sensor_detail = {"rssi": None, "proto": ""}
        self.stop_sensor_detail = {"rssi": None, "proto": ""}
        self.current_mode = None

        # --- SOLOモード用 ---
        self.solo_running = False
        self.solo_start_time = 0.0
        
        # --- MULTIモード用 ---
        self.active_runners = [] 
        self.history_count = 0
        self.multi_hold_runner = None 
        self.multi_hold_expire_time = 0.0

        # --- UI参照 ---
        self.start_sensor_status = None
        self.stop_sensor_status = None
        self.solo_time_display = None
        self.solo_status_text = None
        self.multi_main_time = None
        self.multi_main_status = None
        self.multi_main_name = None
        self.multi_queue_text = None
        self.multi_history_list = None
        
        # --- 計算機用TextField ---
        self.tf_top = None
        self.tf_ratio = None
        self.tf_my = None
        self.lbl_calc_target = None
        self.lbl_calc_res = None

    def main(self, page: ft.Page):
        self.page = page
        page.title = "Gymkhana Timer"
        page.bgcolor = "#1a1a1a"
        page.theme_mode = "dark"
        page.padding = 10
        page.scroll = "auto" 

        try:
            # UI初期化
            self.start_sensor_status = create_sensor_status("START")
            self.stop_sensor_status = create_sensor_status("GOAL")
            
            self.sensor_row = ft.Row(
                [ft.Text("Sensor:", color="grey400"), self.start_sensor_status, self.stop_sensor_status],
                alignment="center", spacing=10, wrap=True
            )

            # スレッド開始
            threading.Thread(target=self.udp_listener, daemon=True).start()
            threading.Thread(target=self.timer_loop, daemon=True).start()

            # 初期画面
            self.show_mode_selection()
        except Exception:
            self.show_fatal_error(traceback.format_exc())

    def show_fatal_error(self, error_details):
        """エラー画面自体がクラッシュしないよう文字列を徹底"""
        if self.page:
            self.page.clean()
            self.page.add(
                ft.Text("⚠️ Render Error", color="red", size=24, weight="bold"),
                ft.Text(error_details, color="white", size=10, font_family="monospace"),
                ft.ElevatedButton("Reload Menu", on_click=lambda _: self.show_mode_selection())
            )
            self.page.update()

    def show_mode_selection(self):
        """メインメニュー (文字列指定)"""
        self.current_mode = None
        self.page.clean()
        self.page.update()

        def create_btn(icon_str, title, subtitle, color_str, click_fn):
            return ft.Container(
                content=ft.Column([
                    ft.Icon(icon_str, size=40, color=color_str),
                    ft.Text(title, size=18, weight="bold", color=color_str),
                    ft.Text(subtitle, size=11, color="grey500")
                ], alignment="center", horizontal_alignment="center"),
                padding=15, bgcolor="grey900", border_radius=12,
                border=ft.border.all(1, color_str),
                on_click=click_fn, ink=True, width=340
            )

        self.page.add(
            create_wifi_info(),
            ft.Container(height=10),
            self.sensor_row,
            ft.Container(height=20),
            ft.Text("モードを選択してください", size=14, color="white", text_align="center"),
            ft.Container(height=10),
            ft.Column([
                create_btn("people", "MULTI MODE", "複数人追走計測 (2センサー)", "cyan", lambda _: self.show_multi_mode()),
                create_btn("timer", "SOLO MODE", "単独練習計測 (1センサー)", "orange", lambda _: self.show_solo_mode()),
                create_btn("calculate", "TIME CALC", "タイム比計算機 (フリック入力)", "green", lambda _: self.show_calc_mode()),
            ], horizontal_alignment="center", spacing=15)
        )
        self.page.update()

    def show_multi_mode(self):
        self.current_mode = "MULTI"
        self.page.clean()
        self.active_runners = []
        self.history_count = 0
        
        self.multi_main_time = ft.Text("0.000", size=70, color="yellow", font_family="monospace", weight="bold")
        self.multi_main_status = ft.Text("READY", size=20, color="grey500")
        self.multi_main_name = ft.Text("---", size=30, color="white", weight="bold")
        self.multi_queue_text = ft.Text("No other runners on course", color="grey500", size=12)
        self.multi_history_list = ft.ListView(expand=True, spacing=2, height=300)

        header = ft.Row([
            ft.IconButton(icon="arrow_back", icon_color="white", on_click=lambda _: self.show_mode_selection()),
            ft.Text("MULTI MODE", size=20, weight="bold", color="cyan"),
            ft.Container(width=40)
        ], alignment="spaceBetween")

        self.page.add(
            header,
            self.sensor_row,
            ft.Divider(color="grey800"),
            ft.Container(
                content=ft.Column([
                    self.multi_main_name, self.multi_main_time, self.multi_main_status
                ], horizontal_alignment="center"),
                padding=20, bgcolor="grey900", border_radius=15, 
                border=ft.border.all(2, "grey800"),
                alignment=ft.alignment.center
            ),
            ft.Text("ON COURSE:", size=12, color="cyan", weight="bold"),
            self.multi_queue_text,
            ft.Divider(color="grey800"),
            ft.Text("RESULT HISTORY:", size=12, color="white"),
            self.multi_history_list
        )
        self.page.update()

    def show_solo_mode(self):
        self.current_mode = "SOLO"
        self.solo_running = False
        self.page.clean()
        
        self.solo_time_display = ft.Text("0.000", size=80, color="yellow", font_family="monospace", weight="bold")
        self.solo_status_text = ft.Text("READY", size=24, color="grey500")
        
        header = ft.Row([
            ft.IconButton(icon="arrow_back", icon_color="white", on_click=lambda _: self.show_mode_selection()),
            ft.Text("SOLO MODE", size=20, weight="bold", color="orange"),
            ft.Container(width=40)
        ], alignment="spaceBetween")

        self.page.add(
            header,
            self.sensor_row,
            ft.Column([
                ft.Container(height=40),
                self.solo_status_text,
                self.solo_time_display,
                ft.Container(height=40),
                ft.ElevatedButton(text="RESET TIMER", on_click=lambda _: self.reset_solo_timer(), color="white", bgcolor="red900", width=150, height=50)
            ], horizontal_alignment="center")
        )
        self.page.update()

    def show_calc_mode(self):
        """タイム計算機"""
        self.current_mode = "CALC"
        self.page.clean()

        self.tf_top = ft.TextField(label="Top Time (sec)", keyboard_type="number", color="yellow", on_change=self.on_calc_update)
        self.tf_ratio = ft.TextField(label="Target Ratio (%)", value="100", keyboard_type="number", color="cyan", on_change=self.on_calc_update)
        self.tf_my = ft.TextField(label="Your Time (sec)", keyboard_type="number", color="white", on_change=self.on_calc_update)
        
        self.lbl_calc_target = ft.Text("Target Time: 0.000", color="grey500", size=18, weight="bold")
        self.lbl_calc_res = ft.Text("--- %", size=50, weight="bold", color="green")

        header = ft.Row([
            ft.IconButton(icon="arrow_back", icon_color="white", on_click=lambda _: self.show_mode_selection()),
            ft.Text("TIME CALCULATOR", size=20, weight="bold", color="green"),
            ft.Container(width=40)
        ], alignment="spaceBetween")

        self.page.add(
            header,
            ft.Container(height=10),
            ft.Column([
                self.tf_top,
                ft.Row([ft.Container(self.tf_ratio, expand=True), ft.Container(self.lbl_calc_target, padding=10)]),
                self.tf_my,
                ft.Divider(color="grey800"),
                ft.Container(
                    content=ft.Column([ft.Text("Result", size=12, color="grey500"), self.lbl_calc_res], horizontal_alignment="center"),
                    alignment=ft.alignment.center
                )
            ], spacing=15)
        )
        self.page.update()

    def on_calc_update(self, e):
        try:
            top = float(self.tf_top.value) if self.tf_top.value else 0
            ratio = float(self.tf_ratio.value) if self.tf_ratio.value else 0
            my = float(self.tf_my.value) if self.tf_my.value else 0
            if top > 0 and ratio > 0: self.lbl_calc_target.value = f"Target Time: {top / (ratio/100):.3f}"
            if top > 0 and my > 0:
                res = (my / top) * 100
                self.lbl_calc_res.value = f"{res:.2f} %"
                if res < 105: self.lbl_calc_res.color = "green"
                elif res < 110: self.lbl_calc_res.color = "yellow"
                else: self.lbl_calc_res.color = "red"
            else:
                self.lbl_calc_res.value = "--- %"; self.lbl_calc_res.color = "grey500"
        except Exception: pass
        if self.page: self.page.update()

    def reset_solo_timer(self):
        self.solo_running = False
        if self.solo_time_display:
            self.solo_time_display.value = "0.000"; self.solo_time_display.color = "yellow"
        if self.solo_status_text:
            self.solo_status_text.value = "RESET"
        self.page.update()

    def udp_listener(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sock.bind(('0.0.0.0', UDP_PORT))
            self.sock.settimeout(1.0)
            while self.running:
                try:
                    data, addr = self.sock.recvfrom(BUFFER_SIZE)
                    msg = data.decode('utf-8').strip()
                    if msg.startswith("{"):
                        try:
                            j = json.loads(msg)
                            if j.get("status") == "alive":
                                stype = j.get("sensor")
                                if stype == "START":
                                    self.last_start_sensor_time = time.time()
                                    self.start_sensor_detail = {"rssi": j.get("rssi"), "proto": j.get("proto")}
                                elif stype == "GOAL":
                                    self.last_stop_sensor_time = time.time()
                                    self.stop_sensor_detail = {"rssi": j.get("rssi"), "proto": j.get("proto")}
                        except Exception: pass
                        continue
                    if self.current_mode == "MULTI":
                        if msg == "START": self.handle_multi_start()
                        if msg == "STOP": self.handle_multi_stop()
                    elif self.current_mode == "SOLO":
                        if msg == "START" or msg == "STOP": self.handle_solo_signal()
                except socket.timeout: continue
        except Exception: pass

    def handle_multi_start(self):
        self.history_count += 1
        self.active_runners.append({'num': self.history_count, 'name': 'Rider', 'start_time': time.time()})
        self.update_multi_ui()

    def handle_multi_stop(self):
        if not self.active_runners: return
        runner = self.active_runners.pop(0); res = time.time() - runner['start_time']
        self.multi_hold_runner = {'num': runner['num'], 'time': res}
        self.multi_hold_expire_time = time.time() + MULTI_GOAL_DISPLAY_TIME
        if self.multi_history_list:
            self.multi_history_list.controls.insert(0, ft.Text(f"#{runner['num']} Result: {res:.3f}s", color="yellow", size=16, weight="bold"))
            if len(self.multi_history_list.controls) > MAX_HISTORY_COUNT: self.multi_history_list.controls.pop()
        self.update_multi_ui()

    def update_multi_ui(self):
        if not self.multi_main_time: return
        now = time.time()
        if self.multi_hold_runner and now < self.multi_hold_expire_time:
            self.multi_main_name.value = f"#{self.multi_hold_runner['num']} FINISH"
            self.multi_main_time.value = f"{self.multi_hold_runner['time']:.3f}"; self.multi_main_time.color = "red"
        elif self.active_runners:
            r = self.active_runners[0]
            self.multi_main_name.value = f"#{r['num']} RUNNING"; self.multi_main_time.color = "yellow"
        else:
            self.multi_main_name.value = "---"; self.multi_main_time.value = "0.000"; self.multi_main_time.color = "grey500"
        if self.multi_queue_text:
            others = [f"#{r['num']}" for r in self.active_runners[1:]]
            self.multi_queue_text.value = f"On Course: {', '.join(others)}" if others else "No other runners"
        if self.page: self.page.update()

    def handle_solo_signal(self):
        now = time.time()
        if not self.solo_running:
            self.solo_running = True; self.solo_start_time = now
            if self.solo_status_text: self.solo_status_text.value = "RUNNING!"
            if self.solo_time_display: self.solo_time_display.color = "green"
        else:
            if now - self.solo_start_time < MIN_LAP_TIME: return
            self.solo_running = False; res = now - self.solo_start_time
            if self.solo_time_display: 
                self.solo_time_display.value = f"{res:.3f}"; self.solo_time_display.color = "red"
            if self.solo_status_text: self.solo_status_text.value = "FINISH"
        if self.page: self.page.update()

    def timer_loop(self):
        while self.running:
            try:
                now = time.time()
                if self.current_mode == "SOLO" and self.solo_running and self.solo_time_display:
                    self.solo_time_display.value = f"{now - self.solo_start_time:.3f}"
                if self.current_mode == "MULTI":
                    if self.multi_hold_runner and now > self.multi_hold_expire_time: self.multi_hold_runner = None
                    if not self.multi_hold_runner and self.active_runners and self.multi_main_time:
                        self.multi_main_time.value = f"{now - self.active_runners[0]['start_time']:.3f}"
                    self.update_multi_ui()
                def up(c, t, d, l):
                    if not c: return
                    if now - t < SENSOR_TIMEOUT:
                        c.bgcolor = "green"
                        c.content.value = f"{l}: ONLINE\n{d['rssi']}dBm" if d['rssi'] else f"{l}: ONLINE"
                    else:
                        c.bgcolor = "grey800"; c.content.value = f"{l}\nOFFLINE"
                up(self.start_sensor_status, self.last_start_sensor_time, self.start_sensor_detail, "START")
                up(self.stop_sensor_status, self.last_stop_sensor_time, self.stop_sensor_detail, "GOAL")
                if self.page: self.page.update()
            except Exception: pass
            time.sleep(0.1)

def main_launcher(page: ft.Page):
    app = GymkhanaApp()
    app.main(page)

if __name__ == "__main__":
    # v0.28.3 用
    ft.app(target=main_launcher)
