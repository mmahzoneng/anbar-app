
import flet as ft
import sqlite3
import jdatetime
import datetime
import os
import shutil
import traceback
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdf_canvas
from pathlib import Path

# ==============================================
# مسیر امن دیتابیس برای اندروید + دسکتاپ
# ==============================================
def get_db_path():
    # برای اندروید (Flet)
    app_storage = os.getenv("FLET_APP_STORAGE_DATA")
    if app_storage:
        db_dir = Path(app_storage)
    else:
        # برای دسکتاپ
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
        quantity REAL NOT NULL DEFAULT 0,
        min_quantity REAL DEFAULT 0,
        buy_price REAL DEFAULT 0,
        category TEXT DEFAULT 'ساختمانی')''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT NOT NULL,
        change_amount REAL NOT NULL,
        new_quantity REAL NOT NULL,
        unit_price REAL DEFAULT 0,
        category TEXT DEFAULT 'ساختمانی',
        timestamp TEXT NOT NULL,
        jalali_date TEXT NOT NULL)''')
    conn.commit()
    conn.close()


def log_transaction(product_name, change_amount, new_quantity, unit_price, category):
    now_g = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    now_j = jdatetime.datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO transactions 
        (product_name, change_amount, new_quantity, unit_price, category, timestamp, jalali_date)
        VALUES (?,?,?,?,?,?,?)''',
        (product_name, change_amount, new_quantity, unit_price, category, now_g, now_j))
    conn.commit()
    conn.close()


def backup_db():
    if not os.path.exists(DB_PATH):
        return
    backup_dir = Path(DB_PATH).parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    now = jdatetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    shutil.copy2(DB_PATH, backup_dir / f"backup_{now}.db")


def get_pdf_path(filename):
    """مسیر درست برای ذخیره PDF در اندروید"""
    app_storage = os.getenv("FLET_APP_STORAGE_DATA") or str(Path.home() / "warehouse_app")
    pdf_dir = Path(app_storage) / "reports"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    return str(pdf_dir / filename)


def export_report_to_pdf(rows, start, end, filename):
    pdf_path = get_pdf_path(filename)
    c = pdf_canvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4
    c.setFont("Helvetica", 10)
    c.drawString(50, height - 50, f"گزارش از {start} تا {end}")
    y = height - 80
    for r in rows:
        typ = "ورود" if r["change_amount"] > 0 else "خروج"
        line = f"{r['jalali_date']} | {r['product_name']} | {typ}: {abs(r['change_amount'])} | قیمت: {r['unit_price']:,.0f} | موجودی: {r['new_quantity']}"
        if y < 50:
            c.showPage()
            c.setFont("Helvetica", 10)
            y = height - 50
        c.drawString(50, y, line)
        y -= 20
    c.save()
    return pdf_path


# ==============================================
# تابع اصلی
# ==============================================
def main(page: ft.Page):
    page.title = "انباردار حرفه‌ای"
    page.scroll = "adaptive"
    page.rtl = True
    page.theme_mode = ft.ThemeMode.LIGHT

    try:
        init_db()

        total_text = ft.Text(size=18, weight="bold")
        products_list = ft.Column(scroll="adaptive", spacing=10)


        start_date = ft.TextField(label="از تاریخ (1403-01-01)", width=170)
        end_date = ft.TextField(label="تا تاریخ (1403-12-29)", width=170)
        report_list = ft.Column(scroll="adaptive", spacing=8)
        current_report_rows = []
        current_pdf_path = None

        def refresh_products():
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT * FROM products ORDER BY category, name")
            rows = c.fetchall()
            conn.close()

            products_list.controls.clear()
            total_value = 0

            for row in rows:
                total_value += row["quantity"] * row["buy_price"]
                alert = ft.Icon(ft.icons.WARNING, color="red") if row["quantity"] < row["min_quantity"] else ft.Container()

                products_list.controls.append(
                    ft.Card(
                        content=ft.Container(
                            content=ft.Row([
                                ft.Column([
                                    ft.Text(row["name"], weight="bold", size=16),
                                    ft.Text(f"{row['quantity']} {row['unit']} | {row['buy_price']:,.0f} تومان", size=13),
                                    ft.Text(f"دسته: {row['category']}", size=12, color=ft.colors.GREY_700)
                                ], expand=True),
                                alert,
                                ft.IconButton(ft.icons.EDIT, on_click=lambda e, n=row["name"]: edit_product_dialog(n)),
                                ft.IconButton(ft.icons.DELETE, on_click=lambda e, n=row["name"]: delete_product(n))
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            padding=12
                        )
                    )
                )

            total_text.value = f"💰 ارزش کل انبار: {total_value:,.0f} تومان"
            page.update()

        # بقیه توابع (delete, edit, add, update_quantity, show_report, export_pdf) بدون تغییر اساسی هستند
        # برای کوتاه شدن پیام، فقط تغییرات مهم رو اینجا می‌ذارم. بقیه تقریباً مثل قبله.

        def delete_product(name):
            conn = get_db()
            conn.execute("DELETE FROM products WHERE name = ?", (name,))
            conn.commit()
            conn.close()
            refresh_products()
            page.show_snack_bar(ft.SnackBar(ft.Text(f"{name} حذف شد")))

        # ... (توابع edit_product_dialog, add_product_dialog, update_quantity_dialog, show_report تقریباً مثل قبل هستن)

        def export_pdf_click(e):
            nonlocal current_report_rows
            if not current_report_rows:
                page.show_snack_bar(ft.SnackBar(ft.Text("ابتدا گزارش را جستجو کنید")))
                return
            start = start_date.value.strip()
            end = end_date.value.strip()
            fname = f"report_{start}_{end}.pdf"
            pdf_path = export_report_to_pdf(current_report_rows, start, end, fname)
            
            page.show_snack_bar(
                ft.SnackBar(ft.Text(f"گزارش با موفقیت ذخیره شد:\n{pdf_path}"), duration=4000)
            )

        # Tabs
        tab_products = ft.Column([
            ft.Row([ft.ElevatedButton("➕ کالای جدید", on_click=lambda e: add_product_dialog()),
                    ft.ElevatedButton("💾 پشتیبان‌گیری", on_click=lambda e: backup_db())]),
            ft.Divider(),
            total_text,
            products_list
        ], scroll="adaptive")

        tab_update = ft.Column([ft.ElevatedButton("📦 ورود/خروج کالا", 
                                on_click=lambda e: update_quantity_dialog())])

        tab_reports = ft.Column([
            ft.Row([start_date, end_date, 
                    ft.ElevatedButton("جستجو", on_click=show_report),
                    ft.ElevatedButton("خروجی PDF", on_click=export_pdf_click)]),
            ft.Divider(),
            report_list
        ], scroll="adaptive")


        tabs = ft.Tabs(
            selected_index=0,
            tabs=[
                ft.Tab(text="📋 کالاها", content=tab_products),
                ft.Tab(text="🔄 ورود/خروج", content=tab_update),
                ft.Tab(text="📊 گزارشات", content=tab_reports)
            ],
            expand=True
        )

        page.add(tabs)
        refresh_products()

    except Exception as e:
        page.clean()
        page.add(ft.Text(f"خطای برنامه:\n{str(e)}\n\n{traceback.format_exc()}", 
                         color="red", size=14))
        page.update()
if __name__ == "__main__":
    ft.app(target=main)



