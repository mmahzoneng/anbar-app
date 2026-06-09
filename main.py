import flet as ft
import sqlite3
import jdatetime
import datetime
import os
import shutil
import csv
import traceback
import sys
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError


def get_log_path():
    try:
        dl = os.getenv("FLET_APP_STORAGE_DOWNLOADS")
        if dl:
            return Path(dl) / "error_log.txt"
    except:
        pass
    return Path.home() / "Downloads" / "error_log.txt"


def log_error(msg):
    try:
        p = get_log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write("[" + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "]\n")
            f.write(msg + "\n")
            f.write("-" * 50 + "\n\n")
    except:
        pass


sys.excepthook = lambda t, v, tb: log_error("".join(traceback.format_exception(t, v, tb)))


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
            c.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    unit TEXT NOT NULL DEFAULT 'عدد',
                    category TEXT NOT NULL DEFAULT 'ساختمانی',
                    min_qty REAL NOT NULL DEFAULT 0,
                    note TEXT DEFAULT '',
                    created_at TEXT DEFAULT ''
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS txns (
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
                )
            """)

    def _migrate(self):
        for col in ["category TEXT DEFAULT ''", "price REAL DEFAULT 0",
                    "supplier TEXT DEFAULT ''", "invoice_no TEXT DEFAULT ''",
                    "receipt_no TEXT DEFAULT ''"]:
            try:
                with self._conn() as c:
                    c.execute("ALTER TABLE txns ADD COLUMN " + col)
            except:
                pass
        for col in ["note TEXT DEFAULT ''", "created_at TEXT DEFAULT ''"]:
            try:
                with self._conn() as c:
                    c.execute("ALTER TABLE products ADD COLUMN " + col)
            except:
                pass

    def _auto_backup(self):
        today = jdatetime.date.today().strftime("%Y-%m-%d")
        dest = self.backup_dir / ("auto_" + today + ".db")
        if not dest.exists() and Path(self.path).exists():
            try:
                shutil.copy2(self.path, dest)
                for old in sorted(self.backup_dir.glob("auto_*.db"), reverse=True)[7:]:
                    old.unlink()
            except:
                pass

    def all_products(self):
        with self._conn() as c:
            return c.execute("SELECT * FROM products ORDER BY category, name").fetchall()

    def add_product(self, name, unit, category, min_qty, note):
        now_j = jdatetime.datetime.now().strftime("%Y-%m-%d")
        with self._conn() as c:
            c.execute(
                "INSERT INTO products (name,unit,category,min_qty,note,created_at) VALUES (?,?,?,?,?,?)",
                (name, unit, category, min_qty, note, now_j)
            )

    def update_product(self, pid, name, unit, category, min_qty, note):
        with self._conn() as c:
            c.execute(
                "UPDATE products SET name=?,unit=?,category=?,min_qty=?,note=? WHERE id=?",
                (name, unit, category, min_qty, note, pid)
            )

    def delete_product(self, name):
        with self._conn() as c:
            c.execute("DELETE FROM products WHERE name=?", (name,))
            c.execute("DELETE FROM txns WHERE product_name=?", (name,))

    def qty(self, name):
        with self._conn() as c:
            return c.execute(
                "SELECT COALESCE(SUM(delta),0) FROM txns WHERE product_name=?",
                (name,)
            ).fetchone()[0]

    def add_txn(self, name, category, delta, price, supplier, note, jdate, invoice_no, receipt_no):
        with self._conn() as c:
            current = c.execute(
                "SELECT COALESCE(SUM(delta),0) FROM txns WHERE product_name=?",
                (name,)
            ).fetchone()[0]
            balance = current + delta
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            jd = jdate or jdatetime.datetime.now().strftime("%Y-%m-%d")
            c.execute(
                "INSERT INTO txns (product_name,category,delta,balance,price,supplier,note,invoice_no,receipt_no,jdate,ts) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (name, category, delta, balance, price, supplier, note, invoice_no, receipt_no, jd, now)
            )
        return True

    def get_txn(self, txn_id):
        with self._conn() as c:
            return c.execute("SELECT * FROM txns WHERE id=?", (txn_id,)).fetchone()

    def update_txn(self, txn_id, is_in, qty, price, supplier, note, jdate, invoice_no, receipt_no):
        with self._conn() as c:
            row = c.execute("SELECT * FROM txns WHERE id=?", (txn_id,)).fetchone()
            if not row:
                return False
            name = row["product_name"]
            current = c.execute(
                "SELECT COALESCE(SUM(delta),0) FROM txns WHERE product_name=?",
                (name,)
            ).fetchone()[0]
            new_delta = qty if is_in else -qty
            new_balance = current - row["delta"] + new_delta
            c.execute(
                "UPDATE txns SET delta=?,balance=?,price=?,supplier=?,note=?,jdate=?,invoice_no=?,receipt_no=? WHERE id=?",
                (new_delta, new_balance, price, supplier, note, jdate, invoice_no, receipt_no, txn_id)
            )
        return True

    def delete_txn(self, txn_id):
        with self._conn() as c:
            c.execute("DELETE FROM txns WHERE id=?", (txn_id,))

    def search_txns(self, start="", end="", keyword="", supplier_kw="",
                    txn_type="همه", category="همه", invoice_kw="", receipt_kw=""):
        conds, params = [], []
        if start and end:
            conds.append("jdate BETWEEN ? AND ?")
            params += [start, end]
        if keyword:
            conds.append("product_name LIKE ?")
            params.append("%" + keyword + "%")
        if supplier_kw:
            conds.append("supplier LIKE ?")
            params.append("%" + supplier_kw + "%")
        if invoice_kw:
            conds.append("invoice_no LIKE ?")
            params.append("%" + invoice_kw + "%")
        if receipt_kw:
            conds.append("receipt_no LIKE ?")
            params.append("%" + receipt_kw + "%")
        if txn_type == "ورود":
            conds.append("delta > 0")
        elif txn_type == "خروج":
            conds.append("delta < 0")
        if category != "همه":
            conds.append("category = ?")
            params.append(category)

        q = "SELECT * FROM txns"
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY ts DESC"
        with self._conn() as c:
            return c.execute(q, params).fetchall()

    def summary_by_product(self, start="", end="", category="همه"):
        conds, params = [], []
        if start and end:
            conds.append("jdate BETWEEN ? AND ?")
            params += [start, end]
        if category != "همه":
            conds.append("category = ?")
            params.append(category)
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
        if start and end:
            conds.append("jdate BETWEEN ? AND ?")
            params += [start, end]
        q = "SELECT supplier, COUNT(*) as cnt, SUM(delta) as total_qty, SUM(delta*price) as total_val FROM txns WHERE " + \
            " AND ".join(conds) + " GROUP BY supplier ORDER BY total_val DESC"
        with self._conn() as c:
            return c.execute(q, params).fetchall()

    def low_stock(self):
        return [r for r in self.all_products() if r["min_qty"] > 0 and self.qty(r["name"]) <= r["min_qty"]]

    def total_value(self):
        total = 0
        with self._conn() as c:
            rows = c.execute(
                "SELECT product_name, SUM(delta) as qty FROM txns GROUP BY product_name"
            ).fetchall()
            for r in rows:
                if r["qty"] and r["qty"] > 0:
                    last = c.execute(
                        "SELECT price FROM txns WHERE product_name=? AND delta>0 ORDER BY ts DESC LIMIT 1",
                        (r["product_name"],)
                    ).fetchone()
                    if last:
                        total += r["qty"] * last["price"]
        return total

    def build_txt(self, rows):
        lines = [
            "گزارش انبار فاز ۷",
            "تاریخ: " + jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M"),
            "=" * 40
        ]
        products = {}
        for r in rows:
            name = r["product_name"]
            if name not in products:
                products[name] = {"in": 0, "out": 0, "val": 0}
            if r["delta"] > 0:
                products[name]["in"] += r["delta"]
                products[name]["val"] += r["delta"] * r["price"]
            else:
                products[name]["out"] += abs(r["delta"])

        lines.append("خلاصه به تفکیک کالا:")
        lines.append("-" * 40)
        total_val_all = 0
        for name, data in products.items():
            lines.append(name + ":")
            lines.append("  ورود: " + "{:,.2f}".format(data["in"]) + "  |  خروج: " + "{:,.2f}".format(data["out"]))
            lines.append("  ارزش ورودی: " + "{:,.2f}".format(data["val"]) + " تومان")
            total_val_all += data["val"]
            lines.append("")

        lines += [
            "=" * 40,
            "ارزش کل ورودی: " + "{:,.2f}".format(total_val_all) + " تومان",
            "تعداد تراکنش: " + str(len(rows)),
            "=" * 40,
            "",
            "جزئیات تراکنش‌ها:",
            "-" * 40
        ]
        for r in rows:
            typ = "ورود" if r["delta"] > 0 else "خروج"
            lines.append(r["jdate"] + " | " + r["product_name"] + " | " + typ + ": " + "{:,.2f}".format(abs(r["delta"])))
            if r["delta"] > 0:
                if r["supplier"]:
                    lines.append("  فروشنده: " + r["supplier"])
                if r["invoice_no"]:
                    lines.append("  فاکتور: " + r["invoice_no"])
                if r["receipt_no"]:
                    lines.append("  رسید: " + r["receipt_no"])
                lines.append("  ارزش: " + "{:,.2f}".format(abs(r["delta"]) * r["price"]) + " تومان")
            if r["note"]:
                lines.append("  یادداشت: " + r["note"])
            lines.append("")
        return "\n".join(lines)

    def build_csv_text(self, rows):
        lines = ["تاریخ,کالا,دسته,نوع,تعداد,قیمت,ارزش,فروشنده,فاکتور,رسید"]
        for r in rows:
            typ = "ورود" if r["delta"] > 0 else "خروج"
            lines.append(",".join([
                r["jdate"], r["product_name"], r["category"], typ,
                "{:,.2f}".format(abs(r["delta"])), str(r["price"]),
                "{:,.2f}".format(abs(r["delta"]) * r["price"]),
                r["supplier"], r["invoice_no"], r["receipt_no"]
            ]))
        return "\n".join(lines)

    def send_to_bale(self):
        token = "99350975:ljWJHCnhC8JiCReN7yXzBVX9GbAe3mekIYA"
        chat_id = "936543882"
        try:
            name = "anbar_backup_" + jdatetime.datetime.now().strftime("%Y-%m-%d_%H-%M") + ".db"
            dest = self.backup_dir / name
            shutil.copy2(self.path, dest)

            url = f"https://tapi.bale.ai/bot{token}/sendDocument"
            boundary = "flet_anbar_boundary"

            with open(str(dest), "rb") as f:
                file_content = f.read()

            body = b""
            body += f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'.encode()
            body += f"{chat_id}\r\n".encode()
            body += f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="document"; filename="{name}"\r\n'.encode()
            body += b"Content-Type: application/octet-stream\r\n\r\n"
            body += file_content
            body += f"\r\n--{boundary}--\r\n".encode()

            req = Request(url, data=body)
            req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

            with urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
                return result.get("ok", False)
        except Exception as e:
            log_error(f"Bale send failed: {e}")
            return False

    def download_backup_from_bale(self):
        token = "99350975:ljWJHCnhC8JiCReN7yXzBVX9GbAe3mekIYA"
        try:
            url = f"https://tapi.bale.ai/bot{token}/getUpdates?limit=5&offset=-1"
            with urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            if not data.get("ok") or not data.get("result"):
                return None

            for update in reversed(data["result"]):
                message = update.get("message", {})
                document = message.get("document")
                if document and document.get("file_name", "").endswith(".db"):
                    file_id = document.get("file_id")
                    file_url = f"https://tapi.bale.ai/bot{token}/getFile?file_id={file_id}"
                    with urlopen(file_url, timeout=15) as resp:
                        file_data = json.loads(resp.read().decode())
                    if file_data.get("ok"):
                        download_url = f"https://tapi.bale.ai/file/bot{token}/{file_data['result']['file_path']}"
                        with urlopen(download_url, timeout=60) as resp:
                            content = resp.read()
                        fname = document.get("file_name")
                        dest = self.backup_dir / fname
                        with open(str(dest), "wb") as f:
                            f.write(content)
                        return fname
            return None
        except Exception as e:
            log_error(f"Bale download failed: {e}")
            return None

    def manual_backup(self):
        name = "anbar_backup_" + jdatetime.datetime.now().strftime("%Y-%m-%d_%H-%M") + ".db"
        dest = self.backup_dir / name
        shutil.copy2(self.path, dest)
        return str(dest)

    def list_backups(self):
        return [str(f) for f in sorted(self.backup_dir.glob("*.db"), reverse=True)]

    def restore(self, path):
        shutil.copy2(path, self.path)


# ========== ثابت‌ها ==========
BG = "#F4F6F9"
C_WHITE = "#FFFFFF"
C_DARK = "#1C2B3A"
C_GRAY = "#7A8999"
C_LIGHT = "#E8ECF0"
C_BLUE = "#2563EB"
C_BLUE2 = "#1D4ED8"
C_GREEN = "#16A34A"
C_RED = "#DC2626"
C_ORANGE = "#EA580C"
C_YELLOW = "#D97706"
CATS = ["ساختمانی", "آشپزخانه"]


def main(page: ft.Page):
    try:
        page.title = "انبار فاز 7"
        page.rtl = True
        page.theme_mode = ft.ThemeMode.LIGHT
        page.bgcolor = BG
        page.padding = 0
        page.scroll = "adaptive"

        db = DB()
        active_tab = [0]
        report_rows = []
        body = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=0)

        def show_dialog(title, message, color=C_BLUE):
            def close(e=None):
                dlg.open = False
                page.update()
            dlg = ft.AlertDialog(
                title=ft.Text(title, weight=ft.FontWeight.BOLD, color=color),
                content=ft.Text(message, selectable=True),
                actions=[ft.TextButton("باشه", on_click=close)],
            )
            page.dialog = dlg
            dlg.open = True
            page.update()

        def set_body(controls):
            body.controls = controls
            body.update()
            page.update()

        def page_header(title, back_fn=None):
            ctrls = []
            if back_fn:
                ctrls.append(
                    ft.IconButton(
                        ft.Icons.ARROW_BACK_IOS,
                        icon_color=C_BLUE,
                        icon_size=20,
                        on_click=lambda e: back_fn()
                    )
                )
            ctrls.append(ft.Text(title, size=20, weight=ft.FontWeight.BOLD, color=C_DARK, expand=True))
            return ft.Container(bgcolor=C_WHITE, padding=12, content=ft.Row(controls=ctrls, spacing=4))

        def show_text_page(title, content, back_fn):
            set_body([
                page_header(title, back_fn),
                ft.Container(
                    padding=12,
                    content=ft.Column(spacing=10, controls=[
                        ft.Container(
                            border_radius=8,
                            bgcolor=C_LIGHT,
                            padding=12,
                            content=ft.Text(content, size=12, selectable=True, font_family="monospace"),
                        ),
                    ]),
                ),
            ])

        # ========== داشبورد ==========
        def render_products():
            rows = db.all_products()
            low_count = len(db.low_stock())
            total_val = db.total_value()

            controls = [
                ft.Container(bgcolor=C_BLUE, padding=20, content=ft.Column(spacing=10, controls=[
                    ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                        ft.Column(spacing=4, controls=[
                            ft.Text("انبار فاز 7", size=22, weight=ft.FontWeight.BOLD, color="white"),
                            ft.Text(jdatetime.date.today().strftime("%Y/%m/%d"), size=13, color="#BFDBFE"),
                        ]),
                        ft.Container(border_radius=12, bgcolor=C_BLUE2, padding=12,
                                     content=ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END,
                                                       controls=[
                                                           ft.Text("ارزش کل انبار", size=11, color="white"),
                                                           ft.Text("{:,.2f} ت".format(total_val), size=15,
                                                                   weight=ft.FontWeight.BOLD, color="white"),
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
                    ft.ElevatedButton("➕ کالای جدید", on_click=lambda e: show_product_form(),
                                      bgcolor=C_BLUE, color="white", expand=True, height=44),
                    ft.ElevatedButton("💾", on_click=lambda e: show_backup(),
                                      bgcolor=C_WHITE, color=C_BLUE, height=44, width=54),
                ])),
            ]

            if not rows:
                controls.append(
                    ft.Container(padding=60, content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12,
                        controls=[
                            ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, size=70, color=C_LIGHT),
                            ft.Text("انبار خالی است", size=18, color=C_GRAY)
                        ],
                    ))
                )
            else:
                if low_count > 0:
                    controls.append(
                        ft.Container(margin=10, border_radius=10, bgcolor="#FEF2F2", padding=10,
                                     content=ft.Row(spacing=8, controls=[
                                         ft.Icon(ft.Icons.WARNING_AMBER, color=C_RED, size=18),
                                         ft.Text(str(low_count) + " کالا نیاز به تأمین دارد", size=13,
                                                 color=C_RED, weight=ft.FontWeight.BOLD),
                                     ]))
                    )
                for r in rows:
                    qty = db.qty(r["name"])
                    low = r["min_qty"] > 0 and qty <= r["min_qty"]
                    color = C_RED if low else (C_ORANGE if qty == 0 else C_GREEN)

                    def on_edit(e, row=r):
                        show_product_form(row)

                    def on_del(e, n=r["name"]):
                        db.delete_product(n)
                        show_dialog("حذف", n + " حذف شد", C_RED)
                        render_products()

                    controls.append(
                        ft.Container(margin=10, border_radius=14, bgcolor=C_WHITE, padding=14,
                                     content=ft.Column(spacing=10, controls=[
                                         ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                             ft.Column(spacing=3, expand=True, controls=[
                                                 ft.Text(r["name"], size=15, weight=ft.FontWeight.BOLD, color=C_DARK),
                                                 ft.Row(spacing=6, controls=[
                                                     ft.Container(border_radius=20, bgcolor=C_LIGHT, padding=6,
                                                                  content=ft.Text(r["category"], size=11,
                                                                                  color=C_GRAY))
                                                 ]),
                                             ]),
                                             ft.Row(spacing=0, controls=[
                                                 ft.IconButton(ft.Icons.EDIT_OUTLINED, icon_color=C_BLUE,
                                                               icon_size=18, on_click=on_edit),
                                                 ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_color=C_RED,
                                                               icon_size=18, on_click=on_del),
                                             ]),
                                         ]),
                                         ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                             ft.Container(border_radius=10, bgcolor=color + "15", padding=10,
                                                          content=ft.Column(spacing=2, controls=[
                                                              ft.Text("موجودی", size=10, color=C_GRAY),
                                                              ft.Text(str(qty) + " " + r["unit"], size=16,
                                                                      weight=ft.FontWeight.BOLD, color=color),
                                                          ])),
                                             ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                                       controls=[
                                                           ft.Text("حداقل موجودی", size=10, color=C_GRAY),
                                                           ft.Text(str(r["min_qty"]) + " " + r["unit"], size=13,
                                                                   color=C_DARK),
                                                       ]),
                                             ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END,
                                                       controls=[
                                                           ft.Text("واحد", size=10, color=C_GRAY),
                                                           ft.Text(r["unit"], size=13, color=C_DARK),
                                                       ]),
                                         ]),
                                         ft.Container(visible=low, border_radius=8, bgcolor="#FEF2F2", padding=8,
                                                      content=ft.Row(spacing=6, controls=[
                                                          ft.Icon(ft.Icons.WARNING_AMBER, color=C_RED, size=16),
                                                          ft.Text("موجودی زیر حداقل!", size=12, color=C_RED),
                                                      ])),
                                     ]))
                    )
            set_body(controls)

        # ========== فرم کالا ==========
        def show_product_form(row=None):
            is_edit = row is not None
            f_name = ft.TextField(label="نام کالا", value=row["name"] if is_edit else "", border_color=C_BLUE)
            f_unit = ft.TextField(label="واحد (کیسه، عدد، متر...)", value=row["unit"] if is_edit else "عدد",
                                  border_color=C_BLUE)
            f_cat = ft.Dropdown(label="دسته‌بندی", options=[ft.dropdown.Option(c) for c in CATS],
                                value=row["category"] if is_edit else "ساختمانی")
            f_min = ft.TextField(label="حداقل موجودی هشدار", value=str(row["min_qty"]) if is_edit else "0",
                                 keyboard_type=ft.KeyboardType.NUMBER, border_color=C_BLUE)
            f_note = ft.TextField(label="توضیحات (اختیاری)", value=row["note"] if is_edit else "",
                                  border_color=C_BLUE)

            def save(e):
                name = f_name.value.strip()
                if not name:
                    show_dialog("خطا", "نام کالا را وارد کنید", C_RED)
                    return
                try:
                    min_qty = float(f_min.value or 0)
                except ValueError:
                    show_dialog("خطا", "حداقل موجودی باید عدد باشد", C_RED)
                    return
                try:
                    if is_edit:
                        db.update_product(row["id"], name, f_unit.value.strip(), f_cat.value, min_qty,
                                         f_note.value.strip())
                        show_dialog("موفق", name + " ویرایش شد", C_GREEN)
                    else:
                        db.add_product(name, f_unit.value.strip(), f_cat.value, min_qty, f_note.value.strip())
                        show_dialog("موفق", name + " اضافه شد", C_GREEN)
                except sqlite3.IntegrityError:
                    show_dialog("خطا", "این نام قبلاً ثبت شده است", C_RED)
                    return
                render_products()

            set_body([
                page_header("ویرایش کالا" if is_edit else "کالای جدید", render_products),
                ft.Container(padding=16, content=ft.Column(spacing=12, controls=[
                    f_name, f_unit, f_cat, f_min, f_note,
                    ft.Container(height=8),
                    ft.ElevatedButton("ذخیره" if is_edit else "افزودن کالا", on_click=save,
                                      bgcolor=C_BLUE, color="white", height=48, expand=True),
                ])),
            ])

        # ========== فرم ورود (با جستجوی دستی و فرمت قیمت) ==========
        def render_enter():
            products = db.all_products()
            if not products:
                set_body([
                    page_header("ورود کالا"),
                    ft.Container(padding=40, content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[ft.Icon(ft.Icons.ARROW_UPWARD, size=60, color=C_GRAY),
                                  ft.Text("ابتدا کالا اضافه کنید", size=16, color=C_GRAY)]
                    ))
                ])
                return

            all_names = [r["name"] for r in products]
            prod_map = {r["name"]: r for r in products}

            f_product = ft.Dropdown(label="کالا", options=[ft.dropdown.Option(n) for n in all_names],
                                    value=all_names[0])
            f_qty = ft.TextField(label="تعداد", value="1", keyboard_type=ft.KeyboardType.NUMBER, border_color=C_BLUE)
            f_price = ft.TextField(label="قیمت واحد (تومان)", keyboard_type=ft.KeyboardType.NUMBER, border_color=C_BLUE)
            f_supplier = ft.TextField(label="نام فروشنده / مصالح‌فروش", border_color=C_BLUE)
            f_invoice = ft.TextField(label="شماره فاکتور", border_color=C_BLUE)
            f_receipt = ft.TextField(label="شماره رسید انبار (اختیاری)", border_color=C_BLUE)
            f_note = ft.TextField(label="یادداشت", border_color=C_BLUE)
            f_date = ft.TextField(label="تاریخ (شمسی)", value=jdatetime.datetime.now().strftime("%Y-%m-%d"),
                                  border_color=C_BLUE)

            qty_box = ft.Container(border_radius=10, bgcolor=C_BLUE + "15", padding=12,
                                   content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                       ft.Text("موجودی فعلی:", size=14, color=C_GRAY),
                                       ft.Text(str(db.qty(all_names[0])), size=18, weight=ft.FontWeight.BOLD,
                                               color=C_BLUE),
                                   ]))

            search_field = ft.TextField(label="جستجوی کالا (اختیاری)", border_color=C_BLUE,
                                        hint_text="بخشی از نام کالا را تایپ کنید...")

            def update_dropdown_options(filter_text=""):
                if not filter_text.strip():
                    filtered = all_names
                else:
                    ft_lower = filter_text.lower().strip()
                    filtered = [n for n in all_names if ft_lower in n.lower()]
                if not filtered:
                    filtered = all_names
                f_product.options = [ft.dropdown.Option(n) for n in filtered]
                if f_product.value not in filtered:
                    f_product.value = filtered[0]
                qty_box.content.controls[1].value = str(db.qty(f_product.value))
                page.update()

            def on_search_change(e):
                update_dropdown_options(search_field.value)

            def on_product_change(e):
                qty_box.content.controls[1].value = str(db.qty(f_product.value))
                page.update()

            search_field.on_change = on_search_change
            f_product.on_change = on_product_change

            # ====== فرمت خودکار قیمت ======
            def format_price(e):
                text = f_price.value.replace(",", "")
                if text == "":
                    f_price.value = ""
                    f_price.update()
                    return
                try:
                    num = float(text)
                    f_price.value = "{:,.0f}".format(num)   # عدد صحیح با جداکننده هزارگان
                    f_price.update()
                except ValueError:
                    pass

            f_price.on_blur = format_price

            def save(e):
                try:
                    qty = float(f_qty.value or 0)
                    price = float(f_price.value.replace(",", "") or 0)
                except ValueError:
                    show_dialog("خطا", "تعداد یا قیمت نادرست است", C_RED)
                    return
                if qty <= 0:
                    show_dialog("خطا", "تعداد باید بزرگتر از صفر باشد", C_YELLOW)
                    return
                row = prod_map[f_product.value]
                ok = db.add_txn(row["name"], row["category"], qty, price,
                                f_supplier.value.strip(), f_note.value.strip(), f_date.value.strip(),
                                f_invoice.value.strip(), f_receipt.value.strip())
                if not ok:
                    show_dialog("خطا", "خطا در ثبت!", C_RED)
                    return
                show_dialog("موفق", "ورود ثبت شد ✓", C_GREEN)
                qty_box.content.controls[1].value = str(db.qty(row["name"]))
                f_qty.value = "1"
                f_price.value = ""
                f_supplier.value = ""
                f_invoice.value = ""
                f_receipt.value = ""
                f_note.value = ""
                page.update()

            set_body([
                page_header("ورود کالا"),
                ft.Container(padding=16, content=ft.Column(spacing=12, controls=[
                    search_field, f_product, qty_box, f_qty, f_price, f_supplier, f_invoice, f_receipt, f_note, f_date,
                    ft.ElevatedButton("ثبت ورود", on_click=save, bgcolor=C_GREEN, color="white", height=50,
                                      expand=True),
                ])),
            ])

        # ========== فرم خروج ==========
        def render_exit():
            products = db.all_products()
            if not products:
                set_body([
                    page_header("خروج کالا"),
                    ft.Container(padding=40, content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[ft.Icon(ft.Icons.ARROW_DOWNWARD, size=60, color=C_GRAY),
                                  ft.Text("ابتدا کالا اضافه کنید", size=16, color=C_GRAY)]
                    ))
                ])
                return

            all_names = [r["name"] for r in products]
            prod_map = {r["name"]: r for r in products}

            f_product = ft.Dropdown(label="کالا", options=[ft.dropdown.Option(n) for n in all_names],
                                    value=all_names[0])
            f_qty = ft.TextField(label="تعداد", value="1", keyboard_type=ft.KeyboardType.NUMBER, border_color=C_BLUE)
            f_note = ft.TextField(label="یادداشت", border_color=C_BLUE)
            f_date = ft.TextField(label="تاریخ (شمسی)", value=jdatetime.datetime.now().strftime("%Y-%m-%d"),
                                  border_color=C_BLUE)

            qty_box = ft.Container(border_radius=10, bgcolor=C_BLUE + "15", padding=12,
                                   content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                       ft.Text("موجودی فعلی:", size=14, color=C_GRAY),
                                       ft.Text(str(db.qty(all_names[0])), size=18, weight=ft.FontWeight.BOLD,
                                               color=C_BLUE),
                                   ]))

            search_field = ft.TextField(label="جستجوی کالا (اختیاری)", border_color=C_BLUE,
                                        hint_text="بخشی از نام کالا را تایپ کنید...")

            def update_dropdown_options(filter_text=""):
                if not filter_text.strip():
                    filtered = all_names
                else:
                    ft_lower = filter_text.lower().strip()
                    filtered = [n for n in all_names if ft_lower in n.lower()]
                if not filtered:
                    filtered = all_names
                f_product.options = [ft.dropdown.Option(n) for n in filtered]
                if f_product.value not in filtered:
                    f_product.value = filtered[0]
                qty_box.content.controls[1].value = str(db.qty(f_product.value))
                page.update()

            def on_search_change(e):
                update_dropdown_options(search_field.value)

            def on_product_change(e):
                qty_box.content.controls[1].value = str(db.qty(f_product.value))
                page.update()

            search_field.on_change = on_search_change
            f_product.on_change = on_product_change

            def save(e):
                try:
                    qty = float(f_qty.value or 0)
                except ValueError:
                    show_dialog("خطا", "تعداد نادرست است", C_RED)
                    return
                if qty <= 0:
                    show_dialog("خطا", "تعداد باید بزرگتر از صفر باشد", C_YELLOW)
                    return
                row = prod_map[f_product.value]
                ok = db.add_txn(row["name"], row["category"], -qty, 0,
                                "", f_note.value.strip(), f_date.value.strip(), "", "")
                if not ok:
                    show_dialog("خطا", "خطا در ثبت!", C_RED)
                    return
                show_dialog("موفق", "خروج ثبت شد ✓", C_GREEN)
                qty_box.content.controls[1].value = str(db.qty(row["name"]))
                f_qty.value = "1"
                f_note.value = ""
                page.update()

            set_body([
                page_header("خروج کالا"),
                ft.Container(padding=16, content=ft.Column(spacing=12, controls=[
                    search_field, f_product, qty_box, f_qty, f_note, f_date,
                    ft.ElevatedButton("ثبت خروج", on_click=save, bgcolor=C_RED, color="white", height=50,
                                      expand=True),
                ])),
            ])

        # ========== ویرایش تراکنش ==========
        def show_edit_txn(txn_id, back_fn):
            row = db.get_txn(txn_id)
            if not row:
                show_dialog("خطا", "تراکنش پیدا نشد", C_RED)
                return
            is_in = row["delta"] > 0
            f_qty = ft.TextField(label="تعداد", value=str(abs(row["delta"])), keyboard_type=ft.KeyboardType.NUMBER,
                                 border_color=C_BLUE)
            f_price = ft.TextField(label="قیمت واحد", value=str(row["price"]), keyboard_type=ft.KeyboardType.NUMBER,
                                   border_color=C_BLUE, visible=is_in)
            f_supplier = ft.TextField(label="فروشنده", value=row["supplier"] or "", border_color=C_BLUE,
                                      visible=is_in)
            f_invoice = ft.TextField(label="شماره فاکتور", value=row["invoice_no"] or "", border_color=C_BLUE,
                                     visible=is_in)
            f_receipt = ft.TextField(label="شماره رسید انبار", value=row["receipt_no"] or "", border_color=C_BLUE,
                                     visible=is_in)
            f_note = ft.TextField(label="یادداشت", value=row["note"] or "", border_color=C_BLUE)
            f_date = ft.TextField(label="تاریخ (شمسی)", value=row["jdate"], border_color=C_BLUE)

            def save(e):
                try:
                    qty = float(f_qty.value or 0)
                    price = float(f_price.value or 0) if is_in else 0
                except ValueError:
                    show_dialog("خطا", "مقادیر نادرست است", C_RED)
                    return
                if qty <= 0:
                    show_dialog("خطا", "تعداد باید بزرگتر از صفر باشد", C_YELLOW)
                    return
                ok = db.update_txn(txn_id, is_in, qty, price,
                                   f_supplier.value.strip() if is_in else "",
                                   f_note.value.strip(), f_date.value.strip(),
                                   f_invoice.value.strip() if is_in else "",
                                   f_receipt.value.strip() if is_in else "")
                if not ok:
                    show_dialog("خطا", "موجودی کافی نیست!", C_RED)
                    return
                show_dialog("موفق", "ویرایش شد ✓", C_GREEN)
                back_fn()

            def delete(e):
                db.delete_txn(txn_id)
                show_dialog("حذف", "تراکنش حذف شد", C_RED)
                back_fn()

            set_body([
                page_header("ویرایش تراکنش", back_fn),
                ft.Container(padding=16, content=ft.Column(spacing=12, controls=[
                    ft.Container(border_radius=10, bgcolor="#EFF6FF", padding=12,
                                 content=ft.Column(spacing=4, controls=[
                                     ft.Text("کالا: " + row["product_name"], size=14, weight=ft.FontWeight.BOLD,
                                             color=C_DARK),
                                     ft.Text("نوع: " + ("ورود" if is_in else "خروج"), size=13,
                                             color=C_GREEN if is_in else C_RED),
                                 ])),
                    f_qty, f_price, f_supplier, f_invoice, f_receipt, f_note, f_date,
                    ft.Container(height=4),
                    ft.ElevatedButton("ذخیره تغییرات", on_click=save, bgcolor=C_BLUE, color="white",
                                      height=48, expand=True),
                    ft.ElevatedButton("حذف این تراکنش", on_click=delete, bgcolor=C_RED, color="white",
                                      height=44, expand=True),
                ])),
            ])

        # ========== گزارشات (همه فرمت‌شده) ==========
        def render_reports():
            nonlocal report_rows
            f_start = ft.TextField(label="از تاریخ", hint_text="1403-01-01", expand=True, border_color=C_BLUE)
            f_end = ft.TextField(label="تا تاریخ", hint_text="1403-12-29", expand=True, border_color=C_BLUE)
            f_product = ft.TextField(label="نام کالا", border_color=C_BLUE)
            f_supplier = ft.TextField(label="نام فروشنده", border_color=C_BLUE)
            f_invoice = ft.TextField(label="شماره فاکتور", expand=True, border_color=C_BLUE)
            f_receipt = ft.TextField(label="شماره رسید انبار", expand=True, border_color=C_BLUE)
            f_type = ft.Dropdown(label="نوع", options=[ft.dropdown.Option(x) for x in ["همه", "ورود", "خروج"]],
                                 value="همه")
            f_cat = ft.Dropdown(label="دسته‌بندی", options=[ft.dropdown.Option(x) for x in ["همه"] + CATS],
                                value="همه")
            results = ft.Column(spacing=8)
            active_rtab = [0]

            tab0 = ft.Container(expand=True, padding=10, bgcolor=C_BLUE,
                                content=ft.Text("تراکنش‌ها", size=12, text_align=ft.TextAlign.CENTER,
                                               color="white", weight=ft.FontWeight.BOLD))
            tab1 = ft.Container(expand=True, padding=10, bgcolor=C_WHITE,
                                content=ft.Text("خلاصه کالا", size=12, text_align=ft.TextAlign.CENTER,
                                               color=C_GRAY))
            tab2 = ft.Container(expand=True, padding=10, bgcolor=C_WHITE,
                                content=ft.Text("فروشندگان", size=12, text_align=ft.TextAlign.CENTER,
                                               color=C_GRAY))
            tab3 = ft.Container(expand=True, padding=10, bgcolor=C_WHITE,
                                content=ft.Text("کم‌موجود", size=12, text_align=ft.TextAlign.CENTER,
                                               color=C_GRAY))
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
                end = f_end.value.strip()
                results.controls.clear()

                if tab == 0:
                    rows = db.search_txns(start, end, f_product.value.strip(), f_supplier.value.strip(),
                                          f_type.value, f_cat.value, f_invoice.value.strip(),
                                          f_receipt.value.strip())
                    report_rows = list(rows)
                    if not rows:
                        results.controls.append(ft.Text("نتیجه‌ای یافت نشد", color=C_GRAY, size=15))
                    else:
                        total_in = sum(r["delta"] for r in rows if r["delta"] > 0)
                        total_out = sum(abs(r["delta"]) for r in rows if r["delta"] < 0)
                        total_val = sum(abs(r["delta"]) * r["price"] for r in rows if r["delta"] > 0)
                        results.controls.append(
                            ft.Container(border_radius=10, bgcolor="#EFF6FF", padding=12,
                                         content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                             ft.Column(spacing=2, controls=[
                                                 ft.Text("ورود", size=11, color=C_GRAY),
                                                 ft.Text("{:,.2f}".format(total_in), size=15,
                                                         weight=ft.FontWeight.BOLD, color=C_GREEN)
                                             ]),
                                             ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                                       controls=[
                                                           ft.Text("خروج", size=11, color=C_GRAY),
                                                           ft.Text("{:,.2f}".format(total_out), size=15,
                                                                   weight=ft.FontWeight.BOLD, color=C_RED)
                                                       ]),
                                             ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END,
                                                       controls=[
                                                           ft.Text("ارزش ورودی", size=11, color=C_GRAY),
                                                           ft.Text("{:,.2f} ت".format(total_val), size=15,
                                                                   weight=ft.FontWeight.BOLD, color=C_BLUE)
                                                       ]),
                                         ]))
                        )
                        for r in rows:
                            is_in = r["delta"] > 0
                            tid = r["id"]

                            def make_edit(t):
                                def fn(e):
                                    show_edit_txn(t, render_reports)
                                return fn

                            info = []
                            if r["supplier"]: info.append("فروشنده: " + r["supplier"])
                            if r["invoice_no"]: info.append("فاکتور: " + r["invoice_no"])
                            if r["receipt_no"]: info.append("رسید: " + r["receipt_no"])
                            if r["note"]: info.append(r["note"])
                            results.controls.append(
                                ft.Container(border_radius=10, bgcolor=C_WHITE, padding=12,
                                             content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                                 ft.Column(spacing=3, expand=True, controls=[
                                                     ft.Text(r["product_name"], size=14,
                                                             weight=ft.FontWeight.BOLD, color=C_DARK),
                                                     ft.Text(r["jdate"] + " | " + r["category"], size=11,
                                                             color=C_GRAY),
                                                 ] + [ft.Text(line, size=11, color=C_BLUE) for line in info]),
                                                 ft.Column(spacing=4,
                                                           horizontal_alignment=ft.CrossAxisAlignment.END,
                                                           controls=[
                                                               ft.Container(border_radius=6, padding=6,
                                                                            bgcolor="#DCFCE7" if is_in else "#FEE2E2",
                                                                            content=ft.Text(
                                                                                ("↑ " if is_in else "↓ ") + str(
                                                                                    abs(r["delta"])),
                                                                                color=C_GREEN if is_in else C_RED,
                                                                                size=13,
                                                                                weight=ft.FontWeight.BOLD)),
                                                               ft.Text("{:,.2f} ت".format(
                                                                   abs(r["delta"]) * r["price"]) if is_in else "",
                                                                       size=11, color=C_GRAY),
                                                               ft.IconButton(ft.Icons.EDIT_OUTLINED,
                                                                             icon_color=C_BLUE,
                                                                             icon_size=16,
                                                                             on_click=make_edit(tid)),
                                                           ]),
                                             ]))
                            )

                elif tab == 1:
                    rows = db.summary_by_product(start, end, f_cat.value)
                    if not rows:
                        results.controls.append(ft.Text("نتیجه‌ای یافت نشد", color=C_GRAY))
                    else:
                        for r in rows:
                            results.controls.append(
                                ft.Container(border_radius=10, bgcolor=C_WHITE, padding=12,
                                             content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                                 ft.Column(spacing=2, expand=True, controls=[
                                                     ft.Text(r["product_name"], size=14,
                                                             weight=ft.FontWeight.BOLD, color=C_DARK),
                                                     ft.Text(r["category"], size=11, color=C_GRAY)
                                                 ]),
                                                 ft.Column(spacing=2,
                                                           horizontal_alignment=ft.CrossAxisAlignment.END,
                                                           controls=[
                                                               ft.Text("ورود: {0:,.2f}".format(r["total_in"]), size=12,
                                                                       color=C_GREEN),
                                                               ft.Text("خروج: {0:,.2f}".format(r["total_out"]), size=12,
                                                                       color=C_RED),
                                                               ft.Text("{:,.2f} ت".format(r["total_val"]), size=12,
                                                                       weight=ft.FontWeight.BOLD, color=C_BLUE),
                                                           ]),
                                             ]))
                            )

                elif tab == 2:
                    rows = db.summary_by_supplier(start, end)
                    if not rows:
                        results.controls.append(ft.Text("نتیجه‌ای یافت نشد", color=C_GRAY))
                    else:
                        for r in rows:
                            results.controls.append(
                                ft.Container(border_radius=10, bgcolor=C_WHITE, padding=12,
                                             content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                                 ft.Column(spacing=2, expand=True, controls=[
                                                     ft.Text(r["supplier"], size=14, weight=ft.FontWeight.BOLD,
                                                             color=C_DARK),
                                                     ft.Text(
                                                         str(r["cnt"]) + " بار خرید | " + str(
                                                             r["total_qty"]) + " واحد",
                                                         size=12, color=C_GRAY),
                                                 ]),
                                                 ft.Column(spacing=2,
                                                           horizontal_alignment=ft.CrossAxisAlignment.END,
                                                           controls=[
                                                               ft.Text("جمع خرید", size=10, color=C_GRAY),
                                                               ft.Text("{:,.2f} ت".format(r["total_val"]), size=14,
                                                                       weight=ft.FontWeight.BOLD, color=C_BLUE),
                                                           ]),
                                             ]))
                            )

                elif tab == 3:
                    lows = db.low_stock()
                    if not lows:
                        results.controls.append(
                            ft.Container(border_radius=10, bgcolor="#DCFCE7", padding=16,
                                         content=ft.Row(spacing=8, controls=[
                                             ft.Icon(ft.Icons.CHECK_CIRCLE, color=C_GREEN),
                                             ft.Text("همه کالاها موجودی کافی دارند", size=14, color=C_GREEN)
                                         ]))
                        )
                    else:
                        for r in lows:
                            qty = db.qty(r["name"])
                            results.controls.append(
                                ft.Container(border_radius=10, bgcolor="#FEF2F2", padding=12,
                                             content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                                 ft.Column(spacing=2, expand=True, controls=[
                                                     ft.Text(r["name"], size=14, weight=ft.FontWeight.BOLD,
                                                             color=C_DARK),
                                                     ft.Text(r["category"], size=12, color=C_GRAY)
                                                 ]),
                                                 ft.Column(spacing=2,
                                                           horizontal_alignment=ft.CrossAxisAlignment.END,
                                                           controls=[
                                                               ft.Text("موجودی: " + str(qty) + " " + r["unit"],
                                                                       size=13, color=C_RED,
                                                                       weight=ft.FontWeight.BOLD),
                                                               ft.Text("حداقل: " + str(r["min_qty"]), size=11,
                                                                       color=C_GRAY),
                                                           ]),
                                             ]))
                            )
                page.update()

            def export_csv(e):
                nonlocal report_rows
                if not report_rows:
                    show_dialog("خطا", "ابتدا جستجو کنید", C_YELLOW)
                    return
                try:
                    content = db.build_csv_text(report_rows)
                    show_text_page("گزارش CSV", content, render_reports)
                except Exception as ex:
                    show_dialog("خطا", str(ex), C_RED)

            def export_txt(e):
                nonlocal report_rows
                if not report_rows:
                    show_dialog("خطا", "ابتدا جستجو کنید", C_YELLOW)
                    return
                try:
                    content = db.build_txt(report_rows)
                    show_text_page("گزارش متنی", content, render_reports)
                except Exception as ex:
                    show_dialog("خطا", str(ex), C_RED)

            set_body([
                page_header("گزارشات"),
                ft.Container(padding=12, content=ft.Column(spacing=10, controls=[
                    ft.Row(controls=[f_start, f_end], spacing=10),
                    f_product, f_supplier,
                    ft.Row(controls=[f_invoice, f_receipt], spacing=10),
                    ft.Row(controls=[f_type, f_cat], spacing=10),
                    ft.Row(spacing=10, controls=[
                        ft.ElevatedButton("🔍 نمایش", on_click=search, bgcolor=C_BLUE, color="white",
                                          expand=True, height=44),
                        ft.ElevatedButton("📥 CSV", on_click=export_csv, bgcolor=C_WHITE, color=C_BLUE,
                                          height=44),
                        ft.ElevatedButton("🖨", on_click=export_txt, bgcolor=C_WHITE, color=C_BLUE,
                                          height=44, width=54),
                    ]),
                ])),
                ft.Container(bgcolor=C_WHITE, content=tabs_row),
                ft.Container(padding=12, content=results),
            ])

        # ========== پشتیبان‌گیری ==========
        def show_backup():
            backups = db.list_backups()

            def do_backup(e):
                try:
                    path = db.manual_backup()
                    show_dialog("بکاپ ذخیره شد ✓",
                                "فایل در حافظه داخلی برنامه ذخیره شد.\n\nنام فایل:\n" + Path(path).name,
                                C_GREEN)
                    show_backup()
                except Exception as ex:
                    show_dialog("خطا", str(ex), C_RED)

            def do_bale_backup(e):
                try:
                    success = db.send_to_bale()
                    if success:
                        show_dialog("موفق ✓", "بکاپ به بله ارسال شد!", C_GREEN)
                    else:
                        show_dialog("خطا", "ارسال ناموفق. اینترنت یا اطلاعات ربات را بررسی کنید.", C_RED)
                except Exception as ex:
                    show_dialog("خطا", str(ex), C_RED)

            def do_download_from_bale(e):
                fname = db.download_backup_from_bale()
                if fname:
                    show_dialog("موفق", f"فایل {fname} از بله دریافت و به لیست بک‌آپ‌ها اضافه شد.", C_GREEN)
                    show_backup()
                else:
                    show_dialog("خطا",
                                "نتوانستیم فایلی پیدا کنیم.\nمطمئن شوید فایل .db را در ربات برای خود ربات فرستاده‌اید.",
                                C_RED)

            def do_restore(path):
                try:
                    db.restore(path)
                    render_products()
                    page.snack_bar = ft.SnackBar(
                        ft.Text("✅ بازگردانی با موفقیت انجام شد", color="white"),
                        bgcolor=C_GREEN
                    )
                    page.snack_bar.open = True
                    page.update()
                except Exception as ex:
                    show_dialog("خطا", str(ex), C_RED)

            items = [
                ft.Container(border_radius=12, bgcolor="#EFF6FF", padding=14,
                             content=ft.Column(spacing=6, controls=[
                                 ft.Row(spacing=8, controls=[
                                     ft.Icon(ft.Icons.INFO_OUTLINE, color=C_BLUE, size=18),
                                     ft.Text("پشتیبان‌گیری", size=14, weight=ft.FontWeight.BOLD, color=C_BLUE)
                                 ]),
                                 ft.Text("بکاپ خودکار: هر روز یک بار (۷ روز اخیر)", size=12, color=C_GRAY),
                                 ft.Text("بکاپ دستی: در حافظه داخلی برنامه", size=12, color=C_GRAY),
                             ])),
                ft.Container(height=8),
                ft.ElevatedButton("💾  تهیه بکاپ دستی", on_click=do_backup, bgcolor=C_BLUE, color="white",
                                  height=48, expand=True),
                ft.Container(height=4),
                ft.ElevatedButton("📨  ارسال بکاپ به بله", on_click=do_bale_backup, bgcolor="#229ED9",
                                  color="white", height=48, expand=True),
                ft.Container(height=12),
                ft.Text("📥 دریافت آخرین بک‌آپ از بله", size=14, weight=ft.FontWeight.BOLD,
                        color=C_DARK),
                ft.Text("فایل بک‌آپ (.db) را در ربات بله برای خود ربات بفرستید، سپس دکمهٔ زیر را بزنید.",
                        size=12, color=C_GRAY),
                ft.ElevatedButton("📩 دریافت از بله", on_click=do_download_from_bale, bgcolor=C_ORANGE,
                                  color="white", height=48, expand=True),
                ft.Container(height=8),
                ft.ElevatedButton("🔄 بازخوانی لیست بکاپ‌ها", on_click=lambda e: show_backup(),
                                  bgcolor=C_BLUE, color="white", height=44, expand=True),
                ft.Container(height=8),
                ft.Text("لیست بکاپ‌ها (" + str(len(backups)) + "):", size=14, weight=ft.FontWeight.BOLD,
                        color=C_DARK),
            ]

            if not backups:
                items.append(ft.Text("هنوز بکاپی وجود ندارد", color=C_GRAY))
            else:
                for bp in backups:
                    name = Path(bp).name
                    is_auto = name.startswith("auto_")
                    items.append(
                        ft.Container(border_radius=10, bgcolor=C_WHITE, padding=12,
                                     content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                         ft.Column(spacing=4, expand=True, controls=[
                                             ft.Text(name, size=12, color=C_DARK),
                                             ft.Container(border_radius=20,
                                                          bgcolor=C_GREEN + "20" if is_auto else C_BLUE + "20",
                                                          padding=6,
                                                          content=ft.Text(
                                                              "خودکار" if is_auto else "دستی", size=10,
                                                              color=C_GREEN if is_auto else C_BLUE)),
                                         ]),
                                         ft.TextButton("بازگردانی",
                                                       on_click=lambda e, p=bp: do_restore(p)),
                                     ]))
                    )

            set_body([
                page_header("پشتیبان‌گیری", render_products),
                ft.Container(padding=16, content=ft.Column(spacing=10, controls=items)),
            ])

        # ========== نوار تب ==========
        tab_bar_row = ft.Row(spacing=0)

        def refresh_tabs():
            def make_tab(label, icon, index):
                def click(e):
                    active_tab[0] = index
                    refresh_tabs()
                    if index == 0:
                        render_products()
                    elif index == 1:
                        render_enter()
                    elif index == 2:
                        render_exit()
                    else:
                        render_reports()

                is_active = active_tab[0] == index
                return ft.Container(expand=True, on_click=click, padding=8,
                                    content=ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                                      spacing=2, controls=[
                                            ft.Icon(icon, color=C_BLUE if is_active else C_GRAY, size=22),
                                            ft.Text(label, size=10, color=C_BLUE if is_active else C_GRAY,
                                                    weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.NORMAL),
                                        ]))

            tab_bar_row.controls = [
                make_tab("انبار", ft.Icons.INVENTORY_2, 0),
                make_tab("ورود", ft.Icons.ARROW_UPWARD, 1),
                make_tab("خروج", ft.Icons.ARROW_DOWNWARD, 2),
                make_tab("گزارشات", ft.Icons.BAR_CHART, 3),
            ]
            tab_bar_row.update()

        page.add(ft.Column(expand=True, spacing=0, controls=[
            ft.Container(expand=True, content=body),
            ft.Container(bgcolor=C_WHITE, padding=4, content=tab_bar_row),
        ]))

        refresh_tabs()
        render_products()

    except Exception:
        log_error("FATAL ERROR in main():\n" + traceback.format_exc())


if __name__ == "__main__":
    ft.app(target=main)
