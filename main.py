
import flet as ft
import sqlite3
import jdatetime
import datetime
import os
import shutil
import csv
import traceback
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdf_canvas
from pathlib import Path

# ==============================================
# لایهٔ دیتابیس (مستقل از UI)
# - موجودی از روی SUM(change_amount) محاسبه می‌شود
# - شناسهٔ محصول (product_id) مبناست (نه اسم)
# - برای سازگاری با دیتابیس‌های قدیمی: migration ساده انجام می‌شود
# ==============================================
class WarehouseDB:
    def __init__(self, db_dir=None):
        # مسیر امن: اندروید -> FLET_APP_STORAGE_DATA ، دسکتاپ -> ~/warehouse_app
        if db_dir:
            self._db_dir = Path(db_dir)
        else:
            app_storage = os.getenv("FLET_APP_STORAGE_DATA")
            self._db_dir = Path(app_storage) if app_storage else (Path.home() / "warehouse_app")

        # اطمینان از قابل نوشتن بودن مسیر
        try:
            self._db_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            downloads = os.getenv("FLET_APP_STORAGE_DOWNLOADS") or os.path.expanduser("~/Downloads")
            self._db_dir = Path(downloads) / "warehouse_app"
            self._db_dir.mkdir(parents=True, exist_ok=True)

        self._db_path = str(self._db_dir / "warehouse.db")
        self._init_db()
        self._migrate_if_needed()

    @property
    def db_path(self):
        return self._db_path

    def _get_conn(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        # نکته: foreign key ها در sqlite باید فعال شوند (اگر استفاده کنیم)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self):
        conn = self._get_conn()
        c = conn.cursor()

        # products: quantity نداریم (موجودی از تراکنش‌ها)
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                unit TEXT NOT NULL,
                min_quantity REAL DEFAULT 0,
                buy_price REAL DEFAULT 0,
                category TEXT DEFAULT 'ساختمانی',
                supplier_name TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1
            )
            """
        )

        # transactions: بر اساس product_id
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                product_name TEXT NOT NULL, -- برای خوانایی گزارش (denormalized)
                change_amount REAL NOT NULL,
                new_quantity REAL NOT NULL,
                unit_price REAL DEFAULT 0,
                category TEXT DEFAULT 'ساختمانی',
                seller_name TEXT DEFAULT '',
                description TEXT DEFAULT '',
                entry_date TEXT DEFAULT '', -- تاریخ تراکنش (دستی)
                timestamp TEXT NOT NULL,    -- زمان ثبت (میلادی)
                jalali_date TEXT NOT NULL,  -- تاریخ ثبت (جلالی)
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
            )
            """
        )

        conn.commit()
        conn.close()

    # ---------- ابزارهای migration برای دیتابیس‌های قدیمی ----------
    def _table_columns(self, conn, table):
        c = conn.cursor()
        c.execute(f"PRAGMA table_info({table})")
        return [r["name"] for r in c.fetchall()]

    def _migrate_if_needed(self):
        """
        سناریوهای رایج:
        - دیتابیس قدیمی transactions فقط product_name داشت، product_id نداشت
        - یا ستون‌های جدید مثل seller_name/description/entry_date نداشت
        این migration ساده است: ستون‌های جدید اضافه می‌کنیم و اگر product_id نبود:
        1) product_id را اضافه می‌کنیم
        2) برای هر تراکنش، با product_name، محصول را پیدا می‌کنیم و product_id را پر می‌کنیم
        """
        conn = self._get_conn()
        c = conn.cursor()


