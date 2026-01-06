import flet as ft
import socket
import json
import threading
import time
import datetime

# 分割したファイルをインポート
import config
from network import UdpListener
import ui_components as ui

class GymkhanaApp:
    def __init__(self):
        self.running = True
        
        # 状態変数
        self.last_start_sensor_time = 0.0
        self.last_stop_sensor_time = 0.0
        self.start_sensor_detail = {"rssi": None, "proto": ""}
        self.stop_sensor_detail = {"rssi": None, "proto": ""}
        
        self.current_mode = None
        self.solo_running = False
        self.solo_start_time = 0.0
        self.active_runners = [] 
        self.history_count = 0
        self.multi_hold_runner = None 
        self.multi_hold_expire_time = 0.0

        # 計算機モード用
        self.calc_target = "top" 

        # 通信モジュール
        self.udp_server = UdpListener(self.on_udp_message)

        # UIパーツ参照用
        self.solo_time_display = None
        self.multi_main_time = None
        self.start_sensor_status = None
        self.stop_sensor_status = None
        
        # ★追加: エラー回避のために初期化
        self.multi_history_list = None

    def main(self, page: ft.Page):
        self.page = page
        page.title = "Gymkhana Timer Mobile"
        page.bgcolor = "#1a1a1a"
        page.padding = 10
        page.scroll = ft.ScrollMode.AUTO 

        page.window.prevent_close = True
        page.window.on_event = self.window_event

        self.init_common_ui()

        # 通信とタイマーを開始
        self.udp_server.start()
        threading.Thread(target=self.timer_loop, daemon=True).start()

        self.show_mode_selection()

    def window_event(self, e):
        if e.data == "close":
            self.running = False
            self.udp_server.stop()
            self.page.window.destroy()

    def init_common_ui(self):
        self.start_sensor_status = ui.create_sensor_status("START")
        self.stop_sensor_status = ui.create_sensor_status("GOAL")
        
        self.sensor_row = ft.Row(
            [ft.Text("Sensor:", color="grey"), self.start_sensor_status, self.stop_sensor_status],
            alignment=ft.MainAxisAlignment.CENTER, spacing=10, wrap=True
        )

    # --- UDPメッセージ受信処理 (コールバック) ---
    def on_udp_message(self, message):
        # 信号解析
        is_start = False
        is_stop = False
        
        # JSON (死活監視など)
        if message.startswith("{"):
            try:
                j = json.loads(message)
                if j.get("status") == "alive":
                    stype = j.get("sensor")
                    rssi = j.get("rssi")
                    proto = j.get("proto")
                    
                    if stype == "START": 
                        self.last_start_sensor_time = time.time()
                        self.start_sensor_detail = {"rssi": rssi, "proto": proto}
                    elif stype == "GOAL": 
                        self.last_stop_sensor_time = time.time()
                        self.stop_sensor_detail = {"rssi": rssi, "proto": proto}
                
                # エントリー情報
                elif j.get("type") == "ENTRY":
                    name = j.get("name")
                    rid = j.get("id")
                    if self.current_mode == "MULTI":
                        self.next_rider_name = name
                        self.next_rider_id = rid
                        print(f"Next Rider Registered: {name}")
            except: pass
            return

        # 計測コマンド
        if message == "START":
            is_start = True
            self.last_start_sensor_time = time.time()
        elif message == "STOP":
            is_stop = True
            self.last_stop_sensor_time = time.time()

        # モードごとの処理呼び出し
        if self.current_mode == "MULTI":
            if is_start: 
                rider_name = getattr(self, 'next_rider_name', 'Unknown')
                rider_id = getattr(self, 'next_rider_id', '---')
                self.handle_multi_start(rider_name, rider_id)
                self.next_rider_name = "Unknown"
                self.next_rider_id = "---"
            if is_stop: self.handle_multi_stop()
        elif self.current_mode == "SOLO":
            if is_start or is_stop:
                self.handle_solo_signal()

    # --- 画面構築・遷移 ---
    def show_mode_selection(self):
        self.current_mode = None
        self.page.clean()

        btn_multi = ui.create_mode_button("people", "MULTI MODE", "複数人追走計測 (2センサー)", "cyan", lambda e: self.show_multi_mode())
        btn_solo = ui.create_mode_button("timer", "SOLO MODE", "単独計測 (1センサー)", "orange", lambda e: self.show_solo_mode())
        btn_calc = ui.create_mode_button("calculate", "TIME CALC", "タイム比・目標計算", "green", lambda e: self.show_calc_mode())

        self.page.add(
            ui.create_wifi_header(),
            ft.Container(height=10),
            self.sensor_row,
            ft.Container(height=30),
            ft.Text("モードを選択してください", size=16, color="white", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
            ft.Container(height=20),
            btn_multi,
            ft.Container(height=15),
            btn_solo,
            ft.Container(height=15),
            btn_calc
        )
        self.page.update()

    def show_multi_mode(self):
        self.current_mode = "MULTI"
        self.page.clean()
        self.active_runners = []
        self.history_count = 0
        
        # ★ここでインスタンス変数に代入
        self.multi_list_view = ft.ListView(expand=True, spacing=2, padding=10, auto_scroll=False, height=300)
        self.multi_history_list = self.multi_list_view # 別名でも参照できるようにする(念のため)

        header = ui.create_back_header("MULTI MODE", "cyan", lambda e: self.show_mode_selection(),
            ft.ElevatedButton("CLEAR LOG", color="white", bgcolor="red900", on_click=self.reset_multi_history)
        )

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
            padding=20, bgcolor="grey900", border_radius=15, border=ft.border.all(2, "grey800"),
            alignment=ft.alignment.center
        )

        self.multi_queue_text = ft.Text("No other runners on course", color="grey", size=14)

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
            # ★ここで self.multi_list_view を使用
            self.multi_list_view
        )
        self.page.update()

    def show_solo_mode(self):
        self.current_mode = "SOLO"
        self.page.clean()
        self.solo_running = False
        self.solo_start_time = 0.0
        
        self.solo_time_display = ft.Text(value="0.000", size=70, color="yellow", font_family="monospace", weight=ft.FontWeight.BOLD)
        self.solo_status_text = ft.Text(value="READY", size=24, color="grey400")
        
        header = ui.create_back_header("SOLO MODE", "orange", lambda e: self.show_mode_selection())

        content = ft.Column([
            ft.Container(height=20),
            ft.Text("スタートセンサーのみ使用 (通過でStart/Stop切替)", color="grey", size=12, text_align=ft.TextAlign.CENTER),
            ft.Container(height=40),
            self.solo_status_text,
            self.solo_time_display,
            ft.Container(height=40),
            ft.ElevatedButton("RESET", color="white", bgcolor="red900", on_click=self.reset_solo_timer, width=150, height=50)
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)

        self.page.add(header, self.sensor_row, content)
        self.page.update()

    def show_calc_mode(self):
        """タイム計算機画面 (Top比/仮想タイム)"""
        self.current_mode = "CALC"
        self.page.clean()
        
        header = ui.create_back_header("TIME CALCULATOR", "green", lambda e: self.show_mode_selection())

        self.calc_target = "top" # 'top', 'ratio', 'my'
        
        # --- UIパーツ ---
        # 1. Top Time 入力
        self.txt_top = ft.Text(value="", size=30, color="yellow", text_align=ft.TextAlign.RIGHT)
        self.con_top = ft.Container(
            content=self.txt_top,
            on_click=lambda e: self.select_calc_input("top"),
            border=ft.border.all(2, "cyan"),
            border_radius=5, width=180, height=60, padding=10, bgcolor="grey900",
            alignment=ft.alignment.center_right
        )

        # 2. Ratio & Virtual Top
        self.txt_ratio = ft.Text(value="105", size=30, color="cyan", text_align=ft.TextAlign.RIGHT)
        self.con_ratio = ft.Container(
            content=self.txt_ratio,
            on_click=lambda e: self.select_calc_input("ratio"),
            border=ft.border.all(2, "transparent"),
            border_radius=5, width=100, height=60, padding=10, bgcolor="grey900",
            alignment=ft.alignment.center_right
        )
        self.lbl_virtual_top = ft.Text("Target: 0.000", size=20, color="grey", weight=ft.FontWeight.BOLD)

        # 3. My Time
        self.txt_my = ft.Text(value="", size=30, color="white", text_align=ft.TextAlign.RIGHT)
        self.con_my = ft.Container(
            content=self.txt_my,
            on_click=lambda e: self.select_calc_input("my"),
            border=ft.border.all(2, "transparent"),
            border_radius=5, width=180, height=60, padding=10, bgcolor="grey900",
            alignment=ft.alignment.center_right
        )

        # 4. 結果 (Percentage)
        self.calc_result_text = ft.Text("0.00 %", size=60, color="green", weight=ft.FontWeight.BOLD)

        # テンキー作成
        def k(lbl, col="grey800", width=80): 
            return ui.create_calc_key(lbl, lambda e: self.on_calc_key_click(lbl), col, width)

        keypad = ft.Column([
            ft.Row([k("7"), k("8"), k("9")], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([k("4"), k("5"), k("6")], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([k("1"), k("2"), k("3")], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([k("0", width=170), k(".")], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([k("C", "red900"), k("BS", "grey700", 170)], alignment=ft.MainAxisAlignment.CENTER),
        ], spacing=10)

        # レイアウト配置
        self.page.add(
            header,
            ft.Container(height=10),
            
            # Top Time
            ft.Row([ft.Text("Top Time:", width=80), self.con_top], alignment=ft.MainAxisAlignment.CENTER),
            
            # Ratio & Virtual
            ft.Row([
                ft.Text("Ratio(%):", width=80), 
                self.con_ratio,
                ft.Container(width=10),
                self.lbl_virtual_top
            ], alignment=ft.MainAxisAlignment.CENTER),
            
            # My Time
            ft.Row([ft.Text("My Time:", width=80), self.con_my], alignment=ft.MainAxisAlignment.CENTER),
            
            ft.Divider(color="grey"),
            
            # Result
            ft.Container(
                content=ft.Column([
                    ft.Text("My Time / Top Time", color="grey", size=12),
                    self.calc_result_text
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                alignment=ft.alignment.center
            ),
            
            ft.Container(height=10),
            keypad
        )
        self.page.update()

    # --- CALCモード用ロジック ---
    def select_calc_input(self, target):
        self.calc_target = target
        # 枠線の切り替え
        self.con_top.border = ft.border.all(2, "cyan" if target == "top" else "transparent")
        self.con_ratio.border = ft.border.all(2, "cyan" if target == "ratio" else "transparent")
        self.con_my.border = ft.border.all(2, "cyan" if target == "my" else "transparent")
        self.page.update()

    def on_calc_key_click(self, val):
        if self.calc_target == "top": target_txt = self.txt_top
        elif self.calc_target == "ratio": target_txt = self.txt_ratio
        else: target_txt = self.txt_my
        
        curr = target_txt.value
        
        if val == "C":
            target_txt.value = ""
        elif val == "BS":
            if len(curr) > 0: target_txt.value = curr[:-1]
        elif val == ".":
            if "." not in curr: target_txt.value = curr + "."
        else:
            target_txt.value = curr + val
        
        self.calc_gym_ratios()
        self.page.update()

    def calc_gym_ratios(self):
        try:
            top = float(self.txt_top.value) if self.txt_top.value else 0.0
            ratio = float(self.txt_ratio.value) if self.txt_ratio.value else 0.0
            my = float(self.txt_my.value) if self.txt_my.value else 0.0

            # 1. 仮想トップタイム (Target)
            if top > 0 and ratio > 0:
                virtual = top / (ratio / 100.0)
                self.lbl_virtual_top.value = f"Target: {virtual:.3f}"
            else:
                self.lbl_virtual_top.value = "Target: 0.000"

            # 2. 結果 (My / Top)
            if top > 0 and my > 0:
                res = (my / top) * 100.0
                self.calc_result_text.value = f"{res:.2f} %"
                if res < 105.0: self.calc_result_text.color = "green"
                elif res < 110.0: self.calc_result_text.color = "yellow"
                else: self.calc_result_text.color = "red"
            else:
                self.calc_result_text.value = "0.00 %"
                self.calc_result_text.color = "grey"

        except:
            self.calc_result_text.value = "Error"

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
            if current - self.solo_start_time < config.MIN_LAP_TIME: return
            self.solo_running = False
            result = current - self.solo_start_time
            self.solo_time_display.value = f"{result:.3f}"
            self.solo_status_text.value = "FINISH"
            self.solo_time_display.color = "red"
            self.page.update()

    # --- MULTIモード用ロジック ---
    def reset_multi_history(self, e):
        """履歴ログをクリア（走行中のデータは消さない）"""
        # self.active_runners.clear() # 走行中は消さない方が安全
        self.multi_list_view.controls.clear()
        # self.history_count = 0 # 番号は継続させる
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
        log_item = ui.create_multi_log_item(runner['num'], runner['name'], time_str)
        if self.multi_list_view:
            self.multi_list_view.controls.insert(0, log_item)
            if len(self.multi_list_view.controls) > config.MAX_HISTORY_COUNT:
                self.multi_list_view.controls.pop()

        # ゴール表示維持の設定
        self.multi_hold_runner = runner
        self.multi_hold_expire_time = time.time() + config.MULTI_GOAL_DISPLAY_TIME
        
        self.update_multi_ui_state()

    def update_multi_ui_state(self):
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
                time_val = f"{display_runner.get('result_time', 0):.3f}"
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

    def update_sensor_ui(self):
        """センサー状態表示の更新"""
        now = time.time()
        
        # START
        if now - self.last_start_sensor_time < config.SENSOR_TIMEOUT:
            # Containerの中身(Text)を更新するのではなく、Containerそのものの色を変える
            # ただし、Containerのcontentにアクセスして値を変更する必要がある
            # ui.create_sensor_status で作成された Container の content は Text
            
            # 以下の実装はUIパーツの参照方法に依存するため、
            # ui_components.py の変更なしで動くようにプロパティ操作を行う
            self.start_sensor_status.bgcolor = "green"
            self.start_sensor_status.content.value = "START: OK"
            
            info = self.start_sensor_detail
            if info["rssi"] is not None:
                self.start_sensor_status.content.value += f"\n{info['rssi']}dBm"
        else:
            self.start_sensor_status.bgcolor = "grey800"
            self.start_sensor_status.content.value = "START\n--"
            
        # STOP
        if now - self.last_stop_sensor_time < config.SENSOR_TIMEOUT:
            self.stop_sensor_status.bgcolor = "green"
            self.stop_sensor_status.content.value = "GOAL: OK"
            
            info = self.stop_sensor_detail
            if info["rssi"] is not None:
                self.stop_sensor_status.content.value += f"\n{info['rssi']}dBm"
        else:
            self.stop_sensor_status.bgcolor = "grey800"
            self.stop_sensor_status.content.value = "GOAL\n--"

    def timer_loop(self):
        """画面更新ループ"""
        while self.running:
            try:
                now = time.time()
                
                # SOLOモードのタイマー計算
                if self.current_mode == "SOLO" and self.solo_running and self.solo_time_display:
                    self.solo_time_display.value = f"{now - self.solo_start_time:.3f}"
                    self.page.update()
                
                # MULTIモードのタイマー計算
                elif self.current_mode == "MULTI":
                    if self.multi_hold_runner and now > self.multi_hold_expire_time:
                        self.multi_hold_runner = None
                        self.update_multi_ui_state()

                    if not self.multi_hold_runner and self.active_runners:
                        target = self.active_runners[0]
                        current_time = now - target['start_time']
                        if self.multi_main_time:
                            self.multi_main_time.value = f"{current_time:.3f}"
                            self.multi_main_time.color = "yellow"
                            self.page.update()
                
                # センサー状態更新
                if self.page:
                    self.update_sensor_ui()
                    self.page.update()

            except Exception:
                pass
            time.sleep(0.05)

if __name__ == "__main__":
    app = GymkhanaApp()
    ft.app(target=app.main)
