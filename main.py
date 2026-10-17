import json
import os
import random
import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog, font as tkfont

import yt_dlp

# ---------- palette ----------
BG = "#0a0e0b"
PANEL = "#121913"
BORDER = "#24402a"
GREEN = "#97ce4c"
GREEN_HI = "#b9f06a"
CYAN = "#6fe3ff"
TEXT = "#d6e8cf"
MUTED = "#6c8270"
RED = "#ff5c5c"
AMBER = "#ffc857"

# ---------- VPN detection ----------
# Mullvad's endpoint says for certain if you're on a Mullvad exit. For every other
# provider we match the network owner name against this list. Add your provider
# here if it isn't detected.
CHECK_URL = "https://am.i.mullvad.net/json"
VPN_KEYWORDS = [
    "mullvad", "proton", "nordvpn", "nord security", "expressvpn", "express vpn", "surfshark",
    "private internet access", "windscribe", "ivpn", "cyberghost", "tunnelbear", "airvpn",
    "m247", "datacamp", "cdn77", "quadranet", "xtom", "leaseweb", "tzulo", "packethub",
    "cloudflare warp", "tor project", "hosting", "vpn", "colocation", "data center",
]
VPN_REGEX = re.compile(r"\b(" + "|".join(re.escape(k) for k in VPN_KEYWORDS) + r")\b", re.I)
RECHECK_SECONDS = 4

READY_LINES = [
    "Ready. Whenever you're done staring at it.",
    "Idle. Paste a link, genius.",
    "Standing by. Try not to break anything.",
]
DONE_LINES = [
    "Done. *burp* You're welcome.",
    "Done. That was barely science.",
    "Extracted. Go enjoy your noise.",
]


def pick_mono():
    available = set(tkfont.families())
    for name in ("JetBrains Mono", "Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono", "Courier New"):
        if name in available:
            return name
    return "TkFixedFont"


def check_connection(proxy=""):
    """Returns (state, text). state is 'secure', 'exposed' or 'unknown'."""
    opts = {"quiet": True, "no_warnings": True, "cachedir": False}
    if proxy:
        opts["proxy"] = proxy
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = json.loads(ydl.urlopen(CHECK_URL).read().decode("utf-8"))
    except Exception as e:
        return "unknown", f"CAN'T VERIFY ({type(e).__name__})"

    ip = data.get("ip", "?")
    org = data.get("organization") or "unknown network"
    place = ", ".join(x for x in (data.get("city"), data.get("country")) if x) or "unknown location"

    if data.get("mullvad_exit_ip"):
        return "secure", f"SECURE  ·  Mullvad exit  ·  {place}"
    if VPN_REGEX.search(org):
        return "secure", f"SECURE?  ·  {org}  ·  {place}"
    return "exposed", f"EXPOSED  ·  {ip}  ·  {org}"


def parse_time(text):
    """'90', '1:30' or '1:02:30' -> seconds. Empty -> None. Bad input -> ValueError."""
    text = text.strip()
    if not text:
        return None
    seconds = 0.0
    for part in text.split(":"):
        seconds = seconds * 60 + float(part)
    if seconds < 0:
        raise ValueError
    return seconds


class Logger:
    """Sends yt-dlp messages to the GUI log box."""

    def __init__(self, app):
        self.app = app

    def debug(self, msg):
        if not msg.startswith("[debug]"):
            self.app.log(msg)

    def info(self, msg):
        self.app.log(msg)

    def warning(self, msg):
        self.app.log("WARNING: " + msg)

    def error(self, msg):
        self.app.log("ERROR: " + msg)