# افزودن ستون‌های احتمالی
        prod_cols = self._table_columns(conn, "products")
        tran_cols = self._table_columns(conn, "transactions")

        # products: supplier_name, is_active
        if "supplier_name" not in prod_cols:
            try:
                c.execute("ALTER TABLE products ADD COLUMN supplier_name TEXT DEFAULT ''")
            except:
                pass
        if "is_active" not in prod_cols:
            try:
                c.execute("ALTER TABLE products ADD COLUMN is_active INTEGER DEFAULT 1")
            except:
                pass

        # transactions: seller_name, description, entry_date, product_id
        if "seller_name" not in tran_cols:
            try:
                c.execute("ALTER TABLE transactions ADD COLUMN seller_name TEXT DEFAULT ''")
            except:
                pass
        if "description" not in tran_cols:
            try:
                c.execute("ALTER TABLE transactions ADD COLUMN description TEXT DEFAULT ''")
            except:
                pass
        if "entry_date" not in tran_cols:
            try:
                c.execute("ALTER TABLE transactions ADD COLUMN entry_date TEXT DEFAULT ''")
            except:
                pass

        if "product_id" not in tran_cols:
            # اضافه کردن ستون
            try:
                c.execute("ALTER TABLE transactions ADD COLUMN product_id INTEGER")
            except:
                pass

            # پر کردن product_id برای ردیف‌های قبلی بر اساس product_name
            try:
                c.execute("SELECT id, product_name FROM transactions WHERE product_id IS NULL OR product_id = ''")
                rows = c.fetchall()
                for r in rows:
                    c.execute("SELECT id FROM products WHERE name=?", (r["product_name"],))
                    pr = c.fetchone()
                    if pr:
                        c.execute("UPDATE transactions SET product_id=? WHERE id=?", (pr["id"], r["id"]))
            except:
                # اگر جدول/ستون قدیمی خیلی متفاوت باشد، migration را بی‌صدا رد می‌کنیم
                pass

        conn.commit()
        conn.close()

    # ---------- عملیات اصلی ----------
    def get_all_products(self, active_only=True):
        conn = self._get_conn()
        c = conn.cursor()
        if active_only:
            c.execute("SELECT * FROM products WHERE is_active=1 ORDER BY category, name")
        else:
            c.execute("SELECT * FROM products ORDER BY category, name")
        rows = c.fetchall()
        conn.close()
        return rows

    def get_product_by_id(self, pid):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM products WHERE id=?", (pid,))
        row = c.fetchone()
        conn.close()
        return row

    def get_product_by_name(self, name):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM products WHERE name=?", (name,))
        row = c.fetchone()
        conn.close()
        return row

    def add_product(self, name, unit, min_qty, price, category, supplier, initial_qty=0):
        """
        اتمیک: محصول + تراکنش اولیه در یک connection و یک commit
        """
        conn = self._get_conn()
        c = conn.cursor()
        try:
            c.execute(
                """
                INSERT INTO products (name, unit, min_quantity, buy_price, category, supplier_name, is_active)
                VALUES (?,?,?,?,?,?,1)
                """,
                (name, unit, min_qty, price, category, supplier),
            )
            pid = c.lastrowid

            if initial_qty and float(initial_qty) != 0:
                now_g = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                now_j = jdatetime.datetime.now().strftime("%Y-%m-%d")
                entry_date = now_j  # موجودی اولیه تاریخ همان روز


                c.execute(
                    """
                    INSERT INTO transactions
                    (product_id, product_name, change_amount, new_quantity, unit_price, category,
                     seller_name, description, entry_date, timestamp, jalali_date)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        pid,
                        name,
                        float(initial_qty),
                        float(initial_qty),
                        float(price),
                        category,
                        supplier,
                        "موجودی اولیه",
                        entry_date,
                        now_g,
                        now_j,
                    ),
                )

            conn.commit()
            return pid
        finally:
            conn.close()

    def update_product(self, pid, name, unit, min_qty, price, category, supplier):
        """
        نکته: اگر نام کالا تغییر کند، برای خوانایی گزارش، product_name در تراکنش‌ها هم آپدیت می‌شود
        (اما موجودی با product_id درست می‌ماند)
        """
        conn = self._get_conn()
        c = conn.cursor()
        try:
            c.execute("SELECT name FROM products WHERE id=?", (pid,))
            old = c.fetchone()
            old_name = old["name"] if old else None

            c.execute(
                """
                UPDATE products
                SET name=?, unit=?, min_quantity=?, buy_price=?, category=?, supplier_name=?
                WHERE id=?
                """,
                (name, unit, min_qty, price, category, supplier, pid),
            )

            if old_name and old_name != name:
                c.execute("UPDATE transactions SET product_name=? WHERE product_id=?", (name, pid))

            conn.commit()
        finally:
            conn.close()

    def deactivate_product(self, pid):
        """
        به‌جای حذف فیزیکی، غیرفعال می‌کنیم تا تراکنش‌ها سالم بمانند.
        """
        conn = self._get_conn()
        c = conn.cursor()
        try:
            c.execute("UPDATE products SET is_active=0 WHERE id=?", (pid,))
            conn.commit()
        finally:
            conn.close()

    def get_quantity_by_product_id(self, pid):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute(
            "SELECT COALESCE(SUM(change_amount), 0) as qty FROM transactions WHERE product_id=?",
            (pid,),
        )
        qty = c.fetchone()["qty"]
        conn.close()
        return float(qty or 0)

    def log_transaction(self, product_id, change, unit_price, category, seller_name="", description="", entry_date=""):
        """
        new_quantity را خود دیتابیس/منطق بر اساس موجودی فعلی محاسبه می‌کند تا اشتباه UI اثر نگذارد.
        """
        conn = self._get_conn()
        c = conn.cursor()
        try:
            # گرفتن نام محصول (برای گزارش)
            c.execute("SELECT name FROM products WHERE id=?", (product_id,))
            pr = c.fetchone()
            if not pr:
                raise ValueError("کالا یافت نشد")

            product_name = pr["name"]

            # موجودی فعلی
            c.execute(
                "SELECT COALESCE(SUM(change_amount), 0) as qty FROM transactions WHERE product_id=?",
                (product_id,),
            )
            current_qty = float(c.fetchone()["qty"] or 0)
            new_qty = current_qty + float(change)

            if new_qty < 0:
                raise ValueError("موجودی کافی نیست")

            now_g = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            now_j = jdatetime.datetime.now().strftime("%Y-%m-%d")

            # entry_date اگر خالی بود همان امروز
            entry_date = (entry_date or "").strip() or now_j


            c.execute(
                """
                INSERT INTO transactions
                (product_id, product_name, change_amount, new_quantity, unit_price, category,
                 seller_name, description, entry_date, timestamp, jalali_date)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    product_id,
                    product_name,
                    float(change),
                    float(new_qty),
                    float(unit_price),
                    category,
                    (seller_name or "").strip(),
                    (description or "").strip(),
                    entry_date,
                    now_g,
                    now_j,
                ),
            )

            conn.commit()
            return new_qty
        finally:
            conn.close()

    def search_transactions(self, start=None, end=None, keyword=None, date_field="entry_date"):
        """
        date_field:
          - 'entry_date' => تاریخ واردشده توسط کاربر (پیشنهاد)
          - 'jalali_date' => تاریخ ثبت سیستم
        """
        start = (start or "").strip()
        end = (end or "").strip()
        keyword = (keyword or "").strip()

        if date_field not in ("entry_date", "jalali_date"):
            date_field = "entry_date"

        conn = self._get_conn()
        c = conn.cursor()
        conditions = []
        params = []

        if start and end:
            conditions.append(f"{date_field} BETWEEN ? AND ?")
            params.extend([start, end])
        elif start:
            conditions.append(f"{date_field} >= ?")
            params.append(start)
        elif end:
            conditions.append(f"{date_field} <= ?")
            params.append(end)

        if keyword:
            conditions.append("(product_name LIKE ? OR seller_name LIKE ? OR description LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])

        query = "SELECT * FROM transactions"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY timestamp DESC"

        c.execute(query, params)
        rows = c.fetchall()
        conn.close()
        return rows

    def backup(self, downloads_dir=None):
        if not os.path.exists(self._db_path):
            return None, None

        backup_dir = self._db_dir / "backups"
        backup_dir.mkdir(exist_ok=True)

        now = jdatetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_filename = f"backup_{now}.db"
        backup_path = backup_dir / backup_filename
        shutil.copy2(self._db_path, backup_path)

        download_path = None
        if downloads_dir:
            try:
                d = Path(downloads_dir)
                d.mkdir(parents=True, exist_ok=True)
                download_path = d / backup_filename
                shutil.copy2(self._db_path, download_path)
            except:
                download_path = None

        return str(backup_path), str(download_path) if download_path else None

    def restore(self, file_path):
        shutil.copy2(file_path, self._db_path)

    def export_pdf(self, rows, start, end, filename):
        pdf_dir = self._db_dir / "reports"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = pdf_dir / filename

        c = pdf_canvas.Canvas(str(pdf_path), pagesize=A4)
        width, height = A4

        # نکته: Helvetica فارسی را درست نمی‌زند، فعلاً انگلیسی/عدد بهتر است
        c.setFont("Helvetica", 10)
        c.drawString(50, height - 50, f"Report: {start} to {end}")

        y = height - 80
        for r in rows:
            typ = "IN" if r["change_amount"] > 0 else "OUT"
            seller = r["seller_name"] or ""
            desc = r["description"] or ""
            line = (


                f"{r['entry_date'] or r['jalali_date']} | {r['product_name']} | {typ}: {abs(r['change_amount'])} | "
                f"Price: {r['unit_price']:,.0f} | Qty: {r['new_quantity']} | {seller} | {desc}"
            )
            if y < 50:
                c.showPage()
                c.setFont("Helvetica", 10)
                y = height - 50
            c.drawString(50, y, line[:140])  # کوتاه‌سازی ساده برای جلوگیری از بیرون‌زدن
            y -= 18

        c.save()
        return str(pdf_path)

    def export_csv(self, rows, filepath):
        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["تاریخ تراکنش", "تاریخ ثبت", "کالا", "نوع", "تعداد", "قیمت واحد", "موجودی", "فروشنده", "توضیحات"]
            )
            for r in rows:
                typ = "ورود" if r["change_amount"] > 0 else "خروج"
                writer.writerow(
                    [
                        r["entry_date"],
                        r["jalali_date"],
                        r["product_name"],
                        typ,
                        abs(r["change_amount"]),
                        r["unit_price"],
                        r["new_quantity"],
                        r["seller_name"],
                        r["description"],
                    ]
                )


