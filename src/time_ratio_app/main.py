import flet as ft

def main(page: ft.Page):
    page.title = "Gymkhana Ratio Calc"
    page.theme_mode = ft.ThemeMode.DARK
    page.window_width = 400
    page.window_height = 850
    page.scroll = ft.ScrollMode.AUTO

    def to_seconds(m, s):
        try:
            return float(m or 0) * 60 + float(s or 0)
        except:
            return 0

    def format_time(total_seconds):
        m = int(total_seconds // 60)
        s = total_seconds % 60
        return f"{m}:{s:06.3f}"

    def calculate(e):
        # 100%仮想タイムの取得
        top_total = to_seconds(top_min.value, top_sec.value)
        # 自分のタイムの取得
        my_total = to_seconds(my_min.value, my_sec.value)

        if top_total > 0:
            # タイム比計算
            ratio = (my_total / top_total) * 100
            result_val.value = f"{ratio:.3f} %"
            
            # 色分け判定（おまけ）
            if ratio < 105: result_val.color = ft.colors.LIGHT_BLUE_ACCENT
            elif ratio < 115: result_val.color = ft.colors.GREEN_ACCENT
            else: result_val.color = ft.colors.WHITE

            # サンプルタイム一覧の更新
            target_list.controls.clear()
            # 表示したい比率のリスト
            ratios = [105, 110, 115, 120, 125]
            for r in ratios:
                t_sec = top_total * (r / 100)
                # 120%以上は少し強調
                text_weight = ft.FontWeight.BOLD if r >= 120 else ft.FontWeight.NORMAL
                text_color = ft.colors.ORANGE_ACCENT if r >= 120 else ft.colors.WHITE70
                
                target_list.controls.append(
                    ft.Row([
                        ft.Text(f"{r}%", width=50, size=18, weight=text_weight, color=text_color),
                        ft.Text(format_time(t_sec), size=22, weight=text_weight, color=text_color)
                    ], alignment=ft.MainAxisAlignment.CENTER)
                )
        else:
            result_val.value = "Input Top Time"
        
        page.update()

    # --- UI Components ---
    top_min = ft.TextField(label="100% 仮想タイム (分)", value="1", keyboard_type=ft.KeyboardType.NUMBER, expand=1)
    top_sec = ft.TextField(label="秒.xxx", value="30.000", keyboard_type=ft.KeyboardType.NUMBER, expand=2)
    
    my_min = ft.TextField(label="自分のタイム (分)", value="1", keyboard_type=ft.KeyboardType.NUMBER, expand=1)
    my_sec = ft.TextField(label="秒.xxx", value="45.000", keyboard_type=ft.KeyboardType.NUMBER, expand=2)

    result_val = ft.Text("--- %", size=48, weight=ft.FontWeight.BOLD)
    target_list = ft.Column(spacing=10)

    # --- Layout ---
    page.add(
        ft.Container(
            content=ft.Column([
                ft.Text("🏁 基準タイム設定 (100%)", size=18, color=ft.colors.BLUE_200),
                ft.Row([top_min, top_sec]),
                
                ft.Divider(height=30, thickness=1),
                
                ft.Text("⏱️ 自分のタイム入力", size=18, color=ft.colors.GREEN_200),
                ft.Row([my_min, my_sec]),
                
                ft.ElevatedButton("計算 & サンプル表示", on_click=calculate, width=400, height=60, 
                                 style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10))),
                
                ft.Container(
                    content=ft.Column([
                        ft.Text("現在のタイム比", size=16),
                        result_val,
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=20,
                    alignment=ft.alignment.center
                ),

                ft.Text("🎯 サンプルタイム一覧", size=18, color=ft.colors.AMBER_200),
                ft.Container(
                    content=target_list,
                    bgcolor=ft.colors.WHITE10,
                    padding=20,
                    border_radius=10
                )
            ], spacing=15),
            padding=20
        )
    )

if __name__ == "__main__":
    ft.app(target=main)
