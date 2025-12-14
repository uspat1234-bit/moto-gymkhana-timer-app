import flet as ft
import socket
import json
import threading
import time

# 受信設定 (ESP32やPCからのブロードキャストを受け取る)
UDP_PORT = 5005
BUFFER_SIZE = 1024

# センサー接続監視のタイムアウト時間（秒）
SENSOR_TIMEOUT = 5.0

class GymkhanaApp:
    def __init__(self):
        self.running = True
        self.time_display = None
        self.status_text = None
        
        # センサー状態表示用
        self.start_sensor_status = None
        self.stop_sensor_status = None
        
        self.start_time = 0.0
        self.is_running = False
        
        # センサーの最終通信時刻
        self.last_start_sensor_time = 0.0
        self.last_stop_sensor_time = 0.0

    def main(self, page: ft.Page):
        self.page = page
        page.title = "Gymkhana Timer Mobile"
        page.vertical_alignment = ft.MainAxisAlignment.CENTER
        page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        page.bgcolor = "#1a1a1a" # ダークモード
        page.padding = 20

        # --- UIパーツ ---
        
        # 接続情報表示エリア
        wifi_info = ft.Container(
            content=ft.Column([
                ft.Text("テザリング設定情報", size=14, color="grey400", weight=ft.FontWeight.BOLD),
                ft.Text("SSID: motogym", size=18, color="white", weight=ft.FontWeight.BOLD),
                ft.Text("PASS: 12345678", size=18, color="white", weight=ft.FontWeight.BOLD),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=15,
            border=ft.border.all(1, "grey800"),
            border_radius=10,
            margin=ft.margin.only(bottom=20)
        )

        # センサー状態表示エリア
        self.start_sensor_status = ft.Container(
            content=ft.Text("START センサー", color="white", weight=ft.FontWeight.BOLD),
            padding=10,
            border_radius=5,
            bgcolor="grey800", # 初期状態: 未接続
            width=150,
            alignment=ft.alignment.center
        )

        self.stop_sensor_status = ft.Container(
            content=ft.Text("GOAL センサー", color="white", weight=ft.FontWeight.BOLD),
            padding=10,
            border_radius=5,
            bgcolor="grey800", # 初期状態: 未接続
            width=150,
            alignment=ft.alignment.center
        )

        sensor_row = ft.Row(
            [self.start_sensor_status, self.stop_sensor_status],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=20
        )

        # タイム表示（巨大文字）
        self.time_display = ft.Text(
            value="0.000",
            size=80,
            color="yellow",
            font_family="monospace", # 等幅フォント
            weight=ft.FontWeight.BOLD
        )

        # ステータス表示
        self.status_text = ft.Text(
            value="WAITING FOR SIGNAL...",
            size=20,
            color="grey400"
        )

        # ボタン（手動リセット用）
        btn_reset = ft.ElevatedButton(
            text="RESET",
            color="white",
            bgcolor="red900",
            on_click=self.reset_timer
        )

        # 画面に追加
        page.add(
            ft.Column(
                [
                    wifi_info,     # 追加: テザリング情報
                    sensor_row,    # 追加: センサー状態
                    ft.Container(height=30),
                    self.status_text,
                    self.time_display,
                    ft.Container(height=50),
                    btn_reset
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )

        # UDP受信スレッドを開始
        self.udp_thread = threading.Thread(target=self.udp_listener, daemon=True)
        self.udp_thread.start()

        # タイマー更新 & センサー監視スレッドを開始
        self.timer_thread = threading.Thread(target=self.timer_loop, daemon=True)
        self.timer_thread.start()

    def reset_timer(self, e):
        self.is_running = False
        self.start_time = 0.0
        self.time_display.value = "0.000"
        self.time_display.color = "yellow"
        self.status_text.value = "RESET"
        self.page.update()

    def udp_listener(self):
        """UDPパケットを待ち受ける"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # スマホでも 0.0.0.0 でバインドすればブロードキャストを受け取れます
            sock.bind(('0.0.0.0', UDP_PORT))
            sock.settimeout(1.0)
            print(f"UDP Listening on port {UDP_PORT}...")

            while self.running:
                try:
                    data, addr = sock.recvfrom(BUFFER_SIZE)
                    message = data.decode('utf-8').strip()
                    
                    # 受信データ判定
                    # 想定メッセージ:
                    # - 計測: "START", "STOP"
                    # - 死活監視: {"status": "alive", "sensor": "START"} (JSON形式)
                    
                    if message.startswith("{"):
                        # JSONメッセージの場合 (死活監視など)
                        try:
                            json_data = json.loads(message)
                            if json_data.get("status") == "alive":
                                sensor_type = json_data.get("sensor")
                                if sensor_type == "START":
                                    self.last_start_sensor_time = time.time()
                                elif sensor_type == "GOAL": # または STOP
                                    self.last_stop_sensor_time = time.time()
                        except:
                            pass
                    else:
                        # シンプルなコマンドの場合
                        if "START" in message:
                            self.handle_start()
                            # 信号が来たということは生きている
                            self.last_start_sensor_time = time.time()
                        elif "STOP" in message:
                            self.handle_stop()
                            # 信号が来たということは生きている
                            self.last_stop_sensor_time = time.time()
                        
                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"UDP Error: {e}")

        finally:
            sock.close()

    def handle_start(self):
        """スタート処理"""
        self.is_running = True
        self.start_time = time.time()
        self.status_text.value = "RUNNING!"
        self.time_display.color = "green"
        self.page.update()

    def handle_stop(self):
        """ゴール処理"""
        if self.is_running:
            self.is_running = False
            end_time = time.time()
            result = end_time - self.start_time
            self.time_display.value = f"{result:.3f}"
            self.status_text.value = "FINISH"
            self.time_display.color = "red"
            self.page.update()

    def update_sensor_ui(self):
        """センサーの接続状態（色）を更新"""
        current_time = time.time()
        
        # スタートセンサー
        if current_time - self.last_start_sensor_time < SENSOR_TIMEOUT:
            self.start_sensor_status.bgcolor = "green"
            self.start_sensor_status.content.value = "START: OK"
        else:
            self.start_sensor_status.bgcolor = "red900"
            self.start_sensor_status.content.value = "START: ❌"

        # ゴールセンサー
        if current_time - self.last_stop_sensor_time < SENSOR_TIMEOUT:
            self.stop_sensor_status.bgcolor = "green"
            self.stop_sensor_status.content.value = "GOAL: OK"
        else:
            self.stop_sensor_status.bgcolor = "red900"
            self.stop_sensor_status.content.value = "GOAL: ❌"

    def timer_loop(self):
        """画面のタイム更新とセンサー監視を行うループ"""
        while self.running:
            # タイム更新
            if self.is_running:
                current = time.time() - self.start_time
                self.time_display.value = f"{current:.3f}"
            
            # センサー状態更新
            self.update_sensor_ui()
            
            self.page.update()
            time.sleep(0.05) # 20fps程度で更新

if __name__ == "__main__":
    app = GymkhanaApp()
    ft.app(target=app.main)
