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

class GymkhanaApp:
    def __init__(self):
        self.running = True
        
        # --- 共通状態 ---
        self.last_start_sensor_time = 0.0
        self.last_stop_sensor_time = 0.0
        
        # --- SOLOモード用状態 ---
        self.solo_running = False
        self.solo_start_time = 0.0
        
        # --- MULTIモード用状態 ---
        # 走行中のランナー情報を保持するリスト
        # [{'id': uuid, 'start_time': float, 'ui_text': ft.Text, 'ui_row': ft.Container}]
        self.active_runners = [] 
        self.history_count = 0

    def main(self, page: ft.Page):
        self.page = page
        page.title = "Gymkhana Timer Mobile"
        page.bgcolor = "#1a1a1a"
        page.padding = 10
        # スマホ対応: 画面からはみ出た場合にスクロールできるようにする
        page.scroll = ft.ScrollMode.AUTO 
        
        # --- 共通ヘッダー (接続情報) ---
        self.wifi_info = ft.Container(
            content=ft.Row(
                [
                    ft.Text("SSID: motogym", color="white", weight=ft.FontWeight.BOLD),
                    ft.Text("PASS: 12345678", color="white", weight=ft.FontWeight.BOLD),
                ], 
                alignment=ft.MainAxisAlignment.CENTER, 
                spacing=20,
                wrap=True # ★追加: 画面幅が狭いと折り返す
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
            [
                ft.Text("Sensor:", color="grey"), 
                self.start_sensor_status, 
                self.stop_sensor_status
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=10,
            wrap=True # ★追加: 画面幅が狭いと折り返す
        )

        # --- タブ 1: MULTIモード (2センサー/追走) ---
        self.multi_list_view = ft.ListView(expand=True, spacing=5, padding=10, auto_scroll=False)
        
        # MULTIモード用リセットボタン
        btn_multi_reset = ft.ElevatedButton(
            text="CLEAR HISTORY", 
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
            # ft.Text("STARTセンサーで計測開始、GOALセンサーで順次ゴールします。", color="grey", size=12, text_align=ft.TextAlign.CENTER),
            ft.Divider(color="grey"),
            self.multi_list_view,
            ft.Container(content=btn_multi_reset, alignment=ft.alignment.center, padding=10) 
        ], expand=True)

        # --- タブ 2: SOLOモード (1センサー/単独) ---
        self.solo_time_display = ft.Text(value="0.000", size=70, color="yellow", font_family="monospace", weight=ft.FontWeight.BOLD)
        self.solo_status_text = ft.Text(value="READY", size=20, color="grey400")
        
        # SOLOモードのリセットボタンは削除しました（センサー操作でリセット・再スタート）

        tab_solo_content = ft.Column([
            ft.Container(height=20),
            ft.Text("SOLO MODE (1 Sensor)", size=20, weight=ft.FontWeight.BOLD, color="orange"),
            ft.Text("スタートセンサーのみ使用 (通過でStart/Stop切替)", color="grey", size=12, text_align=ft.TextAlign.CENTER),
            ft.Container(height=40),
            self.solo_status_text,
            self.solo_time_display,
            ft.Container(height=40),
            # btn_solo_reset を削除
        ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, expand=True)

        # --- タブ構成 ---
        self.tabs = ft.Tabs(
            selected_index=0,
            animation_duration=300,
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

    # --- MULTIモード用ロジック ---
    def reset_multi_history(self, e):
        """MULTIモードの履歴をクリアする"""
        self.active_runners.clear()
        self.multi_list_view.controls.clear()
        self.history_count = 0
        self.page.update()

    def handle_multi_start(self):
        """新しい走者をリストに追加"""
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
            padding=15,
            bgcolor="grey900",
            border_radius=10,
            border=ft.border.all(1, "grey800")
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
        self.page.update()

    def handle_multi_stop(self):
        """一番長く走っている走者をゴールさせる"""
        if not self.active_runners:
            return

        target_runner = None
        for runner in self.active_runners:
            if runner['ui_status'].value == "RUNNING":
                target_runner = runner
                break
        
        if not target_runner:
            return

        end_time = time.time()
        result = end_time - target_runner['start_time']
        
        target_runner['ui_time'].value = f"{result:.3f}"
        target_runner['ui_time'].color = "red"
        target_runner['ui_status'].value = "FINISH"
        target_runner['ui_status'].color = "red"
        target_runner['ui_container'].border = ft.border.all(1, "red900")
        
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
                    current_tab = self.tabs.selected_index
                    
                    is_start = False
                    is_stop = False
                    
                    if "START" in message:
                        is_start = True
                        self.last_start_sensor_time = time.time()
                    elif "STOP" in message:
                        is_stop = True
                        self.last_stop_sensor_time = time.time()
                    
                    if current_tab == 0:
                        if is_start: self.handle_multi_start()
                        if is_stop: self.handle_multi_stop()
                    else:
                        if is_start:
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
            current_tab = self.tabs.selected_index
            now = time.time()
            
            if current_tab == 1 and self.solo_running:
                self.solo_time_display.value = f"{now - self.solo_start_time:.3f}"
            
            if current_tab == 0:
                for runner in self.active_runners:
                    if runner['ui_status'].value == "RUNNING":
                        runner['ui_time'].value = f"{now - runner['start_time']:.3f}"
            
            self.update_sensor_ui()
            self.page.update()
            time.sleep(0.05)

if __name__ == "__main__":
    app = GymkhanaApp()
    ft.app(target=app.main)
