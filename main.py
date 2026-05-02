import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import psutil, threading, csv, os, time, platform
import subprocess, math, shutil, struct, wave, tempfile
import smtplib, base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from collections import deque

# ═══════════════════════════════════════════════
#  PALETTE
# ═══════════════════════════════════════════════
BG      = "#04080F"
BG_SIDE = "#070D1A"
BG_BAR  = "#070D1A"
BG_CARD = "#0C1524"
BG_C2   = "#0F1B2E"
BG_DARK = "#030710"
BG_GRPH = "#040B16"
BG_INP  = "#091220"

BDR     = "#14243C"
BDR_L   = "#1B3254"
BDR_H   = "#244470"

CYAN    = "#00D4FF"
CYAN_D  = "#0090BB"
BLUE    = "#3D8BFD"
PURP    = "#A76EFF"
GREEN   = "#00DC80"
GREEN_D = "#00A85E"
YELL    = "#FFC830"
RED     = "#FF3F4F"
RED_D   = "#C01830"
ORANGE  = "#FF8A00"

TH      = "#EDF3FF"   # text heading
TS      = "#7A96BA"   # text secondary
TM      = "#3E5670"   # text muted
TD      = "#1E3048"   # text dim

LOG_F   = "sysmon_log.csv"
MAIL_F  = "sysmon_email.cfg"
HIST    = 90
LOG_SEC = 10


# ═══════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════
def fmt(b, s="B"):
    for u in ("", "K", "M", "G", "T"):
        if abs(b) < 1024:
            return f"{b:.1f} {u}{s}"
        b /= 1024
    return f"{b:.1f} P{s}"

def lerp(c1, c2, t):
    t = max(0.0, min(1.0, t))
    r1,g1,b1 = int(c1[1:3],16),int(c1[3:5],16),int(c1[5:7],16)
    r2,g2,b2 = int(c2[1:3],16),int(c2[3:5],16),int(c2[5:7],16)
    return f"#{int(r1+(r2-r1)*t):02x}{int(g1+(g2-g1)*t):02x}{int(b1+(b2-b1)*t):02x}"

def gcol(v):
    if v < 50:  return lerp(GREEN,  YELL,   v / 50)
    if v < 80:  return lerp(YELL,   ORANGE, (v-50)/30)
    return             lerp(ORANGE, RED,    min((v-80)/20, 1.0))

def enc(pw): return base64.b64encode(pw.encode()).decode() if pw else ""
def dec(s):
    if not s: return ""
    try:    return base64.b64decode(s.encode()).decode()
    except: return s