class App:
    def __init__(self, root):
        self.root = root
        self.busy = False
        self.abort = False
        self.angle = 0
        self.mono = pick_mono()

        root.title("SONIC EXTRACTOR")
        root.geometry("720x810")
        root.minsize(580, 730)
        root.configure(bg=BG)
        self.dark_titlebar()

        self.f_body = (self.mono, 10)
        self.f_small = (self.mono, 8, "bold")
        self.f_title = (self.mono, 20, "bold")

        self.build_styles()
        self.build_header()
        self.build_vpn_bar()
        self.build_body()
        self.update_mode()
        self.animate()
        self.recheck()

    # ---------- setup ----------
    def dark_titlebar(self):
        """Dark title bar on Windows 10/11; silently ignored elsewhere."""
        try:
            import ctypes
            self.root.update()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            value = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
        except Exception:
            pass

    def build_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Portal.Horizontal.TProgressbar",
            troughcolor=PANEL, background=GREEN, bordercolor=BORDER,
            lightcolor=GREEN, darkcolor=GREEN, thickness=10,
        )
        style.configure(
            "Lab.TCombobox",
            fieldbackground=PANEL, background=PANEL, foreground=TEXT,
            arrowcolor=GREEN, bordercolor=BORDER, lightcolor=PANEL, darkcolor=PANEL,
            selectbackground=PANEL, selectforeground=TEXT, padding=4,
        )
        style.map(
            "Lab.TCombobox",
            fieldbackground=[("readonly", PANEL), ("disabled", PANEL)],
            foreground=[("disabled", BORDER), ("readonly", TEXT)],
            selectbackground=[("readonly", PANEL)],
            selectforeground=[("readonly", TEXT)],
            bordercolor=[("focus", GREEN)],
        )
        self.root.option_add("*TCombobox*Listbox.background", PANEL)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", GREEN)
        self.root.option_add("*TCombobox*Listbox.selectForeground", BG)
        self.root.option_add("*TCombobox*Listbox.font", (self.mono, 10))

    def build_header(self):
        header = tk.Canvas(self.root, height=100, bg=BG, highlightthickness=0)
        header.pack(fill="x")
        self.header = header

        cx, cy = 70, 50
        header.create_oval(cx - 46, cy - 46, cx + 46, cy + 46, outline="#1c3320", width=2)
        self.arcs = []
        for r, color, w in [(38, GREEN, 3), (30, GREEN_HI, 2), (22, GREEN, 3), (14, CYAN, 2)]:
            arc = header.create_arc(cx - r, cy - r, cx + r, cy + r, start=0, extent=250,
                                    style="arc", outline=color, width=w)
            self.arcs.append(arc)
        header.create_oval(cx - 6, cy - 6, cx + 6, cy + 6, fill=GREEN_HI, outline="")

        header.create_text(140, 38, anchor="w", text="SONIC EXTRACTOR", fill=GREEN, font=self.f_title)
        header.create_text(142, 70, anchor="w", fill=MUTED, font=(self.mono, 9),
                           text="paste a link. get an mp3. try not to overthink it.")
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")

    def build_vpn_bar(self):
        bar = tk.Frame(self.root, bg=PANEL, padx=22, pady=10)
        bar.pack(fill="x")
        self.vpn_label = tk.Label(bar, text="CHECKING CONNECTION...", bg=PANEL, fg=CYAN,
                                  font=(self.mono, 9, "bold"), anchor="w")
        self.vpn_label.pack(side="left", fill="x", expand=True)
        self.button(bar, "RECHECK", self.recheck).pack(side="right", ipadx=8)
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")

    def label(self, parent, text):
        return tk.Label(parent, text=text, bg=BG, fg=MUTED, font=self.f_small, anchor="w")

    def entry(self, parent, var):
        return tk.Entry(
            parent, textvariable=var, bg=PANEL, fg=TEXT, insertbackground=GREEN,
            relief="flat", font=self.f_body, highlightthickness=1,
            highlightbackground=BORDER, highlightcolor=GREEN,
            selectbackground=GREEN, selectforeground=BG,
        )

    def button(self, parent, text, command, primary=False):
        bg, fg = (GREEN, BG) if primary else (parent["bg"], GREEN)
        hover_bg, hover_fg = (GREEN_HI, BG) if primary else (GREEN, BG)
        btn = tk.Button(
            parent, text=text, command=command, bg=bg, fg=fg, activebackground=hover_bg,
            activeforeground=hover_fg, relief="flat", bd=0, cursor="hand2",
            font=(self.mono, 11 if primary else 9, "bold"), highlightthickness=0 if primary else 1,
            highlightbackground=GREEN, highlightcolor=GREEN,
        )
        btn.bind("<Enter>", lambda e: btn.configure(bg=hover_bg, fg=hover_fg) if btn["state"] != "disabled" else None)
        btn.bind("<Leave>", lambda e: btn.configure(bg=bg, fg=fg) if btn["state"] != "disabled" else None)
        return btn

    def build_body(self):
        body = tk.Frame(self.root, bg=BG, padx=22, pady=14)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(10, weight=1)

        # link
        self.label(body, "TARGET LINK").grid(row=0, column=0, columnspan=2, sticky="w")
        self.url_var = tk.StringVar()
        self.url_entry = self.entry(body, self.url_var)
        self.url_entry.grid(row=1, column=0, columnspan=2, sticky="ew", ipady=8, pady=(4, 10))
        self.url_entry.bind("<Return>", lambda e: self.start())
        self.url_entry.focus()

        # folder
        self.label(body, "DROP ZONE").grid(row=2, column=0, columnspan=2, sticky="w")
        self.folder_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Music"))
        self.entry(body, self.folder_var).grid(row=3, column=0, sticky="ew", ipady=8, pady=(4, 10))
        self.button(body, "BROWSE", self.browse).grid(row=3, column=1, sticky="ns", padx=(8, 0), pady=(4, 10), ipadx=12)

        # proxy
        self.label(body, "PROXY (OPTIONAL)  e.g. socks5h://127.0.0.1:9050").grid(row=4, column=0, columnspan=2, sticky="w")
        self.proxy_var = tk.StringVar()
        self.entry(body, self.proxy_var).grid(row=5, column=0, columnspan=2, sticky="ew", ipady=8, pady=(4, 10))

        # options
        wrap = tk.Frame(body, bg=BG)
        wrap.grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 6))
        row_a = tk.Frame(wrap, bg=BG)
        row_a.pack(anchor="w", pady=(0, 8))
        opts = tk.Frame(wrap, bg=BG)
        opts.pack(anchor="w")

        self.label(row_a, "MODE").pack(side="left")
        self.mode_var = tk.StringVar(value="MP3 (audio)")
        mode_box = ttk.Combobox(row_a, textvariable=self.mode_var, values=["MP3 (audio)", "MP4 (video)"],
                                width=12, state="readonly", style="Lab.TCombobox")
        mode_box.pack(side="left", padx=(8, 24))
        mode_box.bind("<<ComboboxSelected>>", lambda e: self.update_mode())
        self.label(row_a, "RESOLUTION").pack(side="left")
        self.res_var = tk.StringVar(value="BEST")
        self.res_box = ttk.Combobox(row_a, textvariable=self.res_var, values=["BEST", "1080", "720", "480", "360"],
                                    width=6, state="readonly", style="Lab.TCombobox")
        self.res_box.pack(side="left", padx=(8, 0))

        self.label(opts, "BITRATE").pack(side="left")
        self.bitrate_var = tk.StringVar(value="320")
        self.bit_box = ttk.Combobox(opts, textvariable=self.bitrate_var, values=["320", "256", "192", "128"],
                                    width=5, state="readonly", style="Lab.TCombobox")
        self.bit_box.pack(side="left", padx=(8, 24))
        self.playlist_var = tk.BooleanVar(value=False)
        self.check(opts, "FULL PLAYLIST", self.playlist_var).pack(side="left")

        self.label(opts, "START").pack(side="left", padx=(24, 6))
        self.start_var = tk.StringVar()
        self.entry(opts, self.start_var).pack(side="left", ipady=4)
        self.label(opts, "END").pack(side="left", padx=(12, 6))
        self.end_var = tk.StringVar()
        self.entry(opts, self.end_var).pack(side="left", ipady=4)
        for child in opts.winfo_children():
            if isinstance(child, tk.Entry):
                child.configure(width=8)

        # stealth options
        self.lock_var = tk.BooleanVar(value=True)
        self.check(body, "BLOCK DOWNLOADS WITHOUT A VPN  (and kill it if the VPN drops)", self.lock_var) \
            .grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 12))

        # go button
        self.go = self.button(body, "EXTRACT", self.start, primary=True)
        self.go.grid(row=8, column=0, columnspan=2, sticky="ew", ipady=10)

        # progress
        self.progress = ttk.Progressbar(body, maximum=100, style="Portal.Horizontal.TProgressbar")
        self.progress.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(14, 6))

        # log
        log_wrap = tk.Frame(body, bg=BORDER, padx=1, pady=1)
        log_wrap.grid(row=10, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        self.log_box = tk.Text(
            log_wrap, height=6, state="disabled", wrap="word", bg=PANEL, fg=GREEN,
            relief="flat", font=(self.mono, 9), padx=10, pady=8, highlightthickness=0,
            insertbackground=GREEN, selectbackground=GREEN, selectforeground=BG,
        )
        self.log_box.pack(fill="both", expand=True)
        self.log_box.tag_configure("err", foreground=RED)
        self.log_box.tag_configure("warn", foreground=AMBER)

        self.status_var = tk.StringVar(value=random.choice(READY_LINES))
        self.status_label = tk.Label(body, textvariable=self.status_var, bg=BG, fg=CYAN,
                                     font=(self.mono, 9), anchor="w")
        self.status_label.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(10, 0))

    def update_mode(self):
        """Bitrate only matters for MP3, resolution only for video."""
        video = self.mode_var.get().startswith("MP4")
        self.bit_box.configure(state="disabled" if video else "readonly")
        self.res_box.configure(state="readonly" if video else "disabled")

    def check(self, parent, text, var):
        return tk.Checkbutton(
            parent, text=text, variable=var, bg=BG, fg=TEXT, selectcolor=PANEL,
            activebackground=BG, activeforeground=GREEN, font=self.f_small,
            highlightthickness=0, bd=0, cursor="hand2",
        )

    # ---------- animation ----------
    def animate(self):
        self.angle = (self.angle + (9 if self.busy else 2)) % 360
        for i, arc in enumerate(self.arcs):
            direction = 1 if i % 2 == 0 else -1
            start = (self.angle * (i + 1) * 0.7 * direction) % 360
            self.header.itemconfigure(arc, start=start)
        self.root.after(33, self.animate)

    # ---------- thread-safe helpers ----------
    def log(self, text):
        tag = "err" if text.startswith("ERROR") else "warn" if text.startswith("WARNING") else ""

        def _do():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", "> " + text + "\n", tag)
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.root.after(0, _do)

    def set_status(self, text, color=CYAN):
        def _do():
            self.status_var.set(text)
            self.status_label.configure(fg=color)
        self.root.after(0, _do)

    def set_progress(self, value):
        self.root.after(0, lambda: self.progress.configure(value=value))

    def set_vpn(self, state, text):
        color = {"secure": GREEN, "exposed": RED, "unknown": AMBER}.get(state, CYAN)
        icon = {"secure": "●", "exposed": "▲", "unknown": "?"}.get(state, "…")
        self.root.after(0, lambda: self.vpn_label.configure(text=f"{icon}  {text}", fg=color))

    def set_busy(self, busy):
        def _do():
            self.busy = busy
            if busy:
                self.go.configure(state="disabled", text="EXTRACTING...", bg=BORDER, fg=MUTED)
            else:
                self.go.configure(state="normal", text="EXTRACT", bg=GREEN, fg=BG)
        self.root.after(0, _do)

    # ---------- actions ----------
    def browse(self):
        folder = filedialog.askdirectory(initialdir=self.folder_var.get())
        if folder:
            self.folder_var.set(folder)

    def recheck(self):
        proxy = self.proxy_var.get().strip() if hasattr(self, "proxy_var") else ""
        self.set_vpn("checking", "CHECKING CONNECTION...")

        def work():
            state, text = check_connection(proxy)
            self.set_vpn(state, text)
        threading.Thread(target=work, daemon=True).start()

    def start(self):
        if self.busy:
            return
        url = self.url_var.get().strip()
        if not url:
            self.set_status("No link? Seriously? Paste something.", RED)
            self.url_entry.configure(highlightbackground=RED, highlightcolor=RED)
            self.root.after(900, lambda: self.url_entry.configure(highlightbackground=BORDER, highlightcolor=GREEN))
            return
        folder = self.folder_var.get().strip()
        os.makedirs(folder, exist_ok=True)

        try:
            start_s = parse_time(self.start_var.get())
            end_s = parse_time(self.end_var.get())
            if start_s is not None and end_s is not None and end_s <= start_s:
                raise ValueError
        except ValueError:
            self.set_status("Bad start/end time. Use 90, 1:30 or 1:02:30, and end after start.", RED)
            return

        # capture UI values here, on the main thread
        settings = {
            "mode": self.mode_var.get(),
            "res": self.res_var.get(),
            "start": start_s,
            "end": end_s,
            "url": url,
            "folder": folder,
            "proxy": self.proxy_var.get().strip(),
            "bitrate": self.bitrate_var.get(),
            "playlist": self.playlist_var.get(),
            "lock": self.lock_var.get(),
        }
        self.abort = False
        self.set_busy(True)
        self.set_progress(0)
        self.set_status("Checking your connection first...")
        threading.Thread(target=self.download, args=(settings,), daemon=True).start()

    def monitor(self, proxy, stop):
        """Kill switch: re-checks the connection while a download runs."""
        while not stop.wait(RECHECK_SECONDS):
            state, text = check_connection(proxy)
            self.set_vpn(state, text)
            if state != "secure":
                self.abort = True
                self.log("ERROR: VPN dropped, killing the download.")
                return

    def progress_hook(self, d):
        if self.abort:
            raise yt_dlp.utils.DownloadCancelled("connection no longer protected")
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                self.set_progress(d["downloaded_bytes"] / total * 100)
            speed = d.get("_speed_str", "").strip()
            eta = d.get("_eta_str", "").strip()
            self.set_status(f"Pulling data... {d.get('_percent_str', '').strip()}  {speed}  ETA {eta}")
        elif d["status"] == "finished":
            self.set_progress(100)
            self.set_status("Crunching audio. Science takes a second.", AMBER)

    def download(self, s):
        stop = threading.Event()
        try:
            # preflight VPN check
            state, text = check_connection(s["proxy"])
            self.set_vpn(state, text)
            if s["lock"] and state != "secure":
                self.set_status("Blocked. Connect your VPN, or untick the lock if you like living dangerously.", RED)
                self.log("ERROR: " + ("could not verify the connection." if state == "unknown"
                                      else "no VPN detected, refusing to download."))
                return

            if s["lock"]:
                threading.Thread(target=self.monitor, args=(s["proxy"], stop), daemon=True).start()

            self.set_status("Fine. Spinning up the portal...")
            options = {
                "format": "bestaudio/best",
                "outtmpl": os.path.join(s["folder"], "%(title)s.%(ext)s"),
                "writethumbnail": True,
                "noplaylist": not s["playlist"],
                "cachedir": False,          # don't leave a cache folder behind
                "logger": Logger(self),
                "progress_hooks": [self.progress_hook],
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": s["bitrate"],
                    },
                    {"key": "FFmpegMetadata", "add_metadata": True},
                    {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"},
                    {"key": "EmbedThumbnail"},
                ],
                # crop the 16:9 thumbnail to a square so it looks like album art
                "postprocessor_args": {
                    "thumbnailsconvertor+ffmpeg_o": ["-vf", "crop='min(iw,ih)':'min(iw,ih)'"],
                },
            }
            if s["mode"].startswith("MP4"):
                if s["res"] == "BEST":
                    options["format"] = "bv*+ba/b"
                else:
                    h = s["res"]
                    options["format"] = (f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/"
                                         f"bv*[height<={h}]+ba/b[height<={h}]")
                options["merge_output_format"] = "mp4"
                options["postprocessors"] = [
                    {"key": "FFmpegMetadata", "add_metadata": True},
                    {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"},
                    {"key": "EmbedThumbnail"},
                ]
                options["postprocessor_args"] = {}   # no square crop for video thumbnails
            if s["proxy"]:
                options["proxy"] = s["proxy"]
            if s["start"] is not None or s["end"] is not None:
                end = s["end"] if s["end"] is not None else float("inf")
                options["download_ranges"] = yt_dlp.utils.download_range_func(None, [(s["start"] or 0, end)])
                options["force_keyframes_at_cuts"] = True   # accurate cut point

            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([s["url"]])

            if self.abort:
                raise RuntimeError("connection dropped during download")
            self.set_status(random.choice(DONE_LINES), GREEN)
            self.log("Saved to: " + s["folder"])
        except Exception as e:
            if self.abort:
                self.set_status("VPN dropped. Download killed. You're welcome.", RED)
            else:
                self.set_status("That broke. Probably not my fault. Check the log.", RED)
                self.log(f"ERROR: {e}")
        finally:
            stop.set()
            self.set_busy(False)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
