
import flet as ft
import sqlite3
import jdatetime
import datetime
import os
import shutil
import csv
from pathlib import Path


class DB:
    def __init__(self):
        storage = os.getenv("FLET_APP_STORAGE_DATA")
        base = Path(storage) if storage else Path.home() / ".warehouse_pro"
        base.mkdir(parents=True, exist_ok=True)
        self.path = str(base / "warehouse.db")
        self._init()

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
                category TEXT NOT NULL DEFAULT 'عمومی',
                min_qty REAL NOT NULL DEFAULT 0,
                price REAL NOT NULL DEFAULT 0,
                supplier TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS txns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT NOT NULL,
                delta REAL NOT NULL,
                balance REAL NOT NULL,
                price REAL NOT NULL DEFAULT 0,
                category TEXT DEFAULT '',
                supplier TEXT DEFAULT '',
                note TEXT DEFAULT '',
                jdate TEXT NOT NULL,
                ts TEXT NOT NULL
            )""")

    def all_products(self):
        with self._conn() as c:
            return c.execute("SELECT * FROM products ORDER BY category, name").fetchall()

    def add_product(self, name, unit, category, min_qty, price, supplier, initial=0):
        with self._conn() as c:
            c.execute(
                "INSERT INTO products (name,unit,category,min_qty,price,supplier) VALUES (?,?,?,?,?,?)",
                (name, unit, category, min_qty, price, supplier),
            )
        if initial > 0:
            self.add_txn(name, initial, price, category, supplier, "موجودی اولیه")

    def update_product(self, pid, name, unit, category, min_qty, price, supplier):
        with self._conn() as c:
            c.execute(
                "UPDATE products SET name=?,unit=?,category=?,min_qty=?,price=?,supplier=? WHERE id=?",
                (name, unit, category, min_qty, price, supplier, pid),
            )

    def delete_product(self, name):
        with self._conn() as c:
            c.execute("DELETE FROM products WHERE name=?", (name,))

    def qty(self, name):
        with self._conn() as c:
            r = c.execute("SELECT COALESCE(SUM(delta),0) FROM txns WHERE product_name=?", (name,)).fetchone()
            return r[0]

    def add_txn(self, name, delta, price, category, supplier, note="", jdate=None):
        balance = self.qty(name) + delta
        if balance < 0:
            return False
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        jd = jdate or jdatetime.datetime.now().strftime("%Y-%m-%d")
        with self._conn() as c:
            c.execute(
                "INSERT INTO txns (product_name,delta,balance,price,category,supplier,note,jdate,ts) VALUES (?,?,?,?,?,?,?,?,?)",
                (name, delta, balance, price, category, supplier, note, jd, now),
            )
        return True

    def search_txns(self, start="", end="", keyword="", supplier_kw=""):
        conds = []
        params = []
        if start and end:
            conds.append("jdate BETWEEN ? AND ?")
            params += [start, end]
        if keyword:
            conds.append("product_name LIKE ?")
            params.append("%" + keyword + "%")
        if supplier_kw:
            conds.append("supplier LIKE ?")
            params.append("%" + supplier_kw + "%")
        q = "SELECT * FROM txns"
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY ts DESC"
        with self._conn() as c:
            return c.execute(q, params).fetchall()

    def export_csv(self, rows, path):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["تاریخ", "کالا", "نوع", "تعداد", "قیمت", "موجودی", "فروشنده", "یادداشت"])
            for r in rows:
                w.writerow([
                    r["jdate"], r["product_name"],
                    "ورود" if r["delta"] > 0 else "خروج",
                    abs(r["delta"]), r["price"], r["balance"],
                    r["supplier"], r["note"],
                ])

    def backup(self):
        dl = os.getenv("FLET_APP_STORAGE_DOWNLOADS") or os.path.expanduser("~/Downloads")
        dl = Path(dl)
        dl.mkdir(parents=True, exist_ok=True)
        name = "backup_" + jdatetime.datetime.now().strftime("%Y-%m-%d_%H-%M") + ".db"
        dest = dl / name
        shutil.copy2(self.path, dest)
        return str(dest)

    def list_backups(self):
        dl = os.getenv("FLET_APP_STORAGE_DOWNLOADS") or os.path.expanduser("~/Downloads")
        files = sorted(Path(dl).glob("backup_*.db"), reverse=True)
        return [str(f) for f in files]

    def restore(self, backup_path):
        shutil.copy2(backup_path, self.path)


C_BLUE  = "#1E3A5F"
C_GREEN = "#2ECC71"
C_RED   = "#E74C3C"
C_WARN  = "#F39C12"
C_BG    = "#F0F4F8"
C_WHITE = "#FFFFFF"
C_DARK  = "#1A1A2E"
C_GRAY  = "#6B7280"

CATS = ["عمومی", "ساختمانی", "آشپزخانه", "ابزارآلات", "الکتریکی", "سایر"]


def main(page: ft.Page):
    page.title = "انباردار حرفه‌ای"
    page.rtl = True
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = C_BG
    page.padding = 0
    page.scroll = ft.ScrollMode.AUTO

    db = DB()
    active_tab = [0]
    report_rows = []
    body = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=0)

    def snack(msg, color=C_BLUE):
        page.snack_bar = ft.SnackBar(
            ft.Text(msg, color="white"),
            bgcolor=color,
            duration=2500,
        )
        page.snack_bar.open = True
        page.update()

    def set_body(controls):
        body.controls = controls
        body.update()

    # ── کارت کالا ──────────────────────────────
    def product_card(row):
        qty = db.qty(row["name"])
        low = qty <= row["min_qty"] and row["min_qty"] > 0
        qty_color = C_RED if low else C_GREEN

        def on_edit(e, r=row):
            show_product_form(r)

        def on_delete(e, n=row["name"]):
            db.delete_product(n)
            snack(n + " حذف شد", C_RED)
            render_products()

        card = ft.Container(
            margin=8,
            border_radius=12,
            bgcolor=C_WHITE,
            padding=12,
            content=ft.Column(
                spacing=8,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Column(
                                spacing=2,
                                expand=True,
                                controls=[
                                    ft.Text(row["name"], size=16, weight=ft.FontWeight.BOLD, color=C_DARK),
                                    ft.Text(row["category"] + " | " + (row["supplier"] or "—"), size=12, color=C_GRAY),
                                ],
                            ),
                            ft.Row(
                                spacing=0,
                                controls=[
                                    ft.IconButton(ft.Icons.EDIT_OUTLINED, icon_color=C_BLUE, icon_size=20, on_click=on_edit),
                                    ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_color=C_RED, icon_size=20, on_click=on_delete),
                                ],
                            ),
                        ],
                    ),
                    ft.Divider(height=1),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Column(spacing=2, controls=[
                                ft.Text("موجودی", size=11, color=C_GRAY),
                                ft.Text(str(qty) + " " + row["unit"], size=15, weight=ft.FontWeight.BOLD, color=qty_color),
                            ]),
                            ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                                ft.Text("قیمت واحد", size=11, color=C_GRAY),
                                ft.Text("{:,.0f} ت".format(row["price"]), size=13, color=C_DARK),
                            ]),
                            ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END, controls=[
                                ft.Text("ارزش", size=11, color=C_GRAY),
                                ft.Text("{:,.0f} ت".format(qty * row["price"]), size=13, weight=ft.FontWeight.BOLD, color=C_BLUE),
                            ]),
                        ],
                    ),
                ],
            ),
        )
        if low:
            card.content.controls.append(
                ft.Container(
                    border_radius=6,
                    bgcolor="#FEF2F2",
                    padding=6,
                    content=ft.Text("⚠️ موجودی زیر حداقل!", size=12, color=C_RED),
                )
            )
        return card

    # ── تب کالاها ──────────────────────────────
    def render_products():
        rows = db.all_products()
        total = sum(db.qty(r["name"]) * r["price"] for r in rows)

        controls = [
            ft.Container(
                padding=16,
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Column(spacing=2, controls=[
                            ft.Text("انبار کالا", size=22, weight=ft.FontWeight.BOLD, color=C_DARK),
                            ft.Text(str(len(rows)) + " قلم کالا", size=13, color=C_GRAY),
                        ]),
                        ft.Container(
                            border_radius=10,
                            bgcolor=C_BLUE,
                            padding=10,
                            content=ft.Column(
                                spacing=0,
                                horizontal_alignment=ft.CrossAxisAlignment.END,
                                controls=[
                                    ft.Text("ارزش کل", size=10, color="#AECBFF"),
                                    ft.Text("{:,.0f} ت".format(total), size=14, weight=ft.FontWeight.BOLD, color="white"),
                                ],
                            ),
                        ),
                    ],
                ),
            ),
            ft.Container(
                padding=16,
                content=ft.Row(
                    spacing=10,
                    controls=[
                        ft.ElevatedButton(
                            "➕ کالای جدید",
                            on_click=lambda e: show_product_form(),
                            bgcolor=C_BLUE,
                            color="white",
                            expand=True,
                        ),
                        ft.ElevatedButton(
                            "💾 بکاپ",
                            on_click=lambda e: show_backup(),
                            bgcolor=C_WHITE,
                            color=C_BLUE,
                        ),
                    ],
                ),
            ),
        ]

        if not rows:
            controls.append(ft.Container(
                padding=40,
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, size=60, color=C_GRAY),
                        ft.Text("هنوز کالایی ثبت نشده", size=16, color=C_GRAY),
                    ],
                ),
            ))
        else:
            for r in rows:
                controls.append(product_card(r))

        set_body(controls)

    # ── فرم کالا ───────────────────────────────
    def show_product_form(row=None):
        is_edit = row is not None
        f_name     = ft.TextField(label="نام کالا", value=row["name"] if is_edit else "")
        f_unit     = ft.TextField(label="واحد", value=row["unit"] if is_edit else "عدد")
        f_cat      = ft.Dropdown(
            label="دسته‌بندی",
            options=[ft.dropdown.Option(c) for c in CATS],
            value=row["category"] if is_edit else "عمومی",
        )
        f_min      = ft.TextField(label="حداقل موجودی", value=str(row["min_qty"]) if is_edit else "0", keyboard_type=ft.KeyboardType.NUMBER)
        f_price    = ft.TextField(label="قیمت خرید (تومان)", value=str(row["price"]) if is_edit else "0", keyboard_type=ft.KeyboardType.NUMBER)
        f_supplier = ft.TextField(label="فروشنده / تأمین‌کننده", value=row["supplier"] if is_edit else "")
        f_initial  = ft.TextField(label="موجودی اولیه", value="0", keyboard_type=ft.KeyboardType.NUMBER)

        def save(e):
            name = f_name.value.strip()
            if not name:
                snack("نام کالا را وارد کنید", C_RED)
                return
            try:
                min_qty = float(f_min.value or 0)
                price   = float(f_price.value or 0)
                initial = float(f_initial.value or 0) if not is_edit else 0
            except ValueError:
                snack("مقادیر عددی نادرست است", C_RED)
                return
            try:
                if is_edit:
                    db.update_product(row["id"], name, f_unit.value, f_cat.value, min_qty, price, f_supplier.value.strip())
                    snack(name + " ویرایش شد")
                else:
                    db.add_product(name, f_unit.value, f_cat.value, min_qty, price, f_supplier.value.strip(), initial)
                    snack(name + " اضافه شد", C_GREEN)
            except sqlite3.IntegrityError:
                snack("این نام قبلاً ثبت شده است", C_RED)
                return
            render_products()

        items = [f_name, f_unit, f_cat, f_min, f_price, f_supplier]
        if not is_edit:
            items.append(f_initial)
        items.append(ft.ElevatedButton(
            "ذخیره" if is_edit else "افزودن",
            on_click=save,
            bgcolor=C_BLUE,
            color="white",
            height=48,
            expand=True,
        ))

        set_body([
            ft.Container(
                padding=16,
                content=ft.Row(controls=[
                    ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda e: render_products(), icon_color=C_BLUE),
                    ft.Text("ویرایش کالا" if is_edit else "کالای جدید", size=20, weight=ft.FontWeight.BOLD, color=C_DARK),
                ]),
            ),
            ft.Container(padding=16, content=ft.Column(spacing=12, controls=items)),
        ])

    # ── تب ورود/خروج ───────────────────────────
    def render_txn():
        products = db.all_products()
        if not products:
            set_body([ft.Container(
                padding=40,
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, size=60, color=C_GRAY),
                        ft.Text("ابتدا کالا اضافه کنید", size=16, color=C_GRAY),
                    ],
                ),
            )])
            return

        names = [r["name"] for r in products]
        f_product = ft.Dropdown(
            label="انتخاب کالا",
            options=[ft.dropdown.Option(n) for n in names],
            value=names[0],
        )
        f_delta   = ft.TextField(label="تعداد (مثبت=ورود / منفی=خروج)", value="1", keyboard_type=ft.KeyboardType.NUMBER)
        f_note    = ft.TextField(label="یادداشت (اختیاری)")
        f_date    = ft.TextField(label="تاریخ شمسی", value=jdatetime.datetime.now().strftime("%Y-%m-%d"))
        qty_text  = ft.Text("موجودی فعلی: " + str(db.qty(names[0])), size=14, color=C_BLUE, weight=ft.FontWeight.BOLD)

        def on_change(e):
            qty_text.value = "موجودی فعلی: " + str(db.qty(f_product.value))
            page.update()

        f_product.on_change = on_change

        def save(e):
            try:
                delta = float(f_delta.value or 0)
            except ValueError:
                snack("تعداد نادرست است", C_RED)
                return
            if delta == 0:
                snack("تعداد نمی‌تواند صفر باشد", C_WARN)
                return
            row = next((r for r in products if r["name"] == f_product.value), None)
            ok = db.add_txn(row["name"], delta, row["price"], row["category"], row["supplier"], f_note.value.strip(), f_date.value.strip())
            if not ok:
                snack("موجودی کافی نیست!", C_RED)
                return
            snack("تراکنش ثبت شد ✓", C_GREEN)
            qty_text.value = "موجودی فعلی: " + str(db.qty(row["name"]))
            f_delta.value = "1"
            f_note.value = ""
            page.update()

        set_body([
            ft.Container(padding=16, content=ft.Text("ورود / خروج کالا", size=22, weight=ft.FontWeight.BOLD, color=C_DARK)),
            ft.Container(padding=16, content=ft.Column(spacing=12, controls=[
                f_product, qty_text, f_delta, f_note, f_date,
                ft.ElevatedButton("ثبت تراکنش", on_click=save, bgcolor=C_GREEN, color="white", height=50, expand=True),
            ])),
        ])

    # ── تب جستجو ───────────────────────────────
    def render_reports():
        nonlocal report_rows
        f_start    = ft.TextField(label="از تاریخ", hint_text="1403-01-01", expand=True)
        f_end      = ft.TextField(label="تا تاریخ", hint_text="1403-12-29", expand=True)
        f_product  = ft.TextField(label="نام کالا", hint_text="جستجو در نام کالا...")
        f_supplier = ft.TextField(label="نام فروشنده", hint_text="جستجو در فروشندگان...")
        results    = ft.Column(spacing=8)
        summary    = ft.Text("", size=13, color=C_GRAY)

        def search(e):
            nonlocal report_rows
            rows = db.search_txns(
                f_start.value.strip(), f_end.value.strip(),
                f_product.value.strip(), f_supplier.value.strip(),
            )
            report_rows = rows
            results.controls.clear()
            if not rows:
                summary.value = ""
                results.controls.append(ft.Text("نتیجه‌ای یافت نشد", color=C_GRAY, size=15))
            else:
                total_in  = sum(r["delta"] for r in rows if r["delta"] > 0)
                total_out = sum(abs(r["delta"]) for r in rows if r["delta"] < 0)
                summary.value = str(len(rows)) + " تراکنش | ورود: " + str(total_in) + " | خروج: " + str(total_out)
                for r in rows:
                    is_in = r["delta"] > 0
                    results.controls.append(ft.Container(
                        border_radius=10,
                        bgcolor=C_WHITE,
                        padding=12,
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Column(spacing=2, expand=True, controls=[
                                    ft.Text(r["product_name"], size=14, weight=ft.FontWeight.BOLD, color=C_DARK),
                                    ft.Text(r["jdate"] + " | " + (r["supplier"] or "—"), size=11, color=C_GRAY),
                                    ft.Text(r["note"] or "", size=11, color=C_GRAY),
                                ]),
                                ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END, controls=[
                                    ft.Container(
                                        border_radius=6,
                                        bgcolor="#E8FFF3" if is_in else "#FEF2F2",
                                        padding=6,
                                        content=ft.Text(
                                            ("↑ " if is_in else "↓ ") + str(abs(r["delta"])),
                                            color=C_GREEN if is_in else C_RED,
                                            size=13,
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                    ),
                                    ft.Text("مانده: " + str(r["balance"]), size=12, color=C_GRAY),
                                ]),
                            ],
                        ),
                    ))
            page.update()

        def export(e):
            if not report_rows:
                snack("ابتدا جستجو کنید", C_WARN)
                return
            dl = os.getenv("FLET_APP_STORAGE_DOWNLOADS") or os.path.expanduser("~/Downloads")
            fname = "report_" + jdatetime.datetime.now().strftime("%Y-%m-%d_%H-%M") + ".csv"
            db.export_csv(report_rows, Path(dl) / fname)
            snack("فایل CSV ذخیره شد ✓", C_GREEN)

        set_body([
            ft.Container(padding=16, content=ft.Text("جستجو و گزارشات", size=22, weight=ft.FontWeight.BOLD, color=C_DARK)),
            ft.Container(padding=16, content=ft.Column(spacing=10, controls=[
                ft.Row(controls=[f_start, f_end], spacing=10),
                f_product,
                f_supplier,
                ft.Row(spacing=10, controls=[
                    ft.ElevatedButton("🔍 جستجو", on_click=search, bgcolor=C_BLUE, color="white", expand=True),
                    ft.ElevatedButton("📥 CSV", on_click=export, bgcolor=C_WHITE, color=C_BLUE),
                ]),
                summary,
                ft.Divider(),
                results,
            ])),
        ])

    # ── پشتیبان‌گیری ────────────────────────────
    def show_backup():
        backups = db.list_backups()

        def do_backup(e):
            try:
                db.backup()
                snack("بکاپ ذخیره شد ✓", C_GREEN)
                show_backup()
            except Exception as ex:
                snack("خطا: " + str(ex), C_RED)

        def do_restore(path):
            try:
                db.restore(path)
                snack("بازگردانی انجام شد ✓", C_GREEN)
                render_products()
            except Exception as ex:
                snack("خطا: " + str(ex), C_RED)

        items = [
            ft.ElevatedButton("💾 تهیه بکاپ جدید", on_click=do_backup, bgcolor=C_BLUE, color="white", height=48, expand=True),
            ft.Text("بکاپ‌های قبلی:", size=14, weight=ft.FontWeight.BOLD, color=C_DARK),
        ]

        if not backups:
            items.append(ft.Text("هنوز بکاپی ثبت نشده", color=C_GRAY, size=14))
        else:
            for bp in backups:
                name = Path(bp).name
                items.append(ft.Container(
                    border_radius=10,
                    bgcolor=C_WHITE,
                    padding=12,
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text(name, size=12, color=C_DARK, expand=True),
                            ft.TextButton("بازگردانی", on_click=lambda e, p=bp: do_restore(p)),
                        ],
                    ),
                ))

        set_body([
            ft.Container(
                padding=16,
                content=ft.Row(controls=[
                    ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda e: render_products(), icon_color=C_BLUE),
                    ft.Text("پشتیبان‌گیری", size=20, weight=ft.FontWeight.BOLD, color=C_DARK),
                ]),
            ),
            ft.Container(padding=16, content=ft.Column(spacing=12, controls=items)),
        ])

    # ── نوار تب ────────────────────────────────
    tab_bar_row = ft.Row(spacing=0)

    def refresh_tabs():
        def make_tab(label, icon, index):
            def click(e):
                active_tab[0] = index
                refresh_tabs()
                [render_products, render_txn, render_reports][index]()

            is_active = active_tab[0] == index
            return ft.Container(
                expand=True,
                on_click=click,
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=2,
                    controls=[
                        ft.Icon(icon, color=C_BLUE if is_active else C_GRAY, size=24),
                        ft.Text(
                            label, size=11,
                            color=C_BLUE if is_active else C_GRAY,
                            weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.NORMAL,
                        ),
                    ],
                ),
            )

        tab_bar_row.controls = [
            make_tab("کالاها",    ft.Icons.INVENTORY_2, 0),
            make_tab("ورود/خروج", ft.Icons.SWAP_VERT,   1),
            make_tab("جستجو",     ft.Icons.SEARCH,      2),
        ]
        tab_bar_row.update()

    page.add(ft.Column(
        expand=True,
        spacing=0,
        controls=[
            ft.Container(expand=True, content=body),
            ft.Container(bgcolor=C_WHITE, padding=8, content=tab_bar_row),
        ],
    ))

    refresh_tabs()
    render_products()


if __name__ == "__main__":
    ft.app(target=main)
