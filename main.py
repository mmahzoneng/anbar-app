
import flet as ft
import sqlite3
import jdatetime
import datetime
import os
import shutil
import traceback
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdf_canvas

# ----------------------------------------------
# توابع دیتابیس
# ----------------------------------------------
def get_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path):
    conn = get_db(db_path)
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

def log_transaction(db_path, product_name, change_amount, new_quantity, unit_price, category):
    now_g = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    now_j = jdatetime.datetime.now().strftime("%Y-%m-%d")
    conn = get_db(db_path)
    c = conn.cursor()
    c.execute('''INSERT INTO transactions
        (product_name, change_amount, new_quantity, unit_price, category, timestamp, jalali_date)
        VALUES (?,?,?,?,?,?,?)''',
        (product_name, change_amount, new_quantity, unit_price, category, now_g, now_j))
    conn.commit()
    conn.close()

def backup_db(db_path):
    if not os.path.exists(db_path):
        return
    os.makedirs("backups", exist_ok=True)
    now = jdatetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    shutil.copy2(db_path, f"backups/backup_{now}.db")

def export_report_to_pdf(rows, start, end, filename):
    c = pdf_canvas.Canvas(filename, pagesize=A4)
    width, height = A4
    c.setFont("Helvetica", 10)
    c.drawString(50, height - 50, f"Report from {start} to {end}")
    y = height - 80
    for r in rows:
        typ = "IN" if r["change_amount"] > 0 else "OUT"
        line = f"{r['jalali_date']} | {r['product_name']} | {typ}: {abs(r['change_amount'])} | Price: {r['unit_price']:,.0f} | New Qty: {r['new_quantity']}"
        if y < 50:
            c.showPage()
            c.setFont("Helvetica", 10)
            y = height - 50
        c.drawString(50, y, line)
        y -= 20
    c.save()

