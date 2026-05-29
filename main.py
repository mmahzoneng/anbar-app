
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
    app_storage = os.getenv("FLET_APP_STORAGE_DATA")
    if app_storage:
        db_dir = Path(app_storage)
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

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            unit TEXT NOT NULL,
            quantity REAL NOT NULL DEFAULT 0,
            min_quantity REAL DEFAULT 0,
            buy_price REAL DEFAULT 0,
            category TEXT DEFAULT 'ساختمانی'
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            change_amount REAL NOT NULL,
            new_quantity REAL NOT NULL,
            unit_price REAL DEFAULT 0,
            category TEXT DEFAULT 'ساختمانی',
            timestamp TEXT NOT NULL,
            jalali_date TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


def log_transaction(product_name, change_amount, new_quantity, unit_price, category):
    now_g = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    now_j = jdatetime.datetime.now().strftime("%Y-%m-%d")

    conn = get_db()
    c = conn.cursor()

    c.execute(
        """
        INSERT INTO transactions 
        (product_name, change_amount, new_quantity, unit_price, category, timestamp, jalali_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (product_name, change_amount, new_quantity, unit_price, category, now_g, now_j),
    )

    conn.commit()
    conn.close()


def backup_db():
    if not os.path.exists(DB_PATH):
        return None

    backup_dir = Path(DB_PATH).parent / "backups"
    backup_dir.mkdir(exist_ok=True)

    now = jdatetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_path = backup_dir / f"backup_{now}.db"
    shutil.copy2(DB_PATH, backup_path)

    return str(backup_path)


def get_pdf_path(filename):
    app_storage = os.getenv("FLET_APP_STORAGE_DATA")
    if app_storage:
        base_dir = Path(app_storage)
    else:
        base_dir = Path.home() / "warehouse_app"

    pdf_dir = base_dir / "reports"
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
        line = (
            f"{r['jalali_date']} | {r['product_name']} | "
            f"{typ}: {abs(r['change_amount'])} | "
            f"قیمت: {r['unit_price']:,.0f} | موجودی: {r['new_quantity']}"
        )

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

        # -------------------------
        # پیام
        # -------------------------
        def show_message(msg):
            page.snack_bar = ft.SnackBar(ft.Text(msg))
            page.snack_bar.open = True
            page.update()

        # -------------------------
        # رفرش لیست کالا
        # -------------------------
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

                products_list.controls.append(
                    ft.Card(
                        content=ft.Container(
                            padding=12,
                            content=ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Column(
                                        expand=True,
                                        controls=[
                                            ft.Text(row["name"], weight="bold", size=16),
                                            ft.Text(
                                                f"{row['quantity']} {row['unit']} | {row['buy_price']:,.0f} تومان",
                                                size=13,
                                            ),
                                            ft.Text(
                                                f"دسته: {row['category']}",
                                                size=12,
                                                color=ft.colors.GREY_700,
                                            ),
                                        ],
                                    ),
                                    ft.IconButton(
                                        ft.icons.DELETE,
                                        on_click=lambda e, n=row["name"]: delete_product(n),
                                    ),
                                ],
                            ),
                        )
                    )
                )

            total_text.value = f"💰 ارزش کل انبار: {total_value:,.0f} تومان"
            page.update()

        def delete_product(name):
            conn = get_db()
            c = conn.cursor()
            c.execute("DELETE FROM products WHERE name=?", (name,))
            conn.commit()
            conn.close()
            refresh_products()
            show_message(f"{name} حذف شد")

        # -------------------------
        # افزودن کالا
        # -------------------------
        def add_product_dialog():
            name = ft.TextField(label="نام کالا")
            unit = ft.TextField(label="واحد", value="عدد")
            qty = ft.TextField(label="تعداد اولیه", value="0")
            min_qty = ft.TextField(label="حداقل موجودی", value="0")
            price = ft.TextField(label="قیمت خرید", value="0")
            cat = ft.Dropdown(
                label="دسته",
                options=[ft.dropdown.Option("ساختمانی"), ft.dropdown.Option("آشپزخانه")],
                value="ساختمانی",
                width=200,
            )

            def save(e):
                try:
                    qty_val = float(qty.value or 0)
                    min_qty_val = float(min_qty.value or 0)
                    price_val = float(price.value or 0)
                except ValueError:
                    show_message("تعداد/قیمت باید عدد باشد")
                    return


                if not name.value or not name.value.strip():
                    show_message("نام کالا را وارد کنید")
                    return

                conn2 = get_db()
                c2 = conn2.cursor()
                try:
                    c2.execute(
                        """
                        INSERT INTO products (name, unit, quantity, min_quantity, buy_price, category)
                        VALUES (?,?,?,?,?,?)
                        """,
                        (name.value.strip(), unit.value.strip(), qty_val, min_qty_val, price_val, cat.value),
                    )
                    conn2.commit()

                    if qty_val != 0:
                        log_transaction(name.value.strip(), qty_val, qty_val, price_val, cat.value)

                except sqlite3.IntegrityError:
                    show_message("کالایی با این نام قبلاً ثبت شده است")
                    conn2.close()
                    return

                conn2.close()
                dialog.open = False
                refresh_products()
                page.update()

            dialog = ft.AlertDialog(
                title=ft.Text("کالای جدید"),
                content=ft.Column([name, unit, qty, min_qty, price, cat], height=350),
                actions=[
                    ft.TextButton("ذخیره", on_click=save),
                    ft.TextButton("انصراف", on_click=lambda e: setattr(dialog, "open", False)),
                ],
            )

            page.dialog = dialog
            dialog.open = True
            page.update()

        # -------------------------
        # ورود/خروج
        # -------------------------
        def update_quantity_dialog():
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT name FROM products ORDER BY name")
            prods = [row["name"] for row in c.fetchall()]
            conn.close()

            if not prods:
                show_message("ابتدا کالایی اضافه کنید")
                return

            product_drop = ft.Dropdown(
                label="کالا",
                options=[ft.dropdown.Option(p) for p in prods],
                value=prods[0],
            )
            delta_field = ft.TextField(label="تعداد (مثبت=ورود، منفی=خروج)", value="0")

            def save(e):
                try:
                    delta = float(delta_field.value or 0)
                except ValueError:
                    show_message("تعداد باید عدد باشد")
                    return

                conn2 = get_db()
                c2 = conn2.cursor()
                c2.execute(
                    "SELECT quantity, buy_price, category FROM products WHERE name=?",
                    (product_drop.value,),
                )
                row = c2.fetchone()

                if not row:
                    show_message("کالا پیدا نشد")
                    conn2.close()
                    return

                new_qty = row["quantity"] + delta
                if new_qty < 0:
                    show_message("موجودی کافی نیست!")
                    conn2.close()
                    return

                c2.execute(
                    "UPDATE products SET quantity=? WHERE name=?",
                    (new_qty, product_drop.value),
                )
                conn2.commit()
                conn2.close()

                log_transaction(product_drop.value, delta, new_qty, row["buy_price"], row["category"])

                dialog.open = False
                refresh_products()
                page.update()

            dialog = ft.AlertDialog(
                title=ft.Text("ورود/خروج"),
                content=ft.Column([product_drop, delta_field], tight=True),
                actions=[
                    ft.TextButton("ثبت", on_click=save),
                    ft.TextButton("انصراف", on_click=lambda e: setattr(dialog, "open", False)),
                ],
            )

            page.dialog = dialog
            dialog.open = True
            page.update()


# -------------------------
        # گزارش
        # -------------------------
        def show_report(e):
            nonlocal current_report_rows

            start = start_date.value.strip()
            end = end_date.value.strip()
            if not start or not end:
                show_message("لطفاً هر دو تاریخ را وارد کنید")
                return

            conn = get_db()
            c = conn.cursor()
            c.execute(
                """
                SELECT * FROM transactions
                WHERE jalali_date BETWEEN ? AND ?
                ORDER BY timestamp DESC
                """,
                (start, end),
            )
            rows = c.fetchall()
            conn.close()

            current_report_rows = rows
            report_list.controls.clear()

            if not rows:
                report_list.controls.append(ft.Text("هیچ تراکنشی در این بازه یافت نشد", size=16))
            else:
                for r in rows:
                    typ = "ورود" if r["change_amount"] > 0 else "خروج"
                    report_list.controls.append(
                        ft.Text(
                            f"{r['jalali_date']} | {r['product_name']} | {typ}: {abs(r['change_amount'])} | "
                            f"قیمت: {r['unit_price']:,.0f} | موجودی: {r['new_quantity']}"
                        )
                    )

            page.update()

        def export_pdf_click(e):
            nonlocal current_report_rows
            if not current_report_rows:
                show_message("ابتدا گزارش را جستجو کنید")
                return

            start = start_date.value.strip()
            end = end_date.value.strip()
            fname = f"report_{start}_{end}.pdf"
            pdf_path = export_report_to_pdf(current_report_rows, start, end, fname)
            show_message(f"گزارش ذخیره شد:\n{pdf_path}")

        def backup_click(e):
            bp = backup_db()
            if bp:
                show_message(f"بکاپ ساخته شد:\n{bp}")
            else:
                show_message("دیتابیس برای بکاپ پیدا نشد")

        # -------------------------
        # تب‌ها (سازگار با 0.21.2)
        # -------------------------
        tab_products = ft.Column(
            [
                ft.Row(
                    [
                        ft.ElevatedButton("➕ کالای جدید", on_click=lambda e: add_product_dialog()),
                        ft.ElevatedButton("💾 پشتیبان‌گیری", on_click=backup_click),
                    ],
                    wrap=True,
                ),
                ft.Divider(),
                total_text,
                products_list,
            ],
            scroll="adaptive",
            expand=True,
        )

        tab_update = ft.Column(
            [
                ft.ElevatedButton("📦 ورود/خروج کالا", on_click=lambda e: update_quantity_dialog())
            ],
            expand=True,
        )

        tab_reports = ft.Column(
            [
                ft.Row(
                    [
                        start_date,
                        end_date,
                        ft.ElevatedButton("جستجو", on_click=show_report),
                        ft.ElevatedButton("خروجی PDF", on_click=export_pdf_click),
                    ],
                    wrap=True,
                ),
                ft.Divider(),
                report_list,
            ],
            scroll="adaptive",
            expand=True,
        )

        content_area = ft.Container(content=tab_products, expand=True)

        def change_tab(e):
            if tabs.selected_index == 0:
                content_area.content = tab_products
            elif tabs.selected_index == 1:
                content_area.content = tab_update
            elif tabs.selected_index == 2:
                content_area.content = tab_reports
            page.update()


        tabs = ft.Tabs(
            selected_index=0,
            tabs=[
                ft.Tab(label="📋 کالاها"),
                ft.Tab(label="🔄 ورود/خروج"),
                ft.Tab(label="📊 گزارشات"),
            ],
            on_change=change_tab,
        )

        page.add(ft.Column([tabs, content_area], expand=True))

        refresh_products()
        page.update()

    except Exception as e:
        page.clean()
        page.add(
            ft.Text(
                f"خطای برنامه:\n{str(e)}\n\n{traceback.format_exc()}",
                color="red",
                size=14,
            )
        )
        page.update()


if __name__ == "__main__":
    ft.app(target=main)