# ==============================================
# UI (Flet)
# ==============================================
def main(page: ft.Page):
    page.title = "انباردار حرفه‌ای"
    page.rtl = True
    page.theme_mode = ft.ThemeMode.LIGHT

    # برای سازگاری بهتر بین نسخه‌های Flet:
    try:
        page.scroll = ft.ScrollMode.ADAPTIVE
    except Exception:
        page.scroll = "adaptive"

    db = WarehouseDB()

    total_text = ft.Text(size=18, weight="bold")
    products_list = ft.Column(spacing=10)
    try:
        products_list.scroll = ft.ScrollMode.ADAPTIVE
    except Exception:
        products_list.scroll = "adaptive"

    # گزارش
    start_date = ft.TextField(label="از تاریخ (اختیاری) 1403-01-01", width=190)
    end_date = ft.TextField(label="تا تاریخ (اختیاری) 1403-12-29", width=190)
    search_text = ft.TextField(label="جستجو (کالا/فروشنده/توضیحات)", width=260)
    date_mode = ft.Dropdown(
        label="فیلتر تاریخ بر اساس",
        width=220,
        value="entry_date",
        options=[
            ft.dropdown.Option("entry_date", "تاریخ تراکنش (ورودی کاربر)"),
            ft.dropdown.Option("jalali_date", "تاریخ ثبت سیستم"),
        ],
    )

    report_list = ft.Column(spacing=8)
    try:
        report_list.scroll = ft.ScrollMode.ADAPTIVE
    except Exception:
        report_list.scroll = "adaptive"

    current_report_rows = []

    # فرم‌های درون صفحه
    form_area = ft.Column()

    # یک FilePicker ثابت (تا هر بار overlay اضافه نشود)
    file_picker = ft.FilePicker()
    page.overlay.append(file_picker)

    def show_form(form_content):
        form_area.controls.clear()
        form_area.controls.append(form_content)
        page.update()

    def hide_form(_e=None):
        form_area.controls.clear()
        page.update()

    def show_message(msg):
        page.snack_bar = ft.SnackBar(ft.Text(str(msg)))
        page.snack_bar.open = True
        page.update()
    
        

    def safe_run(fn, context=""):
        """
        Wrapper برای اینکه روی موبایل خطاها را ببینی.
        """
        try:
            return fn()
        except Exception as ex:
            print("ERROR:", context)
            print(traceback.format_exc())
            show_message(f"خطا ({context}): {ex}")
            return None

    # ---------- محصولات ----------
    def refresh_products():
        def _do():
            rows = db.get_all_products(active_only=True)
            products_list.controls.clear()
            total_value = 0.0

            for row in rows:
                qty = db.get_quantity_by_product_id(row["id"])
                total_value += qty * float(row["buy_price"] or 0)


                supplier = f" | فروشنده: {row['supplier_name']}" if row["supplier_name"] else ""
                # هشدار کمبود
                warn = ""
                try:
                    if qty < float(row["min_quantity"] or 0):
                        warn = "  (کمتر از حداقل!)"
                except:
                    pass

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
                                            ft.Text(f"{row['name']}{supplier}", weight="bold", size=16),
                                            ft.Text(
                                                f"{qty:g} {row['unit']} | {float(row['buy_price'] or 0):,.0f} تومان{warn}",
                                                size=13,
                                            ),
                                            ft.Text(f"حداقل موجودی: {row['min_quantity']}", size=12),
                                            ft.Text(
                                                f"دسته: {row['category']}",
                                                size=12,
                                                color=ft.colors.GREY_700,
                                            ),
                                        ],
                                    ),
                                    ft.Row(
                                        controls=[
                                            ft.IconButton(
                                                ft.icons.EDIT,
                                                icon_color="blue",
                                                data=row,
                                                on_click=edit_product_form,
                                            ),
                                            ft.IconButton(
                                                ft.icons.DELETE,
                                                icon_color="red",
                                                data=row,
                                                on_click=deactivate_product_click,
                                            ),
                                        ]
                                    ),
                                ],
                            ),
                        )
                    )
                )

            total_text.value = f"💰 ارزش کل انبار: {total_value:,.0f} تومان"
            page.update()

        safe_run(_do, "refresh_products")

    def deactivate_product_click(e):
        row = e.control.data

        def _do():
            db.deactivate_product(row["id"])
            refresh_products()
            show_message(f"{row['name']} غیرفعال شد (حذف فیزیکی انجام نشد)")
            hide_form()

        safe_run(_do, "deactivate_product")

    # ---------- افزودن کالا ----------
    def add_product_form(_e):
        name = ft.TextField(label="نام کالا")
        unit = ft.TextField(label="واحد", value="عدد")
        initial_qty = ft.TextField(label="موجودی اولیه", value="0")
        min_qty = ft.TextField(label="حداقل موجودی", value="0")
        price = ft.TextField(label="قیمت خرید", value="0")
        cat = ft.Dropdown(
            label="دسته",
            options=[
                ft.dropdown.Option("ساختمانی"),
                ft.dropdown.Option("آشپزخانه"),
                ft.dropdown.Option("ابزارآلات"),
                ft.dropdown.Option("سایر"),
            ],
            value="ساختمانی",
            width=220,
        )
        supplier = ft.TextField(label="نام فروشنده / تأمین‌کننده", value="")


        def save(_e):
            def _do():
                product_name = (name.value or "").strip()
                if not product_name:
                    show_message("نام کالا را وارد کنید")
                    return

                try:
                    initial_qty_val = float(initial_qty.value or 0)
                    min_qty_val = float(min_qty.value or 0)
                    price_val = float(price.value or 0)
                except ValueError:
                    show_message("مقادیر عددی نامعتبر است")
                    return

                db.add_product(
                    product_name,
                    (unit.value or "").strip() or "عدد",
                    min_qty_val,
                    price_val,
                    cat.value,
                    (supplier.value or "").strip(),
                    initial_qty_val,
                )
                hide_form()
                refresh_products()
                show_message("✅ کالا ثبت شد")

            try:
                safe_run(_do, "add_product")
            except sqlite3.IntegrityError:
                show_message("کالایی با این نام قبلاً ثبت شده است")

        form_content = ft.Container(
            padding=10,
            border=ft.border.all(1, ft.colors.BLUE_200),
            border_radius=10,
            width=500,
            content=ft.Column(
                [
                    ft.Text("افزودن کالای جدید", size=18, weight="bold"),
                    name,
                    unit,
                    initial_qty,
                    min_qty,
                    price,
                    cat,
                    supplier,
                    ft.Row(
                        [
                            ft.ElevatedButton("ذخیره", on_click=save),
                            ft.ElevatedButton("انصراف", on_click=hide_form),
                        ],
                        wrap=True,
                    ),
                ],
                tight=True,
                spacing=7,
            ),
        )
        show_form(form_content)

    # ---------- ویرایش کالا ----------
    def edit_product_form(e):
        row = e.control.data
        name = ft.TextField(label="نام کالا", value=str(row["name"]))
        unit = ft.TextField(label="واحد", value=str(row["unit"]))
        min_qty = ft.TextField(label="حداقل موجودی", value=str(row["min_quantity"]))
        price = ft.TextField(label="قیمت خرید", value=str(row["buy_price"]))
        cat = ft.Dropdown(
            label="دسته",
            options=[
                ft.dropdown.Option("ساختمانی"),
                ft.dropdown.Option("آشپزخانه"),
                ft.dropdown.Option("ابزارآلات"),
                ft.dropdown.Option("سایر"),
            ],
            value=row["category"],
            width=220,
        )
        supplier = ft.TextField(label="نام فروشنده", value=str(row["supplier_name"] or ""))

        def save_edit(_e):
            def _do():
                new_name = (name.value or "").strip()
                if not new_name:
                    show_message("نام کالا را وارد کنید")
                    return

                try:
                    min_qty_val = float(min_qty.value or 0)
                    price_val = float(price.value or 0)
                except ValueError:
                    show_message("مقادیر عددی نامعتبر است")
                    return

                db.update_product(
                    row["id"],
                    new_name,
                    (unit.value or "").strip() or "عدد",
                    min_qty_val,
                    price_val,
                    cat.value,
                    (supplier.value or "").strip(),
                )

                hide_form()
                refresh_products()
                show_message("✅ ویرایش انجام شد")

            try:
                safe_run(_do, "edit_product")
            except sqlite3.IntegrityError:
                show_message("نام کالا تکراری است")


        form_content = ft.Container(
            padding=15,
            border=ft.border.all(1, ft.colors.BLUE_200),
            border_radius=10,
            content=ft.Column(
                [
                    ft.Text("ویرایش کالا", size=20, weight="bold"),
                    name,
                    unit,
                    min_qty,
                    price,
                    cat,
                    supplier,
                    ft.Row(
                        [
                            ft.ElevatedButton("ذخیره تغییرات", on_click=save_edit),
                            ft.ElevatedButton("انصراف", on_click=hide_form),
                        ],
                        wrap=True,
                    ),
                ],
                tight=True,
                spacing=10,
            ),
        )
        show_form(form_content)

    # ---------- ورود/خروج ----------
    def update_quantity_form(_e):
        rows = db.get_all_products(active_only=True)
        if not rows:
            show_message("ابتدا کالایی اضافه کنید")
            return

        # label->id mapping
        prod_options = []
        default_pid = rows[0]["id"]
        for r in rows:
            prod_options.append(ft.dropdown.Option(str(r["id"]), r["name"]))

        product_drop = ft.Dropdown(
            label="کالا",
            options=prod_options,
            value=str(default_pid),
            width=380,
        )

        delta_field = ft.TextField(label="تعداد (مثبت=ورود، منفی=خروج)", value="0", width=380)
        seller_field = ft.TextField(label="فروشنده (اختیاری)", value="", width=380)
        desc_field = ft.TextField(label="توضیحات (اختیاری)", value="", width=380)
        date_field = ft.TextField(
            label="تاریخ تراکنش (جلالی) YYYY-MM-DD",
            value=jdatetime.datetime.now().strftime("%Y-%m-%d"),
            width=380,
        )

        def save(_e):
            def _do():
                try:
                    pid = int(product_drop.value)
                except:
                    show_message("کالا را انتخاب کنید")
                    return

                try:
                    delta = float(delta_field.value or 0)
                except ValueError:
                    show_message("تعداد باید عدد باشد")
                    return

                if delta == 0:
                    show_message("تعداد نمی‌تواند صفر باشد")
                    return

                pr = db.get_product_by_id(pid)
                if not pr:
                    show_message("کالا یافت نشد")
                    return

                # ثبت تراکنش (new_qty داخل دیتابیس محاسبه می‌شود)
                new_qty = db.log_transaction(
                    product_id=pid,
                    change=delta,
                    unit_price=float(pr["buy_price"] or 0),
                    category=pr["category"],
                    seller_name=(seller_field.value or "").strip() or (pr["supplier_name"] or "").strip(),
                    description=(desc_field.value or "").strip(),
                    entry_date=(date_field.value or "").strip(),
                )

                hide_form()
                refresh_products()
                show_message(f"✅ تراکنش ثبت شد. موجودی جدید: {new_qty:g}")

            safe_run(_do, "update_quantity")

        form_content = ft.Container(
            padding=15,
            border=ft.border.all(1, ft.colors.BLUE_200),
            border_radius=10,
            content=ft.Column(
                [
                    ft.Text("ورود/خروج کالا", size=20, weight="bold"),
                    product_drop,
                    delta_field,
                    seller_field,
                    desc_field,
                    date_field,
                    ft.Row(
                        [
                            ft.ElevatedButton("ثبت", on_click=save),


                            ft.ElevatedButton("انصراف", on_click=hide_form),
                        ],
                        wrap=True,
                    ),
                ],
                tight=True,
                spacing=10,
            ),
        )
        show_form(form_content)

    # ---------- گزارش ----------
    def show_report(_e):
        nonlocal current_report_rows

        def _do():
            start = (start_date.value or "").strip()
            end = (end_date.value or "").strip()
            keyword = (search_text.value or "").strip()
            mode = date_mode.value or "entry_date"

            rows = db.search_transactions(start, end, keyword, date_field=mode)
            current_report_rows = rows

            report_list.controls.clear()
            if not rows:
                report_list.controls.append(ft.Text("هیچ تراکنشی یافت نشد", size=16))
            else:
                for r in rows:
                    typ = "ورود" if r["change_amount"] > 0 else "خروج"
                    seller = f" | فروشنده: {r['seller_name']}" if r["seller_name"] else ""
                    desc = f" | توضیحات: {r['description']}" if r["description"] else ""
                    d = r["entry_date"] or r["jalali_date"]
                    report_list.controls.append(
                        ft.Text(
                            f"{d} | {r['product_name']} | {typ}: {abs(r['change_amount'])} | "
                            f"قیمت: {r['unit_price']:,.0f} | موجودی: {r['new_quantity']}{seller}{desc}"
                        )
                    )
            page.update()

        safe_run(_do, "show_report")

    def export_pdf_click(_e):
        def _do():
            if not current_report_rows:
                show_message("ابتدا گزارش را جستجو کنید")
                return
            start = (start_date.value or "").strip() or "all"
            end = (end_date.value or "").strip() or "all"
            fname = f"report_{start}_{end}.pdf"
            pdf_path = db.export_pdf(current_report_rows, start, end, fname)
            show_message(f"گزارش PDF ذخیره شد:\n{pdf_path}")

        safe_run(_do, "export_pdf")

    def export_csv_click(_e):
        def _do():
            if not current_report_rows:
                show_message("ابتدا گزارش را جستجو کنید")
                return
            downloads = os.getenv("FLET_APP_STORAGE_DOWNLOADS") or os.path.expanduser("~/Downloads")
            Path(downloads).mkdir(parents=True, exist_ok=True)
            fname = f"report_{jdatetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.csv"
            file_path = Path(downloads) / fname
            db.export_csv(current_report_rows, file_path)
            show_message(f"فایل CSV ذخیره شد:\n{file_path}")

        safe_run(_do, "export_csv")

    # ---------- بکاپ و بازیابی ----------
    def backup_click(_e):
        def _do():
            downloads = os.getenv("FLET_APP_STORAGE_DOWNLOADS") or os.path.expanduser("~/Downloads")
            bp_main, bp_download = db.backup(downloads)
            if bp_main:
                msg = f"بکاپ اصلی:\n{bp_main}"
                if bp_download:
                    msg += f"\n\nکپی در دانلود:\n{bp_download}"
                show_message(msg)
            else:
                show_message("دیتابیس برای بکاپ پیدا نشد")

        safe_run(_do, "backup")

    def restore_backup(_e):
        def on_file_selected(result: ft.FilePickerResultEvent):
            if result.files and len(result.files) > 0:
                def _do():
                    db.restore(result.files[0].path)
                    show_message("✅ بازیابی انجام شد. برنامه را ببندید و دوباره باز کنید.")
                safe_run(_do, "restore_db")

        file_picker.on_result = on_file_selected
        page.update()
        file_picker.pick_files(allowed_extensions=["db"])


