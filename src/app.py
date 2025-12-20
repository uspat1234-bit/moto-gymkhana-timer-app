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
        
        # ★追加: タブの状態を安全に管理する変数
        self.current_tab_index = 0

        # --- SOLOモード用状態 ---
        self.solo_running = False
        self.solo_start_time = 0.0
        
        # --- MULTIモード用状態 ---
        # 走行中のランナーデータ (辞書リスト)
        # [{'id': 1, 'start_time': 12345.67}]
        self.active_runners = [] 
        self.history_count = 0
        
        # ★追加: MULTIモードのゴール表示制御用
        self.multi_hold_runner = None # ゴール表示を維持するランナー
        self.multi_hold_expire_time = 0.0 # 表示期限

        # --- UIパーツ保持用 ---
        self.multi_main_time = None
        self.multi_main_status = None
        self.multi_queue_text = None
        self.multi_history_list = None
        
        self.solo_time_display = None
        self.solo_status_text = None

    def main(self, page: ft.Page):
        self.page = page
        page.title = "Gymkhana Timer Mobile"
        page.bgcolor = "#1a1a1a" # ダークモード
        page.padding = 10
        # スマホ対応: 画面からはみ出た場合にスクロールできるようにする
        page.scroll = ft.ScrollMode.AUTO 
        
        # --- 共通ヘッダー (接続情報) ---
        self.wifi_info = ft.Container(
            content=ft.Row(
                [
                    ft.Text("SSID: motogym", color="white", weight=ft.FontWeight.BOLD),
                    ft.Text("PASS: password123", color="white", weight=ft.FontWeight.BOLD),
                ], 
                alignment=ft.MainAxisAlignment.CENTER, 
                spacing=20,
                wrap=True # 画面幅が狭いと折り返す
            ),
            padding=10,
            bgcolor="grey900", 
            border_radius=10
        )

        # センサー状態 (共通)
        self.start_sensor_status = ft.Container(
            content=ft.Text("START", color="white", weight=ft.FontWeight.BOLD, size=12),
            padding=5, border_radius=5, bgcolor="grey800", width=80, alignment=ft.alignment.center
        )
        self.stop_sensor_status = ft.Container(
            content=ft.Text("GOAL", color="white", weight=ft.FontWeight.BOLD, size=12),
            padding=5, border_radius=5, bgcolor="grey800", width=80, alignment=ft.alignment.center
        )
        
        sensor_row = ft.Row(
            [ft.Text("Sensor:", color="grey"), self.start_sensor_status, self.stop_sensor_status],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=10,
            wrap=True # 画面幅が狭いと折り返す
        )

        # --- タブ 1: MULTIモード (リニューアル) ---
        
        # 1. メイン表示エリア (一番ゴールに近い人)
        self.multi_main_time = ft.Text("0.000", size=70, color="yellow", font_family="monospace", weight=ft.FontWeight.BOLD)
        self.multi_main_status = ft.Text("READY", size=20, color="grey")
        self.multi_main_name = ft.Text("---", size=30, color="white", weight=ft.FontWeight.BOLD) # ★追加: 名前表示用

        multi_main_container = ft.Container(
            content=ft.Column([
                ft.Text("CURRENT RUNNER", size=12, color="grey"),
                self.multi_main_name, # ★名前を表示
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
            text="CLEAR LOG", 
            color="white", 
            bgcolor="red900", 
            on_click=self.reset_multi_history,
            height=40
        )

        tab_multi_content = ft.Column([
            ft.Container(
                content=ft.Text("MULTI MODE (2 Sensors)", size=20, weight=ft.FontWeight.BOLD, color="cyan"),
                alignment=ft.alignment.center, padding=10
            ),
            multi_main_container,     # メイン表示
            ft.Container(height=10),
            ft.Text("ON COURSE:", size=14, color="cyan", weight=ft.FontWeight.BOLD),
            self.multi_queue_text,    # 後続情報
            ft.Divider(color="grey"),
            ft.Text("RESULT LOG:", size=14, color="white", weight=ft.FontWeight.BOLD),
            self.multi_history_list,  # 履歴
            ft.Container(content=btn_multi_reset, alignment=ft.alignment.center, padding=10) 
        ], scroll=ft.ScrollMode.AUTO)

        # --- タブ 2: SOLOモード (1センサー/単独) ---
        self.solo_time_display = ft.Text(value="0.000", size=70, color="yellow", font_family="monospace", weight=ft.FontWeight.BOLD)
        self.solo_status_text = ft.Text(value="READY", size=20, color="grey400")
        
        # SOLOモードのリセットボタンは削除済み

        tab_solo_content = ft.Column([
            ft.Container(height=20),
            ft.Text("SOLO MODE (1 Sensor)", size=20, weight=ft.FontWeight.BOLD, color="orange"),
            ft.Text("スタートセンサーのみ使用 (通過でStart/Stop切替)", color="grey", size=12, text_align=ft.TextAlign.CENTER),
            ft.Container(height=40),
            self.solo_status_text,
            self.solo_time_display,
            ft.Container(height=40),
        ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, expand=True)

        # --- タブ構成 ---
        self.tabs = ft.Tabs(
            selected_index=0,
            animation_duration=300,
            on_change=self.on_tab_change, # ★追加: タブ切り替えイベント
            tabs=[
                ft.Tab(text="MULTI (追走)", content=tab_multi_content, icon="people"),
                ft.Tab(text="SOLO (単独)", content=tab_solo_content, icon="timer"),
            ],
            expand=True,
            label_color="white",           
            unselected_label_color="grey", 
            indicator_color="cyan",        
            divider_color="transparent",   
        )

        # ページに追加
        page.add(
            self.wifi_info,
            sensor_row,
            self.tabs
        )

        # スレッド開始
        threading.Thread(target=self.udp_listener, daemon=True).start()
        threading.Thread(target=self.timer_loop, daemon=True).start()

    # ★追加: タブ切り替えイベントハンドラ
    def on_tab_change(self, e):
        # タブ切り替え時に変数を更新し、画面を再描画
        self.current_tab_index = e.control.selected_index
        print(f"Tab changed to: {self.current_tab_index}")
        self.page.update()

    # --- SOLOモード用ロジック ---
    def reset_solo_timer(self, e):
        self.solo_running = False
        self.solo_start_time = 0.0
        self.solo_time_display.value = "0.000"
        self.solo_time_display.color = "yellow"
        self.solo_status_text.value = "RESET"
        self.page.update()

    def handle_solo_signal(self):
        """1センサーモードのロジック: トグル動作"""
        current = time.time()
        
        # スタート処理
        if not self.solo_running:
            self.solo_running = True
            self.solo_start_time = current
            self.solo_status_text.value = "RUNNING!"
            self.solo_time_display.color = "green"
            self.page.update()
            print("SOLO: START")
        
        # ゴール処理
        else:
            # 不感時間チェック
            if current - self.solo_start_time < MIN_LAP_TIME:
                return

            self.solo_running = False
            result = current - self.solo_start_time
            self.solo_time_display.value = f"{result:.3f}"
            self.solo_status_text.value = "FINISH"
            self.solo_time_display.color = "red"
            self.page.update()
            print(f"SOLO: FINISH ({result:.3f})")

    # --- MULTIモード用ロジック ---
    def reset_multi_history(self, e):
        """履歴ログをクリア（走行中のデータは消さない）"""
        # self.active_runners.clear() # 走行中は消さない方が安全
        self.multi_history_list.controls.clear()
        # self.history_count = 0 # 番号は継続させる
        self.page.update()

    def handle_multi_start(self, rider_name="Unknown", rider_id="---"):
        """スタート：走行中リストに追加"""
        self.history_count += 1
        
        runner = {
            'num': self.history_count,
            'name': rider_name,
            'rid': rider_id,
            'start_time': time.time(),
            'result_time': None # ゴールタイム
        }
        
        self.active_runners.append(runner)
        self.update_multi_ui_state()

    def handle_multi_stop(self):
        """ゴール：先頭をゴールさせ、ログに追加（3秒表示維持）"""
        if not self.active_runners:
            return

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
        
        # 履歴の先頭に追加
        self.multi_history_list.controls.insert(0, log_item)
        
        # 履歴上限チェック
        if len(self.multi_history_list.controls) > MAX_HISTORY_COUNT:
            self.multi_history_list.controls.pop()

        # ★ゴール表示維持の設定
        self.multi_hold_runner = runner
        self.multi_hold_expire_time = time.time() + MULTI_GOAL_DISPLAY_TIME
        
        self.update_multi_ui_state()

    def update_multi_ui_state(self):
        """MULTIモードの画面表示を更新（タイマー以外）"""
        # メイン表示の更新ロジック:
        # 1. ゴール表示維持中ならその人を表示
        # 2. 維持中でなければ、現在走行中の先頭ランナーを表示
        
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
            # タイムはtimer_loopで更新されるのでここでは仮の値か、前回の値を維持
            # 実際の更新は timer_loop で行うため、ここでは静的な情報のみ更新
        
        # 表示更新
        if display_runner:
            self.multi_main_name.value = f"#{display_runner['num']} {display_runner['name']}"
            self.multi_main_status.value = status_msg
            self.multi_main_status.color = status_color
            if is_holding: # ゴール時はタイムもここで確定させる
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
        # 表示中のランナーを除いたリストを表示
        others = []
        start_index = 0
        
        # もしゴール表示中なら、active_runners の全員が「後続」
        # もし走行中表示なら、active_runners[0] はメインに出ているので、[1:] が後続
        if not is_holding and self.active_runners:
            start_index = 1
            
        for r in self.active_runners[start_index:]:
            others.append(f"#{r['num']} {r['name']}")
            
        if others:
            self.multi_queue_text.value = "Following: " + ", ".join(others)
        else:
            self.multi_queue_text.value = "No other runners on course"
            
        self.page.update()

    # --- 共通ロジック ---
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
                    
                    # ★修正: スレッドセーフな変数を使用
                    current_tab = self.current_tab_index
                    
                    # 信号解析
                    is_start = False
                    is_stop = False
                    
                    if "START" in message:
                        is_start = True
                        self.last_start_sensor_time = time.time()
                    elif "STOP" in message:
                        is_stop = True
                        self.last_stop_sensor_time = time.time()
                    
                    # 死活監視パケット(JSON)の場合は無視
                    if message.startswith("{"):
                         continue

                    # タブごとの動作振り分け
                    if current_tab == 0: # MULTI
                        # 名前は仮で入れる (NFC連携がない場合)
                        if is_start: self.handle_multi_start("Rider", "---")
                        if is_stop: self.handle_multi_stop()
                    else: # SOLO
                        # SOLOモードはどちらのセンサーでも反応させる
                        if is_start or is_stop:
                            self.handle_solo_signal()

                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"UDP Error: {e}")
        finally:
            sock.close()

    def update_sensor_ui(self):
        """センサー状態表示の更新"""
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
        """画面更新ループ"""
        while self.running:
            try:
                now = time.time()
                
                # SOLOモードのタイマー計算（常に更新）
                if self.solo_running:
                    self.solo_time_display.value = f"{now - self.solo_start_time:.3f}"
                
                # MULTIモードのタイマー計算
                # ゴール表示維持中（multi_hold_runnerがいる）の場合はタイマー更新しない（結果を表示し続けるため）
                # 期限切れチェックをここでも行う
                if self.multi_hold_runner and now > self.multi_hold_expire_time:
                    self.multi_hold_runner = None
                    self.update_multi_ui_state() # 画面を走行中モードに戻す

                if not self.multi_hold_runner and self.active_runners:
                    # 先頭ランナーのタイムを更新
                    target = self.active_runners[0]
                    current_time = now - target['start_time']
                    self.multi_main_time.value = f"{current_time:.3f}"
                    self.multi_main_time.color = "yellow"
                
                # センサー状態更新
                self.update_sensor_ui()

                # 画面全体を更新（どのタブにいても更新する）
                self.page.update()

            except Exception as e:
                # 終了時などにエラーが出ても無視
                pass
                
            time.sleep(0.05)

if __name__ == "__main__":
    app = GymkhanaApp()
    ft.app(target=app.main)
