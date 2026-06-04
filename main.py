import flet as ft
import sqlite3
import jdatetime
import datetime
import os
import shutil
import csv
from pathlib import Path

# ==============================================
# دیتابیس
# ==============================================
def get_db_path():
    storage = os.getenv("FLET_APP_STORAGE_DATA")
    if storage:
        db_dir = Path(storage)
    else:
        db_dir = Path.home() / "warehouse_app"
    db_dir.mkdir(parents=True, exist_ok=True)
    return str(db_dir / "anbar.db")

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
        unit TEXT NOT NULL DEFAULT 'عدد',
        quantity REAL DEFAULT 0,
        min_quantity REAL DEFAULT 0,
        buy_price REAL DEFAULT 0,
        category TEXT DEFAULT 'ساختمانی',
        supplier TEXT DEFAULT '')''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT NOT NULL,
        change_amount REAL NOT NULL,
        new_quantity REAL NOT NULL,
        unit_price REAL DEFAULT 0,
        category TEXT DEFAULT 'ساختمانی',
        seller TEXT DEFAULT '',
        note TEXT DEFAULT '',
        jdate TEXT NOT NULL,
        ts TEXT NOT NULL)''')
    conn.commit()
    conn.close()

def log_transaction(product_name, change_amount, new_quantity, unit_price, category, seller="", note=""):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    jalali = jdatetime.datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO transactions 
        (product_name, change_amount, new_quantity, unit_price, category, seller, note, jdate, ts)
        VALUES (?,?,?,?,?,?,?,?,?)''',
        (product_name, change_amount, new_quantity, unit_price, category, seller, note, jalali, now))
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
        page.snack_bar = ft.SnackBar(ft.Text(msg))
        page.snack_bar.open = True
        page.update()

    def close_dialog():
        if page.dialog:
            page.dialog.open = False
            page.update()

    # ---------- افزودن کالا ----------
    def add_product(e=None):
        name = ft.TextField(label="نام کالا")
        unit = ft.TextField(label="واحد", value="عدد")
        qty = ft.TextField(label="موجودی اولیه", value="0")
        price = ft.TextField(label="قیمت خرید", value="0")
        supplier = ft.TextField(label="تأمین‌کننده")

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
                c.execute("INSERT INTO products (name, unit, quantity, buy_price, supplier) VALUES (?,?,?,?,?)",
                          (name.value.strip(), unit.value, q, p, supplier.value.strip()))
                conn.commit()
                if q != 0:
                    log_transaction(name.value.strip(), q, q, p, "ساختمانی", supplier.value.strip())
                show_message("✅ کالا اضافه شد")
            except sqlite3.IntegrityError:
                show_message("این نام قبلاً ثبت شده")
            finally:
                conn.close()
            close_dialog()

        dlg = ft.AlertDialog(
            title=ft.Text("کالای جدید"),
            content=ft.Column([name, unit, qty, price, supplier], spacing=12),
            actions=[ft.TextButton("ذخیره", on_click=save),
                     ft.TextButton("انصراف", on_click=lambda e: close_dialog())]
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

        product_drop = ft.Dropdown(label="کالا", options=[ft.dropdown.Option(p) for p in prods], value=prods[0])
        delta = ft.TextField(label="تعداد (مثبت=ورود، منفی=خروج)", value="0")
        seller = ft.TextField(label="فروشنده")

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

            log_transaction(product_drop.value, d, new_qty, row["buy_price"], "ساختمانی", seller.value)
            close_dialog()
            show_message("✅ ثبت شد")

        dlg = ft.AlertDialog(
            title=ft.Text("ورود / خروج کالا"),
            content=ft.Column([product_drop, delta, seller], spacing=15),
            actions=[ft.TextButton("ثبت", on_click=save),
                     ft.TextButton("انصراف", on_click=lambda e: close_dialog())]
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    # ---------- بکاپ دستی ----------
    def backup_click(e):
        try:
            now = jdatetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
            filename = f"anbar_backup_{now}.db"
            backup_path = Path(DB_PATH).parent / "backups" / filename
            backup_path.parent.mkdir(exist_ok=True)
            
            shutil.copy2(DB_PATH, backup_path)
            show_message(f"✅ بکاپ گرفته شد\n\n{filename}")
        except Exception as ex:
            show_message(f"خطا در بکاپ: {ex}")

    # ---------- صفحه اصلی ----------
    page.add(
        ft.Column([
            ft.Text("انباردار حرفه‌ای", size=26, weight=ft.FontWeight.BOLD),
            ft.ElevatedButton("➕ کالای جدید", on_click=add_product, height=65, width=320),
            ft.ElevatedButton("📦 ورود / خروج کالا", on_click=entry_exit, height=65, width=320),
            ft.ElevatedButton("💾 پشتیبان‌گیری", on_click=backup_click, height=50, width=320),
            ft.Text("\nنسخه ساده و پایدار", size=14, color=ft.colors.GREY_600)
        ], alignment=ft.MainAxisAlignment.CENTER, spacing=20)
    )

    show_message("برنامه آماده است")

if __name__ == "__main__":
    ft.app(target=main)
