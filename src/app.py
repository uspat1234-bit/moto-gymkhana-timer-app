import flet as ft
import socket
import json
import threading
import time
import datetime

# 受信設定
UDP_PORT = 5005
BUFFER_SIZE = 1024

# センサー接続監視のタイムアウト時間（秒）
SENSOR_TIMEOUT = 5.0

# 1センサーモード時の「ゴール禁止時間」（スタート直後の誤反応防止）
MIN_LAP_TIME = 5.0 

# MULTIモードの履歴表示上限数
MAX_HISTORY_COUNT = 20

class GymkhanaApp:
    def __init__(self):
        self.running = True
        
        # --- 共通状態 ---
        self.last_start_sensor_time = 0.0
        self.last_stop_sensor_time = 0.0
        
        # ★追加: タブの状態を安全に管理する変数
        self.current_tab_index = 0

        # --- SOLOモード用状態 ---
        self.solo_running = False
        self.solo_start_time = 0.0
        
        # --- MULTIモード用状態 ---
        # 走行中のランナー情報を保持するリスト
        # [{'id': uuid, 'start_time': float, 'ui_text': ft.Text, 'ui_row': ft.Container}]
        self.active_runners = [] 
        self.history_count = 0

        # --- UIパーツ保持用 ---
        self.multi_list_view = None
        self.solo_time_display = None
        self.solo_status_text = None

    def main(self, page: ft.Page):
        self.page = page
        page.title = "Gymkhana Timer Mobile"
        page.bgcolor = "#1a1a1a" # ダークモード
        page.padding = 15
        page.scroll = ft.ScrollMode.AUTO 

        # 共通パーツの初期化
        self.init_common_ui()

        # スレッド開始
        threading.Thread(target=self.udp_listener, daemon=True).start()
        threading.Thread(target=self.timer_loop, daemon=True).start()

        # 初期画面：モード選択を表示
        self.show_mode_selection()

    def init_common_ui(self):
        # センサー状態表示 (共通で使用)
        self.start_sensor_status = ft.Container(
            content=ft.Text("START", color="white", weight=ft.FontWeight.BOLD, size=12),
            padding=5, border_radius=5, bgcolor="grey800", width=80, alignment=ft.alignment.center
        )
        self.stop_sensor_status = ft.Container(
            content=ft.Text("GOAL", color="white", weight=ft.FontWeight.BOLD, size=12),
            padding=5, border_radius=5, bgcolor="grey800", width=80, alignment=ft.alignment.center
        )
        
        self.sensor_row = ft.Row(
            [ft.Text("Sensor:", color="grey"), self.start_sensor_status, self.stop_sensor_status],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=10
        )

        self.wifi_info = ft.Container(
            content=ft.Row(
                [
                    ft.Text("SSID: motogym", color="white", weight=ft.FontWeight.BOLD),
                    ft.Text("PASS: 12345678", color="white", weight=ft.FontWeight.BOLD),
                ], 
                alignment=ft.MainAxisAlignment.CENTER, spacing=20, wrap=True
            ),
            padding=10, bgcolor="grey900", border_radius=10
        )

    # --- 画面遷移メソッド ---

    def show_mode_selection(self):
        """トップ画面: モード選択"""
        self.current_mode = None
        self.page.clean()
        
        btn_multi = ft.Container(
            content=ft.Column([
                # アイコン指定を文字列に変更
                ft.Icon(name="people", size=50, color="cyan"),
                ft.Text("MULTI MODE", size=20, weight=ft.FontWeight.BOLD, color="cyan"),
                ft.Text("複数人追走計測 (2センサー)", color="grey")
            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=20, bgcolor="grey900", border_radius=10, border=ft.border.all(1, "cyan"),
            on_click=lambda e: self.show_multi_mode(),
            ink=True
        )

        btn_solo = ft.Container(
            content=ft.Column([
                # アイコン指定を文字列に変更
                ft.Icon(name="timer", size=50, color="orange"),
                ft.Text("SOLO MODE", size=20, weight=ft.FontWeight.BOLD, color="orange"),
                ft.Text("単独計測 (1センサー)", color="grey")
            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=20, bgcolor="grey900", border_radius=10, border=ft.border.all(1, "orange"),
            on_click=lambda e: self.show_solo_mode(),
            ink=True
        )

        self.page.add(
            self.wifi_info,
            ft.Container(height=10),
            self.sensor_row,
            ft.Container(height=30),
            ft.Text("モードを選択してください", size=16, color="white", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
            ft.Container(height=20),
            btn_multi,
            ft.Container(height=15),
            btn_solo
        )
        self.page.update()

    def show_multi_mode(self):
        """MULTIモード画面"""
        self.current_mode = "MULTI"
        self.page.clean()
        
        # 初期化
        self.active_runners = []
        self.history_count = 0
        self.multi_list_view = ft.ListView(expand=True, spacing=5, padding=10, auto_scroll=False)

        # ヘッダー (戻るボタン付き)
        header = ft.Row([
            # アイコン指定を文字列に変更
            ft.IconButton(icon="arrow_back", icon_color="white", on_click=lambda e: self.show_mode_selection()),
            ft.Text("MULTI MODE", size=20, weight=ft.FontWeight.BOLD, color="cyan"),
            ft.ElevatedButton("CLEAR", color="white", bgcolor="red900", on_click=self.reset_multi_history)
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        self.page.add(
            header,
            self.sensor_row,
            ft.Divider(color="grey"),
            self.multi_list_view
        )
        self.page.update()

    def show_solo_mode(self):
        """SOLOモード画面"""
        self.current_mode = "SOLO"
        self.page.clean()
        
        # 初期化
        self.solo_running = False
        self.solo_start_time = 0.0
        
        self.solo_time_display = ft.Text(value="0.000", size=80, color="yellow", font_family="monospace", weight=ft.FontWeight.BOLD)
        self.solo_status_text = ft.Text(value="READY", size=24, color="grey400")
        
        # ヘッダー (戻るボタン付き)
        header = ft.Row([
            # アイコン指定を文字列に変更
            ft.IconButton(icon="arrow_back", icon_color="white", on_click=lambda e: self.show_mode_selection()),
            ft.Text("SOLO MODE", size=20, weight=ft.FontWeight.BOLD, color="orange"),
            ft.Container(width=40) # レイアウト調整
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        content = ft.Column([
            ft.Container(height=40),
            self.solo_status_text,
            self.solo_time_display,
            ft.Container(height=40),
            ft.ElevatedButton("RESET", color="white", bgcolor="red900", on_click=self.reset_solo_timer, width=150, height=50)
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)

        self.page.add(
            header,
            self.sensor_row,
            content
        )
        self.page.update()

    # --- ロジック ---

    def reset_solo_timer(self, e):
        self.solo_running = False
        self.solo_start_time = 0.0
        self.solo_time_display.value = "0.000"
        self.solo_time_display.color = "yellow"
        self.solo_status_text.value = "RESET"
        self.page.update()

    def handle_solo_signal(self):
        current = time.time()
        if not self.solo_running:
            self.solo_running = True
            self.solo_start_time = current
            self.solo_status_text.value = "RUNNING!"
            self.solo_time_display.color = "green"
            self.page.update()
        else:
            if current - self.solo_start_time < MIN_LAP_TIME: return
            self.solo_running = False
            result = current - self.solo_start_time
            self.solo_time_display.value = f"{result:.3f}"
            self.solo_status_text.value = "FINISH"
            self.solo_time_display.color = "red"
            self.page.update()

    def reset_multi_history(self, e):
        self.active_runners.clear()
        self.multi_list_view.controls.clear()
        self.history_count = 0
        self.page.update()

    def handle_multi_start(self):
        self.history_count += 1
        start_time = time.time()
        
        time_text = ft.Text("0.000", size=30, color="green", font_family="monospace", weight=ft.FontWeight.BOLD)
        status_text = ft.Text("RUNNING", size=12, color="green")
        
        item_card = ft.Container(
            content=ft.Row([
                ft.Text(f"#{self.history_count}", size=16, color="grey", width=40),
                ft.Column([
                    time_text,
                    ft.Text(datetime.datetime.now().strftime("%H:%M:%S Start"), size=10, color="grey")
                ], expand=True),
                status_text
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=15, bgcolor="grey900", border_radius=10, border=ft.border.all(1, "grey800")
        )
        
        runner = {
            'id': self.history_count,
            'start_time': start_time,
            'ui_time': time_text,
            'ui_status': status_text,
            'ui_container': item_card
        }
        
        self.active_runners.append(runner)
        self.multi_list_view.controls.insert(0, item_card)
        
        if len(self.multi_list_view.controls) > MAX_HISTORY_COUNT:
            self.multi_list_view.controls.pop()
            if self.active_runners:
                self.active_runners.pop(0)

        self.page.update()

    def handle_multi_stop(self):
        if not self.active_runners: return
        target_runner = None
        for runner in self.active_runners:
            if runner['ui_status'].value == "RUNNING":
                target_runner = runner
                break
        
        if not target_runner: return

        end_time = time.time()
        result = end_time - target_runner['start_time']
        
        target_runner['ui_time'].value = f"{result:.3f}"
        target_runner['ui_time'].color = "red"
        target_runner['ui_status'].value = "FINISH"
        target_runner['ui_status'].color = "red"
        target_runner['ui_container'].border = ft.border.all(1, "red900")
        self.page.update()

    # --- 監視ループ ---

    def udp_listener(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(('0.0.0.0', UDP_PORT))
            sock.settimeout(1.0)
            print(f"UDP Listening on port {UDP_PORT}...")

            while self.running:
                try:
                    data, addr = sock.recvfrom(BUFFER_SIZE)
                    message = data.decode('utf-8').strip()
                    
                    # 信号解析
                    is_start = False
                    is_stop = False
                    if "START" in message:
                        is_start = True
                        self.last_start_sensor_time = time.time()
                    elif "STOP" in message:
                        is_stop = True
                        self.last_stop_sensor_time = time.time()
                    
                    if message.startswith("{"): continue

                    # ★現在のモードに基づいて処理
                    if self.current_mode == "MULTI":
                        if is_start: self.handle_multi_start()
                        if is_stop: self.handle_multi_stop()
                    elif self.current_mode == "SOLO":
                        if is_start or is_stop:
                            self.handle_solo_signal()

                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"UDP Error: {e}")
        finally:
            sock.close()

    def update_sensor_ui(self):
        now = time.time()
        if now - self.last_start_sensor_time < SENSOR_TIMEOUT:
            self.start_sensor_status.bgcolor = "green"
        else:
            self.start_sensor_status.bgcolor = "grey800"
            
        if now - self.last_stop_sensor_time < SENSOR_TIMEOUT:
            self.stop_sensor_status.bgcolor = "green"
        else:
            self.stop_sensor_status.bgcolor = "grey800"

    def timer_loop(self):
        while self.running:
            try:
                now = time.time()
                
                # ★現在のモードに基づいて更新
                if self.current_mode == "SOLO":
                    if self.solo_running and self.solo_time_display:
                        self.solo_time_display.value = f"{now - self.solo_start_time:.3f}"
                        self.page.update()
                
                elif self.current_mode == "MULTI":
                    updated = False
                    for runner in self.active_runners:
                        if runner['ui_status'].value == "RUNNING":
                            runner['ui_time'].value = f"{now - runner['start_time']:.3f}"
                            updated = True
                    if updated:
                        self.page.update()
                
                # センサー状態は常に更新
                self.update_sensor_ui()
                self.page.update()

            except Exception:
                pass
            time.sleep(0.05)

if __name__ == "__main__":
    app = GymkhanaApp()
    ft.app(target=app.main)