# ----------------------------------------------
# تابع اصلی برنامه
# ----------------------------------------------
def main(page: ft.Page):
    page.title = "انباردار حرفه‌ای"
    page.scroll = "adaptive"
    page.theme_mode = ft.ThemeMode.LIGHT

    try:
        app_dir = page.get_application_directory()
        db_path = os.path.join(app_dir, "warehouse.db")
        init_db(db_path)

        total_text = ft.Text(size=18, weight="bold")
        products_list = ft.Column(scroll="adaptive")
        start_date = ft.TextField(label="از تاریخ (مثال 1403-01-01)", width=160)
        end_date = ft.TextField(label="تا تاریخ (مثال 1403-12-29)", width=160)
        report_list = ft.Column(scroll="adaptive")
        current_report_rows = []

        def refresh_products():
            conn = get_db(db_path)
            c = conn.cursor()
            c.execute("SELECT name, unit, quantity, min_quantity, buy_price, category FROM products ORDER BY category, name")
            rows = c.fetchall()
            conn.close()
            products_list.controls.clear()
            total_value = 0
            for row in rows:
                total_value += row["quantity"] * row["buy_price"]


                alert_icon = ft.Icon(ft.icons.WARNING, color=ft.colors.RED, size=16) if row["quantity"] < row["min_quantity"] else ft.Container()
                products_list.controls.append(
                    ft.Card(content=ft.Container(content=ft.Row([
                        ft.Column([ft.Text(row["name"], weight="bold", size=16),
                                    ft.Text(f"{row['quantity']} {row['unit']}  |  {row['buy_price']:,.0f} تومان", size=12),
                                    ft.Text(f"دسته: {row['category']}", size=10, color=ft.colors.GREY_600)], expand=True),
                        alert_icon,
                        ft.IconButton(ft.icons.EDIT, on_click=lambda e, n=row["name"]: edit_product_dialog(n)),
                        ft.IconButton(ft.icons.DELETE, on_click=lambda e, n=row["name"]: delete_product(n))],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN), padding=10)))
            total_text.value = f"💰 ارزش کل انبار: {total_value:,.0f} تومان"
            page.update()

        def delete_product(name):
            conn = get_db(db_path)
            c = conn.cursor()
            c.execute("DELETE FROM products WHERE name = ?", (name,))
            conn.commit()
            conn.close()
            refresh_products()
            page.snack_bar = ft.SnackBar(ft.Text(f"{name} حذف شد"))
            page.snack_bar.open = True
            page.update()

        def edit_product_dialog(old_name):
            conn = get_db(db_path)
            c = conn.cursor()
            c.execute("SELECT name, unit, buy_price, category FROM products WHERE name = ?", (old_name,))
            row = c.fetchone()
            conn.close()
            if not row:
                page.snack_bar = ft.SnackBar(ft.Text("کالا پیدا نشد"))
                page.snack_bar.open = True
                page.update()
                return
            name_field = ft.TextField(label="نام جدید", value=row["name"])
            unit_field = ft.TextField(label="واحد", value=row["unit"])
            price_field = ft.TextField(label="قیمت جدید", value=str(row["buy_price"]))
            category_drop = ft.Dropdown(label="دسته", options=[ft.dropdown.Option("ساختمانی"), ft.dropdown.Option("آشپزخانه")], value=row["category"])

            def save(e):
                try:
                    price_val = float(price_field.value or 0)
                except ValueError:
                    page.snack_bar = ft.SnackBar(ft.Text("قیمت باید عدد باشد"))
                    page.snack_bar.open = True
                    page.update()
                    return
                conn2 = get_db(db_path)
                c2 = conn2.cursor()
                try:
                    c2.execute("UPDATE products SET name=?, unit=?, buy_price=?, category=? WHERE name=?",
                               (name_field.value, unit_field.value, price_val, category_drop.value, old_name))
                    conn2.commit()
                except sqlite3.IntegrityError:
                    page.snack_bar = ft.SnackBar(ft.Text("نام جدید تکراری است"))
                    page.snack_bar.open = True
                finally:
                    conn2.close()
                dialog.open = False
                refresh_products()
                page.update()

            dialog = ft.AlertDialog(
                title=ft.Text("ویرایش"),
                content=ft.Column([name_field, unit_field, price_field, category_drop], tight=True),
                actions=[ft.TextButton("ذخیره", on_click=save),
                         ft.TextButton("انصراف", on_click=lambda e: setattr(dialog, "open", False))])
            page.dialog = dialog
            dialog.open = True
            page.update()

        def add_product_dialog():
            name = ft.TextField(label="نام کالا")


            unit = ft.TextField(label="واحد", value="عدد")
            qty = ft.TextField(label="تعداد اولیه", value="0")
            min_qty = ft.TextField(label="حداقل موجودی", value="0")
            price = ft.TextField(label="قیمت خرید", value="0")
            cat = ft.Dropdown(label="دسته", options=[ft.dropdown.Option("ساختمانی"), ft.dropdown.Option("آشپزخانه")], value="ساختمانی", width=200)

            def save(e):
                try:
                    qty_val = float(qty.value or 0)
                    min_qty_val = float(min_qty.value or 0)
                    price_val = float(price.value or 0)
                except ValueError:
                    page.snack_bar = ft.SnackBar(ft.Text("لطفاً تعداد و قیمت را به صورت عددی وارد کنید"))
                    page.snack_bar.open = True
                    page.update()
                    return
                conn2 = get_db(db_path)
                c2 = conn2.cursor()
                try:
                    c2.execute("INSERT INTO products (name, unit, quantity, min_quantity, buy_price, category) VALUES (?,?,?,?,?,?)",
                               (name.value, unit.value, qty_val, min_qty_val, price_val, cat.value))
                    conn2.commit()
                    if qty_val != 0:
                        log_transaction(db_path, name.value, qty_val, qty_val, price_val, cat.value)
                except sqlite3.IntegrityError:
                    page.snack_bar = ft.SnackBar(ft.Text("کالایی با این نام قبلاً ثبت شده است"))
                    page.snack_bar.open = True
                finally:
                    conn2.close()
                dialog.open = False
                refresh_products()
                page.update()

            dialog = ft.AlertDialog(
                title=ft.Text("کالای جدید"),
                content=ft.Column([name, unit, qty, min_qty, price, cat], height=350),
                actions=[ft.TextButton("ذخیره", on_click=save),
                         ft.TextButton("انصراف", on_click=lambda e: setattr(dialog, "open", False))])
            page.dialog = dialog
            dialog.open = True
            page.update()

        def update_quantity_dialog():
            conn = get_db(db_path)
            c = conn.cursor()
            c.execute("SELECT name FROM products")
            prods = [row["name"] for row in c.fetchall()]
            conn.close()
            if not prods:
                page.snack_bar = ft.SnackBar(ft.Text("ابتدا کالایی اضافه کنید"))
                page.snack_bar.open = True
                page.update()
                return
            product_drop = ft.Dropdown(label="کالا", options=[ft.dropdown.Option(p) for p in prods])
            delta_field = ft.TextField(label="تعداد (مثبت = ورود، منفی = خروج)", value="0")

            def save(e):
                try:
                    delta = float(delta_field.value or 0)
                except ValueError:
                    page.snack_bar = ft.SnackBar(ft.Text("تعداد باید عدد باشد"))
                    page.snack_bar.open = True
                    page.update()
                    return
                conn2 = get_db(db_path)
                c2 = conn2.cursor()
                c2.execute("SELECT quantity, buy_price, category FROM products WHERE name=?", (product_drop.value,))
                row = c2.fetchone()
                if not row:
                    page.snack_bar = ft.SnackBar(ft.Text("کالا پیدا نشد"))
                    page.snack_bar.open = True
                    page.update()
                    conn2.close()
                    return
                new_qty = row["quantity"] + delta
                if new_qty < 0:
                    page.snack_bar = ft.SnackBar(ft.Text("موجودی کافی نیست!"))
                    page.snack_bar.open = True
                    page.update()


                    conn2.close()
                    return
                c2.execute("UPDATE products SET quantity=? WHERE name=?", (new_qty, product_drop.value))
                conn2.commit()
                log_transaction(db_path, product_drop.value, delta, new_qty, row["buy_price"], row["category"])
                conn2.close()
                dialog.open = False
                refresh_products()
                page.update()

            dialog = ft.AlertDialog(
                title=ft.Text("ورود/خروج"),
                content=ft.Column([product_drop, delta_field]),
                actions=[ft.TextButton("ثبت", on_click=save),
                         ft.TextButton("انصراف", on_click=lambda e: setattr(dialog, "open", False))])
            page.dialog = dialog
            dialog.open = True
            page.update()

        def show_report(e):
            nonlocal current_report_rows
            start = start_date.value.strip()
            end = end_date.value.strip()
            if not start or not end:
                page.snack_bar = ft.SnackBar(ft.Text("لطفاً هر دو تاریخ را وارد کنید"))
                page.snack_bar.open = True
                page.update()
                return
            conn = get_db(db_path)
            c = conn.cursor()
            c.execute("""SELECT product_name, change_amount, new_quantity, unit_price, timestamp, jalali_date
                         FROM transactions WHERE jalali_date BETWEEN ? AND ? ORDER BY timestamp DESC""", (start, end))
            rows = c.fetchall()
            conn.close()
            current_report_rows = rows
            report_list.controls.clear()
            if not rows:
                report_list.controls.append(ft.Text("هیچ تراکنشی یافت نشد"))
            else:
                for r in rows:
                    typ = "ورود" if r["change_amount"] > 0 else "خروج"
                    report_list.controls.append(ft.Text(
                        f"{r['jalali_date']} | {r['product_name']} | {typ}: {abs(r['change_amount'])} | قیمت: {r['unit_price']:,.0f} | موجودی بعد: {r['new_quantity']}"))
            page.update()

        def export_pdf_click(e):
            if not current_report_rows:
                page.snack_bar = ft.SnackBar(ft.Text("ابتدا گزارش را جستجو کنید"))
                page.snack_bar.open = True
                page.update()
                return
            start = start_date.value.strip()
            end = end_date.value.strip()
            if not start or not end:
                page.snack_bar = ft.SnackBar(ft.Text("تاریخ را وارد کنید"))
                page.snack_bar.open = True
                page.update()
                return
            fname = f"report_{start}_{end}.pdf"
            export_report_to_pdf(current_report_rows, start, end, fname)
            page.snack_bar = ft.SnackBar(ft.Text(f"گزارش در فایل {fname} ذخیره شد"))
            page.snack_bar.open = True
            page.update()

        tab_products = ft.Column([
            ft.Row([ft.ElevatedButton("➕ کالای جدید", on_click=lambda e: add_product_dialog()),
                    ft.ElevatedButton("💾 پشتیبان", on_click=lambda e: backup_db(db_path))]),
            ft.Divider(), total_text, products_list])
        tab_update = ft.Column([ft.ElevatedButton("📦 ورود/خروج کالا", on_click=lambda e: update_quantity_dialog())])
        tab_reports = ft.Column([
            ft.Row([start_date, end_date, ft.ElevatedButton("جستجو", on_click=show_report),
                    ft.ElevatedButton("خروجی PDF", on_click=export_pdf_click)]),
            ft.Divider(), report_list])
        tabs = ft.Tabs(selected_index=0, tabs=[
            ft.Tab(text="📋 کالاها", content=tab_products),
            ft.Tab(text="🔄 ورود/خروج", content=tab_update),
            ft.Tab(text="📊 گزارشات", content=tab_reports)], expand=True)
        page.add(tabs)
        refresh_products()

    except Exception as e:
        # این بخش خطا رو مستقیم روی صفحه نشون میده
        page.clean()
        page.add(ft.Text(f"Error:\n{e}\n\n{traceback.format_exc()}", color="red", size=12))
        page.update()


if __name__ == "__main__":
    ft.app(target=main)
