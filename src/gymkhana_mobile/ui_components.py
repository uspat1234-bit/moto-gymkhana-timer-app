import flet as ft
import datetime

def create_wifi_header():
    """共通ヘッダー (Wi-Fi情報)"""
    return ft.Container(
        content=ft.Row(
            [
                ft.Text("SSID: motogym", color="white", weight=ft.FontWeight.BOLD),
                ft.Text("PASS: 12345678", color="white", weight=ft.FontWeight.BOLD),
            ], 
            alignment=ft.MainAxisAlignment.CENTER, spacing=20, wrap=True
        ),
        padding=10, bgcolor="grey900", border_radius=10
    )

def create_sensor_status(label):
    """センサー状態表示の箱を作成"""
    return ft.Container(
        content=ft.Text(f"{label}\n--", color="white", weight=ft.FontWeight.BOLD, size=12, text_align=ft.TextAlign.CENTER),
        padding=5, border_radius=5, bgcolor="grey800", width=120, alignment=ft.alignment.center
    )

def create_mode_button(icon_name, title, subtitle, color, on_click):
    """モード選択ボタンを作成"""
    return ft.Container(
        content=ft.Column([
            ft.Icon(name=icon_name, size=50, color=color),
            ft.Text(title, size=20, weight=ft.FontWeight.BOLD, color=color),
            ft.Text(subtitle, color="grey")
        ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        padding=20, bgcolor="grey900", border_radius=10, border=ft.border.all(1, color),
        on_click=on_click, ink=True
    )

def create_back_header(title, color, on_back, extra_btn=None):
    """各モードのヘッダー (戻るボタン付き)"""
    items = [
        ft.IconButton(icon="arrow_back", icon_color="white", on_click=on_back),
        ft.Text(title, size=20, weight=ft.FontWeight.BOLD, color=color),
    ]
    if extra_btn:
        items.append(extra_btn)
    else:
        items.append(ft.Container(width=40)) # レイアウト調整用ダミー
        
    return ft.Row(items, alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

def create_calc_key(label, on_click, color="grey800", width=80):
    """計算機のキーボタン"""
    return ft.Container(
        content=ft.Text(label, size=24, color="white", weight=ft.FontWeight.BOLD),
        width=width, height=60, bgcolor=color, border_radius=10,
        alignment=ft.alignment.center,
        on_click=on_click,
        ink=True
    )

def create_multi_runner_card(num, start_time_str, time_text_control, status_text_control):
    """MULTIモードの走行中カード"""
    return ft.Container(
        content=ft.Row([
            ft.Text(f"#{num}", size=16, color="grey", width=40),
            ft.Column([
                time_text_control,
                ft.Text(f"{start_time_str} Start", size=10, color="grey")
            ], expand=True),
            status_text_control
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        padding=15, bgcolor="grey900", border_radius=10, border=ft.border.all(1, "grey800")
    )

def create_multi_log_item(num, name, time_str):
    """MULTIモードの履歴ログアイテム"""
    return ft.Container(
        content=ft.Row([
            ft.Text(f"#{num}", color="grey", size=14, width=30),
            ft.Text(f"{name}", color="white", size=16, weight=ft.FontWeight.BOLD, expand=True), 
            ft.Text(time_str, color="yellow", size=24, font_family="monospace", weight=ft.FontWeight.BOLD),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        padding=10, bgcolor="grey900", border_radius=5, border=ft.border.all(1, "grey800")
    )
