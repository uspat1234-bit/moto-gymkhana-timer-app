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
    """Wi-Fi情報表示ヘッダー (文字列指定でエラー回避)"""
    return ft.Container(
        content=ft.Row([
            ft.Text("SSID: motogym", color="white", weight="bold"),
            ft.Text("PASS: 12345678", color="white", weight="bold"),
        ], alignment=ft.MainAxisAlignment.CENTER, spacing=20, wrap=True),
        padding=10, bgcolor="grey900", border_radius=10
    )

def create_sensor_status(label):
    """センサー状態表示用ボックス (エラー修正: Alignmentクラスを明示)"""
    return ft.Container(
        content=ft.Text(f"{label}\n--", color="white", weight="bold", size=12, text_align=ft.TextAlign.CENTER),
        padding=5, border_radius=5, bgcolor="grey800", width=120, alignment=ft.Alignment(0, 0)
    )

class GymkhanaApp:
    def __init__(self):
        self.running = True
        self.page = None
        # 共通センサー状態
        self.last_start_sensor_time = 0.0
        self.last_stop_sensor_time = 0.0
        self.start_sensor_detail = {"rssi": None}
        self.stop_sensor_detail = {"rssi": None}
        
        self.current_mode = None 
        self.solo_running = False
        self.solo_start_time = 0.0
        self.active_runners = [] 
        self.history_count = 0
        self.multi_hold_runner = None 
        self.multi_hold_expire_time = 0.0

    def main(self, page: ft.Page):
        self.page = page
        page.title = "Gymkhana Timer"
        page.bgcolor = "#1a1a1a"
        page.theme_mode = ft.ThemeMode.DARK
        page.padding = 10
        page.scroll = ft.ScrollMode.AUTO

        try:
            # UI初期化 (修正: alignment属性を修正)
            self.start_sensor_status = create_sensor_status("START")
            self.stop_sensor_status = create_sensor_status("GOAL")
            self.sensor_row = ft.Row(
                [ft.Text("Sensor:", color="grey400"), self.start_sensor_status, self.stop_sensor_status],
                alignment=ft.MainAxisAlignment.CENTER, spacing=10
            )

            # 別スレッドで監視開始 (デーモンスレッド)
            threading.Thread(target=self.udp_listener, daemon=True).start()
            threading.Thread(target=self.timer_loop, daemon=True).start()

            self.show_mode_selection()
        except Exception as e:
            self.show_error(e)

    def show_error(self, e):
        self.page.clean()
        self.page.add(
            ft.Text("⚠️ Fatal Error", color="red", size=24, weight="bold"),
            ft.Text(traceback.format_exc(), color="white", font_family="monospace", size=12),
            ft.Button(content=ft.Text("Reload Menu"), on_click=lambda _: self.show_mode_selection())
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
                ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=15, bgcolor="grey900", border_radius=10,
                border=ft.Border(
                    top=ft.BorderSide(1, color), bottom=ft.BorderSide(1, color),
                    left=ft.BorderSide(1, color), right=ft.BorderSide(1, color)
                ),
                on_click=click_fn, ink=True
            )

        self.page.add(
            create_wifi_info(),
            ft.Container(height=10),
            self.sensor_row,
            ft.Container(height=20),
            ft.Text("モードを選択してください", size=14, color="white", text_align=ft.TextAlign.CENTER),
            ft.Container(height=10),
            create_btn("people", "MULTI MODE", "複数人追走 (2センサー)", "cyan", lambda _: self.show_multi_mode()),
            ft.Container(height=10),
            create_btn("timer", "SOLO MODE", "単独計測 (1センサー)", "orange", lambda _: self.show_solo_mode()),
            ft.Container(height=10),
            create_btn("calculate", "TIME CALC", "タイム比計算機", "green", lambda _: self.show_calc_mode())
        )
        self.page.update()

    # --- 各モード表示ロジック ---
    def show_multi_mode(self):
        self.current_mode = "MULTI"
        self.page.clean()
        self.multi_main_time = ft.Text("0.000", size=60, color="yellow", weight="bold", font_family="monospace")
        self.multi_main_name = ft.Text("---", size=24, color="white", weight="bold")
        self.multi_main_status = ft.Text("READY", size=16, color="grey")
        self.multi_history_list = ft.ListView(expand=True, spacing=5, height=300)
        self.multi_queue_text = ft.Text("No other runners", color="grey", size=12)

        self.page.add(
            ft.Row([
                ft.IconButton(icon="arrow_back", on_click=lambda _: self.show_mode_selection()),
                ft.Text("MULTI MODE", size=20, weight="bold", color="cyan"),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            self.sensor_row,
            ft.Container(
                content=ft.Column([
                    self.multi_main_name, self.multi_main_time, self.multi_main_status
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=20, bgcolor="grey900", border_radius=15, alignment=ft.Alignment(0, 0),
                border=ft.Border(
                    top=ft.BorderSide(2, "grey800"), bottom=ft.BorderSide(2, "grey800"),
                    left=ft.BorderSide(2, "grey800"), right=ft.BorderSide(2, "grey800")
                )
            ),
            ft.Text("ON COURSE:", size=12, color="cyan", weight="bold"),
            self.multi_queue_text,
            ft.Divider(color="grey800"),
            ft.Text("HISTORY:", size=12, color="white"),
            self.multi_history_list
        )
        self.page.update()

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
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            self.sensor_row,
            ft.Container(height=40),
            ft.Column([
                self.solo_status_text,
                self.solo_time_display,
                ft.Container(height=20),
                ft.Button(content=ft.Text("RESET"), color="white", bgcolor="red900", on_click=lambda _: self.reset_solo())
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        )
        self.page.update()

    def show_calc_mode(self):
        """タイム計算機画面 (TextField方式に変更)"""
        self.current_mode = "CALC"
        self.page.clean()
        
        # ユーザー入力を受け付けるTextField (数値キーボード指定)
        self.tf_top = ft.TextField(label="Top Time", keyboard_type=ft.KeyboardType.NUMBER, color="yellow", on_change=self.on_calc_update)
        self.tf_ratio = ft.TextField(label="Target Ratio (%)", value="105", keyboard_type=ft.KeyboardType.NUMBER, color="cyan", on_change=self.on_calc_update)
        self.tf_my = ft.TextField(label="Your Time", keyboard_type=ft.KeyboardType.NUMBER, color="white", on_change=self.on_calc_update)
        
        self.lbl_target = ft.Text("Target: 0.000", color="grey", size=18, weight="bold")
        self.calc_result = ft.Text("0.00 %", size=50, weight="bold", color="green")

        self.page.add(
            ft.Row([
                ft.IconButton(icon="arrow_back", on_click=lambda _: self.show_mode_selection()),
                ft.Text("TIME CALC", size=20, weight="bold", color="green")
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Column([
                self.tf_top,
                ft.Row([self.tf_ratio, self.lbl_target], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                self.tf_my,
                ft.Divider(),
                ft.Container(
                    content=ft.Column([
                        ft.Text("Current Ratio", size=12, color="grey"),
                        self.calc_result
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    alignment=ft.Alignment(0,0)
                )
            ], spacing=15)
        )
        self.page.update()

    def on_calc_update(self, e):
        """入力が変更されたら即座に再計算"""
        try:
            top = float(self.tf_top.value or 0)
            ratio = float(self.tf_ratio.value or 0)
            my = float(self.tf_my.value or 0)
            
            if top > 0 and ratio > 0:
                self.lbl_target.value = f"Target: {top / (ratio/100):.3f}"
            
            if top > 0 and my > 0:
                res = (my / top) * 100
                self.calc_result.value = f"{res:.2f} %"
                self.calc_result.color = "green" if res < 105 else ("yellow" if res < 110 else "red")
            else:
                self.calc_result.value = "0.00 %"
                self.calc_result.color = "grey"
        except:
            pass
        self.page.update()

    # --- 共通ロジック ---
    def reset_solo(self):
        self.solo_running = False
        self.solo_time_display.value = "0.000"
        self.solo_time_display.color = "yellow"
        self.solo_status_text.value = "RESET"
        self.page.update()

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
                    if self.current_mode == "MULTI":
                        if msg == "START": self.handle_multi_start()
                        if msg == "STOP": self.handle_multi_stop()
                    elif self.current_mode == "SOLO":
                        if msg == "START" or msg == "STOP": self.handle_solo_signal()
                except socket.timeout: continue
        except: pass

    def handle_multi_start(self):
        self.history_count += 1
        self.active_runners.append({'num': self.history_count, 'start_time': time.time()})
        self.update_multi_ui()

    def handle_multi_stop(self):
        if not self.active_runners: return
        runner = self.active_runners.pop(0)
        res = time.time() - runner['start_time']
        self.multi_hold_runner = {'num': runner['num'], 'time': res}
        self.multi_hold_expire_time = time.time() + MULTI_GOAL_DISPLAY_TIME
        self.multi_history_list.controls.insert(0, ft.Text(f"#{runner['num']} Result: {res:.3f}s", color="yellow"))
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
        if self.page: self.page.update()

    def handle_solo_signal(self):
        now = time.time()
        if not self.solo_running:
            self.solo_running = True; self.solo_start_time = now
            self.solo_status_text.value = "RUNNING!"; self.solo_time_display.color = "green"
        else:
            if now - self.solo_start_time < MIN_LAP_TIME: return
            self.solo_running = False; res = now - self.solo_start_time
            self.solo_time_display.value = f"{res:.3f}"; self.solo_time_display.color = "red"; self.solo_status_text.value = "FINISH"
        if self.page: self.page.update()

    def timer_loop(self):
        while self.running:
            try:
                now = time.time()
                if self.current_mode == "SOLO" and self.solo_running:
                    self.solo_time_display.value = f"{now - self.solo_start_time:.3f}"
                if self.current_mode == "MULTI":
                    if self.multi_hold_runner and now > self.multi_hold_expire_time: self.multi_hold_runner = None
                    if not self.multi_hold_runner and self.active_runners:
                        self.multi_main_time.value = f"{now - self.active_runners[0]['start_time']:.3f}"
                    self.update_multi_ui()
                def up(c, t, l):
                    if now - t < SENSOR_TIMEOUT:
                        c.bgcolor = "green"; c.content.value = f"{l}: OK"
                    else:
                        c.bgcolor = "grey800"; c.content.value = f"{l}\n--"
                up(self.start_sensor_status, self.last_start_sensor_time, "START")
                up(self.stop_sensor_status, self.last_stop_sensor_time, "GOAL")
                if self.page: self.page.update()
            except: pass
            time.sleep(0.1)

def main_launcher(page: ft.Page):
    app = GymkhanaApp()
    app.main(page)

if __name__ == "__main__":
    ft.app(target=main_launcher)
