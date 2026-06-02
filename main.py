import flet as ft
import sqlite3
import jdatetime
import datetime
import os
import shutil
import csv
import traceback
import sys
from pathlib import Path

def get_error_log_path():
    try:
        dl = os.getenv("FLET_APP_STORAGE_DOWNLOADS")
        if dl:
            return Path(dl) / "error_log.txt"
    except:
        pass
    return Path.home() / "Downloads" / "error_log.txt"

ERROR_LOG_PATH = get_error_log_path()

def log_error_to_file(msg):
    try:
        ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(ERROR_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]\n")
            f.write(msg + "\n")
            f.write("-" * 50 + "\n\n")
    except:
        pass

def global_exception_handler(exc_type, exc_value, exc_tb):
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    log_error_to_file(msg)

sys.excepthook = global_exception_handler


class DB:
    def __init__(self):
        storage = os.getenv("FLET_APP_STORAGE_DATA")
        base = Path(storage) if storage else Path.home() / ".anbar_pro"
        base.mkdir(parents=True, exist_ok=True)
        self._db_dir = base
        self.path = str(base / "anbar.db")
        self.backup_dir = base / "backups"
        self.backup_dir.mkdir(exist_ok=True)
        self._init()
        self._migrate()
        self._auto_backup()

    def _conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def _init(self):
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                unit TEXT NOT NULL DEFAULT 'عدد',
                category TEXT NOT NULL DEFAULT 'ساختمانی',
                min_qty REAL NOT NULL DEFAULT 0,
                note TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS txns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT NOT NULL,
                category TEXT DEFAULT '',
                delta REAL NOT NULL,
                balance REAL NOT NULL,
                price REAL NOT NULL DEFAULT 0,
                supplier TEXT DEFAULT '',
                note TEXT DEFAULT '',
                invoice_no TEXT DEFAULT '',
                receipt_no TEXT DEFAULT '',
                jdate TEXT NOT NULL,
                ts TEXT NOT NULL
            )""")

    def _migrate(self):
        cols_txns = ["category TEXT DEFAULT ''", "price REAL DEFAULT 0", "supplier TEXT DEFAULT ''", "invoice_no TEXT DEFAULT ''", "receipt_no TEXT DEFAULT ''"]
        cols_products = ["note TEXT DEFAULT ''", "created_at TEXT DEFAULT ''"]
        with self._conn() as c:
            for col in cols_txns:
                try: c.execute("ALTER TABLE txns ADD COLUMN " + col)
                except: pass
            for col in cols_products:
                try: c.execute("ALTER TABLE products ADD COLUMN " + col)
                except: pass

    def _auto_backup(self):
        today = jdatetime.date.today().strftime("%Y-%m-%d")
        dest = self.backup_dir / ("auto_" + today + ".db")
        if not dest.exists() and Path(self.path).exists():
            try:
                shutil.copy2(self.path, dest)
                autos = sorted(self.backup_dir.glob("auto_*.db"), reverse=True)
                for old in autos[7:]: old.unlink()
            except: pass

    def all_products(self):
        with self._conn() as c:
            return c.execute("SELECT * FROM products ORDER BY category, name").fetchall()

    def add_product(self, name, unit, category, min_qty, note, initial=0):
        now_j = jdatetime.datetime.now().strftime("%Y-%m-%d")
        with self._conn() as c:
            c.execute("INSERT INTO products (name,unit,category,min_qty,note,created_at) VALUES (?,?,?,?,?,?)", (name, unit, category, min_qty, note, now_j))
        if initial > 0:
            self.add_txn(name, category, initial, 0, "موجودی اولیه", "موجودی اولیه هنگام راه‌اندازی", now_j, "", "")

    def update_product(self, pid, name, unit, category, min_qty, note):
        with self._conn() as c:
            c.execute("UPDATE products SET name=?,unit=?,category=?,min_qty=?,note=? WHERE id=?", (name, unit, category, min_qty, note, pid))

    def delete_product(self, name):
        with self._conn() as c:
            c.execute("DELETE FROM products WHERE name=?", (name,))
            c.execute("DELETE FROM txns WHERE product_name=?", (name,))

    def qty(self, name):
        with self._conn() as c:
            return c.execute("SELECT COALESCE(SUM(delta),0) FROM txns WHERE product_name=?", (name,)).fetchone()[0]

    def add_txn(self, name, category, delta, price, supplier, note, jdate, invoice_no, receipt_no):
        with self._conn() as c:
            current = c.execute("SELECT COALESCE(SUM(delta),0) FROM txns WHERE product_name=?", (name,)).fetchone()[0]
            balance = current + delta
            if balance < 0: return False
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            jd = jdate or jdatetime.datetime.now().strftime("%Y-%m-%d")
            c.execute("INSERT INTO txns (product_name,category,delta,balance,price,supplier,note,invoice_no,receipt_no,jdate,ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (name, category, delta, balance, price, supplier, note, invoice_no, receipt_no, jd, now))
        return True

    def get_txn(self, txn_id):
        with self._conn() as c:
            return c.execute("SELECT * FROM txns WHERE id=?", (txn_id,)).fetchone()

    def update_txn(self, txn_id, is_in, qty, price, supplier, note, jdate, invoice_no, receipt_no):
        with self._conn() as c:
            row = c.execute("SELECT * FROM txns WHERE id=?", (txn_id,)).fetchone()
            if not row: return False
            old_delta = row["delta"]
            name = row["product_name"]
            current = c.execute("SELECT COALESCE(SUM(delta),0) FROM txns WHERE product_name=?", (name,)).fetchone()[0]
            new_delta = qty if is_in else -qty
            new_balance = current - old_delta + new_delta
            if new_balance < 0: return False
            c.execute("UPDATE txns SET delta=?,balance=?,price=?,supplier=?,note=?,jdate=?,invoice_no=?,receipt_no=? WHERE id=?",
                (new_delta, new_balance, price, supplier, note, jdate, invoice_no, receipt_no, txn_id))
        return True

    def delete_txn(self, txn_id):
        with self._conn() as c:
            c.execute("DELETE FROM txns WHERE id=?", (txn_id,))

    def search_txns(self, start="", end="", keyword="", supplier_kw="", txn_type="همه", category="همه", invoice_kw="", receipt_kw=""):
        conds, params = [], []
        if start and end: conds.append("jdate BETWEEN ? AND ?"); params += [start, end]
        if keyword: conds.append("product_name LIKE ?"); params.append("%" + keyword + "%")
        if supplier_kw: conds.append("supplier LIKE ?"); params.append("%" + supplier_kw + "%")
        if invoice_kw: conds.append("invoice_no LIKE ?"); params.append("%" + invoice_kw + "%")
        if receipt_kw: conds.append("receipt_no LIKE ?"); params.append("%" + receipt_kw + "%")
        if txn_type == "ورود": conds.append("delta > 0")
        elif txn_type == "خروج": conds.append("delta < 0")
        if category != "همه": conds.append("category = ?"); params.append(category)
        q = "SELECT * FROM txns" + (" WHERE " + " AND ".join(conds) if conds else "") + " ORDER BY ts DESC"
        with self._conn() as c:
            return c.execute(q, params).fetchall()

    def summary_by_product(self, start="", end="", category="همه"):
        conds, params = [], []
        if start and end: conds.append("jdate BETWEEN ? AND ?"); params += [start, end]
        if category != "همه": conds.append("category = ?"); params.append(category)
        where = " WHERE " + " AND ".join(conds) if conds else ""
        q = """SELECT product_name, category,
            SUM(CASE WHEN delta>0 THEN delta ELSE 0 END) as total_in,
            SUM(CASE WHEN delta<0 THEN ABS(delta) ELSE 0 END) as total_out,
            SUM(CASE WHEN delta>0 THEN delta*price ELSE 0 END) as total_val
            FROM txns""" + where + " GROUP BY product_name ORDER BY category, product_name"
        with self._conn() as c:
            return c.execute(q, params).fetchall()

    def summary_by_supplier(self, start="", end=""):
        conds = ["supplier != ''", "delta > 0"]
        params = []
        if start and end: conds.append("jdate BETWEEN ? AND ?"); params += [start, end]
        q = """SELECT supplier, COUNT(*) as cnt, SUM(delta) as total_qty, SUM(delta*price) as total_val
            FROM txns WHERE """ + " AND ".join(conds) + " GROUP BY supplier ORDER BY total_val DESC"
        with self._conn() as c:
            return c.execute(q, params).fetchall()

    def low_stock(self):
        return [r for r in self.all_products() if r["min_qty"] > 0 and self.qty(r["name"]) <= r["min_qty"]]

    def total_value(self):
        total = 0
        with self._conn() as c:
            rows = c.execute("SELECT product_name, SUM(delta) as qty FROM txns GROUP BY product_name").fetchall()
            for r in rows:
                if r["qty"] and r["qty"] > 0:
                    last = c.execute("SELECT price FROM txns WHERE product_name=? AND delta>0 ORDER BY ts DESC LIMIT 1", (r["product_name"],)).fetchone()
                    if last: total += r["qty"] * last["price"]
        return total

    def export_csv(self, rows, path):
        with open(str(path), "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["تاریخ", "کالا", "دسته", "نوع", "تعداد", "قیمت واحد", "ارزش", "موجودی", "فروشنده", "فاکتور", "رسید انبار", "یادداشت"])
            for r in rows:
                typ = "ورود" if r["delta"] > 0 else "خروج"
                w.writerow([r["jdate"], r["product_name"], r["category"], typ, abs(r["delta"]), r["price"], abs(r["delta"]) * r["price"], r["balance"], r["supplier"], r["invoice_no"], r["receipt_no"], r["note"]])

    def export_txt(self, rows, path):
        with open(str(path), "w", encoding="utf-8") as f:
            f.write("گزارش انبار حرفه‌ای\n")
            f.write("تاریخ چاپ: " + jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M") + "\n")
            f.write("=" * 50 + "\n\n")
            total_in  = sum(r["delta"] for r in rows if r["delta"] > 0)
            total_out = sum(abs(r["delta"]) for r in rows if r["delta"] < 0)
            total_val = sum(abs(r["delta"]) * r["price"] for r in rows if r["delta"] > 0)
            f.write("خلاصه:\n  جمع ورود: " + str(total_in) + "\n  جمع خروج: " + str(total_out) + "\n")
            f.write("  ارزش ورودی: " + "{:,.0f}".format(total_val) + " تومان\n  تعداد تراکنش: " + str(len(rows)) + "\n")
            f.write("\n" + "=" * 50 + "\n\n")
            for r in rows:
                typ = "ورود" if r["delta"] > 0 else "خروج"
                f.write(r["jdate"] + " | " + r["product_name"] + " | " + typ + ": " + str(abs(r["delta"])) + "\n")
                if r["delta"] > 0:
                    if r["supplier"]: f.write("  فروشنده: " + r["supplier"] + "\n")
                    if r["invoice_no"]: f.write("  فاکتور: " + r["invoice_no"] + "\n")
                    if r["receipt_no"]: f.write("  رسید: " + r["receipt_no"] + "\n")
                    f.write("  ارزش: " + "{:,.0f}".format(abs(r["delta"]) * r["price"]) + " تومان\n")
                if r["note"]: f.write("  یادداشت: " + r["note"] + "\n")
                f.write("\n")

    def manual_backup(self):
        dl = os.getenv("FLET_APP_STORAGE_DOWNLOADS") or os.path.expanduser("~/Downloads")
        dl = Path(dl)
        dl.mkdir(parents=True, exist_ok=True)
        name = "anbar_backup_" + jdatetime.datetime.now().strftime("%Y-%m-%d_%H-%M") + ".db"
        shutil.copy2(self.path, dl / name)
        shutil.copy2(self.path, self.backup_dir / name)
        return str(dl / name)

    def list_backups(self):
        return [str(f) for f in sorted(self.backup_dir.glob("*.db"), reverse=True)]

    def restore(self, path):
        shutil.copy2(path, self.path)


BG      = "#F4F6F9"
C_WHITE = "#FFFFFF"
C_DARK  = "#1C2B3A"
C_GRAY  = "#7A8999"
C_LIGHT = "#E8ECF0"
C_BLUE  = "#2563EB"
C_BLUE2 = "#1D4ED8"
C_GREEN = "#16A34A"
C_RED   = "#DC2626"
C_ORANGE= "#EA580C"
C_YELLOW= "#D97706"

CATS = ["ساختمانی", "آشپزخانه"]


def main(page: ft.Page):
    try:
        page.title = "انبار حرفه‌ای"
        page.rtl = True
        page.theme_mode = ft.ThemeMode.LIGHT
        page.bgcolor = BG
        page.padding = 0
        page.scroll = "adaptive"

        db = DB()
        active_tab = [0]
        report_rows = []
        body = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=0)

        def snack(msg, color=C_BLUE):
            page.snack_bar = ft.SnackBar(ft.Text(msg, color="white"), bgcolor=color, duration=3000)
            page.snack_bar.open = True
            page.update()

        def set_body(controls):
            body.controls = controls
            body.update()
            page.update()

        def page_header(title, back_fn=None):
            controls = []
            if back_fn:
                controls.append(ft.IconButton(ft.Icons.ARROW_BACK_IOS, icon_color=C_BLUE, icon_size=20, on_click=lambda e: back_fn()))
            controls.append(ft.Text(title, size=20, weight=ft.FontWeight.BOLD, color=C_DARK, expand=True))
            return ft.Container(bgcolor=C_WHITE, padding=12, content=ft.Row(controls=controls, spacing=4))

        def render_products():
            rows = db.all_products()
            low_count = len(db.low_stock())
            total_val = db.total_value()

            controls = [
                ft.Container(bgcolor=C_BLUE, padding=20, content=ft.Column(spacing=10, controls=[
                    ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                        ft.Column(spacing=4, controls=[
                            ft.Text("انبار حرفه‌ای", size=22, weight=ft.FontWeight.BOLD, color="white"),
                            ft.Text(jdatetime.date.today().strftime("%Y/%m/%d"), size=13, color="#BFDBFE"),
                        ]),
                        ft.Container(border_radius=12, bgcolor=C_BLUE2, padding=12,
                            content=ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END, controls=[
                                ft.Text("ارزش کل انبار", size=11, color="white"),
                                ft.Text("{:,.0f} ت".format(total_val), size=15, weight=ft.FontWeight.BOLD, color="white"),
                            ])),
                    ]),
                    ft.Row(spacing=10, controls=[
                        ft.Container(expand=True, border_radius=10, bgcolor=C_BLUE2, padding=12,
                            content=ft.Column(spacing=4, controls=[
                                ft.Icon(ft.Icons.INVENTORY_2, color="white", size=20),
                                ft.Text(str(len(rows)), size=20, weight=ft.FontWeight.BOLD, color="white"),
                                ft.Text("قلم کالا", size=11, color="#BFDBFE"),
                            ])),
                        ft.Container(expand=True, border_radius=10, bgcolor=C_BLUE2, padding=12,
                            content=ft.Column(spacing=4, controls=[
                                ft.Icon(ft.Icons.WARNING_AMBER, color="#FCD34D", size=20),
                                ft.Text(str(low_count), size=20, weight=ft.FontWeight.BOLD, color="white"),
                                ft.Text("کم‌موجود", size=11, color="#BFDBFE"),
                            ])),
                    ]),
                ])),
                ft.Container(padding=12, content=ft.Row(spacing=10, controls=[
                    ft.ElevatedButton("➕ کالای جدید", on_click=lambda e: show_product_form(), bgcolor=C_BLUE, color="white", expand=True, height=44),
                    ft.ElevatedButton("💾", on_click=lambda e: show_backup(), bgcolor=C_WHITE, color=C_BLUE, height=44, width=54),
                ])),
            ]

            if not rows:
                controls.append(ft.Container(padding=60, content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12,
                    controls=[ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, size=70, color=C_LIGHT), ft.Text("انبار خالی است", size=18, color=C_GRAY)],
                )))
            else:
                if low_count > 0:
                    controls.append(ft.Container(margin=10, border_radius=10, bgcolor="#FEF2F2", padding=10,
                        content=ft.Row(spacing=8, controls=[
                            ft.Icon(ft.Icons.WARNING_AMBER, color=C_RED, size=18),
                            ft.Text(str(low_count) + " کالا نیاز به تأمین دارد", size=13, color=C_RED, weight=ft.FontWeight.BOLD),
                        ])))
                for r in rows:
                    qty = db.qty(r["name"])
                    low = r["min_qty"] > 0 and qty <= r["min_qty"]
                    color = C_RED if low else (C_ORANGE if qty == 0 else C_GREEN)
                    def on_edit(e, row=r): show_product_form(row)
                    def on_del(e, n=r["name"]):
                        db.delete_product(n)
                        snack(n + " حذف شد", C_RED)
                        render_products()
                    controls.append(ft.Container(margin=10, border_radius=14, bgcolor=C_WHITE, padding=14,
                        content=ft.Column(spacing=10, controls=[
                            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                ft.Column(spacing=3, expand=True, controls=[
                                    ft.Text(r["name"], size=15, weight=ft.FontWeight.BOLD, color=C_DARK),
                                    ft.Row(spacing=6, controls=[ft.Container(border_radius=20, bgcolor=C_LIGHT, padding=6, content=ft.Text(r["category"], size=11, color=C_GRAY))]),
                                ]),
                                ft.Row(spacing=0, controls=[
                                    ft.IconButton(ft.Icons.EDIT_OUTLINED, icon_color=C_BLUE, icon_size=18, on_click=on_edit),
                                    ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_color=C_RED, icon_size=18, on_click=on_del),
                                ]),
                            ]),
                            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                ft.Container(border_radius=10, bgcolor=color + "15", padding=10,
                                    content=ft.Column(spacing=2, controls=[
                                        ft.Text("موجودی", size=10, color=C_GRAY),
                                        ft.Text(str(qty) + " " + r["unit"], size=16, weight=ft.FontWeight.BOLD, color=color),
                                    ])),
                                ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                                    ft.Text("حداقل موجودی", size=10, color=C_GRAY),
                                    ft.Text(str(r["min_qty"]) + " " + r["unit"], size=13, color=C_DARK),
                                ]),
                                ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END, controls=[
                                    ft.Text("واحد", size=10, color=C_GRAY),
                                    ft.Text(r["unit"], size=13, color=C_DARK),
                                ]),
                            ]),
                            ft.Container(visible=low, border_radius=8, bgcolor="#FEF2F2", padding=8,
                                content=ft.Row(spacing=6, controls=[
                                    ft.Icon(ft.Icons.WARNING_AMBER, color=C_RED, size=16),
                                    ft.Text("موجودی زیر حداقل!", size=12, color=C_RED),
                                ])),
                        ])))
            set_body(controls)

        def show_product_form(row=None):
            is_edit = row is not None
            f_name = ft.TextField(label="نام کالا", value=row["name"] if is_edit else "", border_color=C_BLUE)
            f_unit = ft.TextField(label="واحد (مثال: کیسه، عدد، متر)", value=row["unit"] if is_edit else "عدد", border_color=C_BLUE)
            f_cat  = ft.Dropdown(label="دسته‌بندی", options=[ft.dropdown.Option(c) for c in CATS], value=row["category"] if is_edit else "ساختمانی")
            f_min  = ft.TextField(label="حداقل موجودی هشدار", value=str(row["min_qty"]) if is_edit else "0", keyboard_type=ft.KeyboardType.NUMBER, border_color=C_BLUE)
            f_note    = ft.TextField(label="توضیحات (اختیاری)", value=row["note"] if is_edit else "", border_color=C_BLUE)
            f_initial = ft.TextField(label="موجودی اولیه (الان در انبار دارید)", value="0", keyboard_type=ft.KeyboardType.NUMBER, border_color=C_BLUE, visible=not is_edit)

            def save(e):
                name = f_name.value.strip()
                if not name:
                    snack("نام کالا را وارد کنید", C_RED)
                    return
                try:
                    min_qty  = float(f_min.value or 0)
                    initial  = float(f_initial.value or 0) if not is_edit else 0
                except ValueError:
                    snack("مقادیر عددی نادرست است", C_RED)
                    return
                try:
                    if is_edit:
                        db.update_product(row["id"], name, f_unit.value.strip(), f_cat.value, min_qty, f_note.value.strip())
                        snack(name + " ویرایش شد", C_GREEN)
                    else:
                        db.add_product(name, f_unit.value.strip(), f_cat.value, min_qty, f_note.value.strip(), initial)
                        snack(name + " اضافه شد", C_GREEN)
                except sqlite3.IntegrityError:
                    snack("این نام قبلاً ثبت شده است", C_RED)
                    return
                render_products()

            set_body([
                page_header("ویرایش کالا" if is_edit else "کالای جدید", render_products),
                ft.Container(padding=16, content=ft.Column(spacing=12, controls=[
                    f_name, f_unit, f_cat, f_min, f_note, f_initial,
                    ft.Container(height=8),
                    ft.ElevatedButton("ذخیره" if is_edit else "افزودن کالا", on_click=save, bgcolor=C_BLUE, color="white", height=48, expand=True),
                ])),
            ])

        def render_txn():
            products = db.all_products()
            if not products:
                set_body([page_header("ورود / خروج"), ft.Container(padding=40, content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, size=60, color=C_GRAY), ft.Text("ابتدا کالا اضافه کنید", size=16, color=C_GRAY)],
                ))])
                return

            names = [r["name"] for r in products]
            prod_map = {r["name"]: r for r in products}

            f_product  = ft.Dropdown(label="کالا", options=[ft.dropdown.Option(n) for n in names], value=names[0])
            f_type     = ft.Dropdown(label="نوع عملیات", options=[ft.dropdown.Option("ورود"), ft.dropdown.Option("خروج")], value="ورود")
            f_qty      = ft.TextField(label="تعداد", value="1", keyboard_type=ft.KeyboardType.NUMBER, border_color=C_BLUE)
            f_price    = ft.TextField(label="قیمت واحد (تومان)", keyboard_type=ft.KeyboardType.NUMBER, border_color=C_BLUE)
            f_supplier = ft.TextField(label="نام فروشنده / مصالح‌فروش", border_color=C_BLUE)
            f_invoice  = ft.TextField(label="شماره فاکتور", border_color=C_BLUE)
            f_receipt  = ft.TextField(label="شماره رسید انبار (اختیاری)", border_color=C_BLUE)
            f_note     = ft.TextField(label="یادداشت", border_color=C_BLUE)
            f_date     = ft.TextField(label="تاریخ (شمسی)", value=jdatetime.datetime.now().strftime("%Y-%m-%d"), border_color=C_BLUE)

            qty_box = ft.Container(border_radius=10, bgcolor=C_BLUE + "15", padding=12,
                content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                    ft.Text("موجودی فعلی:", size=14, color=C_GRAY),
                    ft.Text(str(db.qty(names[0])), size=18, weight=ft.FontWeight.BOLD, color=C_BLUE),
                ]))

            in_fields = ft.Column(spacing=12, visible=True, controls=[f_price, f_supplier, f_invoice, f_receipt])

            def on_product_change(e):
                qty_box.content.controls[1].value = str(db.qty(f_product.value))
                page.update()

            def on_type_change(e):
                in_fields.visible = (f_type.value == "ورود")
                in_fields.update()
                page.update()

            f_product.on_change = on_product_change
            f_type.on_change = on_type_change

            def save(e):
                try:
                    qty = float(f_qty.value or 0)
                except ValueError:
                    snack("تعداد نادرست است", C_RED)
                    return
                if qty <= 0:
                    snack("تعداد باید بزرگتر از صفر باشد", C_YELLOW)
                    return
                is_in = f_type.value == "ورود"
                if is_in:
                    try: price = float(f_price.value or 0)
                    except ValueError:
                        snack("قیمت نادرست است", C_RED)
                        return
                    supplier = f_supplier.value.strip()
                    invoice  = f_invoice.value.strip()
                    receipt  = f_receipt.value.strip()
                else:
                    price = 0; supplier = ""; invoice = ""; receipt = ""

                delta = qty if is_in else -qty
                row = prod_map[f_product.value]
                ok = db.add_txn(row["name"], row["category"], delta, price, supplier, f_note.value.strip(), f_date.value.strip(), invoice, receipt)
                if not ok:
                    snack("موجودی کافی نیست!", C_RED)
                    return
                snack("ثبت شد ✓", C_GREEN)
                qty_box.content.controls[1].value = str(db.qty(row["name"]))
                f_qty.value = "1"; f_price.value = ""; f_supplier.value = ""
                f_invoice.value = ""; f_receipt.value = ""; f_note.value = ""
                page.update()

            # دکمه اضطراری برای رفع محدودیت خروج
            def emergency_fix(e):
                row = prod_map[f_product.value]
                db.add_txn(
                    row["name"], row["category"], 100000,
                    0, "موجودی فرضی",
                    "رفع محدودیت خروج - موجودی واقعی بعداً اصلاح شود",
                    jdatetime.datetime.now().strftime("%Y-%m-%d"),
                    "", ""
                )
                snack(f"موجودی {row['name']} موقتاً ۱۰۰۰۰۰ تا شد. حالا می‌تونی خروج بدی.", C_GREEN)
                qty_box.content.controls[1].value = str(db.qty(row["name"]))
                page.update()

            set_body([
                page_header("ورود / خروج کالا"),
                ft.Container(padding=16, content=ft.Column(spacing=12, controls=[
                    f_product, qty_box, f_type, f_qty,
                    in_fields,
                    f_note, f_date,
                    ft.ElevatedButton("ثبت", on_click=save, bgcolor=C_GREEN, color="white", height=50, expand=True),
                    ft.Container(
                        visible=(f_type.value == "خروج"),
                        content=ft.ElevatedButton(
                            "⚡ رفع محدودیت خروج",
                            on_click=emergency_fix,
                            bgcolor=C_ORANGE,
                            color="white",
                            height=44,
                            expand=True,
                        ),
                    ),
                ])),
            ])

        def show_edit_txn(txn_id, back_fn):
            row = db.get_txn(txn_id)
            if not row:
                snack("تراکنش پیدا نشد", C_RED)
                return
            is_in = row["delta"] > 0
            f_qty     = ft.TextField(label="تعداد", value=str(abs(row["delta"])), keyboard_type=ft.KeyboardType.NUMBER, border_color=C_BLUE)
            f_price   = ft.TextField(label="قیمت واحد (تومان)", value=str(row["price"]), keyboard_type=ft.KeyboardType.NUMBER, border_color=C_BLUE, visible=is_in)
            f_supplier= ft.TextField(label="فروشنده", value=row["supplier"] or "", border_color=C_BLUE, visible=is_in)
            f_invoice = ft.TextField(label="شماره فاکتور", value=row["invoice_no"] or "", border_color=C_BLUE, visible=is_in)
            f_receipt = ft.TextField(label="شماره رسید انبار", value=row["receipt_no"] or "", border_color=C_BLUE, visible=is_in)
            f_note    = ft.TextField(label="یادداشت", value=row["note"] or "", border_color=C_BLUE)
            f_date    = ft.TextField(label="تاریخ (شمسی)", value=row["jdate"], border_color=C_BLUE)

            def save(e):
                try:
                    qty   = float(f_qty.value or 0)
                    price = float(f_price.value or 0) if is_in else 0
                except ValueError:
                    snack("مقادیر نادرست است", C_RED)
                    return
                if qty <= 0:
                    snack("تعداد باید بزرگتر از صفر باشد", C_YELLOW)
                    return
                ok = db.update_txn(txn_id, is_in, qty, price,
                    f_supplier.value.strip() if is_in else "",
                    f_note.value.strip(), f_date.value.strip(),
                    f_invoice.value.strip() if is_in else "",
                    f_receipt.value.strip() if is_in else "")
                if not ok:
                    snack("موجودی کافی نیست!", C_RED)
                    return
                snack("ویرایش شد ✓", C_GREEN)
                back_fn()

            def delete(e):
                db.delete_txn(txn_id)
                snack("تراکنش حذف شد", C_RED)
                back_fn()

            set_body([
                page_header("ویرایش تراکنش", back_fn),
                ft.Container(padding=16, content=ft.Column(spacing=12, controls=[
                    ft.Container(border_radius=10, bgcolor="#EFF6FF", padding=12,
                        content=ft.Column(spacing=4, controls=[
                            ft.Text("کالا: " + row["product_name"], size=14, weight=ft.FontWeight.BOLD, color=C_DARK),
                            ft.Text("نوع: " + ("ورود" if is_in else "خروج"), size=13, color=C_GREEN if is_in else C_RED),
                        ])),
                    f_qty, f_price, f_supplier, f_invoice, f_receipt, f_note, f_date,
                    ft.Container(height=4),
                    ft.ElevatedButton("ذخیره تغییرات", on_click=save, bgcolor=C_BLUE, color="white", height=48, expand=True),
                    ft.ElevatedButton("حذف این تراکنش", on_click=delete, bgcolor=C_RED, color="white", height=44, expand=True),
                ])),
            ])

        def render_reports():
            nonlocal report_rows
            f_start    = ft.TextField(label="از تاریخ", hint_text="1403-01-01", expand=True, border_color=C_BLUE)
            f_end      = ft.TextField(label="تا تاریخ", hint_text="1403-12-29", expand=True, border_color=C_BLUE)
            f_product  = ft.TextField(label="نام کالا", border_color=C_BLUE)
            f_supplier = ft.TextField(label="نام فروشنده", border_color=C_BLUE)
            f_invoice  = ft.TextField(label="شماره فاکتور", border_color=C_BLUE)
            f_receipt  = ft.TextField(label="شماره رسید انبار", border_color=C_BLUE)
            f_type     = ft.Dropdown(label="نوع", options=[ft.dropdown.Option(x) for x in ["همه", "ورود", "خروج"]], value="همه")
            f_cat      = ft.Dropdown(label="دسته‌بندی", options=[ft.dropdown.Option(x) for x in ["همه"] + CATS], value="همه")
            results = ft.Column(spacing=8)
            active_rtab = [0]

            tab0 = ft.Container(expand=True, padding=10, bgcolor=C_BLUE, content=ft.Text("تراکنش‌ها", size=12, text_align=ft.TextAlign.CENTER, color="white", weight=ft.FontWeight.BOLD))
            tab1 = ft.Container(expand=True, padding=10, bgcolor=C_WHITE, content=ft.Text("خلاصه کالا", size=12, text_align=ft.TextAlign.CENTER, color=C_GRAY))
            tab2 = ft.Container(expand=True, padding=10, bgcolor=C_WHITE, content=ft.Text("فروشندگان", size=12, text_align=ft.TextAlign.CENTER, color=C_GRAY))
            tab3 = ft.Container(expand=True, padding=10, bgcolor=C_WHITE, content=ft.Text("کم‌موجود", size=12, text_align=ft.TextAlign.CENTER, color=C_GRAY))
            all_tabs = [tab0, tab1, tab2, tab3]

            def select_tab(index):
                active_rtab[0] = index
                for i, t in enumerate(all_tabs):
                    t.bgcolor = C_BLUE if i == index else C_WHITE
                    t.content.color = "white" if i == index else C_GRAY
                    t.content.weight = ft.FontWeight.BOLD if i == index else ft.FontWeight.NORMAL
                page.update()

            tab0.on_click = lambda e: select_tab(0)
            tab1.on_click = lambda e: select_tab(1)
            tab2.on_click = lambda e: select_tab(2)
            tab3.on_click = lambda e: select_tab(3)
            tabs_row = ft.Row(spacing=0, controls=all_tabs)

            def search(e):
                nonlocal report_rows
                tab = active_rtab[0]
                start = f_start.value.strip()
                end   = f_end.value.strip()
                results.controls.clear()

                if tab == 0:
                    rows = db.search_txns(start, end, f_product.value.strip(), f_supplier.value.strip(), f_type.value, f_cat.value, f_invoice.value.strip(), f_receipt.value.strip())
                    report_rows = list(rows)
                    if not rows:
                        results.controls.append(ft.Text("نتیجه‌ای یافت نشد", color=C_GRAY, size=15))
                    else:
                        total_in  = sum(r["delta"] for r in rows if r["delta"] > 0)
                        total_out = sum(abs(r["delta"]) for r in rows if r["delta"] < 0)
                        total_val = sum(abs(r["delta"]) * r["price"] for r in rows if r["delta"] > 0)
                        results.controls.append(ft.Container(border_radius=10, bgcolor="#EFF6FF", padding=12,
                            content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                ft.Column(spacing=2, controls=[ft.Text("ورود", size=11, color=C_GRAY), ft.Text(str(total_in), size=15, weight=ft.FontWeight.BOLD, color=C_GREEN)]),
                                ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[ft.Text("خروج", size=11, color=C_GRAY), ft.Text(str(total_out), size=15, weight=ft.FontWeight.BOLD, color=C_RED)]),
                                ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END, controls=[ft.Text("ارزش ورودی", size=11, color=C_GRAY), ft.Text("{:,.0f}ت".format(total_val), size=15, weight=ft.FontWeight.BOLD, color=C_BLUE)]),
                            ])))
                        for r in rows:
                            is_in = r["delta"] > 0
                            tid = r["id"]
                            def make_edit(t):
                                def fn(e): show_edit_txn(t, render_reports)
                                return fn
                            info = []
                            if r["supplier"]: info.append("فروشنده: " + r["supplier"])
                            if r["invoice_no"]: info.append("فاکتور: " + r["invoice_no"])
                            if r["receipt_no"]: info.append("رسید: " + r["receipt_no"])
                            if r["note"]: info.append(r["note"])
                            results.controls.append(ft.Container(border_radius=10, bgcolor=C_WHITE, padding=12,
                                content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                    ft.Column(spacing=3, expand=True, controls=[
                                        ft.Text(r["product_name"], size=14, weight=ft.FontWeight.BOLD, color=C_DARK),
                                        ft.Text(r["jdate"] + " | " + r["category"], size=11, color=C_GRAY),
                                    ] + [ft.Text(line, size=11, color=C_BLUE) for line in info]),
                                    ft.Column(spacing=4, horizontal_alignment=ft.CrossAxisAlignment.END, controls=[
                                        ft.Container(border_radius=6, padding=6, bgcolor="#DCFCE7" if is_in else "#FEE2E2",
                                            content=ft.Text(("↑ " if is_in else "↓ ") + str(abs(r["delta"])), color=C_GREEN if is_in else C_RED, size=13, weight=ft.FontWeight.BOLD)),
                                        ft.Text("{:,.0f}ت".format(abs(r["delta"]) * r["price"]) if is_in else "", size=11, color=C_GRAY),
                                        ft.IconButton(ft.Icons.EDIT_OUTLINED, icon_color=C_BLUE, icon_size=16, on_click=make_edit(tid)),
                                    ]),
                                ])))

                elif tab == 1:
                    rows = db.summary_by_product(start, end, f_cat.value)
                    if not rows:
                        results.controls.append(ft.Text("نتیجه‌ای یافت نشد", color=C_GRAY))
                    else:
                        for r in rows:
                            results.controls.append(ft.Container(border_radius=10, bgcolor=C_WHITE, padding=12,
                                content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                    ft.Column(spacing=2, expand=True, controls=[ft.Text(r["product_name"], size=14, weight=ft.FontWeight.BOLD, color=C_DARK), ft.Text(r["category"], size=11, color=C_GRAY)]),
                                    ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END, controls=[
                                        ft.Text("ورود: " + str(r["total_in"]), size=12, color=C_GREEN),
                                        ft.Text("خروج: " + str(r["total_out"]), size=12, color=C_RED),
                                        ft.Text("{:,.0f}ت".format(r["total_val"]), size=12, weight=ft.FontWeight.BOLD, color=C_BLUE),
                                    ]),
                                ])))

                elif tab == 2:
                    rows = db.summary_by_supplier(start, end)
                    if not rows:
                        results.controls.append(ft.Text("نتیجه‌ای یافت نشد", color=C_GRAY))
                    else:
                        for r in rows:
                            results.controls.append(ft.Container(border_radius=10, bgcolor=C_WHITE, padding=12,
                                content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                    ft.Column(spacing=2, expand=True, controls=[
                                        ft.Text(r["supplier"], size=14, weight=ft.FontWeight.BOLD, color=C_DARK),
                                        ft.Text(str(r["cnt"]) + " بار خرید | " + str(r["total_qty"]) + " واحد", size=12, color=C_GRAY),
                                    ]),
                                    ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END, controls=[
                                        ft.Text("جمع خرید", size=10, color=C_GRAY),
                                        ft.Text("{:,.0f}ت".format(r["total_val"]), size=14, weight=ft.FontWeight.BOLD, color=C_BLUE),
                                    ]),
                                ])))

                elif tab == 3:
                    lows = db.low_stock()
                    if not lows:
                        results.controls.append(ft.Container(border_radius=10, bgcolor="#DCFCE7", padding=16,
                            content=ft.Row(spacing=8, controls=[ft.Icon(ft.Icons.CHECK_CIRCLE, color=C_GREEN), ft.Text("همه کالاها موجودی کافی دارند", size=14, color=C_GREEN)])))
                    else:
                        for r in lows:
                            qty = db.qty(r["name"])
                            results.controls.append(ft.Container(border_radius=10, bgcolor="#FEF2F2", padding=12,
                                content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                    ft.Column(spacing=2, expand=True, controls=[ft.Text(r["name"], size=14, weight=ft.FontWeight.BOLD, color=C_DARK), ft.Text(r["category"], size=12, color=C_GRAY)]),
                                    ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END, controls=[
                                        ft.Text("موجودی: " + str(qty) + " " + r["unit"], size=13, color=C_RED, weight=ft.FontWeight.BOLD),
                                        ft.Text("حداقل: " + str(r["min_qty"]), size=11, color=C_GRAY),
                                    ]),
                                ])))
                page.update()

            def export_csv(e):
                nonlocal report_rows
                if not report_rows:
                    snack("ابتدا جستجو کنید", C_YELLOW)
                    return
                try:
                    dl = os.getenv("FLET_APP_STORAGE_DOWNLOADS") or os.path.expanduser("~/Downloads")
                    dl = Path(dl)
                    dl.mkdir(parents=True, exist_ok=True)
                    fname = "anbar_" + jdatetime.datetime.now().strftime("%Y-%m-%d_%H-%M") + ".csv"
                    db.export_csv(report_rows, dl / fname)
                    snack("CSV ذخیره شد ✓", C_GREEN)
                except Exception as ex:
                    snack("خطا: " + str(ex), C_RED)

            def export_txt(e):
                nonlocal report_rows
                if not report_rows:
                    snack("ابتدا جستجو کنید", C_YELLOW)
                    return
                try:
                    dl = os.getenv("FLET_APP_STORAGE_DOWNLOADS") or os.path.expanduser("~/Downloads")
                    dl = Path(dl)
                    dl.mkdir(parents=True, exist_ok=True)
                    fname = "gozaresh_" + jdatetime.datetime.now().strftime("%Y-%m-%d_%H-%M") + ".txt"
                    db.export_txt(report_rows, dl / fname)
                    snack("گزارش متنی ذخیره شد ✓", C_GREEN)
                except Exception as ex:
                    snack("خطا: " + str(ex), C_RED)

            set_body([
                page_header("گزارشات"),
                ft.Container(padding=12, content=ft.Column(spacing=10, controls=[
                    ft.Row(controls=[f_start, f_end], spacing=10),
                    f_product, f_supplier,
                    ft.Row(controls=[f_invoice, f_receipt], spacing=10),
                    ft.Row(controls=[f_type, f_cat], spacing=10),
                    ft.Row(spacing=10, controls=[
                        ft.ElevatedButton("🔍 نمایش", on_click=search, bgcolor=C_BLUE, color="white", expand=True, height=44),
                        ft.ElevatedButton("📥 CSV", on_click=export_csv, bgcolor=C_WHITE, color=C_BLUE, height=44),
                        ft.ElevatedButton("🖨️", on_click=export_txt, bgcolor=C_WHITE, color=C_BLUE, height=44, width=54),
                    ]),
                ])),
                ft.Container(bgcolor=C_WHITE, content=tabs_row),
                ft.Container(padding=12, content=results),
            ])

        def show_backup():
            backups = db.list_backups()

            def do_backup(e):
                try:
                    db.manual_backup()
                    snack("بکاپ ذخیره شد ✓", C_GREEN)
                    show_backup()
                except Exception as ex:
                    snack("خطا: " + str(ex), C_RED)

            def do_restore(path):
                try:
                    db.restore(path)
                    snack("بازگردانی انجام شد — برنامه را ببندید و باز کنید", C_GREEN)
                except Exception as ex:
                    snack("خطا: " + str(ex), C_RED)

            items = [
                ft.Container(border_radius=12, bgcolor="#EFF6FF", padding=14,
                    content=ft.Column(spacing=6, controls=[
                        ft.Row(spacing=8, controls=[ft.Icon(ft.Icons.INFO_OUTLINE, color=C_BLUE, size=18), ft.Text("پشتیبان‌گیری", size=14, weight=ft.FontWeight.BOLD, color=C_BLUE)]),
                        ft.Text("بکاپ خودکار: هر روز یک بار (۷ روز اخیر)", size=12, color=C_GRAY),
                        ft.Text("بکاپ دستی: در پوشه Downloads ذخیره می‌شود", size=12, color=C_GRAY),
                    ])),
                ft.Container(height=8),
                ft.ElevatedButton("💾  تهیه بکاپ دستی", on_click=do_backup, bgcolor=C_BLUE, color="white", height=48, expand=True),
                ft.Container(height=8),
                ft.Text("لیست بکاپ‌ها (" + str(len(backups)) + "):", size=14, weight=ft.FontWeight.BOLD, color=C_DARK),
            ]

            if not backups:
                items.append(ft.Text("هنوز بکاپی وجود ندارد", color=C_GRAY))
            else:
                for bp in backups:
                    name = Path(bp).name
                    is_auto = name.startswith("auto_")
                    items.append(ft.Container(border_radius=10, bgcolor=C_WHITE, padding=12,
                        content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                            ft.Column(spacing=4, expand=True, controls=[
                                ft.Text(name, size=12, color=C_DARK),
                                ft.Container(border_radius=20, bgcolor=C_GREEN + "20" if is_auto else C_BLUE + "20", padding=6,
                                    content=ft.Text("خودکار" if is_auto else "دستی", size=10, color=C_GREEN if is_auto else C_BLUE)),
                            ]),
                            ft.TextButton("بازگردانی", on_click=lambda e, p=bp: do_restore(p)),
                        ])))

            set_body([
                page_header("پشتیبان‌گیری", render_products),
                ft.Container(padding=16, content=ft.Column(spacing=10, controls=items)),
            ])

        tab_bar_row = ft.Row(spacing=0)

        def refresh_tabs():
            def make_tab(label, icon, index):
                def click(e):
                    active_tab[0] = index
                    refresh_tabs()
                    [render_products, render_txn, render_reports][index]()
                is_active = active_tab[0] == index
                return ft.Container(expand=True, on_click=click, padding=8,
                    content=ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2, controls=[
                        ft.Icon(icon, color=C_BLUE if is_active else C_GRAY, size=22),
                        ft.Text(label, size=10, color=C_BLUE if is_active else C_GRAY,
                                weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.NORMAL),
                    ]))
            tab_bar_row.controls = [
                make_tab("انبار",      ft.Icons.INVENTORY_2, 0),
                make_tab("ورود/خروج", ft.Icons.SWAP_VERT,    1),
                make_tab("گزارشات",   ft.Icons.BAR_CHART,    2),
            ]
            tab_bar_row.update()

        page.add(ft.Column(expand=True, spacing=0, controls=[
            ft.Container(expand=True, content=body),
            ft.Container(bgcolor=C_WHITE, padding=4, content=tab_bar_row),
        ]))

        refresh_tabs()
        render_products()

    except Exception:
        log_error_to_file("FATAL ERROR in main():\n" + traceback.format_exc())


if __name__ == "__main__":
    ft.app(target=main)
