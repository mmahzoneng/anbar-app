
import flet as ft
import sqlite3
import jdatetime
import datetime
import os
import shutil
import traceback
import csv
import threading
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pathlib import Path

# ==============================================
# مسیر امن دیتابیس
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
    c.execute('''CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        unit TEXT NOT NULL,
        min_quantity REAL DEFAULT 0,
        buy_price REAL DEFAULT 0,
        category TEXT DEFAULT 'ساختمانی',
        supplier_name TEXT DEFAULT '')''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT NOT NULL,
        change_amount REAL NOT NULL,
        new_quantity REAL NOT NULL,
        unit_price REAL DEFAULT 0,
        category TEXT DEFAULT 'ساختمانی',
        seller_name TEXT DEFAULT '',
        description TEXT DEFAULT '',
        entry_date TEXT DEFAULT '',
        timestamp TEXT NOT NULL,
        jalali_date TEXT NOT NULL)''')
    
    for col in ["supplier_name TEXT DEFAULT ''"]:
        try: c.execute(f"ALTER TABLE products ADD COLUMN {col}")
        except: pass
    for col in ["seller_name TEXT DEFAULT ''", "description TEXT DEFAULT ''", "entry_date TEXT DEFAULT ''"]:
        try: c.execute(f"ALTER TABLE transactions ADD COLUMN {col}")
        except: pass
    conn.commit()
    conn.close()