# ==============================================
    # تب‌ها
    # ==============================================
    tab_products = ft.Column(
        [
            ft.Row(
                [
                    ft.ElevatedButton("➕ کالای جدید", on_click=add_product_form),
                    ft.ElevatedButton("💾 پشتیبان‌گیری", on_click=backup_click),
                    ft.ElevatedButton("🔄 بازیابی", on_click=restore_backup),
                ],
                wrap=True,
            ),
            ft.Divider(),
            total_text,
            products_list,
        ],
        expand=True,
    )
    try:
        tab_products.scroll = ft.ScrollMode.ADAPTIVE
    except Exception:
        tab_products.scroll = "adaptive"

    tab_update = ft.Column(
        [
            ft.ElevatedButton("📦 ورود/خروج کالا", on_click=update_quantity_form),
        ],
        expand=True,
    )

    tab_reports = ft.Column(
        [
            ft.Row([start_date, end_date, date_mode], wrap=True),
            ft.Row([search_text], wrap=True),
            ft.Row(
                [
                    ft.ElevatedButton("جستجو", on_click=show_report),
                    ft.ElevatedButton("PDF", on_click=export_pdf_click),
                    ft.ElevatedButton("CSV", on_click=export_csv_click),
                ],
                wrap=True,
            ),
            ft.Divider(),
            report_list,
        ],
        expand=True,
    )
    try:
        tab_reports.scroll = ft.ScrollMode.ADAPTIVE
    except Exception:
        tab_reports.scroll = "adaptive"

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
        else:
            content_area.content = tab_reports
            btn_tab_reports.bgcolor, btn_tab_reports.color = "blue", "white"

        page.update()

    btn_tab_products.on_click = lambda e: set_active_tab(0)
    btn_tab_update.on_click = lambda e: set_active_tab(1)
    btn_tab_reports.on_click = lambda e: set_active_tab(2)

    tab_bar = ft.Row([btn_tab_products, btn_tab_update, btn_tab_reports], wrap=True, spacing=10)

    page.add(ft.Column([tab_bar, ft.Divider(), form_area, content_area], expand=True))

    set_active_tab(0)
    refresh_products()


if __name__ == "__main__":
    ft.app(target=main)
