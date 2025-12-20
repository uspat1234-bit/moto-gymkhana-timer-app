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
SENSOR_TIMEOUT = 4.0

# 1センサーモード時の「ゴール禁止時間」（スタート直後の誤反応防止）
MIN_LAP_TIME = 4.0 

# MULTIモードの履歴表示上限数
MAX_HISTORY_COUNT = 20

# MULTIモードのゴール後表示維持時間（秒）
MULTI_GOAL_DISPLAY_TIME = 3.0

class GymkhanaApp:
    def __init__(self):
        self.running = True
        
        # --- 共通状態 ---
        self.last_start_sensor_time = 0.0
        self.last_stop_sensor_time = 0.0
        
        # 現在のモード (None, 'MULTI', 'SOLO')
        self.current_mode = None

        # --- SOLOモード用状態 ---
        self.solo_running = False
        self.solo_start_time = 0.0
        
        # --- MULTIモード用状態 ---
        self.active_runners = [] 
        self.history_count = 0
        
        # MULTIモードのゴール表示制御用
        self.multi_hold_runner = None 
        self.multi_hold_expire_time = 0.0

        # --- UI参照 ---
        self.wifi_info = None
        self.sensor_row = None
        self.start_sensor_status = None
        self.stop_sensor_status = None
        
        # MULTI用UI
        self.multi_main_time = None
        self.multi_main_status = None
        self.multi_main_name = None
        self.multi_queue_text = None
        self.multi_history_list = None
        
        # SOLO用UI
        self.solo_time_display = None
        self.solo_status_text = None

    def main(self, page: ft.Page):
        self.page = page
        page.title = "Gymkhana Timer Mobile"
        page.bgcolor = "#1a1a1a" # ダークモード
        page.padding = 10
        page.scroll = ft.ScrollMode.AUTO 

        # 共通UIパーツの初期化
        self.init_common_ui()

        # スレッド開始
        threading.Thread(target=self.udp_listener, daemon=True).start()
        threading.Thread(target=self.timer_loop, daemon=True).start()

        # 初期画面：モード選択
        self.show_mode_selection()

    def init_common_ui(self):
        # ヘッダー情報
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

        # センサー状態
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
            alignment=ft.MainAxisAlignment.CENTER, spacing=10, wrap=True
        )

    # --- 画面遷移メソッド ---

    def show_mode_selection(self):
        """モード選択画面を表示"""
        self.current_mode = None
        self.page.clean()

        btn_multi = ft.Container(
            content=ft.Column([
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
        """MULTIモード画面を表示"""
        self.current_mode = "MULTI"
        self.page.clean()
        
        # 状態リセット
        self.active_runners = []
        self.history_count = 0
        
        # ヘッダー (戻るボタン付き)
        header = ft.Row([
            ft.IconButton(icon="arrow_back", icon_color="white", on_click=lambda e: self.show_mode_selection()),
            ft.Text("MULTI MODE", size=20, weight=ft.FontWeight.BOLD, color="cyan"),
            ft.Container(width=40) # レイアウト調整
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        # 1. メイン表示エリア (一番ゴールに近い人)
        self.multi_main_time = ft.Text("0.000", size=70, color="yellow", font_family="monospace", weight=ft.FontWeight.BOLD)
        self.multi_main_status = ft.Text("READY", size=20, color="grey")
        self.multi_main_name = ft.Text("---", size=30, color="white", weight=ft.FontWeight.BOLD)

        multi_main_container = ft.Container(
            content=ft.Column([
                ft.Text("CURRENT RUNNER", size=12, color="grey"),
                self.multi_main_name,
                self.multi_main_time,
                self.multi_main_status
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=20,
            bgcolor="grey900",
            border_radius=15,
            border=ft.border.all(2, "grey800"),
            alignment=ft.alignment.center
        )

        # 2. サブ情報エリア (後続のランナー)
        self.multi_queue_text = ft.Text("No other runners on course", color="grey", size=14)
        
        # 3. 履歴リスト (ログ)
        self.multi_history_list = ft.ListView(expand=True, spacing=2, padding=10, auto_scroll=False, height=300)
        
        btn_multi_reset = ft.ElevatedButton(
            text="CLEAR LOG", color="white", bgcolor="red900", 
            on_click=self.reset_multi_history, height=40
        )

        self.page.add(
            header,
            self.sensor_row,
            ft.Divider(color="grey"),
            multi_main_container,
            ft.Container(height=10),
            ft.Text("ON COURSE:", size=14, color="cyan", weight=ft.FontWeight.BOLD),
            self.multi_queue_text,
            ft.Divider(color="grey"),
            ft.Text("RESULT LOG:", size=14, color="white", weight=ft.FontWeight.BOLD),
            self.multi_history_list,
            ft.Container(content=btn_multi_reset, alignment=ft.alignment.center, padding=10)
        )
        self.page.update()

    def show_solo_mode(self):
        """SOLOモード画面を表示"""
        self.current_mode = "SOLO"
        self.page.clean()
        
        # 状態リセット
        self.solo_running = False
        self.solo_start_time = 0.0
        
        self.solo_time_display = ft.Text(value="0.000", size=70, color="yellow", font_family="monospace", weight=ft.FontWeight.BOLD)
        self.solo_status_text = ft.Text(value="READY", size=24, color="grey400")
        
        # ヘッダー (戻るボタン付き)
        header = ft.Row([
            ft.IconButton(icon="arrow_back", icon_color="white", on_click=lambda e: self.show_mode_selection()),
            ft.Text("SOLO MODE", size=20, weight=ft.FontWeight.BOLD, color="orange"),
            ft.Container(width=40)
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        content = ft.Column([
            ft.Container(height=20),
            ft.Text("スタートセンサーのみ使用 (通過でStart/Stop切替)", color="grey", size=12, text_align=ft.TextAlign.CENTER),
            ft.Container(height=40),
            self.solo_status_text,
            self.solo_time_display,
            ft.Container(height=40),
            # SOLOモードはボタンなし(センサー操作のみ)
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)

        self.page.add(
            header,
            self.sensor_row,
            content
        )
        self.page.update()

    # --- SOLOモード用ロジック ---
    def reset_solo_timer(self, e):
        self.solo_running = False
        self.solo_start_time = 0.0
        if self.solo_time_display:
            self.solo_time_display.value = "0.000"
            self.solo_time_display.color = "yellow"
        if self.solo_status_text:
            self.solo_status_text.value = "RESET"
        self.page.update()

    def handle_solo_signal(self):
        current = time.time()
        # 画面パーツが存在しない場合は処理しない
        if not self.solo_time_display: return

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

    # --- MULTIモード用ロジック ---
    def reset_multi_history(self, e):
        # 走行中のデータは消さない方が安全
        if self.multi_history_list:
            self.multi_history_list.controls.clear()
        self.page.update()

    def handle_multi_start(self, rider_name="Unknown", rider_id="---"):
        # 画面パーツが存在しない場合は処理しない
        if not self.multi_main_time: return

        self.history_count += 1
        
        runner = {
            'num': self.history_count,
            'name': rider_name,
            'rid': rider_id,
            'start_time': time.time(),
            'result_time': None
        }
        
        self.active_runners.append(runner)
        self.update_multi_ui_state()

    def handle_multi_stop(self):
        if not self.active_runners: return

        # 一番長く走っている人（リストの先頭）を取り出す
        runner = self.active_runners.pop(0)
        
        # タイム確定
        result_time = time.time() - runner['start_time']
        runner['result_time'] = result_time
        time_str = f"{result_time:.3f}"
        
        # ログに追加するカードを作成
        log_item = ft.Container(
            content=ft.Row([
                ft.Text(f"#{runner['num']}", color="grey", size=14, width=30),
                ft.Text(f"{runner['name']}", color="white", size=16, weight=ft.FontWeight.BOLD, expand=True), 
                ft.Text(time_str, color="yellow", size=24, font_family="monospace", weight=ft.FontWeight.BOLD),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=10,
            bgcolor="grey900",
            border_radius=5,
            border=ft.border.all(1, "grey800")
        )
        
        if self.multi_history_list:
            # 履歴の先頭に追加
            self.multi_history_list.controls.insert(0, log_item)
            # 履歴上限チェック
            if len(self.multi_history_list.controls) > MAX_HISTORY_COUNT:
                self.multi_history_list.controls.pop()

        # ゴール表示維持の設定
        self.multi_hold_runner = runner
        self.multi_hold_expire_time = time.time() + MULTI_GOAL_DISPLAY_TIME
        
        self.update_multi_ui_state()

    def update_multi_ui_state(self):
        """MULTIモードの画面表示を更新（タイマー以外）"""
        if not self.multi_main_time: return

        display_runner = None
        status_msg = "READY"
        status_color = "grey"
        time_val = "0.000"
        time_color = "yellow"

        # ゴール表示維持中かチェック
        is_holding = False
        if self.multi_hold_runner:
            if time.time() < self.multi_hold_expire_time:
                # 表示維持
                display_runner = self.multi_hold_runner
                status_msg = "FINISH"
                status_color = "red"
                time_val = f"{display_runner['result_time']:.3f}"
                time_color = "red"
                is_holding = True
            else:
                # 期限切れ -> クリア
                self.multi_hold_runner = None

        # 維持中でなければ、現在の先頭ランナーを表示
        if not is_holding and self.active_runners:
            display_runner = self.active_runners[0]
            status_msg = f"RUNNING (#{display_runner['num']})"
            status_color = "green"
            # タイムはtimer_loopで更新される
        
        # 表示更新
        if display_runner:
            self.multi_main_name.value = f"#{display_runner['num']} {display_runner['name']}"
            self.multi_main_status.value = status_msg
            self.multi_main_status.color = status_color
            if is_holding:
                self.multi_main_time.value = time_val
                self.multi_main_time.color = time_color
        elif not self.active_runners:
            # 誰もいない状態
            self.multi_main_name.value = "---"
            self.multi_main_time.value = "0.000"
            self.multi_main_status.value = "WAITING ENTRY"
            self.multi_main_status.color = "grey"
            self.multi_main_time.color = "grey"

        # サブ情報の更新（後続ランナー）
        if self.multi_queue_text:
            others = []
            start_index = 0
            
            # ゴール表示中でなければ、先頭(0)はメインに出ているので除外
            if not is_holding and self.active_runners:
                start_index = 1
                
            for r in self.active_runners[start_index:]:
                others.append(f"#{r['num']} {r['name']}")
                
            if others:
                self.multi_queue_text.value = "Following: " + ", ".join(others)
            else:
                self.multi_queue_text.value = "No other runners on course"
            
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
                    
                    is_start = False
                    is_stop = False
                    
                    if "START" in message:
                        is_start = True
                        self.last_start_sensor_time = time.time()
                    elif "STOP" in message:
                        is_stop = True
                        self.last_stop_sensor_time = time.time()
                    
                    if message.startswith("{"): continue

                    # 現在のモードに基づいて処理を分岐
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
        # START
        if now - self.last_start_sensor_time < SENSOR_TIMEOUT:
            self.start_sensor_status.bgcolor = "green"
        else:
            self.start_sensor_status.bgcolor = "grey800"
            
        # STOP
        if now - self.last_stop_sensor_time < SENSOR_TIMEOUT:
            self.stop_sensor_status.bgcolor = "green"
        else:
            self.stop_sensor_status.bgcolor = "grey800"

    def timer_loop(self):
        while self.running:
            try:
                now = time.time()
                
                if self.current_mode == "SOLO":
                    if self.solo_running and self.solo_time_display:
                        self.solo_time_display.value = f"{now - self.solo_start_time:.3f}"
                        self.page.update()
                
                elif self.current_mode == "MULTI":
                    # ゴール表示維持中はタイマー更新しない
                    if self.multi_hold_runner and now > self.multi_hold_expire_time:
                        self.multi_hold_runner = None
                        self.update_multi_ui_state()

                    if not self.multi_hold_runner and self.active_runners:
                        # 先頭ランナーのタイムを更新
                        target = self.active_runners[0]
                        current_time = now - target['start_time']
                        if self.multi_main_time:
                            self.multi_main_time.value = f"{current_time:.3f}"
                            self.multi_main_time.color = "yellow"
                            self.page.update()
                
                # センサー状態は常に更新
                if self.page:
                    self.update_sensor_ui()
                    self.page.update()

            except Exception:
                pass
            time.sleep(0.05)

if __name__ == "__main__":
    app = GymkhanaApp()
    ft.app(target=app.main)