def log_transaction(product_name, change_amount, new_quantity, unit_price, category,
                    description="", entry_date=""):
    now_g = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    now_j = jdatetime.datetime.now().strftime("%Y-%m-%d")
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT supplier_name FROM products WHERE name = ?", (product_name,))
    row = c.fetchone()
    seller = row["supplier_name"] if row else ""
    
    c.execute('''INSERT INTO transactions 
        (product_name, change_amount, new_quantity, unit_price, category,
         seller_name, description, entry_date, timestamp, jalali_date)
        VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (product_name, change_amount, new_quantity, unit_price, category,
         seller, description, entry_date, now_g, now_j))
    conn.commit()
    conn.close()

def get_downloads_dir():
    downloads = os.getenv("FLET_APP_STORAGE_DOWNLOADS")
    if downloads:
        return downloads
    downloads = os.path.expanduser("~/Downloads")
    if os.path.exists(downloads):
        return downloads
    return os.path.expanduser("~")

def backup_db(downloads_dir=None, silent=False):
    if not os.path.exists(DB_PATH):
        return None, None
    
    backup_dir = Path(DB_PATH).parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    now = jdatetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_filename = f"backup_{now}.db"
    backup_path = backup_dir / backup_filename
    shutil.copy2(DB_PATH, backup_path)
    
    download_path = None
    if downloads_dir:
        try:
            download_dir_path = Path(downloads_dir)
            if download_dir_path.exists():
                download_path = download_dir_path / backup_filename
                shutil.copy2(DB_PATH, download_path)
        except:
            pass
    
    return str(backup_path), str(download_path) if download_path else None


def get_pdf_path(filename):
    app_storage = os.getenv("FLET_APP_STORAGE_DATA") or str(Path.home() / "warehouse_app")
    pdf_dir = Path(app_storage) / "reports"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    return str(pdf_dir / filename)

def setup_font():
    assets_dir = os.getenv("FLET_APP_ASSETS", str(Path(__file__).parent / "assets"))
    font_path = Path(assets_dir) / "B Nazanin.ttf"
    if font_path.exists():
        try:
            pdfmetrics.registerFont(TTFont("PersianFont", str(font_path)))
            return "PersianFont"
        except: pass
    return "Helvetica"

FONT_NAME = setup_font()

def export_report_to_pdf(rows, start, end, filename):
    pdf_path = get_pdf_path(filename)
    c = pdf_canvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4
    c.setFont(FONT_NAME, 10)
    c.drawString(50, height - 50, f"گزارش از {start} تا {end}")
    y = height - 80
    for r in rows:
        typ = "ورود" if r["change_amount"] > 0 else "خروج"
        seller = f" | فروشنده: {r['seller_name']}" if "seller_name" in r.keys() and r["seller_name"] else ""
        desc = f" | توضیحات: {r['description']}" if "description" in r.keys() and r["description"] else ""
        line = (f"{r['jalali_date']} | {r['product_name']} | "
                f"{typ}: {abs(r['change_amount'])} | "
                f"قیمت: {r['unit_price']:,.0f} | موجودی: {r['new_quantity']}{seller}{desc}")
        if y < 50:
            c.showPage()
            c.setFont(FONT_NAME, 10)
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

        start_date = ft.TextField(label="از تاریخ (اختیاری)", width=170)
        end_date = ft.TextField(label="تا تاریخ (اختیاری)", width=170)
        search_text = ft.TextField(label="جستجوی کالا یا فروشنده", width=200,
                                   hint_text="نام کالا یا فروشنده...")

        report_list = ft.Column(scroll="adaptive", spacing=8)
        current_report_rows = []

        # ---------- توابع کمکی ----------
        def show_message(msg):
            page.snack_bar = ft.SnackBar(ft.Text(msg))
            page.snack_bar.open = True
            page.update()

        def show_error(title, message):
            page.snack_bar = ft.SnackBar(ft.Text(f"{title}: {message}", color="red"))
            page.snack_bar.open = True
            page.update()

        def close_bottom_sheet():
            if page.bottom_sheet:
                page.close_bottom_sheet()

        # ---------- موجودی فعلی ----------
        def get_current_quantity(product_name):
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT COALESCE(SUM(change_amount), 0) as qty FROM transactions WHERE product_name = ?",
                      (product_name,))
            qty = c.fetchone()["qty"]
            conn.close()
            return qty

        # ---------- رفرش محصولات ----------
        def refresh_products():
            try:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM products ORDER BY category, name")
                rows = c.fetchall()
                conn.close()

                products_list.controls.clear()
                total_value = 0

                for row in rows:
                    quantity = get_current_quantity(row["name"])
                    total_value += quantity * row["buy_price"]


                    supplier = f" | فروشنده: {row['supplier_name']}" if row["supplier_name"] else ""
                    
                    products_list.controls.append(
                        ft.Card(
                            content=ft.Container(
                                padding=12,
                                content=ft.Row([
                                    ft.Column([
                                        ft.Text(f"{row['name']}{supplier}", weight="bold", size=16),
                                        ft.Text(f"{quantity} {row['unit']} | {row['buy_price']:,.0f} تومان", size=13),
                                        ft.Text(f"حداقل موجودی: {row['min_quantity']}", size=12),
                                        ft.Text(f"دسته: {row['category']}", size=12, color=ft.colors.GREY_700),
                                    ], expand=True),
                                    ft.Row([
                                        ft.IconButton(ft.icons.EDIT, icon_color="blue",
                                                      on_click=lambda e, r=row: edit_product_dialog(r)),
                                        ft.IconButton(ft.icons.DELETE, icon_color="red",
                                                      on_click=lambda e, n=row["name"]: delete_product(n)),
                                    ])
                                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                            )
                        )
                    )

                total_text.value = f"💰 ارزش کل انبار: {total_value:,.0f} تومان"
                page.update()
            except Exception as ex:
                show_error("خطا در بارگذاری", str(ex))

        def delete_product(name):
            try:
                conn = get_db()
                conn.execute("DELETE FROM products WHERE name=?", (name,))
                conn.commit()
                conn.close()
                refresh_products()
                show_message(f"{name} حذف شد")
            except Exception as ex:
                show_error("خطا در حذف", str(ex))

        # ---------- پشتیبان‌گیری خودکار ----------
        def auto_backup():
            today = jdatetime.datetime.now().strftime("%Y-%m-%d")
            last_backup_file = Path(DB_PATH).parent / "backups" / "last_backup_date.txt"
            
            should_backup = True
            if last_backup_file.exists():
                try:
                    with open(last_backup_file, "r") as f:
                        last_date = f.read().strip()
                        if last_date == today:
                            should_backup = False
                except:
                    pass
            
            if should_backup:
                downloads = get_downloads_dir()
                backup_db(downloads, silent=True)
                last_backup_file.parent.mkdir(parents=True, exist_ok=True)
                with open(last_backup_file, "w") as f:
                    f.write(today)

        threading.Thread(target=auto_backup, daemon=True).start()

        # ---------- افزودن کالا (BottomSheet) ----------
        def add_product_dialog():
            name = ft.TextField(label="نام کالا")
            unit = ft.TextField(label="واحد", value="عدد")
            min_qty = ft.TextField(label="حداقل موجودی", value="0")
            price = ft.TextField(label="قیمت خرید", value="0")
            cat = ft.Dropdown(label="دسته", options=[ft.dropdown.Option("ساختمانی"), ft.dropdown.Option("آشپزخانه"),
                                 ft.dropdown.Option("ابزارآلات"), ft.dropdown.Option("سایر")], value="ساختمانی", width=200)
            supplier = ft.TextField(label="نام فروشنده / تأمین‌کننده", value="")

            def save(e):
                try:
                    min_qty_val = float(min_qty.value or 0)


                    price_val = float(price.value or 0)
                except ValueError:
                    show_message("مقادیر باید عدد باشند")
                    return
                if not name.value or not name.value.strip():
                    show_message("نام کالا را وارد کنید")
                    return
                conn2 = get_db()
                c2 = conn2.cursor()
                try:
                    c2.execute("INSERT INTO products (name, unit, min_quantity, buy_price, category, supplier_name) VALUES (?,?,?,?,?,?)",
                               (name.value.strip(), unit.value.strip(), min_qty_val, price_val, cat.value, supplier.value.strip()))
                    conn2.commit()
                except sqlite3.IntegrityError:
                    show_message("کالایی با این نام قبلاً ثبت شده است")
                    conn2.close()
                    return
                conn2.close()
                close_bottom_sheet()
                refresh_products()
                page.update()

            sheet = ft.BottomSheet(
                content=ft.Container(
                    padding=20,
                    content=ft.Column([name, unit, min_qty, price, cat, supplier,
                                      ft.ElevatedButton("ذخیره", on_click=save)], tight=True, spacing=10)
                )
            )
            page.show_bottom_sheet(sheet)

        # ---------- ویرایش کالا (BottomSheet) ----------
        def edit_product_dialog(row):
            name = ft.TextField(label="نام کالا", value=str(row["name"]))
            unit = ft.TextField(label="واحد", value=str(row["unit"]))
            min_qty = ft.TextField(label="حداقل موجودی", value=str(row["min_quantity"]))
            price = ft.TextField(label="قیمت خرید", value=str(row["buy_price"]))
            cat = ft.Dropdown(label="دسته", options=[ft.dropdown.Option("ساختمانی"), ft.dropdown.Option("آشپزخانه"),
                                 ft.dropdown.Option("ابزارآلات"), ft.dropdown.Option("سایر")], value=row["category"], width=200)
            supplier = ft.TextField(label="نام فروشنده", value=str(row["supplier_name"] or ""))

            def save_edit(e):
                try:
                    min_qty_val = float(min_qty.value or 0)
                    price_val = float(price.value or 0)
                except ValueError:
                    show_message("مقادیر عددی نامعتبر است")
                    return
                if not name.value or not name.value.strip():
                    show_message("نام کالا را وارد کنید")
                    return
                conn2 = get_db()
                c2 = conn2.cursor()
                try:
                    c2.execute("UPDATE products SET name=?, unit=?, min_quantity=?, buy_price=?, category=?, supplier_name=? WHERE id=?",
                               (name.value.strip(), unit.value.strip(), min_qty_val, price_val, cat.value, supplier.value.strip(), row["id"]))
                    conn2.commit()
                except sqlite3.IntegrityError:
                    show_message("نام کالا تکراری است")
                    conn2.close()
                    return
                conn2.close()
                close_bottom_sheet()
                refresh_products()
                show_message(f"{row['name']} ویرایش شد")
                page.update()

            sheet = ft.BottomSheet(
                content=ft.Container(
                    padding=20,
                    content=ft.Column([name, unit, min_qty, price, cat, supplier,
                                      ft.ElevatedButton("ذخیره تغییرات", on_click=save_edit)], tight=True, spacing=10)
                )
            )
            page.show_bottom_sheet(sheet)

        # ---------- ورود/خروج (BottomSheet) ----------
        def update_quantity_dialog():
            try:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT name FROM products ORDER BY name")
                prods = [row["name"] for row in c.fetchall()]
                conn.close()


                if not prods:
                    show_message("ابتدا کالایی اضافه کنید")
                    return

                product_drop = ft.Dropdown(label="کالا", options=[ft.dropdown.Option(p) for p in prods], value=prods[0], width=380)
                delta_field = ft.TextField(label="تعداد (مثبت=ورود، منفی=خروج)", value="0", width=380)
                desc_field = ft.TextField(label="توضیحات (اختیاری)", value="", width=380)
                date_field = ft.TextField(label="تاریخ (YYYY-MM-DD)", value=jdatetime.datetime.now().strftime("%Y-%m-%d"), width=380)

                def save(e):
                    try:
                        delta = float(delta_field.value or 0)
                    except ValueError:
                        show_message("تعداد باید عدد باشد")
                        return
                    if not product_drop.value:
                        show_message("کالا را انتخاب کنید")
                        return
                    
                    conn2 = get_db()
                    c2 = conn2.cursor()
                    c2.execute("SELECT buy_price, category FROM products WHERE name=?", (product_drop.value,))
                    row = c2.fetchone()
                    if not row:
                        show_message("کالا پیدا نشد")
                        conn2.close()
                        return
                    
                    current_qty = get_current_quantity(product_drop.value)
                    new_qty = current_qty + delta
                    
                    if new_qty < 0:
                        show_message("موجودی کافی نیست!")
                        conn2.close()
                        return
                    
                    log_transaction(product_drop.value, delta, new_qty, row["buy_price"], row["category"],
                                    desc_field.value.strip(), date_field.value.strip())
                    conn2.close()
                    close_bottom_sheet()
                    refresh_products()
                    show_message("✅ تراکنش با موفقیت ثبت شد")

                sheet = ft.BottomSheet(
                    content=ft.Container(
                        padding=20,
                        content=ft.Column([product_drop, delta_field, desc_field, date_field,
                                          ft.ElevatedButton("ثبت", on_click=save)], tight=True, spacing=10)
                    )
                )
                page.show_bottom_sheet(sheet)
            except Exception as ex:
                show_error("خطا در فرم ورود/خروج", str(ex))

        # ---------- گزارش ----------
        def show_report(e):
            nonlocal current_report_rows
            start = start_date.value.strip()
            end = end_date.value.strip()
            keyword = search_text.value.strip()

            try:
                conn = get_db()
                c = conn.cursor()
                conditions = []
                params = []
                if start and end:
                    conditions.append("jalali_date BETWEEN ? AND ?")
                    params.extend([start, end])
                if keyword:
                    conditions.append("(product_name LIKE ? OR seller_name LIKE ?)")
                    params.extend([f"%{keyword}%", f"%{keyword}%"])
                
                query = "SELECT * FROM transactions"
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
                query += " ORDER BY timestamp DESC"
                
                c.execute(query, params)
                rows = c.fetchall()
                conn.close()

                current_report_rows = rows
                report_list.controls.clear()
                if not rows:
                    report_list.controls.append(ft.Text("هیچ تراکنشی یافت نشد", size=16))


                else:
                    for r in rows:
                        typ = "ورود" if r["change_amount"] > 0 else "خروج"
                        seller = f" | فروشنده: {r['seller_name']}" if "seller_name" in r.keys() and r["seller_name"] else ""
                        desc = f" | توضیحات: {r['description']}" if "description" in r.keys() and r["description"] else ""
                        report_list.controls.append(
                            ft.Text(f"{r['jalali_date']} | {r['product_name']} | {typ}: {abs(r['change_amount'])} | "
                                    f"قیمت: {r['unit_price']:,.0f} | موجودی: {r['new_quantity']}{seller}{desc}")
                        )
                page.update()
            except Exception as ex:
                show_error("خطا در نمایش گزارش", str(ex))

        # ---------- بازیابی از پشتیبان ----------
        def restore_backup(e):
            def on_file_selected(result: ft.FilePickerResultEvent):
                if result.files and len(result.files) > 0:
                    file_path = result.files[0].path
                    try:
                        shutil.copy2(file_path, DB_PATH)
                        show_message("✅ بازیابی با موفقیت انجام شد!\nلطفاً برنامه را ببندید و دوباره باز کنید.")
                    except Exception as ex:
                        show_error("خطا در بازیابی", str(ex))
            
            file_picker = ft.FilePicker(on_result=on_file_selected)
            page.overlay.append(file_picker)
            page.update()
            file_picker.pick_files(allowed_extensions=["db"])

        # ---------- خروجی اکسل ----------
        def export_excel_click(e):
            nonlocal current_report_rows
            if not current_report_rows:
                show_message("ابتدا گزارش را جستجو کنید")
                return
            
            downloads = get_downloads_dir()
            fname = f"report_{jdatetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.csv"
            file_path = Path(downloads) / fname
            
            try:
                with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow(["تاریخ", "کالا", "نوع", "تعداد", "قیمت واحد", "موجودی", "فروشنده", "توضیحات"])
                    for r in current_report_rows:
                        typ = "ورود" if r["change_amount"] > 0 else "خروج"
                        writer.writerow([
                            r["jalali_date"],
                            r["product_name"],
                            typ,
                            abs(r["change_amount"]),
                            r["unit_price"],
                            r["new_quantity"],
                            r["seller_name"] if "seller_name" in r.keys() else "",
                            r["description"] if "description" in r.keys() else ""
                        ])
                show_message(f"فایل اکسل ذخیره شد:\n{file_path}")
            except Exception as ex:
                show_error("خطا در ساخت اکسل", str(ex))

        def export_pdf_click(e):
            nonlocal current_report_rows
            if not current_report_rows:
                show_message("ابتدا گزارش را جستجو کنید")
                return
            start = start_date.value.strip()
            end = end_date.value.strip()
            fname = f"report_{start if start else 'all'}_{end if end else 'all'}.pdf"
            try:
                pdf_path = export_report_to_pdf(current_report_rows, start or "نامشخص", end or "نامشخص", fname)
                show_message(f"گزارش PDF ذخیره شد:\n{pdf_path}")
            except Exception as ex:
                show_error("خطا در ساخت PDF", str(ex))

        def backup_click(e):
            downloads = get_downloads_dir()


            bp_main, bp_download = backup_db(downloads)
            if bp_main:
                msg = f"بکاپ اصلی:\n{bp_main}"
                if bp_download:
                    msg += f"\n\nدانلود:\n{bp_download}"
                show_message(msg)
            else:
                show_message("خطا در تهیه پشتیبان")

        # ---------- تب‌ها ----------
        tab_products = ft.Column([
            ft.Row([ft.ElevatedButton("➕ کالای جدید", on_click=lambda e: add_product_dialog()),
                    ft.ElevatedButton("💾 پشتیبان‌گیری", on_click=lambda e: backup_click(e)),
                    ft.ElevatedButton("🔄 بازیابی", on_click=restore_backup)], wrap=True),
            ft.Divider(), total_text, products_list,
        ], scroll="adaptive", expand=True)

        tab_update = ft.Column([
            ft.ElevatedButton("📦 ورود/خروج کالا", on_click=lambda e: update_quantity_dialog())
        ], expand=True)

        tab_reports = ft.Column([
            ft.Row([start_date, end_date], wrap=True),
            ft.Row([search_text], wrap=True),
            ft.Row([ft.ElevatedButton("جستجو", on_click=show_report),
                    ft.ElevatedButton("PDF", on_click=export_pdf_click),
                    ft.ElevatedButton("Excel", on_click=export_excel_click)], wrap=True),
            ft.Divider(), report_list,
        ], scroll="adaptive", expand=True)

        content_area = ft.Container(content=tab_products, expand=True)

        btn_tab_products = ft.ElevatedButton("📋 کالاها")
        btn_tab_update = ft.ElevatedButton("🔄 ورود/خروج")
        btn_tab_reports = ft.ElevatedButton("📊 گزارشات")

        def set_active_tab(index):
            btn_tab_products.bgcolor = btn_tab_products.color = None
            btn_tab_update.bgcolor = btn_tab_update.color = None
            btn_tab_reports.bgcolor = btn_tab_reports.color = None
            if index == 0:
                content_area.content = tab_products
                btn_tab_products.bgcolor, btn_tab_products.color = "blue", "white"
            elif index == 1:
                content_area.content = tab_update
                btn_tab_update.bgcolor, btn_tab_update.color = "blue", "white"
            elif index == 2:
                content_area.content = tab_reports
                btn_tab_reports.bgcolor, btn_tab_reports.color = "blue", "white"
            page.update()

        btn_tab_products.on_click = lambda e: set_active_tab(0)
        btn_tab_update.on_click = lambda e: set_active_tab(1)
        btn_tab_reports.on_click = lambda e: set_active_tab(2)

        tab_bar = ft.Row([btn_tab_products, btn_tab_update, btn_tab_reports], wrap=True, spacing=10)
        page.add(ft.Column([tab_bar, ft.Divider(), content_area], expand=True))

        set_active_tab(0)
        refresh_products()
        page.update()

    except Exception as e:
        page.clean()
        page.add(ft.Text(f"خطای کلی برنامه:\n{str(e)}\n\n{traceback.format_exc()}", color="red", size=14))
        page.update()

if __name__ == "__main__":
    ft.app(target=main)
