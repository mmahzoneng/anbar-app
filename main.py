import flet as ft
import sqlite3
import jdatetime
import datetime
import os
from pathlib import Path

# ==============================================
# دیتابیس ساده و مطمئن
# ==============================================
def get_db_path():
    storage = os.getenv("FLET_APP_STORAGE_DATA")
    if storage:
        db_dir = Path(storage)
    else:
        db_dir = Path.home() / "warehouse_app"
    db_dir.mkdir(parents=True, exist_ok=True)
    return str(db_dir / "warehouse.db")

DB_PATH = get_db_path()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        unit TEXT NOT NULL,
        quantity REAL DEFAULT 0,
        min_quantity REAL DEFAULT 0,
        buy_price REAL DEFAULT 0,
        category TEXT DEFAULT 'ساختمانی')''')
    conn.commit()
    conn.close()

def log_transaction(product_name, change_amount, new_quantity, unit_price, category):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    jalali = jdatetime.datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO transactions 
        (product_name, change_amount, new_quantity, unit_price, category, timestamp, jalali_date)
        VALUES (?,?,?,?,?,?,?)''', 
        (product_name, change_amount, new_quantity, unit_price, category, now, jalali))
    conn.commit()
    conn.close()

# ==============================================
# برنامه اصلی
# ==============================================
def main(page: ft.Page):
    page.title = "انباردار حرفه‌ای"
    page.rtl = True
    page.theme_mode = ft.ThemeMode.LIGHT
    page.scroll = "adaptive"

    init_db()

    def show_message(msg):
        page.snack_bar = ft.SnackBar(ft.Text(msg, size=15))
        page.snack_bar.open = True
        page.update()

    def close_dialog():
        if page.dialog:
            page.dialog.open = False
            page.update()

    # ---------- افزودن کالا ----------
    def add_product(e=None):
        name = ft.TextField(label="نام کالا", width=400)
        unit = ft.TextField(label="واحد", value="عدد", width=400)
        qty = ft.TextField(label="موجودی اولیه", value="0", width=400)
        price = ft.TextField(label="قیمت خرید", value="0", width=400)

        def save(e):
            if not name.value:
                show_message("نام کالا را وارد کنید")
                return
            try:
                q = float(qty.value or 0)
                p = float(price.value or 0)
            except:
                show_message("تعداد و قیمت باید عدد باشد")
                return

            conn = get_db()
            c = conn.cursor()
            try:
                c.execute("INSERT INTO products (name, unit, quantity, buy_price) VALUES (?,?,?,?)",
                          (name.value.strip(), unit.value, q, p))
                conn.commit()
                if q != 0:
                    log_transaction(name.value.strip(), q, q, p, "ساختمانی")
                show_message("✅ کالا اضافه شد")
            except sqlite3.IntegrityError:
                show_message("این نام قبلاً ثبت شده")
            finally:
                conn.close()
            close_dialog()

        dlg = ft.AlertDialog(
            title=ft.Text("کالای جدید"),
            content=ft.Column([name, unit, qty, price], spacing=15),
            actions=[
                ft.TextButton("ذخیره", on_click=save),
                ft.TextButton("انصراف", on_click=lambda e: close_dialog())
            ]
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    # ---------- ورود/خروج ----------
    def entry_exit(e=None):
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT name FROM products ORDER BY name")
        prods = [r["name"] for r in c.fetchall()]
        conn.close()

        if not prods:
            show_message("ابتدا یک کالا اضافه کنید")
            return

        product_drop = ft.Dropdown(label="کالا", options=[ft.dropdown.Option(p) for p in prods], value=prods[0], width=400)
        delta = ft.TextField(label="تعداد (مثبت=ورود، منفی=خروج)", value="0", width=400)
        seller = ft.TextField(label="فروشنده (اختیاری)", width=400)

        def save(e):
            try:
                d = float(delta.value or 0)
            except:
                show_message("تعداد باید عدد باشد")
                return

            conn2 = get_db()
            c2 = conn2.cursor()
            c2.execute("SELECT quantity, buy_price FROM products WHERE name=?", (product_drop.value,))
            row = c2.fetchone()
            new_qty = row["quantity"] + d
            if new_qty < 0:
                show_message("موجودی کافی نیست!")
                conn2.close()
                return

            c2.execute("UPDATE products SET quantity=? WHERE name=?", (new_qty, product_drop.value))
            conn2.commit()
            conn2.close()

            log_transaction(product_drop.value, d, new_qty, row["buy_price"], "ساختمانی")
            close_dialog()
            show_message("✅ ثبت شد")

        dlg = ft.AlertDialog(
            title=ft.Text("ورود / خروج کالا"),
            content=ft.Column([product_drop, delta, seller], spacing=15),
            actions=[
                ft.TextButton("ثبت", on_click=save),
                ft.TextButton("انصراف", on_click=lambda e: close_dialog())
            ]
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    # رابط کاربری ساده
    page.add(
        ft.Column([
            ft.Text("انباردار حرفه‌ای", size=24, weight="bold"),
            ft.ElevatedButton("➕ کالای جدید", on_click=add_product, width=300, height=60),
            ft.ElevatedButton("📦 ورود / خروج کالا", on_click=entry_exit, width=300, height=60),
            ft.Text("\nدکمه‌ها را تست کنید", size=16, color=ft.colors.GREY_600)
        ], alignment=ft.MainAxisAlignment.CENTER, spacing=20)
    )

    show_message("برنامه آماده است ✓")

if __name__ == "__main__":
    ft.app(target=main)