# ═══════════════════════════════════════════════
#  SOUND ENGINE
# ═══════════════════════════════════════════════
class Sound:
    def __init__(self):
        self.on   = True
        self._wav = None
        self._lock = threading.Lock()
        self._gen()

    def _gen(self):
        try:
            f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            self._wav = f.name; f.close()
            sr, dur = 22050, 0.28
            n = int(sr * dur)
            raw = []
            for i in range(n):
                t   = i / sr
                env = math.exp(-8*t) * (0.2 + 0.8*(1 - math.exp(-40*t)))
                v   = env * (math.sin(2*math.pi*900*t)
                             + 0.25*math.sin(2*math.pi*1350*t))
                raw.append(max(-32767, min(32767, int(v * 32767))))
            with wave.open(self._wav, "w") as w:
                w.setnchannels(1); w.setsampwidth(2)
                w.setframerate(sr)
                w.writeframes(struct.pack(f"<{n}h", *raw))
        except Exception:
            self._wav = None

    def play(self):
        if not self.on: return
        with self._lock:
            threading.Thread(target=self._do, daemon=True).start()

    def _do(self):
        try:
            s = platform.system()
            if s == "Windows":
                import winsound
                if self._wav and os.path.exists(self._wav):
                    winsound.PlaySound(self._wav,
                        winsound.SND_FILENAME | winsound.SND_ASYNC)
                else:
                    winsound.Beep(900, 250)
            elif s == "Darwin":
                src = self._wav if (self._wav and os.path.exists(self._wav)) \
                      else "/System/Library/Sounds/Ping.aiff"
                subprocess.Popen(["afplay", src],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif s == "Linux":
                if self._wav and os.path.exists(self._wav):
                    subprocess.Popen(["aplay", "-q", self._wav],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def cleanup(self):
        try:
            if self._wav and os.path.exists(self._wav):
                os.unlink(self._wav)
        except Exception:
            pass


# ═══════════════════════════════════════════════
#  EMAIL ENGINE
class EmailAlert:
    def __init__(self):
        self.enabled  = False
        self.host     = "smtp.gmail.com"
        self.port     = 587
        self.sender   = ""
        self.password = ""
        self.recip    = ""
        self.cooldown = 300   # seconds between emails per resource
        self._last    = {}
        self._lock    = threading.Lock()
        self._load()

    # ── persistence ──────────────────────────
    def _load(self):
        if not os.path.exists(MAIL_F): return
        try:
            cfg = {}
            with open(MAIL_F, encoding="utf-8") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        cfg[k.strip()] = v.strip()
            self.enabled  = cfg.get("enabled","false").lower() == "true"
            self.host     = cfg.get("host", self.host)
            self.port     = int(cfg.get("port", self.port))
            self.sender   = cfg.get("sender", "")
            self.password = dec(cfg.get("password", ""))
            self.recip    = cfg.get("recip", "")
            self.cooldown = int(cfg.get("cooldown", self.cooldown))
        except Exception:
            pass

    def save(self):
        try:
            with open(MAIL_F, "w", encoding="utf-8") as f:
                f.write(f"enabled={'true' if self.enabled else 'false'}\n"
                        f"host={self.host}\nport={self.port}\n"
                        f"sender={self.sender}\npassword={enc(self.password)}\n"
                        f"recip={self.recip}\ncooldown={self.cooldown}\n")
        except Exception:
            pass

    # ── send helpers ─────────────────────────
    def _html(self, subject, body_html):
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = self.sender
        msg["To"]      = self.recip
        msg.attach(MIMEText(body_html, "html"))
        return msg

    def _smtp_send(self, msg):
        srv = smtplib.SMTP(self.host, self.port, timeout=10)
        srv.ehlo(); srv.starttls(); srv.ehlo()
        srv.login(self.sender, self.password)
        srv.sendmail(self.sender, self.recip, msg.as_string())
        srv.quit()

    # ── public API ───────────────────────────
    def send_alert(self, res, val, thr):
        """Fire-and-forget alert email with cooldown."""
        if not self.enabled or not self.sender or not self.recip:
            return
        with self._lock:
            now = time.time()
            if now - self._last.get(res, 0) < self.cooldown:
                return
            self._last[res] = now
        threading.Thread(target=self._do_alert,
                         args=(res, val, thr), daemon=True).start()

    def _do_alert(self, res, val, thr):
        html = (
            f"<div style='font-family:Consolas,monospace;padding:24px;"
            f"background:#0C1524;color:#EDF3FF;"
            f"border:1px solid #14243C;border-radius:10px;max-width:460px'>"
            f"<h2 style='color:#FF3F4F;margin:0 0 14px'>&#9888; System Alert</h2>"
            f"<table cellpadding='7' style='color:#7A96BA;font-size:14px'>"
            f"<tr><td><b>Resource</b></td><td style='color:#EDF3FF'>{res}</td></tr>"
            f"<tr><td><b>Current&nbsp;&nbsp;</b></td><td style='color:#FF3F4F'>{val:.1f}%</td></tr>"
            f"<tr><td><b>Threshold</b></td><td style='color:#FFC830'>{thr:.0f}%</td></tr>"
            f"</table>"
            f"<hr style='border-color:#14243C;margin:14px 0'>"
            f"<p style='color:#3E5670;font-size:11px;margin:0'>"
            f"Time: {datetime.now():%Y-%m-%d %H:%M:%S} &nbsp;|&nbsp; Host: {platform.node()}</p>"
            f"</div>"
        )
        try:
            self._smtp_send(self._html(
                f"CyberArc Alert — {res} at {val:.0f}%", html))
        except Exception:
            pass

    def test(self):
        """Blocking test — returns (bool, message)."""
        if not self.sender or not self.recip:
            return False, "Sender and recipient cannot be empty."
        html = (
            f"<div style='font-family:Consolas,monospace;padding:24px;"
            f"background:#0C1524;color:#EDF3FF;"
            f"border:1px solid #14243C;border-radius:10px;max-width:460px'>"
            f"<h2 style='color:#00DC80;margin:0 0 10px'>&#10003; Test OK</h2>"
            f"<p style='color:#7A96BA'>Email alerts are working correctly.</p>"
            f"<hr style='border-color:#14243C;margin:14px 0'>"
            f"<p style='color:#3E5670;font-size:11px;margin:0'>"
            f"{datetime.now():%Y-%m-%d %H:%M:%S} &nbsp;|&nbsp; {platform.node()}</p>"
            f"</div>"
        )
        try:
            self._smtp_send(self._html("CyberArc — Test Email", html))
            return True, "Test email sent successfully!"
        except smtplib.SMTPAuthenticationError:
            return False, "Authentication failed.\nCheck email address and App Password."
        except smtplib.SMTPConnectError:
            return False, f"Cannot connect to {self.host}:{self.port}."
        except Exception as e:
            return False, f"Error: {e}"


# ═══════════════════════════════════════════════
#  SYSTEM DATA ENGINE
# ═══════════════════════════════════════════════
class SysData:
    def __init__(self):
        self.cpu = self.ram = self.disk = 0.0
        self.cpu_cores_l = psutil.cpu_count(True)  or 1
        self.cpu_cores_p = psutil.cpu_count(False) or 1
        self.cpu_per     = []
        self.freq        = 0.0
        self.freq_max    = 0.0
        self.temp        = None
        vm = psutil.virtual_memory()
        self.ram_tot  = vm.total;  self.ram_use  = 0
        sw = psutil.swap_memory()
        self.swap_tot = sw.total;  self.swap_use = 0;  self.swap_pct = 0.0
        try:    dk = psutil.disk_usage("/"); self.dsk_tot = dk.total
        except: self.dsk_tot = 1
        self.dsk_use = 0
        self.net_up = self.net_dn = 0.0
        self._pn = psutil.net_io_counters()
        self._pt = time.time()
        self.cpu_h = deque([0.0]*HIST, maxlen=HIST)
        self.ram_h = deque([0.0]*HIST, maxlen=HIST)
        self.dsk_h = deque([0.0]*HIST, maxlen=HIST)
        psutil.cpu_percent(interval=None)
        try:
            f = psutil.cpu_freq()
            if f: self.freq_max = f.max or 0
        except: pass

    def tick(self):
        now = time.time()
        dt  = max(now - self._pt, 0.001)
        self.cpu     = psutil.cpu_percent(interval=None)
        self.cpu_per = psutil.cpu_percent(percpu=True, interval=None) or []
        try:
            f = psutil.cpu_freq()
            if f: self.freq = f.current; self.freq_max = f.max or self.freq_max
        except: pass
        vm = psutil.virtual_memory()
        self.ram = vm.percent; self.ram_use = vm.used
        sw = psutil.swap_memory()
        self.swap_pct = sw.percent; self.swap_use = sw.used; self.swap_tot = sw.total
        try:
            dk = psutil.disk_usage("/")
            self.disk = dk.percent; self.dsk_use = dk.used; self.dsk_tot = dk.total
        except: pass
        n = psutil.net_io_counters()
        self.net_up = max(0, (n.bytes_sent - self._pn.bytes_sent) / dt)
        self.net_dn = max(0, (n.bytes_recv - self._pn.bytes_recv) / dt)
        self._pn = n; self._pt = now
        # temperature (platform-safe)
        self.temp = None
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    for e in entries:
                        lb = (e.label or "").lower()
                        if any(k in lb or k in name.lower()
                               for k in ("cpu","core","package","tctl","k10")):
                            self.temp = e.current; break
                    if self.temp is not None: break
                if self.temp is None:
                    first = next(iter(temps.values()), [])
                    if first: self.temp = first[0].current
        except: pass
        self.cpu_h.append(self.cpu)
        self.ram_h.append(self.ram)
        self.dsk_h.append(self.disk)


# ═══════════════════════════════════════════════
#  LOGGER
# ═══════════════════════════════════════════════
class Logger:
    HDR = ["Timestamp","CPU (%)","RAM (%)","Disk (%)","Temp (C)"]
    def __init__(self):
        if not os.path.exists(LOG_F): self._w(self.HDR)
    def _w(self, row):
        try:
            with open(LOG_F, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(row)
        except: pass
    def add(self, c, r, d, t):
        self._w([datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 f"{c:.1f}", f"{r:.1f}", f"{d:.1f}",
                 f"{t:.1f}" if t is not None else "N/A"])
    def read(self):
        try:
            with open(LOG_F, encoding="utf-8") as f:
                return list(csv.reader(f))
        except: return [self.HDR]
    def clear(self):
        try:
            with open(LOG_F, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(self.HDR)
        except: pass


# ═══════════════════════════════════════════════
#  ALERT MANAGER
# ═══════════════════════════════════════════════
class AlertMgr:
    def __init__(self, snd: Sound, mail: EmailAlert):
        self.thr     = {"CPU": 85.0, "RAM": 85.0, "Disk": 90.0}
        self.cd      = 30
        self.snd_on  = True
        self.ntf_on  = True
        self._last   = {}
        self._snd    = snd
        self._mail   = mail

    def check(self, c, r, d):
        now = time.time()
        out = []
        for k, v in {"CPU": c, "RAM": r, "Disk": d}.items():
            if v >= self.thr[k] and now - self._last.get(k, 0) >= self.cd:
                out.append((k, v, self.thr[k]))
                self._last[k] = now
        return out

    def fire(self, res, val, thr):
        if self.snd_on: self._snd.play()
        if self.ntf_on: self._os_notify(res, val, thr)
        self._mail.send_alert(res, val, thr)

    @staticmethod
    def _os_notify(res, val, thr):
        title = f"CyberArc Alert — {res}"
        body  = f"{res} at {val:.0f}% (limit {thr:.0f}%)"
        try:
            s = platform.system()
            if s == "Windows":
                subprocess.Popen(["msg","*",f"{title}: {body}"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif s == "Linux":
                subprocess.Popen(["notify-send","-u","critical",title,body],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif s == "Darwin":
                subprocess.Popen(["osascript","-e",
                    f'display notification "{body}" with title "{title}" sound name "Ping"'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except: pass


# ═══════════════════════════════════════════════
#  WIDGETS
# ═══════════════════════════════════════════════
class Gauge(tk.Canvas):
    SZ = 156
    def __init__(self, parent, label="", sub="", **kw):
        super().__init__(parent, width=self.SZ, height=self.SZ+4,
                         bg=BG_CARD, highlightthickness=0, **kw)
        self._lb = label; self._sb = sub
        self._v = -1.0;   self._a = False
        self._draw(0)

    def set(self, v, alert=False):
        if abs(v - self._v) > 0.3 or alert != self._a:
            self._v = v; self._a = alert; self._draw(v)

    def _draw(self, v):
        self.delete("all")
        S = self.SZ; cx = cy = S/2; r = 58; lw = 10
        pad = r + lw/2 + 2
        col = RED if self._a else gcol(v)
        dim = lerp(BDR, col, 0.18)
        # track
        self.create_arc(cx-pad,cy-pad,cx+pad,cy+pad,
                        start=225,extent=-270,outline=BDR_L,width=lw,style="arc")
        ext = -270 * min(max(v,0),100) / 100
        if abs(ext) > 0.5:
            # glow fill
            self.create_arc(cx-pad,cy-pad,cx+pad,cy+pad,
                            start=225,extent=ext,outline=dim,
                            width=lw+10,style="arc",stipple="gray12")
            # main arc
            self.create_arc(cx-pad,cy-pad,cx+pad,cy+pad,
                            start=225,extent=ext,outline=col,width=lw,style="arc")
            # tip dot
            a = math.radians(225+ext)
            tx = cx + r*math.cos(a); ty = cy - r*math.sin(a)
            self.create_oval(tx-4,ty-4,tx+4,ty+4,fill=col,outline=TH,width=1)
        # segment ticks
        for deg in range(0,271,27):
            a2 = math.radians(225-deg); r1=r+lw/2+3; r2=r1+5
            self.create_line(cx+r1*math.cos(a2),cy-r1*math.sin(a2),
                             cx+r2*math.cos(a2),cy-r2*math.sin(a2),
                             fill=TD,width=1)
        # texts
        self.create_text(cx,cy-10,text=f"{v:.0f}%",
                         font=("Consolas",19,"bold"),fill=col)
        if self._lb:
            self.create_text(cx,cy+13,text=self._lb,
                             font=("Segoe UI",8,"bold"),fill=TS)
        if self._sb:
            self.create_text(cx,cy+26,text=self._sb,
                             font=("Segoe UI",7),fill=TD)


class Graph(tk.Canvas):
    PL,PR,PT,PB = 46,14,28,24
    def __init__(self, parent, colors, labels, **kw):
        super().__init__(parent,bg=BG_GRPH,highlightthickness=0,**kw)
        self._colors  = colors; self._labels = labels
        self._series  = [deque([0.0]*HIST, maxlen=HIST) for _ in colors]
        self._thrs    = {}
        self.bind("<Configure>", lambda e: self._redraw())

    def set_thresholds(self, d):
        self._thrs = d; self._redraw()

    def push(self, *vals):
        for i, v in enumerate(vals):
            if i < len(self._series): self._series[i].append(float(v))
        self._redraw()

    def _redraw(self):
        self.delete("all")
        W = self.winfo_width(); H = self.winfo_height()
        if W < 30 or H < 30: return
        pl,pr,pt,pb = self.PL,self.PR,self.PT,self.PB
        gw = W-pl-pr; gh = H-pt-pb; n = HIST
        # grid
        for p in (0,25,50,75,100):
            y = pt+gh - int(gh*p/100)
            self.create_line(pl,y,W-pr,y,fill=BDR,dash=(2,6))
            self.create_text(pl-6,y,text=f"{p}",
                             font=("Consolas",7),fill=TM,anchor="e")
        # axes
        self.create_line(pl,pt-2,pl,pt+gh+1,fill=BDR_L)
        self.create_line(pl-1,pt+gh,W-pr,pt+gh,fill=BDR_L)
        # threshold lines
        for i,(k,v) in enumerate(self._thrs.items()):
            col=[RED,PURP,GREEN][i%3]
            y = pt+gh - int(gh*min(v,100)/100)
            self.create_line(pl,y,W-pr,y,fill=col,dash=(3,8),width=1)
            self.create_text(W-pr-3,y-7,text=f"{k} {v:.0f}%",
                             font=("Consolas",7),fill=col,anchor="e")
        # series
        for ser, col in zip(self._series, self._colors):
            data = list(ser); pts = []
            for i,v in enumerate(data):
                x = pl + int(gw*i/max(n-1,1))
                y = pt+gh - int(gh*min(max(v,0),100)/100)
                pts += [x,y]
            if len(pts) >= 4:
                fp = [pts[0],pt+gh]+pts+[pts[-2],pt+gh]
                self.create_polygon(*fp,fill=col,stipple="gray12",outline="")
                self.create_line(*pts,fill=col,width=2.2,
                                 smooth=True,joinstyle="round")
                self.create_oval(pts[-2]-3,pts[-1]-3,
                                 pts[-2]+3,pts[-1]+3,
                                 fill=col,outline=TH,width=1)
        # legend
        lx = pl+6
        for lb,co in zip(self._labels,self._colors):
            self.create_rectangle(lx,8,lx+12,18,fill=co,outline="")
            self.create_text(lx+17,13,text=lb,
                             font=("Consolas",8),fill=TS,anchor="w")
            lx += 66
        self.create_text(W//2,H-6,
                         text=f"\u2190 {HIST} samples \u2192",
                         font=("Consolas",7),fill=TM)


class CoreBar(tk.Canvas):
    CW,CH = 22,52
    def __init__(self,parent,idx,**kw):
        super().__init__(parent,width=self.CW,height=self.CH+18,
                         bg=BG_CARD,highlightthickness=0,**kw)
        self._i = idx; self._p = -1; self._draw(0)

    def set(self,p):
        if abs(p-self._p) > 1: self._p = p; self._draw(p)

    def _draw(self,p):
        self.delete("all")
        c  = gcol(p); fh = int(self.CH*min(p,100)/100)
        self.create_rectangle(3,0,self.CW-3,self.CH,
                              fill=BG_DARK,outline=BDR)
        if fh > 0:
            self.create_rectangle(3,self.CH-fh,self.CW-3,self.CH,
                                  fill=c,outline="")
        self.create_text(self.CW//2,self.CH+8,
                         text=f"C{self._i}",font=("Consolas",6),fill=TM)
        self.create_text(self.CW//2,self.CH+17,
                         text=f"{p:.0f}",font=("Consolas",6),fill=c)


class Stat(tk.Frame):
    def __init__(self,parent,label,color,**kw):
        super().__init__(parent,bg=BG_C2,
                         highlightbackground=BDR,highlightthickness=1,**kw)
        tk.Frame(self,bg=color,height=2).pack(fill="x")
        self._v = tk.Label(self,text="--",font=("Consolas",14,"bold"),
                           fg=color,bg=BG_C2)
        self._v.pack(anchor="w",padx=12,pady=(7,0))
        self._s = tk.Label(self,text=label,font=("Segoe UI",8),
                           fg=TS,bg=BG_C2)
        self._s.pack(anchor="w",padx=12,pady=(0,7))

    def set(self,val,sub=None):
        self._v.config(text=val)
        if sub is not None: self._s.config(text=sub)

    def recolor(self,c): self._v.config(fg=c)


def _card(parent, title=None, bg=BG_CARD):
    """Return (outer_frame, content_frame) pair."""
    outer = tk.Frame(parent,bg=bg,highlightbackground=BDR,highlightthickness=1)
    if title:
        hdr = tk.Frame(outer,bg=bg)
        hdr.pack(fill="x",padx=14,pady=(10,0))
        tk.Label(hdr,text=title,font=("Segoe UI",9,"bold"),
                 fg=TS,bg=bg).pack(side="left")
        tk.Frame(outer,bg=BDR,height=1).pack(fill="x",padx=14,pady=(6,0))
    inner = tk.Frame(outer,bg=bg)
    inner.pack(fill="both",expand=True)
    return outer, inner


def _btn(parent, text, fg, bg, cmd, **kw):
    b = tk.Button(parent,text=text,fg=fg,bg=bg,font=("Segoe UI",10,"bold"),
                  bd=0,pady=9,cursor="hand2",relief="flat",
                  activeforeground=TH,activebackground=bg,
                  command=cmd,**kw)
    return b


# ═══════════════════════════════════════════════
#  MAIN APPLICATION
# ═══════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CyberArc — System Monitor Pro")
        self.geometry("1160x740"); self.minsize(980,600)
        self.configure(bg=BG)

        self._snd  = Sound()
        self._d    = SysData()
        self._log  = Logger()
        self._mail = EmailAlert()
        self._al   = AlertMgr(self._snd, self._mail)
        self._run  = True
        self._pause= False
        self._ltick= 0
        self._page = ""
        self._pulse= False

        self._build_topbar()
        self._build_body()
        self._build_alert_bar()

        self.protocol("WM_DELETE_WINDOW", self._quit)
        threading.Thread(target=self._bg_loop, daemon=True).start()
        self._nav("dashboard")
        self._blink()

    # ── TOP BAR ────────────────────────────────────────────────
    def _build_topbar(self):
        bar = tk.Frame(self,bg=BG_BAR,height=48)
        bar.pack(fill="x"); bar.pack_propagate(False)

        tk.Label(bar,text="◆",font=("Segoe UI",15),fg=CYAN,bg=BG_BAR
                 ).pack(side="left",padx=(18,4))
        tk.Label(bar,text="CYBEARC",font=("Consolas",13,"bold"),
                 fg=TH,bg=BG_BAR).pack(side="left")
        tk.Label(bar,text="  System Monitor",font=("Segoe UI",9),
                 fg=TS,bg=BG_BAR).pack(side="left")
        tk.Label(bar,text=" PRO",font=("Consolas",8,"bold"),
                 fg=YELL,bg=BG_BAR).pack(side="left")

        tk.Frame(bar,bg=BDR_L,width=1).pack(side="left",fill="y",padx=14,pady=10)

        # Sound toggle
        self._snd_ico = tk.Label(bar,text="🔔",font=("Segoe UI",13),
                                 fg=GREEN,bg=BG_BAR,cursor="hand2")
        self._snd_ico.pack(side="left",padx=2)
        self._snd_ico.bind("<Button-1>",lambda e: self._toggle_sound())
        self._snd_txt = tk.Label(bar,text="Sound ON",font=("Segoe UI",7),
                                 fg=TM,bg=BG_BAR)
        self._snd_txt.pack(side="left")

        self._clock = tk.StringVar()
        tk.Label(bar,textvariable=self._clock,
                 font=("Consolas",9),fg=TS,bg=BG_BAR
                 ).pack(side="right",padx=18)
        self._dot = tk.Label(bar,text="● LIVE",
                             font=("Consolas",9,"bold"),fg=GREEN,bg=BG_BAR)
        self._dot.pack(side="right",padx=8)

        tk.Frame(self,bg=BDR_L,height=1).pack(fill="x")
        self._tick_clock()

    def _tick_clock(self):
        self._clock.set(datetime.now().strftime("%a  %d %b  %H:%M:%S"))
        self.after(1000,self._tick_clock)

    def _blink(self):
        if not self._pause:
            self._pulse = not self._pulse
            self._dot.config(fg=GREEN if self._pulse else GREEN_D)
        self.after(800,self._blink)

    # ── BODY ───────────────────────────────────────────────────
    def _build_body(self):
        body = tk.Frame(self,bg=BG); body.pack(fill="both",expand=True)
        self._side = tk.Frame(body,bg=BG_SIDE,width=190)
        self._side.pack(side="left",fill="y"); self._side.pack_propagate(False)
        self._host = tk.Frame(body,bg=BG)
        self._host.pack(side="left",fill="both",expand=True)
        self._build_sidebar()
        self._pages = {}
        self._pg_dashboard()
        self._pg_graph()
        self._pg_thresholds()
        self._pg_logs()

    # ── SIDEBAR ────────────────────────────────────────────────
    def _build_sidebar(self):
        tk.Frame(self._side,bg=BDR_L,height=1).pack(fill="x")
        self._nav_btns = {}
        nav = [
            ("dashboard",  "⬡   Dashboard"),
            ("graph",      "∿   Live Graph"),
            ("thresholds", "⚙   Thresholds"),
            ("logs",       "☰   Logs"),
        ]
        for key, label in nav:
            b = tk.Button(self._side,text=label,anchor="w",
                          font=("Segoe UI",10),fg=TS,bg=BG_SIDE,
                          activeforeground=CYAN,activebackground=BG_C2,
                          bd=0,pady=10,padx=18,cursor="hand2",relief="flat",
                          command=lambda k=key: self._nav(k))
            b.pack(fill="x"); self._nav_btns[key] = b

        tk.Frame(self._side,bg=BDR,height=1).pack(fill="x",padx=14,pady=8)

        self._pause_btn = tk.Button(self._side,text="⏸   Pause",anchor="w",
            font=("Segoe UI",10),fg=YELL,bg=BG_SIDE,
            activeforeground=GREEN,activebackground=BG_C2,
            bd=0,pady=10,padx=18,cursor="hand2",relief="flat",
            command=self._toggle_pause)
        self._pause_btn.pack(fill="x")

        tk.Button(self._side,text="⬇   Export CSV",anchor="w",
            font=("Segoe UI",10),fg=TS,bg=BG_SIDE,
            activeforeground=CYAN,activebackground=BG_C2,
            bd=0,pady=10,padx=18,cursor="hand2",relief="flat",
            command=self._export).pack(fill="x")

        tk.Frame(self._side,bg=BG_SIDE).pack(fill="both",expand=True)
        tk.Label(self._side,text="v4.0 Pro  ·  The Cyber Arc",
                 font=("Segoe UI",7),fg=TD,bg=BG_SIDE).pack(pady=(0,12))

    # ── ALERT BANNER ───────────────────────────────────────────
    def _build_alert_bar(self):
        self._af  = tk.Frame(self._host,bg="#280008")
        self._albl= tk.Label(self._af,text="",
                             font=("Segoe UI",10,"bold"),
                             fg=RED,bg="#280008",pady=6,padx=14)
        self._albl.pack(side="left",fill="x",expand=True)
        # flashing dot
        self._fdot = tk.Label(self._af,text="●",font=("Segoe UI",14,"bold"),
                              fg=RED,bg="#280008")
        self._fdot.pack(side="left",padx=4)
        tk.Button(self._af,text="✕  Dismiss",bg=RED,fg=TH,bd=0,
                  font=("Segoe UI",9,"bold"),cursor="hand2",
                  activebackground=RED_D,padx=10,pady=4,
                  command=self._hide_alert).pack(side="right",padx=10,pady=4)
        self._al_vis = False; self._fstate = False
        self._flash()

    def _flash(self):
        if self._al_vis:
            self._fstate = not self._fstate
            self._fdot.config(fg=RED if self._fstate else "#280008")
        self.after(500,self._flash)

    def _show_alert(self,msg):
        self._albl.config(text=f"⚠  {msg}")
        if not self._al_vis:
            ch = list(self._host.winfo_children())
            if ch: self._af.pack(fill="x",before=ch[0])
            else:  self._af.pack(fill="x")
            self._al_vis = True

    def _hide_alert(self):
        if self._al_vis:
            self._af.pack_forget(); self._al_vis = False

    # ── PAGE: DASHBOARD ────────────────────────────────────────
    def _pg_dashboard(self):
        pg = tk.Frame(self._host,bg=BG)
        self._pages["dashboard"] = pg

        hdr = tk.Frame(pg,bg=BG)
        hdr.pack(fill="x",padx=22,pady=(14,0))
        tk.Label(hdr,text="Dashboard",font=("Consolas",16,"bold"),
                 fg=TH,bg=BG).pack(side="left")
        self._upd = tk.Label(hdr,text="",font=("Segoe UI",8),fg=TD,bg=BG)
        self._upd.pack(side="right")

        # Gauges
        grow = tk.Frame(pg,bg=BG); grow.pack(fill="x",padx=22,pady=10)
        self._gauges = {}
        for key,lbl,sub in [
            ("CPU",  "CPU Usage",  f"{self._d.cpu_cores_p}P / {self._d.cpu_cores_l}L"),
            ("RAM",  "Memory",     "Physical RAM"),
            ("Disk", "Disk",       "Root Partition"),
        ]:
            outer,inner = _card(grow)
            tk.Frame(outer,bg={"CPU":CYAN,"RAM":PURP,"Disk":GREEN}[key],
                     height=2).place(relx=0,rely=0,relwidth=1)
            outer.pack(side="left",expand=True,fill="both",padx=5)
            g = Gauge(inner,label=lbl,sub=sub)
            g.pack(pady=10)
            self._gauges[key] = g

        # Stats row 1
        r1 = tk.Frame(pg,bg=BG); r1.pack(fill="x",padx=22,pady=3)
        self._stats = {}
        for key,lbl,col in [
            ("temp","CPU Temperature",ORANGE),
            ("swap","Swap Memory",    PURP),
            ("freq","CPU Frequency",  CYAN),
        ]:
            s = Stat(r1,lbl,col); s.pack(side="left",expand=True,fill="both",padx=4)
            self._stats[key] = s

        # Stats row 2
        r2 = tk.Frame(pg,bg=BG); r2.pack(fill="x",padx=22,pady=3)
        for key,lbl,col in [
            ("up", "Upload Speed",  YELL),
            ("dn", "Download Speed",BLUE),
            ("ru", "RAM Used",      PURP),
            ("du", "Disk Used",     GREEN),
        ]:
            s = Stat(r2,lbl,col); s.pack(side="left",expand=True,fill="both",padx=4)
            self._stats[key] = s

        # Per-core bars
        co,ci = _card(pg, title="Per-Core CPU Usage")
        co.pack(fill="x",padx=22,pady=6)
        row = tk.Frame(ci,bg=BG_CARD); row.pack(fill="x",padx=8,pady=(4,8))
        self._cbars = []
        for i in range(self._d.cpu_cores_l):
            cb = CoreBar(row,i); cb.pack(side="left",padx=2)
            self._cbars.append(cb)

    # ── PAGE: GRAPH ────────────────────────────────────────────
    def _pg_graph(self):
        pg = tk.Frame(self._host,bg=BG)
        self._pages["graph"] = pg

        hdr = tk.Frame(pg,bg=BG); hdr.pack(fill="x",padx=22,pady=(14,6))
        tk.Label(hdr,text="Live Resource Graph",
                 font=("Consolas",14,"bold"),fg=TH,bg=BG).pack(side="left")
        tk.Label(hdr,text=f"  Real-time · {HIST} samples",
                 font=("Segoe UI",8),fg=TM,bg=BG).pack(side="left",padx=10)
        for lbl,col in [("CPU",CYAN),("RAM",PURP),("Disk",GREEN)]:
            pill=tk.Frame(hdr,bg=col,padx=10,pady=2); pill.pack(side="right",padx=4)
            tk.Label(pill,text=lbl,font=("Consolas",8,"bold"),fg=BG,bg=col).pack()

        self._graph = Graph(pg,[CYAN,PURP,GREEN],["CPU","RAM","Disk"])
        self._graph.pack(fill="both",expand=True,padx=22,pady=(0,14))

    # ── PAGE: THRESHOLDS ───────────────────────────────────────
    def _pg_thresholds(self):
        pg = tk.Frame(self._host,bg=BG)
        self._pages["thresholds"] = pg

        wrap = tk.Frame(pg,bg=BG); wrap.pack(fill="both",expand=True)

        # ── LEFT: alert settings ──
        left = tk.Frame(wrap,bg=BG)
        left.pack(side="left",fill="both",expand=True,padx=(22,8),pady=14)

        tk.Label(left,text="Alert Thresholds",
                 font=("Consolas",15,"bold"),fg=TH,bg=BG).pack(anchor="w")
        tk.Label(left,text="Siren + notification fires when usage exceeds limit.",
                 font=("Segoe UI",9),fg=TS,bg=BG).pack(anchor="w",pady=(0,8))

        self._thr_vars = {}
        for res,col in [("CPU",CYAN),("RAM",PURP),("Disk",GREEN)]:
            outer,inner = _card(left)
            tk.Frame(outer,bg=col,height=2).place(relx=0,rely=0,relwidth=1)
            outer.pack(fill="x",pady=4)

            top = tk.Frame(inner,bg=BG_CARD); top.pack(fill="x",padx=12,pady=(10,2))
            tk.Label(top,text=f"{res} Threshold",font=("Segoe UI",11,"bold"),
                     fg=col,bg=BG_CARD).pack(side="left")
            var = tk.DoubleVar(value=self._al.thr[res]); self._thr_vars[res] = var
            pct = tk.Label(top,text=f"{var.get():.0f}%",
                           font=("Consolas",20,"bold"),fg=col,bg=BG_CARD)
            pct.pack(side="right")
            def _cb(x,lbl=pct): lbl.config(text=f"{float(x):.0f}%")
            row = tk.Frame(inner,bg=BG_CARD); row.pack(fill="x",padx=12,pady=(0,10))
            tk.Scale(row,variable=var,from_=1,to=100,orient="horizontal",
                     bg=BG_CARD,fg=TS,troughcolor=BG_DARK,
                     highlightthickness=0,bd=0,showvalue=False,
                     activebackground=col,command=_cb).pack(fill="x")

        # Options
        opt_o,opt_i = _card(left,"Alert Options"); opt_o.pack(fill="x",pady=4)
        self._snd_var = tk.BooleanVar(value=True)
        self._ntf_var = tk.BooleanVar(value=True)
        for txt,var in [("Enable alert sound",self._snd_var),
                        ("Enable OS notification",self._ntf_var)]:
            r = tk.Frame(opt_i,bg=BG_CARD); r.pack(fill="x",padx=12,pady=4)
            tk.Checkbutton(r,text=txt,variable=var,
                           font=("Segoe UI",10),fg=TH,bg=BG_CARD,
                           selectcolor=BG_DARK,activebackground=BG_CARD,
                           activeforeground=TH,cursor="hand2").pack(side="left")

        # Cooldown
        cd_o,cd_i = _card(left,"Alert Cooldown (seconds)"); cd_o.pack(fill="x",pady=4)
        cr = tk.Frame(cd_i,bg=BG_CARD); cr.pack(fill="x",padx=12,pady=10)
        self._cd_var = tk.IntVar(value=self._al.cd)
        cl = tk.Label(cr,text=f"{self._cd_var.get()}s",
                      font=("Consolas",20,"bold"),fg=YELL,bg=BG_CARD)
        cl.pack(side="right")
        def _ccb(x,lbl=cl): lbl.config(text=f"{int(float(x))}s")
        tk.Scale(cr,variable=self._cd_var,from_=5,to=300,orient="horizontal",
                 bg=BG_CARD,fg=TS,troughcolor=BG_DARK,
                 highlightthickness=0,bd=0,showvalue=False,
                 activebackground=YELL,command=_ccb
                 ).pack(side="left",fill="x",expand=True)

        _btn(left,"   ✓   Apply Settings   ",BG,CYAN,
             self._apply_thr).pack(pady=12)

        # ── RIGHT: email ──
        right = tk.Frame(wrap,bg=BG)
        right.pack(side="left",fill="both",expand=True,padx=(8,22),pady=14)

        tk.Label(right,text="Email Alerts",
                 font=("Consolas",15,"bold"),fg=TH,bg=BG).pack(anchor="w")
        tk.Label(right,text="Receive threshold alerts directly to your inbox.",
                 font=("Segoe UI",9),fg=TS,bg=BG).pack(anchor="w",pady=(0,8))

        ec_o,ec_i = _card(right); ec_o.pack(fill="x",pady=4)

        self._em_on = tk.BooleanVar(value=self._mail.enabled)
        er = tk.Frame(ec_i,bg=BG_CARD); er.pack(fill="x",padx=12,pady=(10,4))
        tk.Checkbutton(er,text="Enable email alerts",variable=self._em_on,
                       font=("Segoe UI",10,"bold"),fg=CYAN,bg=BG_CARD,
                       selectcolor=BG_DARK,activebackground=BG_CARD,
                       activeforeground=CYAN,cursor="hand2").pack(side="left")

        self._em_flds = {}
        fields = [
            ("SMTP Host",    "host",     self._mail.host),
            ("SMTP Port",    "port",     str(self._mail.port)),
            ("Sender Email", "sender",   self._mail.sender),
            ("App Password", "password", self._mail.password),
            ("Recipient",    "recip",    self._mail.recip),
        ]
        for lbl,key,default in fields:
            fr = tk.Frame(ec_i,bg=BG_CARD); fr.pack(fill="x",padx=12,pady=3)
            tk.Label(fr,text=lbl,width=14,anchor="w",
                     font=("Segoe UI",9),fg=TS,bg=BG_CARD).pack(side="left")
            ent = tk.Entry(fr,font=("Consolas",9),fg=TH,bg=BG_INP,
                           insertbackground=CYAN,relief="flat",bd=4,
                           show="*" if key=="password" else "")
            ent.pack(side="left",fill="x",expand=True)
            ent.insert(0,default)
            self._em_flds[key] = ent

        # Email cooldown
        ecr = tk.Frame(ec_i,bg=BG_CARD); ecr.pack(fill="x",padx=12,pady=(8,2))
        tk.Label(ecr,text="Email Cooldown",width=14,anchor="w",
                 font=("Segoe UI",9),fg=TS,bg=BG_CARD).pack(side="left")
        self._ecd_var = tk.IntVar(value=self._mail.cooldown)
        ecl = tk.Label(ecr,text=f"{self._mail.cooldown}s",
                       font=("Consolas",14,"bold"),fg=YELL,bg=BG_CARD,width=6,anchor="e")
        ecl.pack(side="right")
        def _eccb(x,lbl=ecl): lbl.config(text=f"{int(float(x))}s")
        tk.Scale(ecr,variable=self._ecd_var,from_=60,to=3600,orient="horizontal",
                 bg=BG_CARD,fg=TS,troughcolor=BG_DARK,
                 highlightthickness=0,bd=0,showvalue=False,
                 activebackground=YELL,command=_eccb
                 ).pack(side="left",fill="x",expand=True)

        tk.Label(ec_i,
                 text="Gmail: Enable 2FA → Security → App Passwords → Generate.",
                 font=("Segoe UI",7),fg=TD,bg=BG_CARD,
                 justify="left").pack(anchor="w",padx=14,pady=(6,2))

        bf = tk.Frame(ec_i,bg=BG_CARD); bf.pack(fill="x",padx=12,pady=(8,12))
        _btn(bf," ✓ Save Config ",BG,CYAN,self._save_email).pack(side="left",padx=(0,6))
        _btn(bf," ✉ Send Test  ",BG,GREEN,self._test_email).pack(side="left")

    # ── PAGE: LOGS ─────────────────────────────────────────────
    def _pg_logs(self):
        pg = tk.Frame(self._host,bg=BG)
        self._pages["logs"] = pg

        hdr = tk.Frame(pg,bg=BG); hdr.pack(fill="x",padx=22,pady=(14,6))
        tk.Label(hdr,text="Performance Logs",
                 font=("Consolas",14,"bold"),fg=TH,bg=BG).pack(side="left")
        for txt,col,cmd in [
            ("⟳ Refresh",CYAN,self._refresh_logs),
            ("🗑 Clear",   RED, self._clear_logs),
        ]:
            tk.Button(hdr,text=txt,font=("Segoe UI",9),fg=col,bg=BG,
                      bd=0,cursor="hand2",activeforeground=TH,
                      command=cmd).pack(side="right",padx=6)

        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure("L.Treeview",
                     background=BG_CARD,foreground=TH,
                     fieldbackground=BG_CARD,rowheight=26,
                     font=("Consolas",9),borderwidth=0)
        st.configure("L.Treeview.Heading",
                     background=BG_SIDE,foreground=CYAN,
                     font=("Segoe UI",9,"bold"),relief="flat",padding=(10,6))
        st.map("L.Treeview",
               background=[("selected",BG_C2)],
               foreground=[("selected",CYAN)])

        cols = ("Timestamp","CPU (%)","RAM (%)","Disk (%)","Temp (C)")
        tf = tk.Frame(pg,bg=BG); tf.pack(fill="both",expand=True,padx=22,pady=(0,8))
        vsb = ttk.Scrollbar(tf,orient="vertical"); vsb.pack(side="right",fill="y")
        self._tree = ttk.Treeview(tf,columns=cols,show="headings",
                                  style="L.Treeview",yscrollcommand=vsb.set)
        vsb.config(command=self._tree.yview)
        for c in cols:
            self._tree.heading(c,text=c)
            self._tree.column(c,width=200 if c=="Timestamp" else 110,anchor="center")
        self._tree.pack(fill="both",expand=True)
        self._log_st = tk.Label(pg,text="",font=("Segoe UI",8),fg=TD,bg=BG)
        self._log_st.pack(anchor="w",padx=24,pady=4)
        self._refresh_logs()

    # ── BACKGROUND LOOP ────────────────────────────────────────
    def _bg_loop(self):
        while self._run:
            if not self._pause:
                try:
                    self._d.tick()
                    self.after(0, self._update_ui)
                    self._ltick += 1
                    if self._ltick >= LOG_SEC:
                        self._log.add(self._d.cpu,self._d.ram,
                                      self._d.disk,self._d.temp)
                        self._ltick = 0
                except Exception as e:
                    print(f"[poll] {e}")
            time.sleep(1)

    # ── UI UPDATE ──────────────────────────────────────────────
    def _update_ui(self):
        d = self._d; a = self._al
        self._upd.config(text=f"Updated {datetime.now().strftime('%H:%M:%S')}")

        trig = a.check(d.cpu, d.ram, d.disk)
        if trig:
            self._show_alert("   |   ".join(
                f"{r}: {v:.0f}% > {t:.0f}%" for r,v,t in trig))
            for r,v,t in trig: a.fire(r,v,t)
        else:
            self._hide_alert()

        self._gauges["CPU"].set(d.cpu,  d.cpu  >= a.thr["CPU"])
        self._gauges["RAM"].set(d.ram,  d.ram  >= a.thr["RAM"])
        self._gauges["Disk"].set(d.disk,d.disk >= a.thr["Disk"])

        # temp
        if d.temp is not None:
            tc = RED if d.temp>80 else ORANGE if d.temp>65 else GREEN
            self._stats["temp"].set(f"{d.temp:.0f}°C","CPU Temperature")
            self._stats["temp"].recolor(tc)
        else:
            self._stats["temp"].set("N/A","Not available")

        self._stats["swap"].set(f"{d.swap_pct:.1f}%",
                                f"{fmt(d.swap_use)} / {fmt(d.swap_tot)}")
        self._stats["freq"].set(f"{d.freq:.0f} MHz",
                                f"{d.cpu_cores_p}P / {d.cpu_cores_l}L cores")
        self._stats["up"].set(fmt(d.net_up,"B/s"),"Upload speed")
        self._stats["dn"].set(fmt(d.net_dn,"B/s"),"Download speed")
        self._stats["ru"].set(fmt(d.ram_use), f"of {fmt(d.ram_tot)}")
        self._stats["du"].set(fmt(d.dsk_use), f"of {fmt(d.dsk_tot)}")

        for i,cb in enumerate(self._cbars):
            if i < len(d.cpu_per): cb.set(d.cpu_per[i])

        if self._page == "graph":
            self._graph.set_thresholds(self._al.thr)
            self._graph.push(d.cpu, d.ram, d.disk)

    # ── NAVIGATION ─────────────────────────────────────────────
    def _nav(self, key):
        for f in self._pages.values(): f.pack_forget()
        self._pages[key].pack(fill="both",expand=True)
        for n,b in self._nav_btns.items():
            b.config(fg=CYAN if n==key else TS,
                     bg=BG_C2 if n==key else BG_SIDE)
        self._page = key
        if key == "graph":
            self._graph.set_thresholds(self._al.thr)
            self._graph.push(self._d.cpu,self._d.ram,self._d.disk)

    # ── ACTIONS ────────────────────────────────────────────────
    def _toggle_sound(self):
        self._snd.on = not self._snd.on
        self._snd_ico.config(fg=GREEN if self._snd.on else TM,
                             text="🔔" if self._snd.on else "🔕")
        self._snd_txt.config(text="Sound ON" if self._snd.on else "Sound OFF")

    def _toggle_pause(self):
        self._pause = not self._pause
        if self._pause:
            self._pause_btn.config(text="▶   Resume",fg=GREEN)
            self._dot.config(text="● PAUSED",fg=YELL)
        else:
            self._pause_btn.config(text="⏸   Pause",fg=YELL)
            self._dot.config(text="● LIVE",fg=GREEN)

    def _apply_thr(self):
        for r,v in self._thr_vars.items(): self._al.thr[r] = v.get()
        self._al.cd     = self._cd_var.get()
        self._al.snd_on = self._snd_var.get()
        self._al.ntf_on = self._ntf_var.get()
        self._al._last.clear()
        messagebox.showinfo("Saved","Alert settings applied.",parent=self)

    def _save_email(self):
        m = self._mail
        m.enabled  = self._em_on.get()
        m.host     = self._em_flds["host"].get().strip()
        m.sender   = self._em_flds["sender"].get().strip()
        m.password = self._em_flds["password"].get()
        m.recip    = self._em_flds["recip"].get().strip()
        m.cooldown = self._ecd_var.get()
        try:    m.port = int(self._em_flds["port"].get().strip() or 587)
        except: m.port = 587
        m.save()
        messagebox.showinfo("Saved","Email config saved successfully.",parent=self)

    def _test_email(self):
        self._save_email()
        ok,msg = self._mail.test()
        if ok: messagebox.showinfo("Success",msg,parent=self)
        else:  messagebox.showerror("Failed",msg,parent=self)

    def _refresh_logs(self):
        for i in self._tree.get_children(): self._tree.delete(i)
        rows = self._log.read()[1:]
        for i,r in enumerate(rows[-300:]):
            self._tree.insert("","end",values=r,
                              tags=("e" if i%2==0 else "o",))
        self._tree.tag_configure("e",background=BG_CARD)
        self._tree.tag_configure("o",background=BG_C2)
        if self._tree.get_children(): self._tree.yview_moveto(1.0)
        self._log_st.config(text=f"{len(rows)} entries  ·  {LOG_F}")

    def _clear_logs(self):
        if messagebox.askyesno("Clear Logs","Delete all log entries?",parent=self):
            self._log.clear(); self._refresh_logs()

    def _export(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV","*.csv"),("All","*.*")],
            initialfile=f"sysmon_{datetime.now():%Y%m%d_%H%M%S}.csv",
            title="Export Log")
        if path:
            try:
                shutil.copy(LOG_F,path)
                messagebox.showinfo("Exported",f"Saved to:\n{path}",parent=self)
            except Exception as e:
                messagebox.showerror("Error",str(e),parent=self)

    def _quit(self):
        self._run = False
        self._snd.cleanup()
        self.after(120, self.destroy)


# ═══════════════════════════════════════════════
if __name__ == "__main__":
    App().mainloop()