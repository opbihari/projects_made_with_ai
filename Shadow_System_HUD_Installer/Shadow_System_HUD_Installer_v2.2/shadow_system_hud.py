#!/usr/bin/env python3
"""
SHADOW SYSTEM HUD  -  desktop accountability engine for the November C Mastery Sprint

Follows YOUR plan day by day. There is no built-in plan: click 'Import plan' and feed it text,
markdown, HTML, Word, CSV, JSON, PDF, pasted text or a link (it also reads Google Docs / Sheets).

  * LIVE OVERLAY: the HUD is a click-through window drawn above your wallpaper, so it works
    with Lively Wallpaper (animated video/GIF/HTML wallpapers) as well as plain images.
    Pick a video here and the HUD sets it through Lively, then screenshots the live wallpaper
    to adapt to it (placement, light/dark text, accent colour, tone-matched warning lines).
  * WIDGETS you can show, restyle, resize and drag anywhere (Widgets... and Edit layout):
      Clock (ink, analog, minimal, stacked, arc, words, neon, resonance), Calendar (ink, seal,
      grid), Moon phase, Sprint, Status, Quests (click to verify / tick), Sprint map,
      Waveplate and Resonance (WuWa-style), System monitor, Music player, Focus timer.
  * The HUD adapts to the wallpaper: calm placement, light/dark text, accent colour, and
    warning lines that match the wallpaper's tone (or your own lines per wallpaper).
  * Quests come from the hub's daily tasks:
      CODE    verified for real: your .c file is compiled with gcc/clang and run against tests
      CHECK   verified from disk (certificate PDFs, folder structure, GitHub remote, git commit)
      MANUAL  videos, quizzes, HackerRank, exams: you tick them yourself (honour system)
  * Unfinished quests CARRY OVER to the next day. The penalty stays until the backlog is cleared.
  * BONUS quest each coding day: commit your code to git (+XP, does not block clearing).
  * CUSTOM WIDGETS (v2.1): add pictures / animated GIF / WebP / APNG you downloaded (from a file,
    a link, or a .zip containing one). They float, animate, drag and resize like built-in widgets.
  * REMOVE WALLPAPER (v2.1): the HUD forgets its wallpaper, restores your original Windows one
    (or a plain colour) and keeps the widgets floating over your own desktop.
  * Penalty mode (slightly desaturated, darkened edges) until everything required is done.
  * Anti-distraction monitor: forces the HUD on top if a game/launcher runs while uncleared.

Setup
  pip install pillow            (required)
  pip install opencv-python     (optional, only for video wallpapers)
  A C compiler (gcc or clang) on PATH, and git on PATH for the bonus/GitHub checks.

Run
  python shadow_system_hud.py
  python shadow_system_hud.py --install-startup      (auto-start at login)
  python shadow_system_hud.py --allow-exit           (lets you close it while uncleared)
  python shadow_system_hud.py --preview out.png [--day N] [--done K] [--mode active|urgent|overdue]
                              [--bg file] [--size 1920x1080]

Note: Windows cannot animate a wallpaper through this API. For GIF/video files the HUD shows one
frame that advances through the file during the day (new frame every 30 minutes).
"""
import colorsys
import datetime as dt
import json
import math
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import base64
import calendar
import ctypes
import bisect
import hashlib
import collections
import io
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile
from ctypes import wintypes
from html.parser import HTMLParser
from functools import lru_cache

try:
    from PIL import (Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont,
                     ImageOps, ImageSequence, ImageStat)
except ImportError:
    sys.exit("Pillow is missing. Run:  pip install pillow")

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog
except Exception:  # headless / preview use
    tk = None

IS_WIN = sys.platform == "win32"
NO_WINDOW = 0x08000000 if IS_WIN else 0
APP_DIR = os.path.join(os.path.expanduser("~"), ".shadow_system_hud")
STATE_PATH = os.path.join(APP_DIR, "player_state.json")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
CUSTOM_DIR = os.path.join(APP_DIR, "custom_widgets")
VIDEO_EXT = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}
ANIMATED_EXT = VIDEO_EXT | {".gif", ".html", ".htm"}

START_DATE = dt.date.today()           # Day 1 of the plan (set by the imported plan)
SPRINT_DAYS = 0                        # number of days in the plan
MILESTONES = {}
PHASES = {1: "YOUR PLAN"}
SPRINT = []


# ==================================================================================
# QUEST BUILDERS  (used by the plan loader; your plan itself comes from 'Import plan')
#   C(...)  code quest, auto-verified      K(...) disk check      M(...) tick by hand
#   Code tests: (stdin, expected[, forbidden]).  expected may be a list (all must appear)
#   and may use "a|b|c" alternatives. mode "tokens": consecutive words; "lines": consecutive
#   lines. tests=None -> compile + run + the `must` patterns must appear in your source.
# ==================================================================================
def C(file, label, tests=None, mode="tokens", must=(), must_not=(),
      stdin="5\n1 2 3 4 5\n", setup=None, expect_files=None):
    return {"kind": "code", "file": file, "label": label, "tests": tests, "mode": mode,
            "must": list(must), "must_not": list(must_not), "stdin": stdin,
            "setup": setup or {}, "expect_files": expect_files or {}}


def M(label):
    return {"kind": "manual", "label": label}


def K(label, checker, bonus=False):
    return {"kind": "check", "label": label, "checker": checker, "bonus": bonus}


def YN(stdin, yes, noun, extra_yes="", extra_no=""):
    """Semantic Yes/No test marker handled by check_yn() to avoid prompt false-positives."""
    return (stdin, f"__YN__:{'1' if yes else '0'}:{noun.upper()}:{extra_yes}:{extra_no}", None)


def _day(n, title, quests, phase=1):
    for i, q in enumerate(quests, 1):
        q.setdefault("bonus", False)
        q["id"] = f"q{i}"
        q["day"] = n
        q["key"] = f"d{n}:q{i}"
    return {"day": n, "title": title, "quests": quests, "phase": phase}


# ==================================================================================
# YOUR PLAN  (Option 1: "Import plan" button - any format | Option 2: edit in Python)
#   * Leave CUSTOM_PLAN = None to use ~/.shadow_system_hud/custom_plan.json (written by Import plan
#     / Edit plan). There is no built-in plan: with none loaded the HUD shows 'NO PLAN LOADED'.
#   * Or uncomment and edit CUSTOM_PLAN below to hardcode your own sprint in Python:
#
# CUSTOM_PLAN = {
#     "start_date": "2026-11-08",
#     "milestones": {7: "TARGET 1", 14: "FINAL"},
#     "phases": {1: "CORE LOGIC", 2: "SYSTEMS & SECURITY"},
#     "days": [
#         (1, "Custom Day 1 Title", [
#             M("Manual task: Watch lecture or complete lab"),
#             C("my_code.c", "Write program", [("5\n", "120")], must=[r"for|while"]),
#         ]),
#     ],
# }
# ==================================================================================
CUSTOM_PLAN = None
CUSTOM_PLAN_PATH = os.path.join(APP_DIR, "custom_plan.json")


def parse_quest_line(line):
    """Parse a 1-line quest shorthand from the GUI editor or custom_plan.json."""
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    low = s.lower()
    if low.startswith("code:"):
        parts = [p.strip() for p in s[5:].split("|")]
        fname = parts[0] if parts else "program.c"
        if not fname.lower().endswith(".c"):
            fname += ".c"
        label = parts[1] if len(parts) > 1 and parts[1] else f"Complete {fname}"
        tests, must, must_not = None, [], []
        for extra in parts[2:]:
            if "=>" in extra:
                tests = []
                for pair in extra.split(";"):
                    if "=>" in pair:
                        inp, exp = pair.split("=>", 1)
                        inp = inp.strip().replace("\\n", "\n")
                        if not inp.endswith("\n"):
                            inp += "\n"
                        tests.append((inp, exp.strip()))
            elif extra.lower().startswith("must:"):
                must = [x.strip() for x in extra[5:].split(",") if x.strip()]
            elif extra.lower().startswith("must_not:"):
                must_not = [x.strip() for x in extra[9:].split(",") if x.strip()]
        return C(fname, label, tests=tests, must=must, must_not=must_not)
    if low.startswith("check:"):
        parts = [p.strip() for p in s[6:].split("|")]
        chk = parts[0] if parts and parts[0] in ("certs", "folders", "github", "git_commit") else "git_commit"
        label = parts[1] if len(parts) > 1 and parts[1] else f"Check: {chk}"
        bonus = any(p.lower() == "bonus" for p in parts[2:]) or (chk == "git_commit")
        return K(label, chk, bonus=bonus)
    if low.startswith("manual:"):
        return M(s[7:].strip())
    return M(s)


def format_quest_line(q):
    """Convert a quest dict into editable 1-line shorthand for the Custom Plan GUI."""
    kind = q.get("kind", "manual")
    if kind == "code":
        base = f"code: {q['file']} | {q['label']}"
        if q.get("tests"):
            t_strs = []
            for t in q["tests"]:
                inp = t[0].replace("\n", "\\n").strip()
                exp = t[1] if isinstance(t[1], str) else " ".join(t[1])
                if not exp.startswith("__YN__:"):
                    t_strs.append(f"{inp} => {exp}")
            if t_strs:
                base += " | " + " ; ".join(t_strs)
        if q.get("must"):
            base += " | must: " + ", ".join(q["must"])
        return base
    if kind == "check":
        b = " | bonus" if q.get("bonus") else ""
        return f"check: {q.get('checker', 'git_commit')} | {q['label']}{b}"
    return f"manual: {q['label']}"


def _quest_from_item(item):
    if isinstance(item, str):
        return parse_quest_line(item)
    if isinstance(item, dict):
        k = item.get("kind", "manual")
        if k == "code":
            t_raw = item.get("tests")
            tests = [tuple(x) for x in t_raw] if isinstance(t_raw, list) else None
            return C(item.get("file", "main.c"), item.get("label", "Code quest"),
                     tests=tests, mode=item.get("mode", "tokens"),
                     must=item.get("must", ()), must_not=item.get("must_not", ()),
                     stdin=item.get("stdin", "5\n1 2 3 4 5\n"),
                     setup=item.get("setup"), expect_files=item.get("expect_files"))
        if k == "check":
            return K(item.get("label", "Disk check"), item.get("checker", "git_commit"),
                     bonus=bool(item.get("bonus", False)))
        return M(item.get("label", "Manual quest"))
    return None


def export_plan_dict():
    """Export the currently active SPRINT plan as a clean JSON-serializable dict."""
    days_out = []
    for d in SPRINT:
        qs = [q for q in d["quests"] if not (q.get("bonus") and q.get("checker") == "git_commit")]
        days_out.append({
            "day": d["day"],
            "title": d["title"],
            "phase": d.get("phase", 1),
            "quests": [format_quest_line(q) for q in qs],
        })
    return {
        "start_date": START_DATE.isoformat(),
        "auto_git_bonus": True,
        "milestones": {str(k): v for k, v in MILESTONES.items()},
        "phases": {str(k): v for k, v in PHASES.items()},
        "days": days_out,
    }


def rebuild_sprint(cfg=None):
    """Build SPRINT, START_DATE, SPRINT_DAYS, MILESTONES, PHASES from CUSTOM_PLAN or custom_plan.json.
    There is no built-in plan: with nothing loaded the plan is empty (nothing is due)."""
    global START_DATE, SPRINT_DAYS, MILESTONES, PHASES, SPRINT
    src = CUSTOM_PLAN
    if src is None:
        p = (cfg or {}).get("custom_plan_file") or CUSTOM_PLAN_PATH
        if p and os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    src = json.load(f)
            except Exception:
                src = None
    START_DATE, MILESTONES, PHASES, SPRINT, SPRINT_DAYS = dt.date.today(), {}, {1: "YOUR PLAN"}, [], 0
    if not (isinstance(src, dict) and src.get("days")):
        return
    try:
        START_DATE = dt.date.fromisoformat(str(src.get("start_date", "")).strip())
    except Exception:
        START_DATE = dt.date.today()
    if isinstance(src.get("milestones"), dict):
        MILESTONES = {int(k): str(v) for k, v in src["milestones"].items() if str(k).isdigit()}
    if isinstance(src.get("phases"), dict) and src["phases"]:
        PHASES = {int(k): str(v) for k, v in src["phases"].items() if str(k).isdigit()} or PHASES
    auto_git = src.get("auto_git_bonus", True)
    raw_days = {}
    for idx, d_item in enumerate(src["days"], 1):
        if isinstance(d_item, (list, tuple)) and len(d_item) >= 3:
            n, title, raw_qs, phase = int(d_item[0]), str(d_item[1]), list(d_item[2]), None
        elif isinstance(d_item, dict):
            n = int(d_item.get("day", idx))
            title = str(d_item.get("title", f"Day {n}"))
            raw_qs = d_item.get("quests", [])
            phase = d_item.get("phase")
        else:
            continue
        if n < 1:
            continue
        qs = [q for q in (_quest_from_item(x) for x in raw_qs) if q is not None]
        if n in raw_days:                                    # same day listed twice: merge
            raw_days[n][1].extend(qs)
        else:
            raw_days[n] = [title, qs, phase]
    new_sprint = []
    first_phase = min(PHASES)
    for n in range(1, (max(raw_days) if raw_days else 0) + 1):          # keep day N at index N-1
        title, qs, phase = raw_days.get(n, ["Rest day", [], None])
        if auto_git and any(q["kind"] == "code" for q in qs) and not any(q.get("checker") == "git_commit" for q in qs):
            qs.append(K("Commit today's code to git", "git_commit", bonus=True))
        try:
            phase = int(phase) if phase is not None else (new_sprint[-1]["phase"] if new_sprint else first_phase)
        except (TypeError, ValueError):
            phase = first_phase
        new_sprint.append(_day(n, title, qs, phase if phase in PHASES else first_phase))
    SPRINT = new_sprint
    SPRINT_DAYS = len(SPRINT)


rebuild_sprint()


# ==================================================================================
# PLAN IMPORT  -  feed the HUD your plan in (almost) any format:
#   plain text / markdown / HTML / Word (.docx) / CSV / JSON / PDF, a pasted block, or a link
# ==================================================================================
PLAN_MAX_BYTES = 8 * 1024 * 1024
PLAN_MAX_DAYS = 366
_MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july", "august",
                "september", "october", "november", "december"]
_MONTHS = {}
for _i, _n in enumerate(_MONTH_NAMES, 1):
    _MONTHS[_n] = _i
    _MONTHS[_n[:3]] = _i
_MONTHS["sept"] = 9
_MON = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
        r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_WD = r"(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?"
_DATE_RES = [
    re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)"),
    re.compile(r"(?<![\d.])(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?![\d])"),
    re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?\s*(?:of\s+)?\b(" + _MON + r")\b\.?(?:,?\s*(\d{4}))?",
               re.I),
    re.compile(r"\b(" + _MON + r")\b\.?\s*(\d{1,2})(?:st|nd|rd|th)?(?!\d)(?:,?\s*(\d{4}))?", re.I),
]
_DAY_RE = re.compile(r"^(?:day|d)\s*[-#.]?\s*(\d{1,3})(?!\d)\s*(?:[:.\-\u2013\u2014)|]+\s*)?(.*)$", re.I)
_PHASE_RE = re.compile(r"^(week|wk|phase|module|stage|part|unit|chapter|month|sprint|section|block)"
                       r"\s*[-#.]?\s*(\d{1,3})(?!\d)\s*(?:[:.\-\u2013\u2014)|]+\s*)?(.*)$", re.I)
_BULLET_RE = re.compile(r"^(?:(?:[-*+\u2022\u25aa\u25e6\u2023\u00b7\u2013\u2014]|\d{1,3}[.)])\s+|"
                        r"\[[ xX\u2713\u2714]?\]\s*|[\u2610\u2611\u2612\u2705\u2714\u25a1\u25a0\u25a2]\s*)")
_ACTION_PREFIXES = ("code:", "check:", "manual:")


def _mk_date(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        return None


def _year_for(m, d, ref=None):
    today = ref or dt.date.today()
    cand = _mk_date(today.year, m, d)
    if cand is not None and (cand - today).days < -200:
        cand = _mk_date(today.year + 1, m, d)
    return cand


def find_date(text, at_start=False):
    """First date in `text` -> (date, start, end), or None. Understands ISO, 8/11/2026 (day first),
    '8 Nov', 'Nov 8th 2026'. A leading weekday name is swallowed."""
    best = None
    for rx_i, rx in enumerate(_DATE_RES):
        for m in rx.finditer(text):
            if rx_i == 0:
                d = _mk_date(m.group(1), m.group(2), m.group(3))
            elif rx_i == 1:
                y = int(m.group(3))
                d = _mk_date(2000 + y if y < 100 else y, m.group(2), m.group(1))
            elif rx_i == 2:
                mon = _MONTHS.get(m.group(2).lower().rstrip("."))
                d = _mk_date(m.group(3), mon, m.group(1)) if m.group(3) else _year_for(mon, m.group(1))
            else:
                mon = _MONTHS.get(m.group(1).lower().rstrip("."))
                d = _mk_date(m.group(3), mon, m.group(2)) if m.group(3) else _year_for(mon, m.group(2))
            if d is None:
                continue
            s, e = m.start(), m.end()
            wd = re.search(r"(?:" + _WD + r")[\s,]*$", text[:s], re.I)
            if wd:
                s = wd.start()
            if at_start and text[:s].strip(" \t([-\u2013\u2014:#*"):
                continue
            if best is None or s < best[1]:
                best = (d, s, e)
            break
    return best


def _decode_text(data):
    if data[:3] == b"\xef\xbb\xbf":
        return data[3:].decode("utf-8", "replace")
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", "replace")


def _clean_item(t):
    t = re.sub(r"\[([^\]]+)\]\((?:[^)]*)\)", r"\1", t)
    t = t.replace("**", "").replace("__", "").replace("`", "")
    return re.sub(r"\s+", " ", t).strip(" \t\u200b")


class _PlanHTML(HTMLParser):
    """HTML -> markdown-ish lines (# headings, - items) plus a list of table rows."""
    SKIP = {"script", "style", "noscript", "head", "template", "svg", "title"}
    BLOCK = {"p", "div", "section", "article", "br", "ul", "ol", "table", "header", "footer",
             "main", "nav", "aside", "details", "form", "blockquote", "pre", "dd", "dt", "figure",
             "tbody", "thead"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines, self.tables = [], []
        self.buf, self.skip, self.head, self.prefix = [], 0, 0, ""
        self.cell, self.row, self.rows = None, None, None

    def flush(self):
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        self.buf = []
        if text:
            self.lines.append(("#" * self.head + " " if self.head else self.prefix) + text)
        self.prefix = ""

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if len(tag) == 2 and tag[0] == "h" and tag[1].isdigit():
            self.flush()
            self.head = int(tag[1])
        elif tag == "summary":
            self.flush()
            self.head = 3
        elif tag == "li":
            self.flush()
            self.prefix = "- "
        elif tag == "input" and dict(attrs).get("type") == "checkbox":
            self.flush()
            self.prefix = "- "
        elif tag == "table":
            self.flush()
            self.rows = []
        elif tag == "tr":
            self.flush()
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []
        elif self.cell is not None and (tag in self.BLOCK or tag == "li"):
            self.cell.append("\n")
        elif tag in self.BLOCK:
            self.flush()

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if len(tag) == 2 and tag[0] == "h" and tag[1].isdigit():
            self.flush()
            self.head = 0
        elif tag == "summary":
            self.flush()
            self.head = 0
        elif tag in ("td", "th"):
            if self.cell is not None and self.row is not None:
                txt = re.sub(r"[ \t\r\f\v]+", " ", "".join(self.cell))
                self.row.append(re.sub(r"\s*\n\s*", "\n", txt).strip())
            self.cell = None
        elif tag == "tr":
            if self.row and any(self.row):
                if self.rows is not None:
                    self.rows.append(self.row)
                self.lines.append("- " + " \u2014 ".join(c.replace("\n", "; ") for c in self.row if c))
            self.row = None
        elif tag == "table":
            if self.rows:
                self.tables.append(self.rows)
            self.rows = None
        elif tag == "li" or tag in self.BLOCK:
            self.flush()

    def handle_data(self, data):
        if self.skip:
            return
        if self.cell is not None:
            self.cell.append(data)
        else:
            self.buf.append(data)


def _html_lines(text):
    p = _PlanHTML()
    p.feed(text)
    p.flush()
    return p.lines, p.tables


def _docx_lines(data):
    zf = zipfile.ZipFile(io.BytesIO(data))
    info = zf.getinfo("word/document.xml")
    if info.file_size > 40 * 1024 * 1024:
        raise ValueError("That Word file is too big to read.")
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ET.fromstring(zf.read("word/document.xml"))
    body = root.find(ns + "body")
    lines, tables = [], []

    def para_text(p):
        out = []
        for el in p.iter():
            if el.tag == ns + "t" and el.text:
                out.append(el.text)
            elif el.tag in (ns + "tab", ns + "br"):
                out.append(" ")
        return re.sub(r"\s+", " ", "".join(out)).strip()

    for el in (body if body is not None else []):
        if el.tag == ns + "p":
            t = para_text(el)
            if not t:
                continue
            st = el.find(f"{ns}pPr/{ns}pStyle")
            style = (st.get(ns + "val") if st is not None else "") or ""
            m = re.match(r"heading\s*(\d)", style, re.I)
            if m:
                lines.append("#" * int(m.group(1)) + " " + t)
            elif style.lower() == "title":
                lines.append("# " + t)
            elif el.find(f"{ns}pPr/{ns}numPr") is not None or "list" in style.lower():
                lines.append("- " + t)
            else:
                lines.append(t)
        elif el.tag == ns + "tbl":
            rows = []
            for tr in el.iter(ns + "tr"):
                cells = [" ".join(para_text(p) for p in tc.iter(ns + "p")).strip()
                         for tc in tr.findall(ns + "tc")]
                if any(cells):
                    rows.append(cells)
                    lines.append("- " + " \u2014 ".join(c for c in cells if c))
            if rows:
                tables.append(rows)
    return lines, tables


def _pdf_text(data):
    for mod, fn in (("pypdf", "PdfReader"), ("PyPDF2", "PdfReader")):
        try:
            lib = __import__(mod)
            rd = getattr(lib, fn)(io.BytesIO(data))
            return "\n".join((pg.extract_text() or "") for pg in rd.pages)
        except ImportError:
            continue
        except Exception as e:
            raise ValueError(f"Could not read that PDF ({e}).")
    raise ValueError("Reading PDFs needs one extra package: run  pip install pypdf  and try again "
                     "(or copy the text out of the PDF and paste it into the box).")


def _md_tables(lines):
    """Pull markdown tables ( | a | b | ) out of text lines; returns (lines, tables)."""
    out, tables, cur = [], [], []
    for ln in lines + [""]:
        s = ln.strip()
        if s.startswith("|") and s.count("|") >= 2:
            if re.match(r"^\|?[\s:\-|]+\|?$", s) and "-" in s:
                continue
            cells = [re.sub(r"<br\s*/?>", "\n", c.strip(), flags=re.I) for c in s.strip("|").split("|")]
            cur.append(cells)
            out.append("- " + " \u2014 ".join(c.replace("\n", "; ") for c in cells if c))
        else:
            if cur:
                tables.append(cur)
                cur = []
            out.append(ln)
    out.pop()
    return out, tables


# ---- header-name tables (CSV / HTML / docx / markdown tables)
def _hn(h):
    return re.sub(r"[^a-z0-9#]", "", str(h).lower())


_H_DAY = {"day", "days", "d", "no", "num", "number", "sno", "sr", "srno", "daynumber", "dayno", "#"}
_H_DATE = {"date", "dates", "when", "on", "day/date"}
_H_TITLE = {"title", "topic", "topics", "theme", "focus", "subject", "heading", "name", "chapter",
            "lesson", "goal", "goals", "headline"}
_H_TASK = {"task", "tasks", "quest", "quests", "item", "items", "todo", "todos", "activity",
           "activities", "work", "assignment", "assignments", "exercise", "exercises",
           "deliverable", "deliverables", "description", "details", "checklist", "objectives",
           "objective", "plan", "whattodo", "tobedone"}
_H_PHASE = {"week", "phase", "stage", "module", "sprint", "month", "unit", "part"}


def _table_columns(row):
    cols = {}
    for i, h in enumerate(row):
        n = _hn(h)
        for key, names in (("day", _H_DAY), ("date", _H_DATE), ("task", _H_TASK),
                           ("title", _H_TITLE), ("phase", _H_PHASE)):
            if n in names and key not in cols:
                cols[key] = i
                break
    return cols


def _split_tasks(cell, semicolons=True):
    cell = str(cell)
    if "\n" in cell or re.search(r"[\u2022\u25cf\u25aa]", cell):        # explicit list: keep ';' inside items
        parts = re.split(r"\s*(?:\n|[\u2022\u25cf\u25aa])\s*", cell)
    elif semicolons:
        parts = re.split(r"\s*;\s+", cell)
    else:
        parts = [cell]
    out = []
    for p in parts:
        p = _BULLET_RE.sub("", p.strip())
        p = _clean_item(p)
        if p:
            out.append(p)
    return out


def _days_from_table(rows):
    """Rows -> day dicts, or None when the table does not look like a plan."""
    if len(rows) < 2:
        return None
    hdr_i, cols = None, {}
    for i, row in enumerate(rows[:5]):
        c = _table_columns(row)
        if ("task" in c or "title" in c) and ("day" in c or "date" in c or "title" in c):
            if len(c) >= 2:
                hdr_i, cols = i, c
                break
    if hdr_i is None:
        return None
    days, cur, phase_name = [], None, None
    body = rows[hdr_i + 1:]
    di = cols.get("day", cols.get("date"))
    one_per_row = ("task" in cols and di is not None and
                   any((di < len(r) and not r[di].strip()) and cols["task"] < len(r) and r[cols["task"]].strip()
                       for r in body))               # blank day cells = one task per row
    for row in body:
        def cell(k):
            i = cols.get(k)
            return row[i].strip() if i is not None and i < len(row) else ""
        dtxt, dctxt = cell("day"), cell("date")
        n, date_ = None, None
        m = re.search(r"\d{1,3}", dtxt)
        if m:
            n = int(m.group())
        fd = find_date(dctxt or dtxt)
        if fd:
            date_ = fd[0]
        if cell("phase"):
            phase_name = cell("phase")
        starts_new = n is not None or date_ is not None or cur is None
        if starts_new:
            if (cur is not None and n is not None and cur["n"] == n):
                starts_new = False
        if starts_new:
            cur = {"n": n, "date": date_, "title": cell("title"), "tasks": [], "phase": phase_name}
            days.append(cur)
        elif cell("title") and not cur["title"]:
            cur["title"] = cell("title")
        tasks = _split_tasks(cell("task"), semicolons=not one_per_row) if "task" in cols else []
        if not tasks and "task" not in cols and cell("title"):
            tasks = [cell("title")]
        cur["tasks"].extend(tasks)
    days = [d for d in days if d["tasks"] or d["title"]]
    return days or None


def _days_from_headerless_table(rows):
    if len(rows) < 2 or max(len(r) for r in rows) < 2:
        return None
    first = [r[0].strip() for r in rows if r and r[0].strip()]
    hits = sum(1 for v in first if _DAY_RE.match(v) or find_date(v, True) or re.fullmatch(r"\d{1,3}", v))
    if not first or hits < 0.6 * len(first):
        return None
    days = []
    for r in rows:
        if not r or not r[0].strip():
            continue
        m = re.search(r"\d{1,3}", r[0])
        fd = find_date(r[0])
        rest = [c for c in r[1:] if c.strip()]
        title = rest[0] if len(rest) >= 2 else ""
        tasks = []
        for c in (rest[1:] if len(rest) >= 2 else rest):
            tasks.extend(_split_tasks(c))
        days.append({"n": int(m.group()) if (m and not fd) else None, "date": fd[0] if fd else None,
                     "title": title, "tasks": tasks, "phase": None})
    return days or None


# ---- text / markdown lines -> days
def _classify(lines):
    toks = []
    n = len(lines)
    for i, raw in enumerate(lines):
        s = raw.rstrip()
        if not s.strip():
            continue
        indent = len(s) - len(s.lstrip())
        s = s.strip()
        level = 0
        md = re.match(r"^(#{1,6})\s+(.*)$", s)
        if md:
            level, s = len(md.group(1)), md.group(2)
        bullet = False
        if not level:
            b = _BULLET_RE.match(s)
            if b:
                bullet, s = True, s[b.end():]
        s = _clean_item(s)
        if not s:
            continue
        low = s.lower()
        if low.startswith(_ACTION_PREFIXES):
            toks.append(("task", s, indent))
            continue
        dm = _DAY_RE.match(s) if (not bullet or indent < 2) else None
        if dm and (level or not bullet or True):
            rest = dm.group(2).strip()
            fd = find_date(rest)
            date_ = None
            if fd:
                date_ = fd[0]
                rest = (rest[:fd[1]] + " " + rest[fd[2]:]).strip(" ()[]-\u2013\u2014:,|")
            toks.append(("day", int(dm.group(1)), _clean_item(rest), date_))
            continue
        if not bullet:
            pm = _PHASE_RE.match(s)
            if pm and (level or len(s) <= 70):
                name = pm.group(3).strip() or f"{pm.group(1).title()} {pm.group(2)}"
                toks.append(("phase", name))
                continue
            fd = find_date(s, at_start=True)
            if fd and (level or len(s) <= 90):
                rest = s[fd[2]:].strip()
                if re.match(r"^\s*(?:[-\u2013\u2014]|to|until)\s*(?:\d|" + _MON + r")", rest, re.I):
                    toks.append(("phase", s))            # a date range such as 'Nov 8 - Nov 14'
                else:
                    toks.append(("date", fd[0], rest.strip(" -\u2013\u2014:,|)(")))
                continue
        if level:
            toks.append(("head", level, s))
            continue
        if bullet:
            toks.append(("task", s, indent))
            continue
        nxt = ""
        for j in range(i + 1, n):
            if lines[j].strip():
                nxt = lines[j].strip()
                break
        if (s.endswith(":") and len(s) <= 70 and nxt and _BULLET_RE.match(nxt)):
            toks.append(("head", 2, s.rstrip(":").strip()))
        else:
            toks.append(("text", s, indent))
    return toks


def _days_from_tokens(toks, notes):
    has_day = any(t[0] in ("day", "date") for t in toks)
    heads = [t for t in toks if t[0] == "head"]
    mode_head = (not has_day) and len(heads) >= 2
    has_bullets = any(t[0] == "task" for t in toks)
    days, cur, pid = [], None, None
    ignored = 0

    def new_day(n, date_, title):
        d = {"n": n, "date": date_, "title": title, "tasks": [], "phase": pid, "_untitled": not title}
        days.append(d)
        return d

    flat = []
    for t in toks:
        k = t[0]
        if k == "phase":
            pid = t[1]
        elif k == "day":
            cur = new_day(t[1], t[3], t[2])
        elif k == "date":
            cur = new_day(None, t[1], t[2])
        elif k == "head":
            if mode_head:
                cur = new_day(None, None, t[2])
        elif k == "task":
            (cur["tasks"] if cur else flat).append(t[1])
        elif k == "text":
            if cur is not None and cur["_untitled"] and not cur["tasks"] and has_bullets \
                    and len(t[1]) <= 90:
                cur["title"], cur["_untitled"] = t[1], False
            elif not has_bullets:
                (cur["tasks"] if cur else flat).append(t[1])
            else:
                ignored += 1
    if flat:
        if days and has_day:
            notes.append(f"{len(flat)} item(s) before the first day heading were skipped.")
        else:
            days.insert(0, {"n": None, "date": None, "title": "", "tasks": flat, "phase": None,
                            "_untitled": True, "_flat": True})
    if ignored:
        notes.append(f"{ignored} descriptive line(s) without a bullet were ignored.")
    return [d for d in days if d["tasks"] or d["title"] or d.get("n")], has_day or mode_head


def _plan_quest_line(text, auto_code):
    t = text.strip()
    if t.lower().startswith(_ACTION_PREFIXES):
        return t
    t = t.replace("|", "/")
    if len(t) > 160:
        t = t[:157].rstrip() + "..."
    if auto_code:
        m = re.search(r"(?<![\w.])([A-Za-z0-9_][\w\-]{0,40}\.c)(?![\w.])", t)
        if m:
            return f"code: {m.group(1)} | {t}"
    return "manual: " + t


def _assemble_plan(days, opts, notes, extra=None):
    """Number the days, fill gaps, name phases and emit the plan dict the HUD loads."""
    extra = extra or {}
    start_opt = opts.get("start")
    per_day = int(opts.get("per_day") or 0)
    auto_code = bool(opts.get("auto_code", True))
    today = dt.date.today()
    if not days:
        raise ValueError("I could not find any tasks in that. Try a list with one task per line, "
                         "optionally under 'Day 1', 'Day 2' ... headings.")
    flat_only = len(days) == 1 and days[0].get("_flat")
    if flat_only and per_day > 0:
        tasks = days[0]["tasks"]
        days = [{"n": i + 1, "date": None, "title": "", "tasks": tasks[k:k + per_day], "phase": None}
                for i, k in enumerate(range(0, len(tasks), per_day))]
    dated = [d for d in days if d.get("date")]
    start = start_opt
    if start is None and extra.get("start_date"):
        fd = find_date(str(extra["start_date"]))
        start = fd[0] if fd else None
    if start is None:
        if dated:
            first = dated[0]
            start = first["date"] - dt.timedelta(days=(first["n"] - 1) if first.get("n") else 0)
        else:
            start = today
    seq = 0
    for d in days:
        if d.get("n") is None:
            if d.get("date"):
                d["n"] = (d["date"] - start).days + 1
            else:
                seq += 1
                d["n"] = seq
        else:
            seq = max(seq, d["n"])
    merged = {}
    for d in sorted(days, key=lambda x: x["n"]):
        if d["n"] < 1 or d["n"] > PLAN_MAX_DAYS:
            notes.append(f"Day {d['n']} is outside 1-{PLAN_MAX_DAYS} and was skipped.")
            continue
        m = merged.get(d["n"])
        if m is None:
            merged[d["n"]] = d
        else:
            m["tasks"].extend(d["tasks"])
            if not m["title"]:
                m["title"] = d["title"]
    if not merged:
        raise ValueError("No usable days were found in that.")
    phase_ids, day_out, ntask, ncode = {}, [], 0, 0
    for n in sorted(merged):                                  # phase names in document order
        pn = merged[n].get("phase")
        if pn is not None and pn not in phase_ids:
            phase_ids[pn] = len(phase_ids) + 1
    last = max(merged)
    unphased = 0 if phase_ids else 1                          # days before the first named phase
    prev_phase, used_unphased = None, False
    for n in range(1, last + 1):
        d = merged.get(n)
        if d is not None and d.get("phase") is not None:
            prev_phase = d["phase"]
        pid = phase_ids[prev_phase] if prev_phase is not None else unphased
        used_unphased = used_unphased or prev_phase is None
        if d is None:
            day_out.append({"day": n, "title": "Rest day", "phase": pid, "quests": []})
            continue
        quests = []
        for t in d["tasks"]:
            line = _plan_quest_line(t, auto_code)
            if line.lower().startswith("manual:") and not line[7:].strip():
                continue
            quests.append(line)
            ntask += 1
            ncode += line.lower().startswith("code:")
        day_out.append({"day": n, "title": (d["title"] or f"Day {n}")[:80], "phase": pid,
                        "quests": quests})
    if ntask == 0:
        raise ValueError("I found day headings but no tasks under them.")
    phases = {str(v): re.sub(r"\s+", " ", k).upper()[:28] for k, v in phase_ids.items()}
    if used_unphased:
        phases[str(unphased)] = "YOUR PLAN"
    plan = {"start_date": start.isoformat(), "auto_git_bonus": True,
            "milestones": ({str(last): "FINAL"} if last >= 2 else {}),
            "phases": phases, "days": day_out}
    if isinstance(extra.get("milestones"), dict):
        plan["milestones"] = {str(k): str(v) for k, v in extra["milestones"].items()}
    if isinstance(extra.get("phases"), dict) and extra["phases"]:
        plan["phases"] = {str(k): str(v) for k, v in extra["phases"].items()}
    plan["_report"] = {"days": last, "quests": ntask, "code": ncode, "notes": notes,
                       "dated": bool(dated)}
    return plan


def _days_from_json(obj, depth=0):
    """Normalise whatever JSON shape we are given into (days, extra)."""
    extra = {}
    if isinstance(obj, dict):
        for k in ("start_date", "milestones", "phases"):
            if k in obj:
                extra[k] = obj[k]
        for key in ("days", "plan", "schedule", "sprint", "curriculum", "roadmap", "items", "tasks"):
            if key in obj and isinstance(obj[key], (list, dict)):
                days, ex = _days_from_json(obj[key], depth + 1)
                extra.update(ex)
                return days, extra
        keys = list(obj)
        if keys and all(isinstance(obj[k], (list, str)) for k in keys):       # {"Day 1": [..], ...}
            days = []
            for k in keys:
                m = _DAY_RE.match(str(k))
                fd = find_date(str(k))
                days.append({"n": int(m.group(1)) if m else None, "date": fd[0] if fd else None,
                             "title": (m.group(2) if m else str(k)).strip(), "phase": None,
                             "tasks": [_clean_item(str(x)) for x in obj[k] if str(x).strip()]
                             if isinstance(obj[k], list) else _split_tasks(obj[k])})
            return days, extra
        return [], extra
    if isinstance(obj, list):
        if obj and all(isinstance(x, str) for x in obj):
            return [{"n": None, "date": None, "title": "", "tasks": [_clean_item(x) for x in obj if x.strip()],
                     "phase": None, "_flat": True}], extra
        days = []
        for i, it in enumerate(obj, 1):
            if isinstance(it, dict):
                raw = None
                for key in ("quests", "tasks", "items", "todo", "checklist", "activities", "work"):
                    if key in it:
                        raw = it[key]
                        break
                tasks = []
                for x in (raw if isinstance(raw, list) else [raw] if raw else []):
                    if isinstance(x, dict):
                        x = x.get("label") or x.get("title") or x.get("task") or x.get("name") or ""
                    x = _clean_item(str(x)) if not str(x).lower().startswith(_ACTION_PREFIXES) else str(x)
                    if x:
                        tasks.append(x)
                n = it.get("day", it.get("n"))
                fd = find_date(str(it.get("date", ""))) if it.get("date") else None
                days.append({"n": int(n) if str(n).isdigit() else None, "date": fd[0] if fd else None,
                             "title": str(it.get("title") or it.get("name") or it.get("topic") or ""),
                             "phase": None, "tasks": tasks})
            elif isinstance(it, (list, tuple)) and len(it) >= 3:      # [n, title, [quests]]
                days.append({"n": int(it[0]), "date": None, "title": str(it[1]), "phase": None,
                             "tasks": [str(x) for x in it[2]]})
        return days, extra
    return [], extra


def _sniff_and_lines(data, name, ctype, depth=0):
    """Return ('json', obj) | ('lines', lines, tables, kind) | ('rows', rows, kind)."""
    low_name = (name or "").lower()
    ext = os.path.splitext(low_name.split("?")[0])[1]
    if not data:
        raise ValueError("That is empty.")
    if data[:4] == b"%PDF":
        return ("lines", _decode_text(_pdf_text(data).encode("utf-8")).splitlines(), [], "pdf")
    if data[:2] == b"PK":
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise ValueError("That zip / Word file is damaged.")
        names = zf.namelist()
        if "word/document.xml" in names:
            lines, tables = _docx_lines(data)
            return ("lines", lines, tables, "docx")
        if depth == 0:
            for want in (".json", ".md", ".markdown", ".txt", ".html", ".htm", ".csv", ".docx", ".pdf"):
                for zi in zf.infolist():
                    if not zi.is_dir() and zi.filename.lower().endswith(want) and zi.file_size <= PLAN_MAX_BYTES:
                        return _sniff_and_lines(zf.read(zi), zi.filename, "", 1)
        raise ValueError("I could not find a plan file (txt / md / html / csv / json / docx) in that zip.")
    text = _decode_text(data)
    if "\x00" in text[:4000]:
        raise ValueError("That does not look like a text document (it is a binary file). "
                         "Supported: txt, md, html, docx, csv, json, pdf, or a link.")
    st = text.lstrip()
    if st[:1] in "{[" and ("json" in ctype or ext == ".json" or st[:1] in "{["):
        try:
            return ("json", json.loads(text))
        except ValueError:
            pass
    looks_html = (ext in (".html", ".htm") or "html" in ctype
                  or (st[:1] == "<" and re.search(r"<\s*(html|body|div|ul|ol|li|h[1-6]|table|p)\b",
                                                  st[:5000], re.I)))
    if looks_html:
        lines, tables = _html_lines(text)
        if len(lines) < 3 and re.search(r"<script", text, re.I):
            raise ValueError("That page builds itself with JavaScript, so there is no plain text to "
                             "read. Export / save it as .html, .md or .txt (or select-all and paste "
                             "the text into the box).")
        return ("lines", lines, tables, "html")
    if ext in (".csv", ".tsv") or "csv" in ctype:
        import csv
        try:
            dialect = csv.Sniffer().sniff(text[:4000], delimiters=",;\t|")
        except Exception:
            dialect = csv.excel_tab if ext == ".tsv" else csv.excel
        rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
        return ("rows", rows, "csv")
    first = text.splitlines()[0] if text.strip() else ""
    for delim in ("\t", ","):
        if first.count(delim) >= 1 and _table_columns(first.split(delim)) and len(_table_columns(first.split(delim))) >= 2:
            import csv
            rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
            return ("rows", rows, "csv")
    lines = text.splitlines()
    lines, tables = _md_tables(lines)
    return ("lines", lines, tables, "text")


def import_plan(data, name="", ctype="", opts=None):
    """Turn any supported plan document into the HUD's plan dict (see export_plan_dict).
    opts: start (date or None), auto_code (bool), per_day (int, for flat lists)."""
    opts = dict(opts or {})
    if len(data) > PLAN_MAX_BYTES:
        raise ValueError("That file is larger than 8 MB.")
    notes = []
    got = _sniff_and_lines(data, name, (ctype or "").lower())
    kind = got[0]
    days, extra, fmt = None, {}, ""
    if kind == "json":
        days, extra = _days_from_json(got[1])
        fmt = "json"
    elif kind == "rows":
        days = _days_from_table(got[1]) or _days_from_headerless_table(got[1])
        fmt = got[2]
        if not days:
            days = [{"n": None, "date": None, "title": "", "phase": None, "_flat": True,
                     "tasks": [" \u2014 ".join(c for c in r if c) for r in got[1]]}]
            notes.append("No Day / Task columns found: every row became one task.")
    else:
        lines, tables, fmt = got[1], got[2], got[3]
        for t in tables:
            days = _days_from_table(t)
            if days:
                break
        if not days:
            toks = _classify(lines)
            days, _structured = _days_from_tokens(toks, notes)
    plan = _assemble_plan(days, opts, notes, extra)
    plan["_report"]["format"] = fmt
    return plan


def plan_summary(plan, limit=40):
    rep = plan.get("_report", {})
    out = [f"{rep.get('days', len(plan['days']))} days, {rep.get('quests', '?')} tasks "
           f"({rep.get('code', 0)} auto-verified .c quests), starting {plan['start_date']}"
           + (f"   [read as {rep['format']}]" if rep.get("format") else "")]
    for n in rep.get("notes", []):
        out.append("  note: " + n)
    out.append("")
    shown = 0
    for d in plan["days"]:
        if shown >= limit:
            out.append(f"... and {len(plan['days']) - shown} more days")
            break
        out.append(f"Day {d['day']:>2}  {d['title']}  ({len(d['quests'])})")
        for q in d["quests"][:6]:
            lab = q.split("|")[1].strip() if q.lower().startswith("code:") and "|" in q else q.split(":", 1)[-1].strip()
            out.append(("   \u25a3 " if q.lower().startswith("code:") else "   \u25a1 ") + lab[:90])
        if len(d["quests"]) > 6:
            out.append(f"   ... +{len(d['quests']) - 6} more")
        shown += 1
    return "\n".join(out)


def fetch_plan_url(url, timeout=25):
    """Download a plan from a link. Understands Google Docs / Sheets and GitHub 'blob' links."""
    u = url.strip()
    p = urllib.parse.urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("Paste the full link, starting with https://")
    host = p.netloc.lower()
    m = re.search(r"/document/d/([\w-]+)", p.path)
    if "docs.google.com" in host and m:
        u = f"https://docs.google.com/document/d/{m.group(1)}/export?format=txt"
    m = re.search(r"/spreadsheets/d/([\w-]+)", p.path)
    if "docs.google.com" in host and m:
        gid = re.search(r"gid=(\d+)", u)
        u = f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv" + (f"&gid={gid.group(1)}" if gid else "")
    if host == "github.com" and "/blob/" in p.path:
        u = "https://raw.githubusercontent.com" + p.path.replace("/blob/", "/", 1)
    req = urllib.request.Request(u, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ShadowSystemHUD/2.2",
        "Accept": "text/html,text/plain,application/json,text/csv,*/*;q=0.5"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(PLAN_MAX_BYTES + 1)
            ctype = r.headers.get("Content-Type", "") or ""
    except urllib.error.HTTPError as e:
        hint = (" Make sure the document is shared as 'Anyone with the link can view'."
                if e.code in (401, 403, 404) and "google" in host else "")
        raise ValueError(f"The server answered {e.code} {e.reason}.{hint}")
    except urllib.error.URLError as e:
        raise ValueError(f"Could not reach that address ({e.reason}).")
    except Exception as e:
        raise ValueError(f"Download failed: {e}")
    if len(data) > PLAN_MAX_BYTES:
        raise ValueError("That page is larger than 8 MB.")
    return data, ctype, os.path.basename(urllib.parse.unquote(p.path)) or host


def plan_signature(plan):
    return hashlib.sha1(json.dumps(plan, sort_keys=True).encode("utf-8")).hexdigest()[:12]




def day_index(day):
    return (day - START_DATE).days + 1


def quests_for(day, completed):
    """Today's quests plus carried-over unfinished ones from earlier sprint days."""
    idx = day_index(day)
    if idx < 1 or idx > SPRINT_DAYS:
        return [], None
    out = []
    for d in SPRINT[:idx]:
        for q in d["quests"]:
            if q["bonus"]:
                if d["day"] == idx:
                    out.append(q)
            elif d["day"] == idx or q["key"] not in completed:
                out.append(q)
    out.sort(key=lambda q: (q["bonus"], q["day"]))
    return out, SPRINT[idx - 1]


def gating(quests):
    return [q for q in quests if not q["bonus"]]


# ==================================================================================
# messages, ranks, config
# ==================================================================================
PENALTY_MSG = {
    "ink": ["The brush is dry. Write the code.",
            "One stroke at a time. One loop at a time.",
            "The mountain does not climb itself."],
    "shadow": ["The shadows are waiting. Write the code.",
               "Weak hunters hide. Open your editor.",
               "Rise from the dark, one loop at a time."],
    "ember": ["Your fire is dying. Feed it code.",
              "Burn the excuse. Compile the loop.",
              "Embers fade fast. Strike now."],
    "sky": ["Clear skies, empty editor. Fix that.",
            "The day is bright. Your code is not written.",
            "Open sky, open file. Begin."],
    "sun": ["The sun is up. So are the quests.",
            "Daylight is burning. Start the loop.",
            "Golden hour is for shipping code."],
}
CLEARED_MSG = {
    "ink": ["The mountain is climbed. Rest, Monarch.",
            "Ink dried, work done. Breathe."],
    "shadow": ["The shadows bow to you. Rest, Monarch.",
               "Quests cleared. The dark answers to you."],
    "ember": ["The flame holds. Quests cleared.", "Forged today. Cleared."],
    "sky": ["Clear skies and a clean slate. Cleared.", "Quests done. Look up at the sky."],
    "sun": ["Day won. The sun is yours.", "Cleared in daylight. Well done."],
}
ESCALATION = {"URGENT": "Under 2 hours left. ",
              "OVERDUE": "Deadline missed. Streak is at risk. "}
BADGE = {"ACTIVE": "PENALTY MODE", "URGENT": "URGENT",
         "OVERDUE": "OVERDUE", "CLEARED": "CLEARED"}
MOODS = {(True, False): "shadow", (True, True): "ember",
         (False, False): "sky", (False, True): "sun"}
RANKS = [("E", 0), ("D", 300), ("C", 800), ("B", 1500), ("A", 2500), ("S", 4000)]
XP_CODE, XP_MANUAL, XP_BONUS, XP_CLEAR = 50, 20, 25, 100

DEFAULT_CONFIG = {
    "wallpaper": "", "workspace": "", "hub_file": "", "deadline": "22:00",
    "engine": "", "overlay_mode": "auto", "overlay_layer": "normal", "lively_exe": "", "compiler_exe": "", "custom_plan_file": "",
    "widgets": None, "focus_minutes": 25, "break_minutes": 5,
    "custom_widgets": [], "no_wallpaper": False, "orig_wallpaper": "", "plan_prompted": False,
    "refresh_minutes": 1, "clock_24h": True, "custom_messages": {},
    "distraction_scan_seconds": 15,
    "distraction_processes": [
        "steam.exe", "genshinimpact.exe", "epicgameslauncher.exe",
        "valorant-win64-shipping.exe", "riotclientservices.exe",
        "fortniteclient-win64-shipping.exe", "gta5.exe"],
}
DEFAULT_STATE = {"xp": 0, "streak": 0, "best_streak": 0, "last_clear_date": None,
                 "day": None, "completed": [], "awarded": [], "focus": {"date": None, "count": 0}}


# ==================================================================================
# persistence + state
# ==================================================================================
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return {**json.loads(json.dumps(default)), **json.load(f)}
    except Exception:
        return json.loads(json.dumps(default))


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def roll_state(st, today):
    iso = today.isoformat()
    if st.get("day") != iso:
        yday = (today - dt.timedelta(days=1)).isoformat()
        if st.get("last_clear_date") not in (yday, iso):
            st["streak"] = 0
        st["day"] = iso
    return st


def rank_info(xp):
    idx = 0
    for i, (_, need) in enumerate(RANKS):
        if xp >= need:
            idx = i
    if idx == len(RANKS) - 1:
        return RANKS[idx][0], 1.0, None
    lo, hi = RANKS[idx][1], RANKS[idx + 1][1]
    return RANKS[idx][0], (xp - lo) / (hi - lo), RANKS[idx + 1][0]


def parse_deadline(text, day):
    hh, mm = text.strip().split(":")
    return dt.datetime.combine(day, dt.time(int(hh), int(mm)))


def compute_level(completed, quests, deadline_dt, now):
    req = gating(quests)
    if not req or all(q["key"] in completed for q in req):
        return "CLEARED"
    rem = (deadline_dt - now).total_seconds()
    if rem < 0:
        return "OVERDUE"
    return "URGENT" if rem < 7200 else "ACTIVE"


def day_done(day_no, completed):
    qs = [q for q in SPRINT[day_no - 1]["quests"] if not q["bonus"]]
    return all(q["key"] in completed for q in qs)


# ==================================================================================
# verification
# ==================================================================================
QUEST_ALIASES = {
    "sum_of_digits.c": ("sum_digits", "sumofdigits", "digits_sum", "digitsum", "sum"),
    "reverse_number.c": ("reverse", "rev_num", "reversenumber", "rev", "reverse_digits"),
    "palindrome_check.c": ("palindrome", "palin", "is_palindrome", "check_palindrome"),
    "armstrong.c": ("armstrong_number", "armstrong_check", "is_armstrong", "arm"),
    "prime_check.c": ("prime", "is_prime", "primenumber", "prime_number", "check_prime"),
    "factorial.c": ("fact", "factorial_num", "factorial_number"),
    "fibonacci.c": ("fib", "fibo", "fibonacci_series", "fib_series"),
    "patterns_basic.c": ("pattern", "patterns", "pyramid", "star_pattern"),
    "floyd_triangle.c": ("floyd", "floyds_triangle", "floyd_pattern"),
    "array_sum_avg.c": ("sum_avg", "array_sum", "arr_sum_avg"),
    "array_min_max.c": ("min_max", "minmax", "array_minmax", "max_min"),
    "array_addresses.c": ("addresses", "arr_addr", "array_addr"),
    "array_reverse.c": ("reverse_array", "arr_reverse", "rev_array"),
    "array_insert.c": ("insert_array", "arr_insert", "insert"),
    "array_delete.c": ("delete_array", "arr_delete", "delete"),
    "linear_binary_search.c": ("binary_search", "linear_search", "search"),
    "bubble_sort.c": ("bubblesort", "sort_bubble", "bubble"),
    "matrix_add_transpose.c": ("matrix_add", "matrix_transpose", "add_transpose"),
    "matrix_diagonals.c": ("diagonals", "diagonal_sum", "matrix_diag"),
    "matrix_multiply.c": ("matrix_mult", "matmul", "multiply_matrix"),
    "string_basics.c": ("str_basics", "string_len_vowels", "string_palindrome"),
    "string_functions.c": ("str_funcs", "string_func", "str_functions"),
    "functions_prime_fact.c": ("prime_fact", "func_prime_fact", "isprime_fact"),
    "storage_classes.c": ("storage", "auto_static", "storage_class"),
    "recursion_basics.c": ("recursion", "recursive", "fact_fib_rec"),
    "pointer_demo.c": ("pointer", "pointers", "ptr_demo"),
    "swap_demo.c": ("swap", "swap_reference", "call_by_reference"),
    "getminmax_pointers.c": ("getminmax", "minmax_ptr", "minmax_pointers"),
    "pointer_array_sum.c": ("ptr_array_sum", "array_sum_ptr", "pointer_sum"),
    "pointer_step_sizes.c": ("pointer_step", "ptr_step", "step_sizes"),
    "my_strcpy.c": ("mystrcpy", "strcpy_ptr", "custom_strcpy"),
    "string_pointer_array.c": ("str_ptr_array", "char_ptr_array", "subjects_ptr"),
    "double_pointer.c": ("double_ptr", "ptr_to_ptr", "pptr"),
    "dynamic_array.c": ("malloc_calloc", "dyn_array", "malloc_demo"),
    "realloc_demo.c": ("realloc", "dyn_realloc"),
    "student_records.c": ("student_struct", "students", "nested_struct"),
    "struct_padding.c": ("padding", "sizeof_struct"),
    "struct_vs_union.c": ("union_demo", "struct_union"),
    "update_marks.c": ("updatemarks", "struct_pointer", "student_ptr"),
    "write_students.c": ("file_students", "students_io", "text_io"),
    "file_copy.c": ("copy_file", "fcopy", "backup_copy"),
    "binary_io.c": ("bin_io", "fwrite_fread", "binary_file"),
    "macros_ifdef.c": ("macros", "define_sqr", "ifdef_demo"),
    "cmdline_args.c": ("argc_argv", "cmdline", "command_line"),
}


def _prepend_path(bindir):
    if not bindir:
        return
    cur = os.environ.get("PATH", "")
    if bindir.lower() not in [p.strip().lower() for p in cur.split(os.pathsep) if p.strip()]:
        os.environ["PATH"] = bindir + os.pathsep + cur


def find_compiler(preferred=""):
    if preferred and os.path.isfile(preferred):
        _prepend_path(os.path.dirname(preferred))
        return preferred
    for c in ("gcc", "clang", "cc", "tcc", "x86_64-w64-mingw32-gcc"):
        p = shutil.which(c)
        if p:
            _prepend_path(os.path.dirname(p))
            return p
    if IS_WIN:
        up = os.environ.get("USERPROFILE", "")
        la = os.environ.get("LOCALAPPDATA", "")
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        candidates = [
            r"C:\msys64\mingw64\bin\gcc.exe",
            r"C:\msys64\ucrt64\bin\gcc.exe",
            r"C:\msys64\clang64\bin\clang.exe",
            r"C:\MinGW64\bin\gcc.exe",
            r"C:\mingw64\bin\gcc.exe",
            r"C:\MinGW\bin\gcc.exe",
            r"C:\TDM-GCC-64\bin\gcc.exe",
            os.path.join(pf, "LLVM", "bin", "clang.exe"),
            os.path.join(pf, "CodeBlocks", "MinGW", "bin", "gcc.exe"),
            os.path.join(pf86, "Dev-Cpp", "MinGW64", "bin", "gcc.exe"),
            os.path.join(up, "scoop", "apps", "gcc", "current", "bin", "gcc.exe"),
            os.path.join(up, "scoop", "apps", "mingw", "current", "bin", "gcc.exe"),
        ]
        wg = os.path.join(la, "Microsoft", "WinGet", "Packages")
        if os.path.isdir(wg):
            try:
                for d in os.listdir(wg):
                    if any(k in d.lower() for k in ("winlibs", "mingw", "llvm", "gcc")):
                        candidates.append(os.path.join(wg, d, "mingw64", "bin", "gcc.exe"))
            except OSError:
                pass
        for c in candidates:
            if os.path.isfile(c):
                _prepend_path(os.path.dirname(c))
                return c
    return None


def _norm_stem(name):
    stem = os.path.splitext(os.path.basename(name))[0].lower()
    stem = re.sub(r"^(?:day\s*\d+|d\d+|q\d+|p\d+|prog\d+|ex\d+|\d+)[_\-\s]*", "", stem)
    return re.sub(r"[_\-\s]+", "", stem)


_WS_CACHE = {"root": None, "ts": 0.0, "out": []}
_WS_LOCK = threading.Lock()
WS_SKIP = {".git", "node_modules", "__pycache__", ".vscode", ".idea", "build_cache", ".venv", "venv",
           "env", ".cache", ".gradle", ".mypy_cache", ".pytest_cache", ".next", ".pio"}


def list_workspace_c_files(root, max_age=2.0):
    """All .c files under root, newest first. Results are reused for `max_age` seconds so one
    verify run (or the background watcher) does not walk the disk once per quest."""
    if not root or not os.path.isdir(root):
        return []
    root = os.path.abspath(root)
    with _WS_LOCK:
        if (_WS_CACHE["root"] == root and max_age > 0
                and time.time() - _WS_CACHE["ts"] < max_age):
            return list(_WS_CACHE["out"])
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in WS_SKIP]
        if d[len(root):].count(os.sep) >= 6:
            dirs[:] = []
        for f in files:
            if f.lower().endswith(".c"):
                p = os.path.join(d, f)
                try:
                    out.append((p, os.path.getmtime(p)))
                except OSError:
                    pass
    out.sort(key=lambda x: x[1], reverse=True)
    with _WS_LOCK:
        _WS_CACHE.update(root=root, ts=time.time(), out=list(out))
    return out


def find_source(root, fname, c_files=None):
    """3-Tier lookup: 1) Exact match, 2) Normalized/Alias stem match."""
    if c_files is None:
        c_files = list_workspace_c_files(root)
    if not c_files:
        return None
    target_low = fname.lower()
    for p, m in c_files:
        if os.path.basename(p).lower() == target_low:
            return (p, m)
    want_norms = {_norm_stem(fname)}
    for al in QUEST_ALIASES.get(target_low, ()):
        want_norms.add(_norm_stem(al))
    for p, m in c_files:
        ns = _norm_stem(p)
        if ns in want_norms or any(w in ns for w in want_norms if len(w) >= 4):
            return (p, m)
    return None


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def _contains_seq(hay, need, first_endswith=False):
    n = len(need)
    if n == 0:
        return False
    for i in range(len(hay) - n + 1):
        w = hay[i:i + n]
        if w == need:
            return True
        if first_endswith and w[1:] == need[1:] and w[0].endswith(need[0]):
            return True
    return False


_PUNCT = ".,:;()[]{}!?'\"="


def clean_stdout(out):
    """Strip interactive printf prompts ('Enter a number: ') so prompt words don't break tests."""
    lines = []
    for ln in out.splitlines():
        cleaned = re.sub(
            r"(?i)^\s*(?:please\s+)?(?:enter|input|give|type|provide)\b[^:\n]{0,65}:\s*",
            "", ln
        )
        if re.match(r"(?i)^\s*(?:please\s+)?(?:enter|input|give|type|provide)\b[^=\d]*$", cleaned):
            continue
        lines.append(cleaned)
    res = "\n".join(lines).strip()
    return res if res else out.strip()


def check_output(out, expected, mode):
    if mode == "lines":
        hay = [" ".join(l.split()).lower() for l in out.splitlines() if l.strip()]
        need = [" ".join(l.split()).lower() for l in expected.splitlines()]
        return _contains_seq(hay, need, first_endswith=True)
    hay = [t.strip(_PUNCT) for t in out.lower().split()]
    need = [t.strip(_PUNCT) for t in expected.lower().split()]
    return _contains_seq(hay, [t for t in need if t])


def _alts(out, spec, mode):
    if mode == "lines":
        return check_output(out, spec, mode)
    return any(check_output(out, a.strip(), mode) for a in spec.split("|") if a.strip())


def check_yn(out, yes, noun, extra_yes="", extra_no=""):
    cleaned = clean_stdout(out).lower()
    n_low = noun.lower()
    extra_neg = "|composite" if n_low == "prime" else ""
    neg_pat = (
        rf"\b(?:not\s+(?:a\s+|an\s+|the\s+)?{re.escape(n_low)}|"
        rf"is\s+not\s+(?:a\s+|an\s+)?{re.escape(n_low)}|"
        rf"isn'?t\s+(?:a\s+|an\s+)?{re.escape(n_low)}|"
        rf"non[-\s]?{re.escape(n_low)}|no|false{extra_neg})\b"
    )
    has_neg = bool(re.search(neg_pat, cleaned))
    pos_pat = rf"\b(?:{re.escape(n_low)}|yes|true)\b"
    has_pos = bool(re.search(pos_pat, cleaned))
    tokens = [t.strip(_PUNCT) for t in cleaned.split() if t.strip(_PUNCT)]
    if yes:
        if has_neg:
            return False, f"YES / {noun}"
        if has_pos or (tokens and tokens[-1] == "1"):
            return True, ""
        return False, f"YES / {noun}"
    else:
        if has_neg or (tokens and tokens[-1] == "0"):
            return True, ""
        return False, f"NO / NOT {noun}"


def test_passes(out, expected, forbid, mode):
    if isinstance(expected, str) and expected.startswith("__YN__:"):
        _, flag, noun, ey, en = expected.split(":", 4)
        return check_yn(out, flag == "1", noun, ey, en)
    cleaned = clean_stdout(out)
    for e in (expected if isinstance(expected, list) else [expected]):
        if not (_alts(cleaned, e, mode) or _alts(out, e, mode)):
            if mode == "tokens" and e == "501" and _alts(cleaned, "0501", mode):
                continue
            return False, e.replace("\n", " / ")
    if forbid and _alts(cleaned, forbid, "tokens"):
        return False, f"output must not contain {forbid.replace('|', ' / ')}"
    return True, ""


def find_repo(root):
    cur = os.path.abspath(root)
    for _ in range(5):
        if os.path.isdir(os.path.join(cur, ".git")):
            return cur
        nxt = os.path.dirname(cur)
        if nxt == cur:
            break
        cur = nxt
    return None


def _bases(root):
    root = os.path.abspath(root)
    return [root, os.path.dirname(root)]


def chk_certs(root, today):
    for b in _bases(root):
        try:
            for name in os.listdir(b):
                p = os.path.join(b, name)
                if os.path.isdir(p) and name.lower() == "certificates":
                    pdfs = [f for f in os.listdir(p) if f.lower().endswith(".pdf")]
                    if len(pdfs) >= 2:
                        return True, f"{len(pdfs)} PDFs in {p}"
                    return False, f"Certificates folder has {len(pdfs)} PDF(s), need 2+"
        except OSError:
            pass
    return False, "no 'Certificates' folder found next to your workspace"


def chk_folders(root, today):
    want = ["01-Loops", "02-Arrays-Strings", "03-Pointers", "04-Structs-Files"]
    for b in _bases(root):
        if all(os.path.isdir(os.path.join(b, w)) for w in want):
            empty = []
            for w in want:
                has_c = any(f.lower().endswith(".c")
                            for _, _, fs in os.walk(os.path.join(b, w)) for f in fs)
                if not has_c:
                    empty.append(w)
            return (not empty), ("all four folders hold .c files" if not empty
                                 else "no .c files in: " + ", ".join(empty))
    return False, "folders 01-Loops, 02-Arrays-Strings, 03-Pointers, 04-Structs-Files missing"


def chk_github(root, today):
    repo = find_repo(root)
    if not repo:
        return False, "no git repository found (run: git init)"
    try:
        cfg = open(os.path.join(repo, ".git", "config"), encoding="utf-8",
                   errors="replace").read()
    except OSError:
        return False, "cannot read .git/config"
    if "github.com" not in cfg:
        return False, "no GitHub remote (git remote add origin ...)"
    if not os.path.isfile(os.path.join(repo, "README.md")):
        return False, "README.md missing in the repo root"
    return True, "GitHub remote + README.md present"


def chk_git_commit(root, today):
    repo = find_repo(root)
    git = shutil.which("git")
    if not repo or not git:
        return False, "no git repo / git not installed"
    try:
        out = subprocess.run([git, "-C", repo, "log", "-1", "--format=%cs"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=NO_WINDOW).stdout.strip()
    except Exception as e:
        return False, f"git error: {e}"
    if out == today.isoformat():
        return True, "committed today"
    return False, f"last commit was {out or 'never'}, commit today's code"


CHECKERS = {"certs": chk_certs, "folders": chk_folders, "github": chk_github,
            "git_commit": chk_git_commit}


def _test_single_c_file(path, q, cc, enforce_must=True):
    try:
        raw_src = open(path, encoding="utf-8", errors="replace").read()
        src = strip_comments(raw_src)
    except OSError as e:
        return False, f"cannot read file: {e}"
    if enforce_must and not q.get("tests"):
        for pat in q["must"]:
            if not re.search(pat, src, flags=re.I):
                return False, f"source is missing construct: {pat}"
    for pat in q["must_not"]:
        if re.search(pat, src, flags=re.I):
            return False, f"source must not use: {pat}"
    cache_dir = os.path.join(APP_DIR, "build_cache", f"{q['key'].replace(':', '_')}_{os.getpid()}")
    os.makedirs(cache_dir, exist_ok=True)
    exe = os.path.join(cache_dir, "prog.exe" if IS_WIN else "prog")
    try:
        try:
            cp = subprocess.run([cc, path, "-o", exe, "-lm"], capture_output=True, text=True,
                                errors="replace", timeout=30, creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            return False, "compiler timed out"
        except Exception as e:
            return False, f"compiler error: {e}"
        if cp.returncode != 0:
            err = " | ".join((cp.stderr or cp.stdout or "compile failed").strip().splitlines()[:2])
            return False, f"compile error: {err[:140]}"
        for name, content in q["setup"].items():
            with open(os.path.join(cache_dir, name), "w", encoding="utf-8") as f:
                f.write(content)

        def run(stdin):
            return subprocess.run([exe], input=stdin, capture_output=True, text=True,
                                  errors="replace", timeout=3, cwd=cache_dir,
                                  creationflags=NO_WINDOW)
        if q["tests"]:
            for t in q["tests"]:
                stdin, expected = t[0], t[1]
                forbid = t[2] if len(t) > 2 else None
                try:
                    rp = run(stdin)
                except subprocess.TimeoutExpired:
                    return False, f"timeout on input {stdin.strip()!r} (infinite loop?)"
                ok, why = test_passes(rp.stdout, expected, forbid, q["mode"])
                if not ok:
                    got = " ".join(clean_stdout(rp.stdout).split())[:50]
                    return False, f"input {stdin.strip()!r}: expected {why!r}, got {got!r}"
            return True, f"verified ({os.path.basename(path)})"
        try:
            rp = run(q["stdin"])
        except subprocess.TimeoutExpired:
            return False, "timeout (infinite loop?)"
        if rp.returncode != 0:
            return False, f"program exited with code {rp.returncode}"
        if not rp.stdout.strip() and not q["expect_files"]:
            return False, "program printed nothing"
        for name, content in q["expect_files"].items():
            p = os.path.join(cache_dir, name)
            if not os.path.isfile(p):
                return False, f"program did not create {name}"
            if content is not None and open(p, errors="replace").read().split() != content.split():
                return False, f"{name} content mismatch"
        return True, f"verified ({os.path.basename(path)})"
    finally:
        shutil.rmtree(cache_dir, ignore_errors=True)


def verify_quest(q, root, cc, today, c_files=None):
    """Returns (ok, message). Uses 3-Tier file matching (Exact -> Alias -> Behavior scan)."""
    try:
        if q["kind"] == "check":
            return CHECKERS[q["checker"]](root, today)
        if not cc:
            return False, "No C compiler (gcc/clang) found. Install MinGW64 or click Locate GCC."
        if c_files is None:
            c_files = list_workspace_c_files(root)
        if not c_files:
            return False, f"No .c files found in {root}"
        found = find_source(root, q["file"], c_files)
        if found:
            ok, msg = _test_single_c_file(found[0], q, cc, enforce_must=True)
            if ok:
                return True, msg
            first_err = f"{os.path.basename(found[0])}: {msg}"
        else:
            first_err = f"{q['file']} not found (checked {len(c_files)} .c files)"
        if q.get("tests"):
            for p, _ in c_files[:25]:
                if found and p == found[0]:
                    continue
                ok, msg = _test_single_c_file(p, q, cc, enforce_must=False)
                if ok:
                    return True, f"matched {os.path.basename(p)} -> passed all tests"
        return False, first_err
    except Exception as e:
        return False, f"verify error: {e}"


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


def _list_processes_native():
    """Process names through the Toolhelp snapshot API: no child process, ~1 ms."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32FirstW.restype = wintypes.BOOL
    k32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)          # TH32CS_SNAPPROCESS
    if not snap or snap == ctypes.c_void_p(-1).value:
        return None
    names = set()
    try:
        pe = PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(pe)
        ok = k32.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            names.add(pe.szExeFile.lower())
            ok = k32.Process32NextW(snap, ctypes.byref(pe))
    finally:
        k32.CloseHandle(snap)
    return names


def list_processes():
    if not IS_WIN:
        return set()
    try:
        names = _list_processes_native()
        if names:
            return names
    except Exception:
        pass
    try:                                                  # fallback: tasklist
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                             text=True, errors="replace", timeout=8,
                             creationflags=NO_WINDOW).stdout
    except Exception:
        return set()
    return {ln.split('","')[0].strip('"').lower() for ln in out.splitlines() if ln}


def scan_processes(watch):
    """Returns (running distraction processes, is Lively running)."""
    names = list_processes()
    return sorted(names & {w.lower() for w in watch}), any("lively" in n for n in names)


# ==================================================================================
# wallpaper loading + analysis
# ==================================================================================
def screen_size():
    if IS_WIN:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
        return (ctypes.windll.user32.GetSystemMetrics(0),
                ctypes.windll.user32.GetSystemMetrics(1))
    return (1920, 1080)


def set_wallpaper(path):
    """Set the Windows wallpaper. An empty path clears it (plain desktop colour)."""
    if IS_WIN:
        ctypes.windll.user32.SystemParametersInfoW(20, 0, os.path.abspath(path) if path else "", 3)


_SYSW = {"ts": 0.0, "v": ""}


def get_system_wallpaper(max_age=30.0):
    """Path of the wallpaper Windows is showing right now ('' if none / not Windows)."""
    if not IS_WIN:
        return ""
    if time.time() - _SYSW["ts"] < max_age:
        return _SYSW["v"]
    v = ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        ctypes.windll.user32.SystemParametersInfoW(0x73, len(buf), buf, 0)   # SPI_GETDESKWALLPAPER
        v = buf.value
    except Exception:
        pass
    _SYSW.update(ts=time.time(), v=v)
    return v


def in_app_dir(path):
    try:
        return os.path.abspath(path).lower().startswith(os.path.abspath(APP_DIR).lower())
    except Exception:
        return False


def default_background(size):
    mask = Image.linear_gradient("L").resize(size)
    return ImageOps.colorize(mask, black=(8, 10, 26), white=(64, 18, 86))


_bg_cache = {"key": None, "img": None, "note": ""}


def load_background(path, now, size):
    if not path or not os.path.isfile(path):
        return default_background(size), "built-in background"
    ext = os.path.splitext(path)[1].lower()
    frac = (now.hour * 60 + now.minute) / 1440.0
    step = int(frac * 48)
    key = (path, os.path.getmtime(path), step if ext in VIDEO_EXT | {".gif"} else 0)
    if _bg_cache["key"] == key:
        return _bg_cache["img"], _bg_cache["note"]
    note = os.path.basename(path)
    try:
        if ext in VIDEO_EXT:
            try:
                import cv2
            except ImportError:
                return default_background(size), "video needs: pip install opencv-python"
            cap = cv2.VideoCapture(path)
            n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
            cap.set(cv2.CAP_PROP_POS_FRAMES, int((step / 48.0) * max(n - 1, 1)))
            ok, frame = cap.read()
            cap.release()
            if not ok:
                return default_background(size), "could not read video frame"
            img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        elif ext == ".gif":
            im = Image.open(path)
            n = getattr(im, "n_frames", 1)
            im.seek(int((step / 48.0) * max(n - 1, 0)))
            img = im.convert("RGB")
        else:
            img = Image.open(path).convert("RGB")
    except Exception as e:
        return default_background(size), f"wallpaper error: {e}"
    _bg_cache.update(key=key, img=img, note=note)
    return img, note


def analyze_bg(img):
    small = img.convert("RGB").resize((96, 54))
    raw = small.tobytes()
    px = list(zip(raw[0::3], raw[1::3], raw[2::3]))
    lum = sum(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in px) / (len(px) * 255)
    bins = [0.0] * 12
    sums = [[0.0, 0.0, 0.0] for _ in range(12)]
    for r, g, b in px:
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        w = s * (1 - abs(2 * l - 1))
        if w < 0.12:
            continue
        i = int(h * 12) % 12
        bins[i] += w
        sums[i][0] += r * w
        sums[i][1] += g * w
        sums[i][2] += b * w
    if max(bins) <= 0:
        accent, hue = (0, 200, 255), 0.5
    else:
        i = bins.index(max(bins))
        accent = tuple(int(sums[i][k] / bins[i]) for k in range(3))
        hue = colorsys.rgb_to_hls(*[c / 255 for c in accent])[0]
    warm = hue < 0.17 or hue > 0.92
    acc_sat = colorsys.rgb_to_hsv(*[c / 255 for c in accent])[1]
    muted = max(bins) <= 0 or acc_sat < 0.38
    mood = "ink" if muted else MOODS[(lum < 0.42, warm)]
    return {"lum": lum, "accent": accent, "hue": hue, "muted": muted, "mood": mood}


def fit_accent(rgb, dark_panel):
    h, l, s = colorsys.rgb_to_hls(*[c / 255 for c in rgb])
    s = max(s, 0.65)
    l = max(l, 0.64) if dark_panel else min(l, 0.34)
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return (int(r * 255), int(g * 255), int(b * 255))


def hex_color(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


def pick_message(level, info, cfg, bg_path, now, empty=False):
    mood = info["mood"]
    if level == "CLEARED":
        pool = CLEARED_MSG[mood]
    else:
        custom = [m.strip() for m in cfg.get("custom_messages", {}).get(bg_path or "", [])
                  if m.strip()]
        pool = custom or PENALTY_MSG[mood]
    rng = random.Random(f"{now:%Y-%m-%d-%H}-{level}")
    return ESCALATION.get(level, "") + rng.choice(pool)


# ==================================================================================
# Lively Wallpaper helpers + live overlay window
# ==================================================================================
def find_lively(preferred=""):
    """Locate Lively's command-capable executable (Lively.exe / livelycu.exe)."""
    if preferred and os.path.isfile(preferred):
        return preferred
    for name in ("livelycu", "Lively", "livelywpf"):
        w = shutil.which(name)
        if w:
            return w
    pf = os.environ.get("ProgramFiles", "")
    la = os.environ.get("LOCALAPPDATA", "")
    for p in (os.path.join(pf, "Lively Wallpaper", "Lively.exe"),
              os.path.join(la, "Programs", "Lively Wallpaper", "Lively.exe"),
              os.path.join(la, "Microsoft", "WindowsApps", "Lively.exe"),
              os.path.join(pf, "Lively Wallpaper", "livelywpf.exe")):
        if os.path.isfile(p):
            return p
    if IS_WIN:
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-Process | Where-Object {$_.ProcessName -like 'Lively*'} | "
                 "ForEach-Object { $_.Path }"],
                capture_output=True, text=True, errors="replace", timeout=15,
                creationflags=NO_WINDOW).stdout
        except Exception:
            out = ""
        for path in out.splitlines():
            d = os.path.dirname(path.strip())
            for _ in range(3):
                for exe in ("Lively.exe", "livelywpf.exe"):
                    c = os.path.join(d, exe)
                    if d and os.path.isfile(c):
                        return c
                d = os.path.dirname(d)
    return None


def lively_set(exe, path):
    """Ask Lively to import + show a video/GIF/HTML file as the wallpaper."""
    try:
        r = subprocess.run([exe, "setwp", "--file", path], capture_output=True, text=True,
                           errors="replace", timeout=30, creationflags=NO_WINDOW)
    except Exception as e:
        return False, str(e)
    return r.returncode == 0, (r.stderr or r.stdout or "").strip()[:200]


def lively_screenshot(exe, out_path, timeout=14):
    """Screenshot of whatever Lively is currently showing (adapts the HUD to it)."""
    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        if os.path.exists(out_path):
            os.remove(out_path)
        subprocess.run([exe, "screenshot", "--file", out_path], capture_output=True,
                       timeout=timeout, creationflags=NO_WINDOW)
    except Exception:
        return None
    end = time.time() + timeout
    while time.time() < end:
        if os.path.isfile(out_path) and os.path.getsize(out_path) > 1000:
            try:
                img = Image.open(out_path).convert("RGB")
                img.load()
                return img
            except Exception:
                pass
        time.sleep(0.25)
    return None


def have_cv2():
    import importlib.util
    return importlib.util.find_spec("cv2") is not None


def install_opencv():
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "opencv-python"],
                           capture_output=True, text=True, errors="replace", timeout=900,
                           creationflags=NO_WINDOW)
        return r.returncode == 0, (r.stderr or r.stdout or "").strip()[-200:]
    except Exception as e:
        return False, str(e)


def premultiplied_bgra(img):
    """Fast C-level RGBA -> premultiplied BGRA bytes for UpdateLayeredWindow (2.5x faster)."""
    return img.convert("RGBA").convert("RGBa").tobytes("raw", "BGRa")


LRESULT = ctypes.c_ssize_t
WNDPROC = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HANDLE),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HANDLE),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 1)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


user32 = gdi32 = kernel32 = None
WS_POPUP = 0x80000000
WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x00080000, 0x00000020
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x00000080, 0x08000000
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
WM_CLOSE, WM_DESTROY = 0x0010, 0x0002
HWND_BOTTOM, HWND_TOPMOST = 1, -1


def _init_win32():
    global user32, gdi32, kernel32
    if user32 is not None:
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    W = wintypes
    user32.DefWindowProcW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = W.ATOM
    user32.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, W.HWND,
                                       W.HMENU, W.HINSTANCE, W.LPVOID]
    user32.CreateWindowExW.restype = W.HWND
    user32.ShowWindow.argtypes = [W.HWND, ctypes.c_int]
    user32.SetWindowPos.argtypes = [W.HWND, W.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, W.UINT]
    user32.GetMessageW.argtypes = [ctypes.POINTER(W.MSG), W.HWND, W.UINT, W.UINT]
    user32.GetMessageW.restype = ctypes.c_int
    user32.TranslateMessage.argtypes = [ctypes.POINTER(W.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(W.MSG)]
    user32.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.GetDC.argtypes = [W.HWND]
    user32.GetDC.restype = W.HDC
    user32.ReleaseDC.argtypes = [W.HWND, W.HDC]
    user32.UpdateLayeredWindow.argtypes = [W.HWND, W.HDC, ctypes.POINTER(W.POINT),
                                           ctypes.POINTER(W.SIZE), W.HDC,
                                           ctypes.POINTER(W.POINT), W.COLORREF,
                                           ctypes.POINTER(BLENDFUNCTION), W.DWORD]
    user32.UpdateLayeredWindow.restype = W.BOOL
    gdi32.CreateCompatibleDC.argtypes = [W.HDC]
    gdi32.CreateCompatibleDC.restype = W.HDC
    gdi32.CreateDIBSection.argtypes = [W.HDC, ctypes.POINTER(BITMAPINFO), W.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), W.HANDLE, W.DWORD]
    gdi32.CreateDIBSection.restype = W.HBITMAP
    gdi32.SelectObject.argtypes = [W.HDC, W.HGDIOBJ]
    gdi32.SelectObject.restype = W.HGDIOBJ
    gdi32.DeleteObject.argtypes = [W.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [W.HDC]
    kernel32.GetModuleHandleW.argtypes = [W.LPCWSTR]
    kernel32.GetModuleHandleW.restype = W.HMODULE


HTCLIENT, HTCAPTION = 1, 2
WM_NCHITTEST, WM_LBUTTONUP = 0x0084, 0x0202
WM_EXITSIZEMOVE, WM_MOUSEWHEEL = 0x0232, 0x020A
GWL_EXSTYLE = -20
SWP_NOZORDER, SWP_FRAMECHANGED = 0x4, 0x20
HWND_NOTOPMOST = -2
VK_MEDIA_NEXT, VK_MEDIA_PREV, VK_MEDIA_PLAY = 0xB0, 0xB1, 0xB3
_WINDOWS = {}
_class_lock = threading.Lock()
_class_state = {"ready": False}
_set_long = [None]


def _init_win32_extra():
    """Extra Win32 prototypes needed by the widget windows (called after _init_win32)."""
    W = wintypes
    user32.GetWindowRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
    user32.GetWindowRect.restype = W.BOOL
    user32.keybd_event.argtypes = [W.BYTE, W.BYTE, W.DWORD, ctypes.c_size_t]
    fn = getattr(user32, "SetWindowLongPtrW", None)
    if fn is not None:
        fn.argtypes = [W.HWND, ctypes.c_int, ctypes.c_ssize_t]
        fn.restype = ctypes.c_ssize_t
    else:
        fn = user32.SetWindowLongW
        fn.argtypes = [W.HWND, ctypes.c_int, ctypes.c_long]
        fn.restype = ctypes.c_long
    _set_long[0] = fn


def _global_proc(hwnd, msg, wp, lp):
    w = _WINDOWS.get(hwnd)
    if w is not None:
        try:
            r = w.handle(hwnd, msg, wp, lp)
        except Exception:
            r = None
        if r is not None:
            return r
    if msg == WM_DESTROY:
        _WINDOWS.pop(hwnd, None)
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wp, lp)


_wndproc_ref = WNDPROC(_global_proc)


def _ensure_class(hinst):
    with _class_lock:
        if _class_state["ready"]:
            return
        wc = WNDCLASSW()
        wc.lpfnWndProc = _wndproc_ref
        wc.hInstance = hinst
        wc.lpszClassName = "ShadowSystemHudWidget"
        user32.RegisterClassW(ctypes.byref(wc))
        _class_state["ready"] = True


class WidgetWindow:
    """One borderless per-pixel-alpha window per widget, on its own message-pump thread.
    Locked mode: non-interactive widgets are click-through, interactive ones take clicks.
    Edit mode: every widget can be dragged by the mouse; the wheel resizes."""

    def __init__(self, wid, layer, events):
        _init_win32()
        _init_win32_extra()
        self.wid, self.layer, self.events = wid, layer, events
        self.hwnd = None
        self.pos = None
        self.edit = False
        self.clickable = False
        self.dragging = False
        self._mode_applied = None
        self._err = None
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(6) or self._err:
            raise RuntimeError(self._err or "widget window did not start")

    # ---- window thread ---------------------------------------------------------
    def handle(self, hwnd, msg, wp, lp):
        if msg == WM_NCHITTEST and self.edit:
            return HTCAPTION
        if msg == WM_LBUTTONUP and not self.edit:
            x = ctypes.c_short(lp & 0xFFFF).value
            y = ctypes.c_short((lp >> 16) & 0xFFFF).value
            self.events.put(("wclick", self.wid, x, y))
            return 0
        if msg == 0x0231:                      # WM_ENTERSIZEMOVE: stop repositioning while dragged
            self.dragging = True
            return None
        if msg == WM_EXITSIZEMOVE:
            self.dragging = False
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            self.pos = (r.left, r.top)
            self.events.put(("wmove", self.wid, r.left, r.top))
            return 0
        if msg == WM_MOUSEWHEEL and self.edit:
            delta = ctypes.c_short((wp >> 16) & 0xFFFF).value
            self.events.put(("wheel", self.wid, delta))
            return 0
        return None

    def _run(self):
        try:
            hinst = kernel32.GetModuleHandleW(None)
            _ensure_class(hinst)
            ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT
            hwnd = user32.CreateWindowExW(ex, "ShadowSystemHudWidget", "Shadow System " + self.wid,
                                          WS_POPUP, 0, 0, 1, 1, None, None, hinst, None)
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            _WINDOWS[hwnd] = self
            self.hwnd = hwnd
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
            self.apply_layer()
        except Exception as e:
            self._err = str(e)
            self._ready.set()
            return
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    # ---- called from any thread ------------------------------------------------
    def apply_layer(self):
        if not self.hwnd:
            return
        z = {"desktop": HWND_BOTTOM, "top": HWND_TOPMOST}.get(self.layer, HWND_NOTOPMOST)
        user32.SetWindowPos(self.hwnd, z, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def set_mode(self, edit, clickable):
        """edit: draggable. clickable: receives clicks (music/focus). Otherwise click-through."""
        key = (bool(edit), bool(clickable))
        if not self.hwnd or key == self._mode_applied:
            return
        self.edit, self.clickable = key
        ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        if not (self.edit or self.clickable):
            ex |= WS_EX_TRANSPARENT
        _set_long[0](self.hwnd, GWL_EXSTYLE, ex)
        user32.SetWindowPos(self.hwnd, None, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE |
                            SWP_FRAMECHANGED)
        self._mode_applied = key

    def set_visible(self, visible):
        if self.hwnd:
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE if visible else SW_HIDE)

    def update(self, img, x, y):
        if not self.hwnd:
            return
        w, h = img.size
        self.update_raw(premultiplied_bgra(img), w, h, x, y)

    def update_raw(self, data, w, h, x, y):
        """Blit ready-made premultiplied BGRA bytes (animated custom widgets use this)."""
        if not self.hwnd:
            return
        with self._lock:
            hdc_screen = user32.GetDC(None)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = w
            bmi.bmiHeader.biHeight = -h
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = 0
            bits = ctypes.c_void_p()
            hbm = gdi32.CreateDIBSection(hdc_screen, ctypes.byref(bmi), 0,
                                         ctypes.byref(bits), None, 0)
            try:
                if not hbm or not bits.value:
                    raise RuntimeError("CreateDIBSection failed")
                ctypes.memmove(bits.value, data, len(data))
                old = gdi32.SelectObject(hdc_mem, hbm)
                move = self.pos is None or (self.pos != (int(x), int(y)) and not self.dragging)
                pt_dst = wintypes.POINT(int(x), int(y))
                size = wintypes.SIZE(w, h)
                pt_src = wintypes.POINT(0, 0)
                blend = BLENDFUNCTION(0, 0, 255, 1)
                ok = user32.UpdateLayeredWindow(
                    self.hwnd, hdc_screen, ctypes.byref(pt_dst) if move else None,
                    ctypes.byref(size), hdc_mem, ctypes.byref(pt_src), 0,
                    ctypes.byref(blend), 2)
                gdi32.SelectObject(hdc_mem, old)
                if not ok:
                    raise ctypes.WinError(ctypes.get_last_error())
                if move:
                    self.pos = (int(x), int(y))
            finally:
                if hbm:
                    gdi32.DeleteObject(hbm)
                gdi32.DeleteDC(hdc_mem)
                user32.ReleaseDC(None, hdc_screen)
        if self.layer != "normal":
            self.apply_layer()

    def close(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            self.hwnd = None


def send_media_key(vk):
    """Global media key press: works with Spotify, browsers, any SMTC player."""
    if not IS_WIN:
        return
    _init_win32()
    _init_win32_extra()
    user32.keybd_event(vk, 0, 1, 0)       # KEYEVENTF_EXTENDEDKEY
    user32.keybd_event(vk, 0, 3, 0)       # ... | KEYEVENTF_KEYUP


MEDIA_PS = r'''
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) { $m = $asTaskGeneric.MakeGenericMethod($type); $t = $m.Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
[void][Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]
[void][Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties, Windows.Media.Control, ContentType = WindowsRuntime]
[void][Windows.Storage.Streams.IRandomAccessStreamWithContentType, Windows.Storage.Streams, ContentType = WindowsRuntime]
$mgr = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
$art = '__ART__'
$lastKey = ''
while ($true) {
  try {
    $s = $mgr.GetCurrentSession()
    if ($s) {
      $p = Await ($s.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
      $pb = $s.GetPlaybackInfo()
      $tl = $s.GetTimelineProperties()
      $key = "$($p.Title)|$($p.Artist)"
      if ($key -ne $lastKey) {
        $lastKey = $key
        try {
          if (Test-Path $art) { Remove-Item $art -Force }
          if ($p.Thumbnail) {
            $st = Await ($p.Thumbnail.OpenReadAsync()) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
            $net = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($st)
            $fs = [System.IO.File]::Create($art)
            $net.CopyTo($fs); $fs.Close(); $net.Close()
          }
        } catch {}
      }
      $o = [ordered]@{ title = [string]$p.Title; artist = [string]$p.Artist; album = [string]$p.AlbumTitle; status = $pb.PlaybackStatus.ToString(); pos = [double]$tl.Position.TotalSeconds; dur = [double]$tl.EndTime.TotalSeconds; app = [string]$s.SourceAppUserModelId; art = [bool](Test-Path $art); key = $key }
      ($o | ConvertTo-Json -Compress)
    } else { '{"none":true}' }
  } catch { '{"none":true}' }
  [Console]::Out.Flush()
  Start-Sleep -Milliseconds 1000
}
'''


class MediaMonitor:
    """Reads Windows' media session (Spotify, browsers, any player) through a background
    PowerShell process. If that fails the music widget still works as a remote control."""

    def __init__(self, art_path):
        self.art_path = art_path
        self.proc = None
        self.info = {}
        self.stamp = 0.0
        self.seen = False

    def start(self):
        if not IS_WIN or self.proc is not None:
            return
        script = MEDIA_PS.replace("__ART__", self.art_path.replace("'", "''"))
        enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        try:
            self.proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-EncodedCommand", enc],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        except Exception:
            self.proc = None
            return
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    self.info = json.loads(line)
                    self.stamp = time.time()
                    self.seen = True
                except ValueError:
                    pass
        except Exception:
            pass

    def snapshot(self):
        d = self.info
        if not d or d.get("none") or time.time() - self.stamp > 6:
            return {"has": False, "reading": self.proc is not None, "seen": self.seen}
        pos = float(d.get("pos") or 0)
        if d.get("status") == "Playing":
            pos += time.time() - self.stamp
        dur = float(d.get("dur") or 0)
        if dur > 0:
            pos = min(pos, dur)
        art = self.art_path if d.get("art") and os.path.isfile(self.art_path) else None
        return {"has": True, "title": d.get("title", ""), "artist": d.get("artist", ""),
                "album": d.get("album", ""), "status": d.get("status", ""), "pos": pos,
                "dur": dur, "app": d.get("app", ""), "art": art, "key": d.get("key", "")}

    def stop(self):
        if self.proc is not None:
            try:
                self.proc.terminate()
            except Exception:
                pass
            self.proc = None


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


def _make_guid(d1, d2, d3, *d4):
    return _GUID(d1, d2, d3, (ctypes.c_ubyte * 8)(*d4))


CLSID_MMDeviceEnumerator = _make_guid(0xBCDE0395, 0xE52F, 0x467C, 0x8E, 0x3D, 0xC4, 0x57, 0x92, 0x91, 0x69, 0x2E)
IID_IMMDeviceEnumerator = _make_guid(0xA95664D2, 0x9614, 0x4F35, 0xA7, 0x46, 0xDE, 0x8D, 0xB6, 0x36, 0x17, 0xE6)
IID_IAudioMeterInformation = _make_guid(0xC02216F6, 0x8C67, 0x4B5B, 0x9D, 0x00, 0xD0, 0x08, 0xE7, 0x3E, 0x00, 0x64)
_COM_CALL = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)


class AudioMonitor:
    """Real-time Windows Core Audio (WASAPI IAudioMeterInformation) loopback peak & stereo
    spectrum analyzer using zero-dependency ctypes COM. Captures any sound/music playing on PC."""

    def __init__(self):
        self.running = False
        self.lock = threading.Lock()
        self.hist = [0.0] * 64
        self.bars = [0.04] * 64
        self.peak = 0.0
        self.raw_peak = 0.0
        self.rolling_max = 0.14
        self.left = 0.0
        self.right = 0.0
        self.bass = 0.0
        self.mid = 0.0
        self.high = 0.0
        self.fast_ema = 0.0
        self.slow_ema = 0.0
        self.prev_p = 0.0
        self.phase = 0.0
        self.last_sound_ts = 0.0
        self.test_until = 0.0
        self.backend = "standby"

    def start(self):
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.running = False

    def trigger_test(self, seconds=5.0):
        self.test_until = time.time() + seconds
        self.start()

    def _release_ptr(self, ptr):
        if ptr and ptr.value:
            try:
                vt = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
                rel = _COM_CALL(ctypes.c_ulong, ctypes.c_void_p)(vt[2])
                rel(ptr)
            except Exception:
                pass
            ptr.value = None

    def _acquire_meter(self, ole32):
        p_enum = ctypes.c_void_p()
        p_dev = ctypes.c_void_p()
        p_meter = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(CLSID_MMDeviceEnumerator), None, 23,
            ctypes.byref(IID_IMMDeviceEnumerator), ctypes.byref(p_enum)
        )
        if hr != 0 or not p_enum.value:
            return None, None, None
        vt_e = ctypes.cast(p_enum, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        get_ep = _COM_CALL(ctypes.c_long, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
                           ctypes.POINTER(ctypes.c_void_p))(vt_e[4])
        # eRender = 0, eMultimedia = 1 (fallback eConsole = 0)
        if get_ep(p_enum, 0, 1, ctypes.byref(p_dev)) != 0 or not p_dev.value:
            if get_ep(p_enum, 0, 0, ctypes.byref(p_dev)) != 0 or not p_dev.value:
                self._release_ptr(p_enum)
                return None, None, None
        vt_d = ctypes.cast(p_dev, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        act = _COM_CALL(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_GUID), wintypes.DWORD,
                        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(vt_d[3])
        if act(p_dev, ctypes.byref(IID_IAudioMeterInformation), 23, None, ctypes.byref(p_meter)) != 0 or not p_meter.value:
            self._release_ptr(p_dev)
            self._release_ptr(p_enum)
            return None, None, None
        return p_enum, p_dev, p_meter

    def _step_signal(self, raw_p, raw_l, raw_r, dt_s):
        raw_p = max(0.0, min(1.0, float(raw_p)))
        raw_l = max(0.0, min(1.0, float(raw_l)))
        raw_r = max(0.0, min(1.0, float(raw_r)))
        self.raw_peak = raw_p
        if raw_p > 0.003:
            self.last_sound_ts = time.time()
            self.rolling_max = max(0.06, max(raw_p, self.rolling_max * 0.985))
            gain = min(4.5, 0.85 / self.rolling_max)
        else:
            gain = 1.0
        p = min(1.0, raw_p * gain)
        l = min(1.0, raw_l * gain)
        r = min(1.0, raw_r * gain)
        self.fast_ema = 0.55 * p + 0.45 * self.fast_ema
        self.slow_ema = 0.15 * p + 0.85 * self.slow_ema
        transient = max(0.0, p - self.slow_ema)
        bass = min(1.0, self.slow_ema * 1.15 + transient * 1.7)
        mid = min(1.0, abs(self.fast_ema - self.slow_ema) * 2.7 + p * 0.58)
        high = min(1.0, abs(p - self.prev_p) * 3.1 + abs(l - r) * 1.5 + p * 0.25)
        self.prev_p = p
        self.phase = (self.phase + dt_s * (4.5 + 15.0 * bass)) % (200 * math.pi)
        with self.lock:
            self.peak, self.left, self.right = p, l, r
            self.bass, self.mid, self.high = bass, mid, high
            self.hist.pop(0)
            self.hist.append(p)
            bars = []
            for i in range(64):
                u = i / 63.0
                h_val = self.hist[i]
                if u < 0.33:
                    band = bass * (0.72 + 0.28 * math.sin(self.phase + i * 0.45))
                elif u < 0.66:
                    band = mid * (0.68 + 0.32 * math.sin(self.phase * 1.45 - i * 0.58))
                else:
                    band = high * (0.64 + 0.36 * math.cos(self.phase * 2.15 + i * 0.78))
                v = min(1.0, max(0.04, 0.54 * band + 0.46 * h_val))
                bars.append(round(v, 3))
            self.bars = bars

    def _loop(self):
        ole32 = None
        p_enum = p_dev = p_meter = None
        get_peak = get_ch_count = get_ch_peaks = None
        last_rebind = 0.0
        if IS_WIN:
            try:
                ole32 = ctypes.windll.ole32
                ole32.CoInitialize(None)
                ole32.CoCreateInstance.argtypes = [
                    ctypes.POINTER(_GUID), ctypes.c_void_p, wintypes.DWORD,
                    ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)
                ]
                ole32.CoCreateInstance.restype = ctypes.c_long
            except Exception:
                ole32 = None
        while self.running:
            now = time.time()
            p = l = r = 0.0
            if now < self.test_until:
                beat = (math.sin(now * 6.5) ** 4) * 0.78 + 0.14 * abs(math.sin(now * 17.0))
                p, l, r = beat, beat * (0.85 + 0.15 * math.sin(now * 3.0)), beat * (0.85 + 0.15 * math.cos(now * 3.0))
                self.backend = "TEST PULSE"
            elif ole32 is not None:
                if p_meter is None or (now - last_rebind > 4.0):
                    last_rebind = now
                    self._release_ptr(p_meter)
                    self._release_ptr(p_dev)
                    self._release_ptr(p_enum)
                    p_enum, p_dev, p_meter = self._acquire_meter(ole32)
                    if p_meter and p_meter.value:
                        vt_m = ctypes.cast(p_meter, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
                        get_peak = _COM_CALL(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_float))(vt_m[3])
                        get_ch_count = _COM_CALL(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint))(vt_m[4])
                        get_ch_peaks = _COM_CALL(ctypes.c_long, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_float))(vt_m[5])
                        self.backend = "WASAPI LIVE"
                    else:
                        get_peak = None
                if get_peak is not None:
                    try:
                        pf = ctypes.c_float(0.0)
                        if get_peak(p_meter, ctypes.byref(pf)) == 0:
                            p = float(pf.value)
                            l = r = p
                            ch = ctypes.c_uint(0)
                            if get_ch_count(p_meter, ctypes.byref(ch)) == 0 and 1 <= ch.value <= 8:
                                arr = (ctypes.c_float * ch.value)()
                                if get_ch_peaks(p_meter, ch.value, arr) == 0:
                                    l = float(arr[0])
                                    r = float(arr[1]) if ch.value >= 2 else l
                        else:
                            p_meter = None
                    except Exception:
                        p_meter = None
            self._step_signal(p, l, r, 0.04)
            time.sleep(0.04)
        self._release_ptr(p_meter)
        self._release_ptr(p_dev)
        self._release_ptr(p_enum)
        if ole32 is not None:
            try:
                ole32.CoUninitialize()
            except Exception:
                pass

    def is_active(self):
        return (time.time() - self.last_sound_ts) < 1.2 or time.time() < self.test_until

    def snapshot(self):
        with self.lock:
            active = (time.time() - self.last_sound_ts) < 1.2 or time.time() < self.test_until
            db = 20.0 * math.log10(max(self.raw_peak or self.peak, 1e-4)) if active and self.peak > 0.001 else -60.0
            return {
                "active": active,
                "peak": round(self.peak, 3),
                "left": round(self.left, 3),
                "right": round(self.right, 3),
                "bass": round(self.bass, 3),
                "mid": round(self.mid, 3),
                "high": round(self.high, 3),
                "db": round(db, 1),
                "hist": list(self.hist),
                "bars": list(self.bars),
                "phase": round(self.phase, 2),
                "backend": self.backend,
            }


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


def read_sys_stats(prev):
    """CPU / RAM / disk / battery without extra packages. Returns (stats, new prev)."""
    out = {"cpu": 0.0, "ram": 0.0, "disk": 0.0, "bat": None}
    new_prev = prev
    if IS_WIN:
        try:
            k = ctypes.windll.kernel32
            ms = MEMORYSTATUSEX()
            ms.dwLength = ctypes.sizeof(ms)
            k.GlobalMemoryStatusEx(ctypes.byref(ms))
            out["ram"] = float(ms.dwMemoryLoad)
            idle, kern, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
            k.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))

            def ft(f):
                return (f.dwHighDateTime << 32) | f.dwLowDateTime
            i, kk, u = ft(idle), ft(kern), ft(user)
            if prev:
                total = (kk - prev[1]) + (u - prev[2])
                if total > 0:
                    out["cpu"] = max(0.0, min(100.0, 100.0 * (1 - (i - prev[0]) / float(total))))
            new_prev = (i, kk, u)
            sp = SYSTEM_POWER_STATUS()
            if k.GetSystemPowerStatus(ctypes.byref(sp)) and sp.BatteryLifePercent <= 100:
                out["bat"] = {"pct": int(sp.BatteryLifePercent),
                              "charging": sp.ACLineStatus == 1}
        except Exception:
            pass
    try:
        du = shutil.disk_usage(os.path.abspath(os.sep))
        out["disk"] = 100.0 * du.used / du.total
    except Exception:
        pass
    return out, new_prev


def fallback_analysis(size):
    orig = default_background(size)
    return {"info": analyze_bg(orig),
            "gray": orig.convert("L").resize((max(1, size[0] // 4), max(1, size[1] // 4))),
            "ts": 0, "wp": None, "note": "built-in background", "exe": ""}


# ==================================================================================
# rendering
# ==================================================================================
FONT_SETS = {
    "sans": ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"],
    "sansl": ["segoeuil.ttf", "segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"],
    "sansb": ["seguisb.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"],
    "serif": ["georgia.ttf", "times.ttf", "DejaVuSerif.ttf"],
    "serifb": ["georgiab.ttf", "timesbd.ttf", "DejaVuSerif-Bold.ttf"],
    "serifi": ["georgiai.ttf", "timesi.ttf", "DejaVuSerif-Italic.ttf"],
    "tech": ["bahnschrift.ttf", "consola.ttf", "DejaVuSansMono.ttf"],
    "techb": ["consolab.ttf", "bahnschrift.ttf", "DejaVuSansMono-Bold.ttf"],
}
CJK_FONTS = ["msyh.ttc", "YuGothB.ttc", "msgothic.ttc", "meiryo.ttc", "simsun.ttc",
             "malgun.ttf", "NotoSerifCJK-Bold.ttc", "NotoSansCJK-Regular.ttc"]
SEAL_CHARS = {"ACTIVE": ("罰", "P"), "URGENT": ("急", "U"),
              "OVERDUE": ("遅", "X"), "CLEARED": ("成", "C")}


@lru_cache(maxsize=96)
def font(size, style="sans"):
    for n in FONT_SETS[style]:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


@lru_cache(maxsize=8)
def cjk_font(size):
    for n in CJK_FONTS:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return None


def has_glyph(f, ch):
    def ink(c):
        im = Image.new("L", (160, 160), 0)
        ImageDraw.Draw(im).text((10, 10), c, font=f, fill=255)
        return im.tobytes()
    try:
        a = ink(ch)
        return any(a) and a != ink("\U0010FFFF")
    except Exception:
        return False


@lru_cache(maxsize=4096)
def _char_len(f, ch):
    return f.getlength(ch)


def tracked(d, xy, text, f, fill, track):
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=f, fill=fill)
        x += _char_len(f, ch) + track
    return x


def tracked_w(f, text, track):
    if not text:
        return 0.0
    return sum(_char_len(f, c) + track for c in text) - track


def fade_line(layer, x, y, w, color, alpha, thick):
    d = ImageDraw.Draw(layer)
    for i in range(int(w)):
        a = int(alpha * (1 - i / w) ** 1.3)
        d.line([(x + i, y), (x + i, y + thick - 1)], fill=tuple(color) + (a,))


def wrap(f, text, maxw):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if f.getlength(t) <= maxw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def shorten(f, text, maxw):
    if f.getlength(text) <= maxw:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if f.getlength(text[:mid] + "...") <= maxw:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "..."


def make_theme(dark, info, level):
    if dark:
        t = dict(fg=(238, 232, 220), muted=(168, 162, 154), ok=(124, 200, 154),
                 warn=(236, 178, 80), bad=(232, 94, 86), fog=(10, 10, 14), fog_a=0.62)
        acc = (224, 78, 64) if info["muted"] else fit_accent(info["accent"], True)
    else:
        t = dict(fg=(34, 29, 27), muted=(108, 100, 94), ok=(48, 98, 70),
                 warn=(166, 102, 24), bad=(170, 34, 34), fog=(246, 241, 232), fog_a=0.76)
        acc = (188, 50, 42) if info["muted"] else fit_accent(info["accent"], False)
    t["accent"] = acc
    t["paper"] = (245, 240, 230)
    t["level_color"] = {"ACTIVE": acc, "URGENT": t["warn"],
                        "OVERDUE": t["bad"], "CLEARED": t["ok"]}[level]
    return t


def fmt_hm(sec):
    sec = int(abs(sec))
    return f"{sec // 3600}h {(sec % 3600) // 60:02d}m"


def draw_seal(S, color, level, paper, seed):
    seal = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(seal)
    d.rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.14), fill=tuple(color) + (255,))
    ins = int(S * 0.08)
    d.rounded_rectangle((ins, ins, S - 1 - ins, S - 1 - ins), radius=int(S * 0.09),
                        outline=tuple(paper) + (170,), width=max(1, int(S * 0.03)))
    glyph, fallback = SEAL_CHARS[level]
    cf = cjk_font(int(S * 0.56))
    if cf and has_glyph(cf, glyph):
        d.text((S / 2, S / 2), glyph, font=cf, fill=tuple(paper) + (255,), anchor="mm")
    else:
        d.text((S / 2, S / 2), fallback, font=font(int(S * 0.55), "serifb"),
               fill=tuple(paper) + (255,), anchor="mm")
    rng = random.Random(seed)
    for _ in range(26):
        x, y = rng.randint(0, S), rng.randint(0, S)
        r = rng.choice((1, 1, 2)) * max(1, S // 60)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(0, 0, 0, 0))
    return seal.rotate(-3, resample=Image.BICUBIC, expand=True)


def enso_polygon(cx, cy, R, seed, steps=150, start=-55, sweep=335):
    """A hand-brushed enso ring as one filled polygon (thick start, thin tapering end)."""
    rng = random.Random(seed)
    jit = [rng.uniform(-0.008, 0.008) for _ in range(steps + 1)]
    for i in range(1, steps + 1):  # smooth the jitter
        jit[i] = 0.6 * jit[i - 1] + 0.4 * jit[i]
    wmax, wmin = R * 0.14, R * 0.014
    outer, inner = [], []
    for i in range(steps + 1):
        t = i / steps
        ang = math.radians(start + sweep * t - 90)
        w = wmin + (wmax - wmin) * (1 - t) ** 0.75 * min(1.0, 0.35 + t * 9)
        w *= 1 + jit[i] * 8
        r = R * (1 + 0.035 * t + jit[i])
        outer.append((cx + (r + w / 2) * math.cos(ang), cy + (r + w / 2) * math.sin(ang)))
        inner.append((cx + (r - w / 2) * math.cos(ang), cy + (r - w / 2) * math.sin(ang)))
    return outer + inner[::-1]


def hand_polygon(cx, cy, ang_deg, length, base_w, tail):
    a = math.radians(ang_deg - 90)
    ux, uy = math.cos(a), math.sin(a)
    px, py = -uy, ux
    tip = (cx + ux * length, cy + uy * length)
    b1 = (cx + px * base_w / 2 - ux * tail, cy + py * base_w / 2 - uy * tail)
    b2 = (cx - px * base_w / 2 - ux * tail, cy - py * base_w / 2 - uy * tail)
    m1 = (cx + px * base_w / 2, cy + py * base_w / 2)
    m2 = (cx - px * base_w / 2, cy - py * base_w / 2)
    return [tip, m1, b1, b2, m2]


@lru_cache(maxsize=16)
def _cached_clock_dial(D, fg_rgb, mut_rgb, seed):
    ss = 3
    S = D * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = S / 2
    R = S * 0.45
    ink = tuple(fg_rgb) + (235,)
    mut = tuple(mut_rgb) + (200,)
    d.polygon(enso_polygon(c, c, R, seed), fill=ink)
    for h in range(60):
        major = h % 5 == 0
        if not major and S < 500:
            continue
        a = math.radians(h * 6 - 90)
        r1 = R * (0.80 if major else 0.86)
        r2 = R * 0.90
        wd = max(1, int(S * (0.006 if h % 15 == 0 else 0.0035)))
        d.line([(c + r1 * math.cos(a), c + r1 * math.sin(a)),
                (c + r2 * math.cos(a), c + r2 * math.sin(a))],
               fill=ink if h % 15 == 0 else mut, width=wd)
    return img


def draw_clock(D, now, theme, level, deadline_dt, seed, sec=None):
    """Ink analog clock: cached brushed Enso ring + tapered hands."""
    ss = 3
    S = D * ss
    img = _cached_clock_dial(D, tuple(theme["fg"]), tuple(theme["muted"]), seed).copy()
    d = ImageDraw.Draw(img)
    c = S / 2
    R = S * 0.45
    ink = tuple(theme["fg"]) + (235,)
    if level != "CLEARED" and deadline_dt is not None:
        rem = (deadline_dt - now).total_seconds()
        if rem > 0:
            now_ang = ((now.hour % 12) + now.minute / 60.0) * 30
            sweep = 360.0 if rem >= 43200 else rem / 43200.0 * 360.0
            rr = R * 0.66
            col = tuple(theme["level_color"]) + (220,)
            d.arc((c - rr, c - rr, c + rr, c + rr), now_ang - 90, now_ang - 90 + sweep,
                  fill=col, width=max(2, int(S * 0.016)))
    hour_ang = ((now.hour % 12) + now.minute / 60.0) * 30
    min_ang = now.minute * 6
    d.polygon(hand_polygon(c, c, hour_ang, R * 0.48, S * 0.032, R * 0.10), fill=ink)
    d.polygon(hand_polygon(c, c, min_ang, R * 0.74, S * 0.022, R * 0.12), fill=ink)
    if sec is not None:
        a = math.radians(sec * 6 - 90)
        d.line([(c - R * 0.16 * math.cos(a), c - R * 0.16 * math.sin(a)),
                (c + R * 0.80 * math.cos(a), c + R * 0.80 * math.sin(a))],
               fill=tuple(theme["accent"]) + (255,), width=max(2, int(S * 0.006)))
    dot = S * 0.034
    d.ellipse((c - dot, c - dot, c + dot, c + dot), fill=tuple(theme["accent"]) + (255,))
    return img.resize((D, D), Image.LANCZOS)


def draw_strip(layer, y, pw, s, ctx, theme):
    """23 sprint days as marks: done, today, upcoming; milestone days are taller."""
    d = ImageDraw.Draw(layer)
    idx, comp = ctx["day_idx"], ctx["completed"]
    step = pw / max(1, SPRINT_DAYS)
    base = y + int(16 * s)
    for n in range(1, SPRINT_DAYS + 1):
        x = step * (n - 0.5)
        ms = n in MILESTONES
        h = int((18 if ms else 11) * s)
        wd = max(2, int(3 * s))
        if n < idx:
            col = theme["ok"] if day_done(n, comp) else theme["bad"]
            d.rounded_rectangle((x - wd / 2, base - h, x + wd / 2, base), radius=1,
                                fill=tuple(col) + (255,))
        elif n == idx:
            r = int(7 * s)
            d.ellipse((x - r, base - h // 2 - r, x + r, base - h // 2 + r),
                      fill=tuple(theme["accent"]) + (255,))
        else:
            d.rounded_rectangle((x - wd / 2, base - h, x + wd / 2, base), radius=1,
                                fill=tuple(theme["muted"]) + (120,))
    return int(34 * s)


# ==================================================================================
# widgets
# ==================================================================================
WIDGET_ORDER = ["clock", "calendar", "moon", "sprint", "status", "quests", "sprintmap",
                "waveplate", "sysmon", "wave", "music", "focus"]
WIDGET_NAMES = {"clock": "Clock", "calendar": "Calendar (ink)", "moon": "Moon phase",
                "sprint": "Sprint", "status": "Status & countdown", "quests": "Quests",
                "sprintmap": "Sprint map", "waveplate": "Waveplate (WuWa)",
                "sysmon": "System monitor", "wave": "Resonance (WuWa)",
                "music": "Music player", "focus": "Focus timer"}
STYLE_CHOICES = {"clock": ["ink", "analog", "minimal", "stacked", "arc", "words", "neon",
                           "resonance"],
                 "calendar": ["ink", "seal", "grid"], "moon": ["ink", "hud"],
                 "sprintmap": ["hex", "ring"], "waveplate": ["ring", "bar"],
                 "sysmon": ["hud", "bars"], "wave": ["wave", "ring"],
                 "music": ["disc", "bar"], "focus": ["ring", "bar"]}
INTERACTIVE = {"music", "focus", "quests"}


def _wd(enabled, style=""):
    return {"enabled": enabled, "style": style, "scale": 1.0, "fx": None, "fy": None}


DEFAULT_WIDGETS = {
    "clock": _wd(True, "ink"), "calendar": _wd(False, "ink"), "moon": _wd(False, "ink"),
    "sprint": _wd(True), "status": _wd(True), "quests": _wd(True),
    "sprintmap": _wd(False, "hex"), "waveplate": _wd(False, "ring"),
    "sysmon": _wd(False, "hud"), "wave": _wd(False, "wave"),
    "music": _wd(True, "disc"), "focus": _wd(False, "ring"),
}


def merge_widgets(saved):
    out = {}
    for wid in WIDGET_ORDER:
        d = dict(DEFAULT_WIDGETS[wid])
        if isinstance(saved, dict) and isinstance(saved.get(wid), dict):
            d.update({k: v for k, v in saved[wid].items() if k in d})
        if STYLE_CHOICES.get(wid) and d["style"] not in STYLE_CHOICES[wid]:
            d["style"] = STYLE_CHOICES[wid][0]
        d["scale"] = min(2.0, max(0.5, float(d["scale"] or 1.0)))
        out[wid] = d
    return out


def _layer(w, h):
    layer = Image.new("RGBA", (max(1, int(w)), max(1, int(h))), (0, 0, 0, 0))
    return layer, ImageDraw.Draw(layer)


def _trim(layer, w, h):
    return layer.crop((0, 0, max(1, int(w)), max(1, int(h))))


def fmt_ms(sec):
    sec = int(max(0, sec))
    return f"{sec // 60}:{sec % 60:02d}"


def pill(d, rect, text, theme, sc, filled=False, color=None):
    col = tuple(color or theme["accent"])
    if filled:
        d.rounded_rectangle(rect, radius=int((rect[3] - rect[1]) / 2), fill=col + (255,))
        tcol = (20, 18, 18) if theme["fg"][0] > 128 else (255, 255, 255)
    else:
        d.rounded_rectangle(rect, radius=int((rect[3] - rect[1]) / 2), outline=col + (255,),
                            width=max(2, int(2 * sc)))
        tcol = col
    f = font(int(13 * sc), "sansb")
    tw = tracked_w(f, text, 2.4 * sc)
    cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    tracked(d, (cx - tw / 2, cy - 9 * sc), text, f, tcol, 2.4 * sc)


def icon_prev(d, cx, cy, r, col):
    d.rectangle((cx - r, cy - r, cx - r * 0.72, cy + r), fill=col)
    d.polygon([(cx + r, cy - r), (cx + r, cy + r), (cx - r * 0.55, cy)], fill=col)


def icon_next(d, cx, cy, r, col):
    d.rectangle((cx + r * 0.72, cy - r, cx + r, cy + r), fill=col)
    d.polygon([(cx - r, cy - r), (cx - r, cy + r), (cx + r * 0.55, cy)], fill=col)


def icon_play(d, cx, cy, r, col):
    d.polygon([(cx - r * 0.65, cy - r), (cx - r * 0.65, cy + r), (cx + r, cy)], fill=col)


def icon_pause(d, cx, cy, r, col):
    d.rectangle((cx - r * 0.8, cy - r, cx - r * 0.25, cy + r), fill=col)
    d.rectangle((cx + r * 0.25, cy - r, cx + r * 0.8, cy + r), fill=col)


HOUR_W = ["twelve", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
          "ten", "eleven"]
MIN_W = {5: "five past", 10: "ten past", 15: "quarter past", 20: "twenty past",
         25: "twenty-five past", 30: "half past", 35: "twenty-five to", 40: "twenty to",
         45: "quarter to", 50: "ten to", 55: "five to"}


def words_time(now):
    m5 = int(round(now.minute / 5.0)) * 5
    h = now.hour
    if m5 == 60:
        m5, h = 0, h + 1
    if m5 == 0:
        return f"{HOUR_W[h % 12]} o'clock"
    if m5 > 30:
        h += 1
    return f"{MIN_W[m5]} {HOUR_W[h % 12]}"


def draw_day_ring(D, now, theme, level, deadline_dt):
    """24-hour ring: progress since midnight, 6h ticks, deadline marker."""
    ss = 3
    S = D * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c, R, wd = S / 2, S * 0.44, max(3, int(S * 0.028))
    box = (c - R, c - R, c + R, c + R)
    d.arc(box, 0, 360, fill=tuple(theme["muted"]) + (90,), width=wd)
    frac = (now.hour * 3600 + now.minute * 60 + now.second) / 86400.0
    d.arc(box, -90, -90 + 360 * frac, fill=tuple(theme["accent"]) + (255,), width=wd)
    for h in (0, 6, 12, 18):
        a = math.radians(h * 15 - 90)
        d.line([(c + R * 0.84 * math.cos(a), c + R * 0.84 * math.sin(a)),
                (c + R * 0.92 * math.cos(a), c + R * 0.92 * math.sin(a))],
               fill=tuple(theme["fg"]) + (220,), width=max(2, int(S * 0.006)))
    if deadline_dt is not None and level != "CLEARED":
        dl = (deadline_dt.hour * 3600 + deadline_dt.minute * 60) / 86400.0
        a = math.radians(dl * 360 - 90)
        r = S * 0.022
        px, py = c + R * math.cos(a), c + R * math.sin(a)
        d.ellipse((px - r, py - r, px + r, py + r), fill=tuple(theme["level_color"]) + (255,))
    a = math.radians(frac * 360 - 90)
    r = S * 0.016
    px, py = c + R * math.cos(a), c + R * math.sin(a)
    d.ellipse((px - r, py - r, px + r, py + r), fill=tuple(theme["fg"]) + (255,))
    return img.resize((D, D), Image.LANCZOS)


def draw_disc(D, theme, art, angle):
    """Vinyl record with the album art (or an accent label) in the middle."""
    ss = 3
    S = D * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    c, R = S / 2, S * 0.48
    ImageDraw.Draw(img).ellipse((c - R, c - R, c + R, c + R), fill=(22, 20, 22, 245))
    ov = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    for i in range(1, 9):
        r = R * (0.42 + 0.065 * i)
        od.ellipse((c - r, c - r, c + r, c + r), outline=(255, 255, 255, 20), width=ss)
    for k in (0, 180):
        od.pieslice((c - R, c - R, c + R, c + R), angle + k, angle + k + 26,
                    fill=(255, 255, 255, 30))
    od.ellipse((c - R, c - R, c + R, c + R), outline=tuple(theme["muted"]) + (130,), width=ss)
    img.alpha_composite(ov)
    L = R * 0.40
    d = ImageDraw.Draw(img)
    if art is not None:
        a = art.convert("RGBA").resize((int(2 * L), int(2 * L)), Image.LANCZOS)
        mask = Image.new("L", a.size, 0)
        ImageDraw.Draw(mask).ellipse((0, 0, a.size[0] - 1, a.size[1] - 1), fill=255)
        img.paste(a, (int(c - L), int(c - L)), mask)
    else:
        d.ellipse((c - L, c - L, c + L, c + L), fill=tuple(theme["accent"]) + (255,))
        r2 = L * 0.55
        d.ellipse((c - r2, c - r2, c + r2, c + r2), outline=(255, 255, 255, 90), width=ss)
    h = R * 0.055
    d.ellipse((c - h, c - h, c + h, c + h), fill=(14, 12, 14, 255))
    return img.resize((D, D), Image.LANCZOS)


# ---------------------------------------------------------------- clock presets
def w_clock(style, ctx, theme, sc):
    now, live = ctx["now"], ctx.get("live")
    fg, muted, acc = theme["fg"], theme["muted"], theme["accent"]
    if ctx["clock_24h"]:
        timestr, ampm = now.strftime("%H:%M"), ""
    else:
        timestr, ampm = now.strftime("%I:%M").lstrip("0"), now.strftime("%p")
    daystr = now.strftime("%A")
    datestr = f"{now.day} {now.strftime('%B %Y')}"
    sec = now.second if live else None

    if style == "analog":
        D = int(230 * sc)
        W_ = D + int(20 * sc)
        layer, d = _layer(W_, D + int(110 * sc))
        clk = draw_clock(D, now, theme, ctx["level"], ctx["deadline_dt"], f"{now:%Y%m%d}", sec=sec)
        layer.alpha_composite(clk, (int(10 * sc), 0))
        y = D + int(8 * sc)
        d.text((W_ / 2, y), daystr, font=font(int(28 * sc), "serifi"), fill=acc, anchor="ma")
        d.text((W_ / 2, y + int(38 * sc)), datestr, font=font(int(21 * sc), "serif"),
               fill=muted, anchor="ma")
        return _trim(layer, W_, y + int(74 * sc)), {}

    if style == "minimal":
        tf = font(int(124 * sc), "sansl")
        tw = tf.getlength(timestr)
        W_ = int(max(tw + 130 * sc, 440 * sc))
        layer, d = _layer(W_, int(300 * sc))
        d.text((-int(4 * sc), 0), timestr, font=tf, fill=fg)
        x = tw + 8 * sc
        if live:
            d.text((x, int(58 * sc)), f":{now.second:02d}", font=font(int(32 * sc), "sansl"),
                   fill=muted)
            x += 74 * sc
        if ampm:
            d.text((x, int(86 * sc)), ampm, font=font(int(28 * sc), "serifi"), fill=muted)
        y = int(150 * sc)
        fi = font(int(30 * sc), "serifi")
        d.text((0, y), daystr, font=fi, fill=acc)
        d.text((fi.getlength(daystr) + 16 * sc, y + 3 * sc), "\u00b7   " + datestr,
               font=font(int(24 * sc), "serif"), fill=muted)
        return _trim(layer, W_, y + int(46 * sc)), {}

    if style == "stacked":
        hh, mm = timestr.split(":")
        tf = font(int(150 * sc), "sansl")
        W_ = int(330 * sc)
        layer, d = _layer(W_, int(560 * sc))
        d.text((-int(6 * sc), 0), hh, font=tf, fill=fg)
        d.text((-int(6 * sc), int(138 * sc)), mm, font=tf, fill=acc)
        if live:
            d.text((tf.getlength(mm) + 6 * sc, int(220 * sc)), f"{now.second:02d}",
                   font=font(int(34 * sc), "sansl"), fill=muted)
        y = int(302 * sc)
        fade_line(layer, 0, y, int(250 * sc), muted, 150, max(1, int(2 * sc)))
        y += int(14 * sc)
        tracked(d, (0, y), daystr.upper() + ((" " + ampm) if ampm else ""),
                font(int(17 * sc), "sansb"), fg, 5 * sc)
        d.text((0, y + int(30 * sc)), datestr, font=font(int(22 * sc), "serif"), fill=muted)
        return _trim(layer, W_, y + int(68 * sc)), {}

    if style == "arc":
        D = int(270 * sc)
        layer, d = _layer(D, D)
        layer.alpha_composite(draw_day_ring(D, now, theme, ctx["level"], ctx["deadline_dt"]),
                              (0, 0))
        d.text((D / 2, D * 0.40), timestr + ((" " + ampm) if ampm else ""),
               font=font(int(54 * sc), "sansl"), fill=fg, anchor="mm")
        d.text((D / 2, D * 0.56), daystr.upper(), font=font(int(15 * sc), "sansb"),
               fill=acc, anchor="mm")
        d.text((D / 2, D * 0.65), datestr, font=font(int(18 * sc), "serif"), fill=muted,
               anchor="mm")
        return layer, {}

    if style == "words":
        f1 = font(int(46 * sc), "serifi")
        W_ = int(460 * sc)
        layer, d = _layer(W_, int(420 * sc))
        y = 0
        tracked(d, (0, y), "IT IS", font(int(14 * sc), "sansb"), muted, 4 * sc)
        y += int(28 * sc)
        for ln in wrap(f1, words_time(now), W_)[:3]:
            d.text((0, y), ln, font=f1, fill=fg)
            y += int(58 * sc)
        y += int(6 * sc)
        fi = font(int(24 * sc), "serifi")
        d.text((0, y), daystr, font=fi, fill=acc)
        d.text((fi.getlength(daystr) + 14 * sc, y + 1 * sc), "\u00b7   " + datestr,
               font=font(int(20 * sc), "serif"), fill=muted)
        return _trim(layer, W_, y + int(40 * sc)), {}

    if style in ("neon", "resonance"):
        return w_clock_extra(style, ctx, theme, sc)

    # default: "ink" (brushed analog ring + digital time + date)
    Dc = int(158 * sc)
    pw = int(470 * sc)
    layer, d = _layer(pw, Dc + int(10 * sc))
    layer.alpha_composite(draw_clock(Dc, now, theme, ctx["level"], ctx["deadline_dt"],
                                     f"{now:%Y%m%d}", sec=sec), (0, 0))
    cx0 = Dc + int(22 * sc)
    tf = font(int(70 * sc), "sansl")
    d.text((cx0 - 2 * sc, 6 * sc), timestr, font=tf, fill=fg)
    xend = cx0 + tf.getlength(timestr)
    if live:
        d.text((xend + 4 * sc, 34 * sc), f":{now.second:02d}", font=font(int(24 * sc), "sansl"),
               fill=muted)
        xend += 44 * sc
    if ampm:
        d.text((xend + 6 * sc, 40 * sc), ampm, font=font(int(22 * sc), "serifi"), fill=muted)
    d.text((cx0, 90 * sc), daystr, font=font(int(26 * sc), "serifi"), fill=acc)
    d.text((cx0, 124 * sc), datestr, font=font(int(20 * sc), "serif"), fill=muted)
    return _trim(layer, pw, Dc), {}


# ---------------------------------------------------------------- sprint / status / quests
def w_sprint(ctx, theme, sc):
    pw = int(460 * sc)
    layer, d = _layer(pw, int(260 * sc))
    fg, muted, acc = theme["fg"], theme["muted"], theme["accent"]
    y = 0
    if ctx["day_info"]:
        idx = ctx["day_idx"]
        sf = font(int(13 * sc), "sansb")
        x2 = tracked(d, (0, y), f"DAY {idx:02d} / {SPRINT_DAYS}", sf, acc, 3 * sc)
        tracked(d, (x2 + 14 * sc, y), f"\u00b7   {PHASES[ctx['day_info']['phase']]}", sf, muted,
                3 * sc)
        y += int(24 * sc)
        tfont = font(int(21 * sc), "serifi")
        for ln in wrap(tfont, ctx["day_info"]["title"], pw)[:2]:
            d.text((0, y), ln, font=tfont, fill=fg)
            y += int(27 * sc)
        y += int(2 * sc)
        y += draw_strip(layer, y, pw, sc, ctx, theme)
        left = [f"{nm} \u00b7 " + ("TODAY" if k == idx else f"{k - idx}d")
                for k, nm in sorted(MILESTONES.items()) if k >= idx]
        if left:
            tracked(d, (0, y), "   \u00b7   ".join(left), font(int(12 * sc), "sansb"), muted,
                    2.6 * sc)
        y += int(22 * sc)
    else:
        d.text((0, y), ctx["no_sprint_text"], font=font(int(22 * sc), "serifi"), fill=fg)
        y += int(40 * sc)
    return _trim(layer, pw, y), {}


def w_status(ctx, theme, sc):
    pw = int(460 * sc)
    layer, d = _layer(pw, int(520 * sc))
    fg, muted, acc, lc = theme["fg"], theme["muted"], theme["accent"], theme["level_color"]
    level, now = ctx["level"], ctx["now"]
    th = max(1, int(2 * sc))
    y = int(4 * sc)
    S = int(58 * sc)
    seal = draw_seal(S, lc, level, theme["paper"], f"{now:%Y%m%d}{level}")
    layer.alpha_composite(seal, (0, y))
    tx = seal.width + int(18 * sc)
    tracked(d, (tx, y + 4 * sc), "SHADOW SYSTEM", font(int(15 * sc), "sansb"), muted, 3.4 * sc)
    tracked(d, (tx, y + 28 * sc), BADGE[level], font(int(14 * sc), "sansb"), lc, 3.8 * sc)
    y += seal.height + int(14 * sc)
    fade_line(layer, 0, y, pw, muted, 120, th)
    y += int(16 * sc)

    rem = ctx["remaining_sec"]
    if level == "CLEARED":
        cap, val, vcol = "TODAY", "all cleared", lc
    elif rem < 0:
        cap, val, vcol = "OVERDUE BY", fmt_hm(rem), lc
    else:
        cap, val = "TIME LEFT TODAY", fmt_hm(rem)
        vcol = lc if level == "URGENT" else fg
    cf2 = font(int(13 * sc), "sansb")
    tracked(d, (0, y), cap, cf2, muted, 3 * sc)
    due = f"DUE {ctx['deadline_str']}"
    tracked(d, (pw - tracked_w(cf2, due, 3 * sc), y), due, cf2, muted, 3 * sc)
    y += int(22 * sc)
    d.text((-int(2 * sc), y), val,
           font=font(int(42 * sc), "sansl" if level != "CLEARED" else "serifi"), fill=vcol)
    y += int(54 * sc)
    fade_line(layer, 0, y, pw, muted, 120, th)
    y += int(14 * sc)

    d.text((0, y), f"Rank {ctx['rank']}   \u00b7   {ctx['xp']} xp   \u00b7   "
                   f"{ctx['streak']} day streak", font=font(int(19 * sc), "serif"), fill=fg)
    y += int(30 * sc)
    bh = max(3, int(4 * sc))
    d.rounded_rectangle((0, y, pw, y + bh), radius=bh // 2, fill=tuple(muted) + (80,))
    d.rounded_rectangle((0, y, max(bh, int(pw * ctx["rank_frac"])), y + bh), radius=bh // 2,
                        fill=acc)
    y += int(22 * sc)
    mf = font(int(23 * sc), "serifi")
    for line in wrap(mf, ctx["message"], pw)[:3]:
        d.text((0, y), line, font=mf, fill=lc)
        y += int(31 * sc)
    return _trim(layer, pw, y + int(4 * sc)), {}


def rgba(c, a=255):
    return tuple(c)[:3] + (int(a),)


def moon_phase(now):
    days = (now - dt.datetime(2000, 1, 6, 18, 14)).total_seconds() / 86400.0
    return (days % 29.530588853) / 29.530588853


MOON_NAMES = [(0.03, "New Moon"), (0.22, "Waxing Crescent"), (0.28, "First Quarter"),
              (0.47, "Waxing Gibbous"), (0.53, "Full Moon"), (0.72, "Waning Gibbous"),
              (0.78, "Last Quarter"), (0.97, "Waning Crescent"), (1.01, "New Moon")]


def draw_stamp(S, color, text, paper, seed, style="serifb"):
    """Ink-seal square with a number/word in it."""
    seal = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(seal)
    d.rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.12), fill=rgba(color))
    ins = int(S * 0.07)
    d.rounded_rectangle((ins, ins, S - 1 - ins, S - 1 - ins), radius=int(S * 0.08),
                        outline=rgba(paper, 170), width=max(1, int(S * 0.025)))
    d.text((S / 2, S / 2), text, font=font(int(S * 0.52), style), fill=rgba(paper),
           anchor="mm")
    rng = random.Random(seed)
    for _ in range(12):
        x, y = rng.randint(0, S), rng.randint(0, S)
        r = rng.choice((1, 1, 2)) * max(1, S // 70)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(0, 0, 0, 0))
    return seal.rotate(-3, resample=Image.BICUBIC, expand=True)


def draw_gauge(D, pct, theme, color):
    ss = 3
    S = D * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dd = ImageDraw.Draw(img)
    c, R, wd = S / 2, S * 0.42, max(4, int(S * 0.055))
    box = (c - R, c - R, c + R, c + R)
    dd.arc(box, 135, 405, fill=rgba(theme["muted"], 90), width=wd)
    pct = min(100.0, max(0.0, pct))
    if pct > 0.5:
        dd.arc(box, 135, 135 + 270 * pct / 100.0, fill=rgba(color), width=wd)
    for i in range(11):
        a = math.radians(135 + 27 * i)
        r1, r2 = R * 0.78, R * 0.86
        dd.line([(c + r1 * math.cos(a), c + r1 * math.sin(a)),
                 (c + r2 * math.cos(a), c + r2 * math.sin(a))],
                fill=rgba(theme["muted"], 170), width=max(1, ss))
    return img.resize((D, D), Image.LANCZOS)


def hex_pts(cx, cy, r):
    return [(cx + r * math.cos(math.radians(60 * i - 30)),
             cy + r * math.sin(math.radians(60 * i - 30))) for i in range(6)]


def spectrum_val(i, t, playing, seed):
    if not playing:
        return 0.07 + 0.03 * math.sin(i * 0.7 + t)
    return 0.22 + 0.78 * abs(math.sin(i * 0.55 + t * 3.1) * math.sin(i * 0.23 - t * 1.7 + seed))


# ---------------------------------------------------------------- extra clock presets
def w_clock_extra(style, ctx, theme, sc):
    now, live = ctx["now"], ctx.get("live")
    fg, muted, acc = theme["fg"], theme["muted"], theme["accent"]
    if ctx["clock_24h"]:
        timestr, ampm = now.strftime("%H:%M"), ""
    else:
        timestr, ampm = now.strftime("%I:%M").lstrip("0"), now.strftime("%p")
    daystr = now.strftime("%A")
    if style == "neon":
        pw, ph = int(450 * sc), int(204 * sc)
        layer, d = _layer(pw, ph)
        T, L = max(2, int(3 * sc)), int(28 * sc)
        for (x0, y0, sx, sy) in ((0, 0, 1, 1), (pw - 1, 0, -1, 1), (0, ph - 1, 1, -1),
                                 (pw - 1, ph - 1, -1, -1)):
            d.line([(x0, y0), (x0 + sx * L, y0)], fill=rgba(acc), width=T)
            d.line([(x0, y0), (x0, y0 + sy * L)], fill=rgba(acc), width=T)
        cf = font(int(13 * sc), "techb")
        tracked(d, (int(26 * sc), int(14 * sc)), "SYS//TIME", cf, rgba(muted), 3 * sc)
        off = now.astimezone().strftime("%z")
        off = f"UTC{off[:3]}:{off[3:]}" if len(off) == 5 else "LOCAL"
        tracked(d, (pw - int(26 * sc) - tracked_w(cf, off, 3 * sc), int(14 * sc)), off, cf,
                rgba(muted), 3 * sc)
        tf = font(int(98 * sc), "tech")
        glow = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        ImageDraw.Draw(glow).text((int(26 * sc), int(34 * sc)), timestr, font=tf,
                                  fill=rgba(acc, 220))
        layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(max(2, int(9 * sc)))))
        d.text((int(26 * sc), int(34 * sc)), timestr, font=tf, fill=rgba(fg))
        xe = int(26 * sc) + tf.getlength(timestr)
        if live:
            d.text((xe + 6 * sc, int(78 * sc)), f":{now.second:02d}",
                   font=font(int(30 * sc), "tech"), fill=rgba(acc))
        by = int(152 * sc)
        d.line([(int(26 * sc), by), (pw - int(26 * sc), by)], fill=rgba(muted, 90), width=2)
        span = pw - int(52 * sc)
        for i in range(13):
            x = int(26 * sc) + span * i / 12.0
            d.line([(x, by - 5 * sc), (x, by + 5 * sc)], fill=rgba(muted, 150), width=1)
        px = int(26 * sc) + span * (now.second / 60.0 if live else now.minute / 60.0)
        d.rounded_rectangle((px - 14 * sc, by - 3 * sc, px + 14 * sc, by + 3 * sc), radius=3,
                            fill=rgba(acc))
        d.text((int(26 * sc), int(166 * sc)),
               f"{daystr.upper()} // {now:%d.%m.%Y}" + (f"  {ampm}" if ampm else ""),
               font=font(int(18 * sc), "tech"), fill=rgba(muted))
        return layer, {}

    # "resonance": concentric rings, tick dots, diamond markers, minute arc
    D = int(290 * sc)
    ss = 3
    S = D * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dd = ImageDraw.Draw(img)
    c, R = S / 2, S * 0.46
    dd.ellipse((c - R, c - R, c + R, c + R), outline=rgba(muted, 150), width=ss * 2)
    for i in range(60):
        a = math.radians(i * 6 - 90)
        r = R * 0.93
        dot = ss * (2.4 if i % 5 == 0 else 1.1)
        x, y = c + r * math.cos(a), c + r * math.sin(a)
        dd.ellipse((x - dot, y - dot, x + dot, y + dot),
                   fill=rgba(fg if i % 5 == 0 else muted, 230))
    r2 = R * 0.80
    for i in range(48):
        a0 = i * 7.5 - 90
        dd.arc((c - r2, c - r2, c + r2, c + r2), a0, a0 + 4.5, fill=rgba(muted, 170),
               width=ss * 2)
    r3 = R * 0.66
    frac = (now.minute * 60 + now.second) / 3600.0
    dd.arc((c - r3, c - r3, c + r3, c + r3), -90, -90 + 360 * frac, fill=rgba(acc),
           width=ss * 3)

    def diamond(px, py, s_, col):
        dd.polygon([(px, py - s_), (px + s_, py), (px, py + s_), (px - s_, py)], fill=col)
    for k in range(4):
        a = math.radians(k * 90 - 90)
        diamond(c + R * 0.55 * math.cos(a), c + R * 0.55 * math.sin(a), ss * 4.5, rgba(fg, 200))
    ha = math.radians(((now.hour % 12) + now.minute / 60.0) * 30 - 90)
    diamond(c + r3 * math.cos(ha), c + r3 * math.sin(ha), ss * 7, rgba(acc))
    if live:
        sa = math.radians(now.second * 6 - 90)
        diamond(c + R * math.cos(sa), c + R * math.sin(sa), ss * 6, rgba(acc))
    layer, d = _layer(D, D)
    layer.alpha_composite(img.resize((D, D), Image.LANCZOS))
    d.text((D / 2, D * 0.46), timestr, font=font(int(56 * sc), "tech"), fill=rgba(fg),
           anchor="mm")
    cf = font(int(13 * sc), "techb")
    t1 = daystr.upper()
    tracked(d, (D / 2 - tracked_w(cf, t1, 4 * sc) / 2, D * 0.60), t1, cf, rgba(acc), 4 * sc)
    t2 = f"{now:%d.%m.%Y}"
    d.text((D / 2, D * 0.69), t2, font=font(int(15 * sc), "tech"), fill=rgba(muted), anchor="mm")
    return layer, {}


# ---------------------------------------------------------------- calendar / moon
def w_calendar(style, ctx, theme, sc):
    now = ctx["now"]
    fg, muted, acc = theme["fg"], theme["muted"], theme["accent"]
    if style == "seal":
        S = int(118 * sc)
        pw = int(380 * sc)
        layer, d = _layer(pw, S + int(24 * sc))
        seal = draw_stamp(S, acc, str(now.day), theme["paper"], f"{now:%Y%m%d}")
        layer.alpha_composite(seal, (0, 0))
        x0 = S + int(26 * sc)
        d.text((x0, int(2 * sc)), now.strftime("%B"), font=font(int(40 * sc), "serif"), fill=fg)
        d.text((x0, int(54 * sc)), now.strftime("%A"), font=font(int(27 * sc), "serifi"),
               fill=acc)
        tracked(d, (x0, int(92 * sc)), str(now.year), font(int(14 * sc), "sansb"), muted,
                5 * sc)
        return _trim(layer, pw, S + int(8 * sc)), {}
    if style == "grid":
        cal = calendar.monthcalendar(now.year, now.month)
        cell = int(36 * sc)
        pw = cell * 7
        layer, d = _layer(pw, int(60 * sc) + cell * len(cal) + 8)
        d.text((0, 0), now.strftime("%B"), font=font(int(30 * sc), "serifi"), fill=fg)
        d.text((pw, int(8 * sc)), str(now.year), font=font(int(18 * sc), "sansl"), fill=muted,
               anchor="ra")
        for i, ch in enumerate("MTWTFSS"):
            d.text((i * cell + cell / 2, int(48 * sc)), ch, font=font(int(12 * sc), "sansb"),
                   fill=muted, anchor="mm")
        nf = font(int(16 * sc), "sans")
        for r, week in enumerate(cal):
            for c, day in enumerate(week):
                if not day:
                    continue
                cx, cy = c * cell + cell / 2, int(60 * sc) + r * cell + cell / 2
                if day == now.day:
                    rr = cell * 0.42
                    d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=rgba(acc))
                    d.text((cx, cy), str(day), font=font(int(16 * sc), "sansb"),
                           fill=(20, 18, 18, 255) if theme["fg"][0] > 128 else (255, 255, 255, 255),
                           anchor="mm")
                else:
                    d.text((cx, cy), str(day), font=nf, fill=rgba(muted if c >= 5 else fg),
                           anchor="mm")
        return layer, {}
    D = int(250 * sc)               # "ink": brushed ring around a big day number
    layer, d = _layer(D, D + int(84 * sc))
    ss = 3
    ring = Image.new("RGBA", (D * ss, D * ss), (0, 0, 0, 0))
    ImageDraw.Draw(ring).polygon(enso_polygon(D * ss / 2, D * ss / 2, D * ss * 0.44,
                                              f"{now:%Y%m}"), fill=rgba(fg, 125))
    layer.alpha_composite(ring.resize((D, D), Image.LANCZOS))
    d.text((D / 2, D * 0.50), str(now.day), font=font(int(118 * sc), "serif"), fill=rgba(fg),
           anchor="mm")
    y = D + int(2 * sc)
    d.text((D / 2, y), now.strftime("%A"), font=font(int(26 * sc), "serifi"), fill=rgba(acc),
           anchor="ma")
    cf = font(int(14 * sc), "sansb")
    t = f"{now:%B}  {now.year}".upper()
    tracked(d, (D / 2 - tracked_w(cf, t, 4 * sc) / 2, y + int(42 * sc)), t, cf, rgba(muted),
            4 * sc)
    return _trim(layer, D, y + int(66 * sc)), {}


def w_moon(style, ctx, theme, sc):
    now = ctx["now"]
    fg, muted, acc = theme["fg"], theme["muted"], theme["accent"]
    p = moon_phase(now)
    illum = (1 - math.cos(2 * math.pi * p)) / 2
    name = next(n for lim, n in MOON_NAMES if p < lim)
    D = int(200 * sc)
    ss = 3
    S = D * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dd = ImageDraw.Draw(img)
    c, R = S / 2, S * 0.36
    dd.ellipse((c - R, c - R, c + R, c + R), fill=rgba(muted, 70))
    k = math.cos(2 * math.pi * p)
    pts = []
    n = 60
    for i in range(n + 1):
        t = math.radians(-90 + 180 * i / n)
        pts.append((R * math.cos(t), R * math.sin(t)))
    for i in range(n + 1):
        t = math.radians(90 - 180 * i / n)
        pts.append((k * R * math.cos(t), R * math.sin(t)))
    sign = 1 if p < 0.5 else -1
    dd.polygon([(c + sign * x, c + y) for x, y in pts], fill=rgba(acc if style == "hud" else fg))
    if style == "ink":
        dd.polygon(enso_polygon(c, c, R * 1.28, f"{now:%Y%m}"), fill=rgba(fg, 150))
    else:
        dd.ellipse((c - R * 1.25, c - R * 1.25, c + R * 1.25, c + R * 1.25),
                   outline=rgba(muted, 160), width=ss * 2)
        for i in range(72):
            a = math.radians(i * 5 - 90)
            r1, r2 = R * (1.34 if i % 6 == 0 else 1.38), R * 1.44
            dd.line([(c + r1 * math.cos(a), c + r1 * math.sin(a)),
                     (c + r2 * math.cos(a), c + r2 * math.sin(a))],
                    fill=rgba(muted, 180), width=max(1, ss))
    pw = int(250 * sc)
    layer, d = _layer(pw, D + int(70 * sc))
    layer.alpha_composite(img.resize((D, D), Image.LANCZOS), ((pw - D) // 2, 0))
    if style == "hud":
        cf = font(int(14 * sc), "techb")
        tracked(d, (pw / 2 - tracked_w(cf, name.upper(), 3 * sc) / 2, D + int(4 * sc)),
                name.upper(), cf, rgba(acc), 3 * sc)
        d.text((pw / 2, D + int(40 * sc)), f"{illum * 100:04.1f}% ILLUM", font=font(int(15 * sc), "tech"),
               fill=rgba(muted), anchor="ma")
    else:
        d.text((pw / 2, D + int(2 * sc)), name, font=font(int(24 * sc), "serifi"),
               fill=rgba(acc), anchor="ma")
        d.text((pw / 2, D + int(36 * sc)), f"{round(illum * 100)}% illuminated",
               font=font(int(16 * sc), "serif"), fill=rgba(muted), anchor="ma")
    return _trim(layer, pw, D + int(66 * sc)), {}


# ---------------------------------------------------------------- futuristic: system + sprint map
def w_sysmon(style, ctx, theme, sc):
    st = ctx.get("sys") or {"cpu": 0, "ram": 0, "disk": 0, "bat": None}
    fg, muted, acc = theme["fg"], theme["muted"], theme["accent"]

    def col(v):
        return theme["bad"] if v > 85 else theme["warn"] if v > 65 else acc
    rows = [("CPU", st["cpu"]), ("RAM", st["ram"]), ("DISK", st["disk"])]
    bat = st.get("bat")
    if style == "bars":
        pw = int(330 * sc)
        layer, d = _layer(pw, int(190 * sc))
        cf = font(int(13 * sc), "techb")
        tracked(d, (0, 0), "SYSTEM STATUS", cf, rgba(acc), 4 * sc)
        y = int(28 * sc)
        items = rows + [("BAT", bat["pct"] if bat else 0)]
        for name, v in items:
            tracked(d, (0, y), name, cf, rgba(muted), 3 * sc)
            txt = ("--" if (name == "BAT" and not bat) else f"{int(v)}%")
            d.text((pw, y - 3 * sc), txt, font=font(int(18 * sc), "tech"), fill=rgba(fg),
                   anchor="ra")
            by = y + int(24 * sc)
            bh = max(3, int(5 * sc))
            d.rounded_rectangle((0, by, pw, by + bh), radius=bh // 2, fill=rgba(muted, 80))
            color = theme["warn"] if (name == "BAT" and bat and bat["pct"] < 20) else col(
                v if name != "BAT" else 0)
            if v > 0.5:
                d.rounded_rectangle((0, by, max(bh, int(pw * min(v, 100) / 100.0)), by + bh),
                                    radius=bh // 2, fill=rgba(color))
            y += int(40 * sc)
        return _trim(layer, pw, y), {}
    Dg = int(122 * sc)
    gap = int(16 * sc)
    pw = 3 * Dg + 2 * gap
    layer, d = _layer(pw, Dg + int(86 * sc))
    cf = font(int(13 * sc), "techb")
    for i, (name, v) in enumerate(rows):
        x = i * (Dg + gap)
        layer.alpha_composite(draw_gauge(Dg, v, theme, col(v)), (x, 0))
        d.text((x + Dg / 2, Dg * 0.50), f"{int(v)}", font=font(int(34 * sc), "tech"),
               fill=rgba(fg), anchor="mm")
        tracked(d, (x + Dg / 2 - tracked_w(cf, name, 3 * sc) / 2, Dg * 0.74), name, cf,
                rgba(muted), 3 * sc)
    y = Dg + int(8 * sc)
    if bat:
        txt = f"BAT {bat['pct']}%" + ("  CHARGING" if bat["charging"] else "")
        bc = theme["warn"] if bat["pct"] < 20 and not bat["charging"] else theme["ok"]
    else:
        txt, bc = "AC POWER  //  NO BATTERY", muted
    tracked(d, (0, y), txt, cf, rgba(bc), 3 * sc)
    d.text((0, y + int(28 * sc)), f"{now_stamp(ctx)}  //  ONLINE", font=font(int(14 * sc), "tech"),
           fill=rgba(muted))
    return _trim(layer, pw, y + int(54 * sc)), {}


def now_stamp(ctx):
    return ctx["now"].strftime("%H:%M:%S")


def w_sprintmap(style, ctx, theme, sc):
    idx, comp = ctx["day_idx"], ctx["completed"]
    fg, muted, acc = theme["fg"], theme["muted"], theme["accent"]
    stat = {}
    for n in range(1, SPRINT_DAYS + 1):
        if day_done(n, comp):
            stat[n] = "done"
        elif n == idx:
            stat[n] = "today"
        elif n < idx:
            stat[n] = "missed"
        else:
            stat[n] = "future"
    ndone = sum(1 for v in stat.values() if v == "done")
    cf = font(int(13 * sc), "techb")
    if style == "ring":
        D = int(270 * sc)
        ss = 3
        S = D * ss
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        dd = ImageDraw.Draw(img)
        c, R = S / 2, S * 0.40
        dd.ellipse((c - R, c - R, c + R, c + R), outline=rgba(muted, 70), width=ss)
        for n in range(1, SPRINT_DAYS + 1):
            a = math.radians((n - 1) / float(SPRINT_DAYS) * 360 - 90)
            x, y = c + R * math.cos(a), c + R * math.sin(a)
            ms = n in MILESTONES
            r = ss * (9 if ms else 6)
            s_ = stat[n]
            if s_ == "done":
                dd.ellipse((x - r, y - r, x + r, y + r), fill=rgba(theme["ok"]))
            elif s_ == "missed":
                dd.ellipse((x - r, y - r, x + r, y + r), fill=rgba(theme["bad"], 200))
            elif s_ == "today":
                rr = r * 1.6
                dd.ellipse((x - rr, y - rr, x + rr, y + rr), fill=rgba(acc))
            else:
                dd.ellipse((x - r, y - r, x + r, y + r), outline=rgba(muted, 190), width=ss * 2)
            if ms:
                dd.ellipse((x - r * 1.5, y - r * 1.5, x + r * 1.5, y + r * 1.5),
                           outline=rgba(theme["warn"], 230), width=ss)
        layer, d = _layer(D, D)
        layer.alpha_composite(img.resize((D, D), Image.LANCZOS))
        d.text((D / 2, D * 0.46), f"{ndone}/{SPRINT_DAYS}", font=font(int(46 * sc), "tech"),
               fill=rgba(fg), anchor="mm")
        tracked(d, (D / 2 - tracked_w(cf, "DAYS CLEAR", 3 * sc) / 2, D * 0.60), "DAYS CLEAR", cf,
                rgba(muted), 3 * sc)
        t2 = f"DAY {max(1, min(idx, SPRINT_DAYS)):02d}"
        tracked(d, (D / 2 - tracked_w(cf, t2, 4 * sc) / 2, D * 0.69), t2, cf, rgba(acc), 4 * sc)
        return layer, {}
    r = int(31 * sc)
    w = math.sqrt(3) * r
    cols = 6
    head = int(30 * sc)
    pw = int(cols * w + w / 2) + 2
    rows = (SPRINT_DAYS + cols - 1) // cols
    ph = head + int(rows * 1.5 * r + 0.5 * r) + 6
    layer, d = _layer(pw, ph)
    tracked(d, (0, 0), f"SPRINT MAP  //  {ndone}/{SPRINT_DAYS} CLEAR", cf, rgba(acc), 3.4 * sc)
    nf = font(int(14 * sc), "techb")
    for n in range(1, SPRINT_DAYS + 1):
        rr, cc = (n - 1) // cols, (n - 1) % cols
        cx = w / 2 + cc * w + (w / 2 if rr % 2 else 0)
        cy = head + r + rr * 1.5 * r
        pts = hex_pts(cx, cy, r * 0.92)
        s_ = stat[n]
        if s_ == "done":
            d.polygon(pts, fill=rgba(theme["ok"], 205))
            tcol = (20, 18, 18, 255) if theme["fg"][0] > 128 else (255, 255, 255, 255)
        elif s_ == "missed":
            d.polygon(pts, fill=rgba(theme["bad"], 150))
            tcol = rgba(fg)
        elif s_ == "today":
            d.polygon(pts, fill=rgba(acc, 70))
            d.line(pts + [pts[0]], fill=rgba(acc), width=max(2, int(3 * sc)))
            tcol = rgba(fg)
        else:
            d.line(pts + [pts[0]], fill=rgba(muted, 150), width=max(1, int(2 * sc)))
            tcol = rgba(muted)
        if n in MILESTONES:
            d.line(pts + [pts[0]], fill=rgba(theme["warn"]), width=max(2, int(3 * sc)))
        d.text((cx, cy), str(n), font=nf, fill=tcol, anchor="mm")
    return _trim(layer, pw, ph), {}


# ---------------------------------------------------------------- WuWa-style: waveplate + resonance
def w_waveplate(style, ctx, theme, sc):
    fg, muted, acc = theme["fg"], theme["muted"], theme["accent"]
    req = [q for q in ctx["quests"] if not q["bonus"]]
    done = sum(1 for q in req if q["done"])
    total = len(req)
    frac = (done / float(total)) if total else 1.0
    val = int(round(240 * frac))
    col = theme["ok"] if frac >= 1 else acc
    cap = "FULL" if frac >= 1 else f"{total - done} QUEST{'S' if total - done != 1 else ''} TO FULL"
    cf = font(int(13 * sc), "techb")
    if style == "bar":
        pw = int(430 * sc)
        layer, d = _layer(pw, int(96 * sc))
        tracked(d, (0, 0), "WAVEPLATE", cf, rgba(acc), 4.4 * sc)
        d.text((pw, -int(4 * sc)), f"{val}", font=font(int(34 * sc), "tech"), fill=rgba(fg),
               anchor="ra")
        d.text((pw, int(38 * sc)), "/ 240", font=font(int(14 * sc), "tech"), fill=rgba(muted),
               anchor="ra")
        n = 24
        gap = int(4 * sc)
        sw = (pw - gap * (n - 1)) / float(n)
        on = int(round(n * frac))
        for i in range(n):
            x0 = i * (sw + gap)
            top = int(50 * sc) + (int(4 * sc) if i % 2 else 0)
            d.polygon([(x0 + sw * 0.25, top), (x0 + sw, top), (x0 + sw * 0.75, top + int(26 * sc)),
                       (x0, top + int(26 * sc))],
                      fill=rgba(col) if i < on else rgba(muted, 70))
        tracked(d, (0, int(80 * sc)), cap, font(int(11 * sc), "techb"), rgba(muted), 3 * sc)
        return _trim(layer, pw, int(98 * sc)), {}
    D = int(230 * sc)
    ss = 3
    S = D * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dd = ImageDraw.Draw(img)
    c, R = S / 2, S * 0.43
    nseg = 48
    on = int(round(nseg * frac))
    wd = int(S * 0.07)
    for i in range(nseg):
        a0 = i * 360.0 / nseg - 90
        dd.arc((c - R, c - R, c + R, c + R), a0 + 1.2, a0 + 360.0 / nseg - 1.2,
               fill=rgba(col) if i < on else rgba(muted, 70), width=wd)
    r2 = R * 0.70
    dd.ellipse((c - r2, c - r2, c + r2, c + r2), outline=rgba(muted, 120), width=ss * 2)
    for k in range(6):
        a = math.radians(k * 60 - 90)
        x, y = c + r2 * math.cos(a), c + r2 * math.sin(a)
        s_ = ss * 5
        dd.polygon([(x, y - s_), (x + s_, y), (x, y + s_), (x - s_, y)], fill=rgba(acc, 220))
    layer, d = _layer(D, D + int(30 * sc))
    layer.alpha_composite(img.resize((D, D), Image.LANCZOS))
    d.text((D / 2, D * 0.45), f"{val}", font=font(int(58 * sc), "tech"), fill=rgba(fg),
           anchor="mm")
    d.text((D / 2, D * 0.62), "/ 240", font=font(int(17 * sc), "tech"), fill=rgba(muted),
           anchor="mm")
    tracked(d, (D / 2 - tracked_w(cf, "WAVEPLATE", 4.4 * sc) / 2, D + int(6 * sc)), "WAVEPLATE",
            cf, rgba(acc), 4.4 * sc)
    return _trim(layer, D, D + int(26 * sc)), {}


def w_wave(style, ctx, theme, sc):
    fg, muted, acc = theme["fg"], theme["muted"], theme["accent"]
    m = ctx.get("media") or {"has": False}
    aud = ctx.get("audio") or {}
    live_audio = bool(aud.get("active")) and float(aud.get("peak", 0.0)) > 0.005
    smtc_playing = bool(m.get("has")) and m.get("status") == "Playing"
    playing = live_audio or smtc_playing
    t = ctx.get("t", 0.0)
    title = m.get("title") or ""
    seed = (sum(ord(ch) for ch in title) % 17) / 3.0
    peak = float(aud.get("peak", 0.0)) if live_audio else (0.55 if smtc_playing else 0.0)
    bass = float(aud.get("bass", peak)) if live_audio else (0.5 + 0.3 * abs(math.sin(t * 2.6)) if smtc_playing else 0.0)
    mid_b = float(aud.get("mid", peak)) if live_audio else (0.45 + 0.3 * abs(math.cos(t * 3.4)) if smtc_playing else 0.0)
    high_b = float(aud.get("high", peak)) if live_audio else (0.35 + 0.25 * abs(math.sin(t * 5.1)) if smtc_playing else 0.0)
    bars = aud.get("bars") if (live_audio and aud.get("bars")) else None
    hist = aud.get("hist") if (live_audio and aud.get("hist")) else None
    if live_audio:
        telem = f"LIVE {aud.get('db', -12.0):+05.1f} dB  //  {int(min(100, peak * 115)):02d}%"
    elif smtc_playing:
        freq = (110 + (sum(ord(ch) for ch in title) % 880) / 2.0) if title else 432.0
        telem = f"SYNC  {freq:05.1f} Hz"
    else:
        telem = "STANDBY"
    cf = font(int(13 * sc), "techb")
    if style == "ring":
        D = int(270 * sc)
        ss = 3
        S = D * ss
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        dd = ImageDraw.Draw(img)
        c = S / 2
        r0 = S * (0.28 + 0.035 * bass)
        rmax = S * 0.21
        n = 64
        for i in range(n):
            a = math.radians(i * 360.0 / n - 90)
            v = bars[i] if bars else spectrum_val(i, t, playing, seed)
            r1 = r0 + rmax * v
            col_bar = acc if (i % 3 != 0 or v > 0.65) else fg
            dd.line([(c + r0 * math.cos(a), c + r0 * math.sin(a)),
                     (c + r1 * math.cos(a), c + r1 * math.sin(a))],
                    fill=rgba(col_bar, 240), width=max(2, int(S * 0.012)))
        dd.ellipse((c - r0 * 0.92, c - r0 * 0.92, c + r0 * 0.92, c + r0 * 0.92),
                   outline=rgba(acc if playing else muted, 165), width=ss * 2)
        layer, d = _layer(D, D)
        layer.alpha_composite(img.resize((D, D), Image.LANCZOS))
        label = "RESONANCE"
        tracked(d, (D / 2 - tracked_w(cf, label, 4 * sc) / 2, D * 0.42), label, cf, rgba(acc),
                4 * sc)
        d.text((D / 2, D * 0.56), telem.split("//")[0].strip(),
               font=font(int(16 * sc), "tech"), fill=rgba(fg), anchor="mm")
        return layer, {}
    pw, ph = int(450 * sc), int(136 * sc)
    ss = 2
    img = Image.new("RGBA", (pw * ss, ph * ss), (0, 0, 0, 0))
    dd = ImageDraw.Draw(img)
    mid_y = int(86 * sc) * ss
    n_ticks = 48
    for i in range(n_ticks):
        tx = int((i + 0.5) * (pw * ss) / n_ticks)
        bv = bars[min(63, int(i * 64 / n_ticks))] if bars else (spectrum_val(i, t, playing, seed) * 0.6 if playing else 0.04)
        th = int(bv * 34 * sc * ss)
        if th > 2:
            dd.line([(tx, mid_y - th), (tx, mid_y + th)], fill=rgba(acc, 68), width=max(1, ss))
    bands = (bass, mid_b, high_b)
    for j in range(3):
        pts = []
        b_energy = bands[j]
        amp0 = (int((12 + 38 * b_energy) * sc) if playing else int(5 * sc)) * ss
        ph_shift = (aud.get("phase", t * 3.0) if live_audio else t * (2.2 + 0.8 * j)) + j * 1.1
        for x in range(0, pw * ss, 3):
            u = x / float(pw * ss)
            env = math.sin(math.pi * u) ** 1.25
            if hist:
                h_idx = min(63, int(u * 63))
                h_mod = 0.45 + 0.85 * hist[h_idx]
            else:
                h_mod = 0.65 + 0.35 * math.sin(t * (1.3 + 0.4 * j) + u * 9 + seed) if playing else 1.0
            carrier = math.sin(2 * math.pi * (2.5 + j * 1.3) * u + ph_shift)
            harmonic = 0.35 * math.cos(2 * math.pi * (5.0 + j * 2.0) * u - ph_shift * 0.7)
            y = mid_y + amp0 * (1 - 0.22 * j) * h_mod * env * (carrier + harmonic)
            pts.append((x, y))
        dd.line(pts, fill=rgba(acc if j == 0 else fg, 255 - 75 * j),
                width=max(2, int((3 - j) * sc * ss)))
    layer, d = _layer(pw, ph)
    layer.alpha_composite(img.resize((pw, ph), Image.LANCZOS))
    tracked(d, (0, 0), "RESONANCE", cf, rgba(acc), 4.4 * sc)
    d.text((pw, -int(2 * sc)), telem, font=font(int(15 * sc), "tech"), fill=rgba(acc if live_audio else muted),
           anchor="ra")
    return layer, {}


# ---------------------------------------------------------------- quests (interactive)
def w_quests(ctx, theme, sc):
    pw = int(460 * sc)
    layer, d = _layer(pw, int(1100 * sc))
    fg, muted, acc = theme["fg"], theme["muted"], theme["accent"]
    quests = ctx["quests"]
    vmsg = ctx.get("vmsg") or {}
    req = [q for q in quests if not q["bonus"]]
    done_n = sum(1 for q in req if q["done"])
    cf2 = font(int(13 * sc), "sansb")
    hdr = f"QUESTS   {done_n}/{len(req)}"
    tracked(d, (0, int(4 * sc)), hdr, cf2, muted, 3 * sc)
    if any(q["bonus"] for q in quests):
        tracked(d, (tracked_w(cf2, hdr, 3 * sc) + 18 * sc, int(4 * sc)), "+ BONUS", cf2, acc,
                3 * sc)
    hits = {}
    vr = (pw - int(104 * sc), 0, pw, int(26 * sc))
    pill(d, vr, "CHECKING" if ctx.get("verifying") else "VERIFY", theme, sc, filled=True)
    hits["verify"] = vr
    y = int(38 * sc)
    ff, f1, tf2 = font(int(21 * sc), "serif"), font(int(18 * sc), "serif"), font(int(14 * sc), "sans")
    tagf = font(int(12 * sc), "sansb")
    R = int(16 * sc)
    visible = quests[:ctx["max_rows"]]
    qx = R + int(14 * sc)
    for q in visible:
        code = q["kind"] == "code"
        detail = None if q["done"] else vmsg.get(q["key"])
        cy = y + int(5 * sc)
        if q["done"]:
            d.ellipse((0, cy, R, cy + R), fill=tuple(theme["ok"]) + (255,))
        elif q["bonus"]:
            d.ellipse((0, cy, R, cy + R), outline=tuple(acc) + (255,), width=max(2, int(2 * sc)))
            d.ellipse((R * .3, cy + R * .3, R * .7, cy + R * .7), fill=tuple(acc) + (255,))
        else:
            d.ellipse((0, cy, R, cy + R), outline=tuple(muted) + (255,),
                      width=max(2, int(2 * sc)))
        main = q["file"] if code else q["label"]
        mfont = ff if code else f1
        tag = f"D{q['day']}" if (q["day"] != ctx["day_idx"] and not q["bonus"]) else ""
        tag_w = int(tagf.getlength(tag) + 14 * sc) if tag else 0
        text = shorten(mfont, main, pw - qx - tag_w)
        d.text((qx, y), text, font=mfont, fill=muted if q["done"] else fg)
        if q["done"]:
            ym = y + int(mfont.size * 0.62)
            d.line([(qx, ym), (qx + mfont.getlength(text), ym)], fill=tuple(muted) + (255,),
                   width=max(1, int(2 * sc)))
        if tag:
            d.text((pw - tagf.getlength(tag), y + 5 * sc), tag, font=tagf, fill=theme["bad"])
        if code or detail:
            sub = detail if detail else q["label"]
            d.text((qx, y + 27 * sc), shorten(tf2, sub, pw - qx), font=tf2,
                   fill=theme["bad"] if detail else muted)
            rowh = int(48 * sc)
        else:
            rowh = int(31 * sc)
        if q["kind"] == "manual":
            hits["tick:" + q["key"]] = (0, y - int(3 * sc), pw, y + rowh - int(3 * sc))
        y += rowh
    extra = len(quests) - len(visible)
    if extra > 0:
        d.text((qx, y), f"+ {extra} more", font=font(int(15 * sc), "serifi"), fill=muted)
        y += int(26 * sc)
    if not quests:
        d.text((0, y), "No quests today.", font=font(int(20 * sc), "serifi"), fill=muted)
        y += int(30 * sc)
    return _trim(layer, pw, y), hits


# ---------------------------------------------------------------- music + focus
def w_music(style, ctx, theme, sc):
    m = ctx.get("media") or {"has": False}
    fg, muted, acc = theme["fg"], theme["muted"], theme["accent"]
    has = bool(m.get("has"))
    playing = has and m.get("status") == "Playing"
    title = (m.get("title") or "Unknown track") if has else "Nothing playing"
    artist = (m.get("artist") or m.get("app") or "") if has else "Start Spotify, YouTube or any player"
    pos, dur = float(m.get("pos") or 0), float(m.get("dur") or 0)
    ctrl = tuple(fg) + (255,)
    hits = {}
    if style == "bar":
        pw, ph = int(430 * sc), int(78 * sc)
        layer, d = _layer(pw, ph)
        r = int(26 * sc)
        cx, cy = r + 2, int(32 * sc)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=tuple(acc) + (255,))
        ic = (20, 18, 18, 255) if theme["fg"][0] > 128 else (255, 255, 255, 255)
        (icon_pause if playing else icon_play)(d, cx + (0 if playing else 2 * sc), cy, r * 0.42, ic)
        hits["play"] = (cx - r, cy - r, cx + r, cy + r)
        tx = cx + r + int(18 * sc)
        right = int(86 * sc)
        d.text((tx, int(2 * sc)), shorten(font(int(21 * sc), "serif"), title, pw - tx - right),
               font=font(int(21 * sc), "serif"), fill=fg)
        d.text((tx, int(30 * sc)), shorten(font(int(15 * sc), "sans"), artist, pw - tx - right),
               font=font(int(15 * sc), "sans"), fill=muted)
        ib = int(9 * sc)
        px, nx = pw - int(62 * sc), pw - int(18 * sc)
        icon_prev(d, px, cy, ib, ctrl)
        icon_next(d, nx, cy, ib, ctrl)
        hits["prev"] = (px - ib - 8, cy - ib - 8, px + ib + 8, cy + ib + 8)
        hits["next"] = (nx - ib - 8, cy - ib - 8, nx + ib + 8, cy + ib + 8)
        by = int(66 * sc)
        d.rounded_rectangle((tx, by, pw, by + max(3, int(4 * sc))), radius=2,
                            fill=tuple(muted) + (90,))
        if dur > 0:
            d.rounded_rectangle((tx, by, tx + int((pw - tx) * pos / dur), by + max(3, int(4 * sc))),
                                radius=2, fill=tuple(acc) + (255,))
        return _trim(layer, pw, int(76 * sc)), hits

    pw, ph = int(440 * sc), int(152 * sc)
    layer, d = _layer(pw, ph)
    D = int(138 * sc)
    art = None
    if m.get("art"):
        try:
            art = ctx.get("art_img") or Image.open(m["art"])
        except Exception:
            art = None
    angle = (ctx.get("t", 0) * 36) % 360 if playing else 24
    layer.alpha_composite(draw_disc(D, theme, art, angle), (0, int(7 * sc)))
    x0 = D + int(24 * sc)
    tw = pw - x0
    status = "NOW PLAYING" if playing else ("PAUSED" if has else "NO MEDIA SESSION")
    tracked(d, (x0, int(4 * sc)), status, font(int(12 * sc), "sansb"), acc if playing else muted,
            3 * sc)
    d.text((x0, int(24 * sc)), shorten(font(int(25 * sc), "serif"), title, tw),
           font=font(int(25 * sc), "serif"), fill=fg)
    d.text((x0, int(58 * sc)), shorten(font(int(16 * sc), "sans"), artist, tw),
           font=font(int(16 * sc), "sans"), fill=muted)
    by = int(92 * sc)
    bh = max(3, int(4 * sc))
    d.rounded_rectangle((x0, by, pw, by + bh), radius=bh // 2, fill=tuple(muted) + (90,))
    if dur > 0:
        d.rounded_rectangle((x0, by, x0 + max(bh, int(tw * min(1.0, pos / dur))), by + bh),
                            radius=bh // 2, fill=tuple(acc) + (255,))
        tf = font(int(12 * sc), "sansb")
        d.text((x0, by + int(8 * sc)), fmt_ms(pos), font=tf, fill=muted)
        d.text((pw - tf.getlength(fmt_ms(dur)), by + int(8 * sc)), fmt_ms(dur), font=tf,
               fill=muted)
    cy = int(134 * sc)
    r = int(17 * sc)
    px, mx, nx = x0 + int(26 * sc), x0 + int(86 * sc), x0 + int(146 * sc)
    icon_prev(d, px, cy, int(9 * sc), ctrl)
    icon_next(d, nx, cy, int(9 * sc), ctrl)
    d.ellipse((mx - r, cy - r, mx + r, cy + r), fill=tuple(acc) + (255,))
    ic = (20, 18, 18, 255) if theme["fg"][0] > 128 else (255, 255, 255, 255)
    (icon_pause if playing else icon_play)(d, mx + (0 if playing else 2 * sc), cy, int(7 * sc), ic)
    hits["prev"] = (px - 22, cy - 22, px + 22, cy + 22)
    hits["play"] = (mx - r, cy - r, mx + r, cy + r)
    hits["next"] = (nx - 22, cy - 22, nx + 22, cy + 22)
    return _trim(layer, pw, ph), hits


def w_focus(style, ctx, theme, sc):
    fo = ctx.get("focus") or {"mode": "focus", "running": False, "remaining": 1500,
                              "total": 1500, "sessions": 0}
    fg, muted, acc = theme["fg"], theme["muted"], theme["accent"]
    col = acc if fo["mode"] == "focus" else theme["ok"]
    total = max(1, fo["total"])
    frac = 1.0 - fo["remaining"] / float(total)
    timestr = fmt_ms(fo["remaining"])
    label = "FOCUS" if fo["mode"] == "focus" else "BREAK"
    hits = {}
    if style == "bar":
        pw, ph = int(430 * sc), int(70 * sc)
        layer, d = _layer(pw, ph)
        tracked(d, (0, 0), label, font(int(13 * sc), "sansb"), col, 3.4 * sc)
        d.text((0, int(18 * sc)), timestr, font=font(int(36 * sc), "sansl"), fill=fg)
        bx = int(150 * sc)
        by = int(40 * sc)
        bh = max(3, int(4 * sc))
        d.rounded_rectangle((bx, by, pw - int(150 * sc), by + bh), radius=bh // 2,
                            fill=tuple(muted) + (90,))
        d.rounded_rectangle((bx, by, bx + max(bh, int((pw - int(150 * sc) - bx) * frac)),
                             by + bh), radius=bh // 2, fill=tuple(col) + (255,))
        b1 = (pw - int(140 * sc), int(18 * sc), pw - int(70 * sc), int(46 * sc))
        b2 = (pw - int(62 * sc), int(18 * sc), pw, int(46 * sc))
        pill(d, b1, "PAUSE" if fo["running"] else "START", theme, sc, filled=True, color=col)
        pill(d, b2, "SKIP", theme, sc, color=muted)
        hits["toggle"], hits["skip"] = b1, b2
        return _trim(layer, pw, ph), hits
    D = int(190 * sc)
    pw = int(270 * sc)
    layer, d = _layer(pw, D + int(110 * sc))
    ss = 3
    S = D * ss
    ring = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    c, R, wd = S / 2, S * 0.44, max(4, int(S * 0.04))
    rd.arc((c - R, c - R, c + R, c + R), 0, 360, fill=tuple(muted) + (90,), width=wd)
    if frac > 0.002:
        rd.arc((c - R, c - R, c + R, c + R), -90, -90 + 360 * min(frac, 1.0),
               fill=tuple(col) + (255,), width=wd)
    layer.alpha_composite(ring.resize((D, D), Image.LANCZOS), (int((pw - D) / 2), 0))
    cxm = pw / 2
    tracked(d, (cxm - tracked_w(font(int(13 * sc), "sansb"), label, 3.4 * sc) / 2, D * 0.27),
            label, font(int(13 * sc), "sansb"), col, 3.4 * sc)
    d.text((cxm, D * 0.48), timestr, font=font(int(44 * sc), "sansl"), fill=fg, anchor="mm")
    n = fo["sessions"]
    dots = min(n, 8)
    if dots:
        dx0 = cxm - (dots - 1) * 7 * sc
        for i in range(dots):
            r = 3.2 * sc
            d.ellipse((dx0 + i * 14 * sc - r, D * 0.68 - r, dx0 + i * 14 * sc + r,
                       D * 0.68 + r), fill=tuple(col) + (255,))
    y = D + int(16 * sc)
    bw, bhh = int(78 * sc), int(32 * sc)
    gap = int(8 * sc)
    x = (pw - (3 * bw + 2 * gap)) / 2
    r1 = (x, y, x + bw, y + bhh)
    r2 = (x + bw + gap, y, x + 2 * bw + gap, y + bhh)
    r3 = (x + 2 * (bw + gap), y, x + 3 * bw + 2 * gap, y + bhh)
    pill(d, r1, "PAUSE" if fo["running"] else "START", theme, sc, filled=True, color=col)
    pill(d, r2, "RESET", theme, sc, color=muted)
    pill(d, r3, "SKIP", theme, sc, color=muted)
    hits["toggle"], hits["reset"], hits["skip"] = r1, r2, r3
    return _trim(layer, pw, y + bhh + int(4 * sc)), hits


def draw_widget(wid, style, ctx, theme, sc):
    if wid == "clock":
        return w_clock(style, ctx, theme, sc)
    if wid == "sprint":
        return w_sprint(ctx, theme, sc)
    if wid == "status":
        return w_status(ctx, theme, sc)
    if wid == "quests":
        return w_quests(ctx, theme, sc)
    if wid == "music":
        return w_music(style, ctx, theme, sc)
    if wid == "focus":
        return w_focus(style, ctx, theme, sc)
    if wid == "calendar":
        return w_calendar(style, ctx, theme, sc)
    if wid == "moon":
        return w_moon(style, ctx, theme, sc)
    if wid == "sysmon":
        return w_sysmon(style, ctx, theme, sc)
    if wid == "sprintmap":
        return w_sprintmap(style, ctx, theme, sc)
    if wid == "waveplate":
        return w_waveplate(style, ctx, theme, sc)
    return w_wave(style, ctx, theme, sc)


# ---------------------------------------------------------------- tiles + placement
def dashed_rect(d, box, color, width, dash, gap):
    x0, y0, x1, y1 = box
    for (ax, ay, bx, by) in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1),
                             (x0, y1, x0, y0)):
        length = math.hypot(bx - ax, by - ay)
        n = max(1, int(length // (dash + gap)))
        for i in range(n + 1):
            t0 = i * (dash + gap) / length
            t1 = min(1.0, (i * (dash + gap) + dash) / length)
            if t0 >= 1:
                break
            d.line([(ax + (bx - ax) * t0, ay + (by - ay) * t0),
                    (ax + (bx - ax) * t1, ay + (by - ay) * t1)], fill=color, width=width)


@lru_cache(maxsize=64)
def _cached_mist_backdrop(w, h, inset, rad, blur_r, fog_rgb, fog_a):
    fm = Image.new("L", (w, h), 0)
    ImageDraw.Draw(fm).rounded_rectangle((inset, inset, w - inset, h - inset),
                                         radius=rad, fill=255)
    fm = fm.filter(ImageFilter.GaussianBlur(max(1, blur_r)))
    fm = fm.point(lambda v: int(v * fog_a))
    base = Image.new("RGBA", (w, h), tuple(fog_rgb) + (0,))
    base.putalpha(fm)
    return base


def widget_tile(content, theme, sc, label="", edit=False):
    """Cached mist backdrop + half-res fast glyph glow + content as one RGBA tile."""
    cw, ch = content.size
    f = int(70 * sc)
    M = int(2.2 * f)
    w, h = cw + 2 * M, ch + 2 * M
    inset = M - int(f * 0.55)
    layer = _cached_mist_backdrop(
        w, h, inset, int(f * 0.9), int(f * 0.6), tuple(theme["fog"]), round(theme["fog_a"], 3)
    ).copy()
    alpha = content.split()[3]
    hw, hh = max(1, cw // 2), max(1, ch // 2)
    ga = alpha.resize((hw, hh), Image.BILINEAR).filter(
        ImageFilter.GaussianBlur(max(1, int(3.5 * sc)))
    ).resize((cw, ch), Image.BILINEAR)
    ga = ga.point(lambda v: min(255, int(v * 2.9)))
    glow = Image.new("RGBA", content.size, tuple(theme["fog"]) + (0,))
    glow.putalpha(ga)
    layer.alpha_composite(glow, (M, M))
    layer.alpha_composite(content, (M, M))
    if edit:
        ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        pad = int(10 * sc)
        box = (M - pad, M - pad, M + cw + pad, M + ch + pad)
        od.rounded_rectangle(box, radius=int(10 * sc), fill=tuple(theme["accent"]) + (34,))
        layer.alpha_composite(ov)
        d = ImageDraw.Draw(layer)
        dashed_rect(d, box, tuple(theme["accent"]) + (255,), max(2, int(2 * sc)),
                    int(12 * sc), int(7 * sc))
        lf = font(int(13 * sc), "sansb")
        text = label.upper()
        tw = tracked_w(lf, text, 2.6 * sc)
        tag = (box[0], box[1] - int(26 * sc), box[0] + tw + int(24 * sc), box[1])
        d.rounded_rectangle(tag, radius=int(8 * sc), fill=tuple(theme["accent"]) + (255,))
        tracked(d, (tag[0] + int(12 * sc), tag[1] + int(5 * sc)), text, lf,
                (20, 18, 18, 255) if theme["fg"][0] > 128 else (255, 255, 255, 255), 2.6 * sc)
    return layer, M


def region_stats(gray, W, H, x, y, w, h):
    gw, gh = gray.size
    sx, sy = gw / float(W), gh / float(H)
    box = (int(max(0, x) * sx), int(max(0, y) * sy), int(min(W, x + w) * sx),
           int(min(H, y + h) * sy))
    if box[2] - box[0] < 1 or box[3] - box[1] < 1:
        return 0.0, 100.0
    st = ImageStat.Stat(gray.crop(box))
    return st.stddev[0], st.mean[0]


SIDE_ORDER = ("music", "focus", "waveplate", "wave", "sysmon", "calendar", "moon", "sprintmap")


def auto_place(sizes, gray, W, H, s):
    """Main widgets stack in the calmer column; the rest fill the opposite side from the
    bottom up, wrapping into further columns."""
    m, tb, gap = int(60 * s), int(70 * s), int(16 * s)
    main = [w for w in ("clock", "sprint", "status", "quests") if w in sizes]
    side = [w for w in SIDE_ORDER if w in sizes]
    colw = max([sizes[w][0] for w in main] or [int(460 * s)])
    xl, xr = m + int(110 * s), W - colw - m - int(20 * s)
    sl = region_stats(gray, W, H, xl, m, colw, int(H * 0.8))[0]
    sr = region_stats(gray, W, H, xr, m, colw, int(H * 0.8))[0]
    right = sr <= sl + 2
    pos = {}
    x = xr if right else xl
    step = -(colw + gap) if right else (colw + gap)
    y = m
    for w in main:
        cw, ch = sizes[w]
        if y + ch > H - tb // 2 and y > m:
            x += step
            y = m
        pos[w] = (x, y)
        y += ch + gap
    sidew = max([sizes[w][0] for w in side] or [0])
    sx = (m + int(110 * s)) if right else (W - sidew - m - int(20 * s))
    sstep = (sidew + gap) if right else -(sidew + gap)
    y = H - tb - m // 2
    for w in side:
        cw, ch = sizes[w]
        if y - ch < m and y < H - tb - m // 2:
            sx += sstep
            y = H - tb - m // 2
        y -= ch
        pos[w] = (sx, y)
        y -= gap
    return pos


def build_ctx(state, cfg, now, quests, day_info, level, remaining_sec, info, message, live,
              extra=None):
    rank, frac, _ = rank_info(state["xp"])
    comp = set(state["completed"])
    idx = day_index(now.date())
    try:
        deadline_dt = parse_deadline(cfg["deadline"], now.date())
    except Exception:
        deadline_dt = None
    no_text = ("No plan loaded. Click 'Import plan'." if SPRINT_DAYS == 0 else
               f"Plan starts {START_DATE:%d %B}" if idx < 1 else "Plan complete. Well fought.")
    ctx = {
        "now": now, "level": level, "remaining_sec": remaining_sec,
        "deadline_str": cfg["deadline"], "deadline_dt": deadline_dt,
        "clock_24h": cfg["clock_24h"], "day_idx": idx, "day_info": day_info,
        "completed": comp, "no_sprint_text": no_text, "max_rows": 8, "live": live,
        "quests": [{**q, "done": q["key"] in comp} for q in quests],
        "rank": rank, "rank_frac": frac, "xp": state["xp"], "streak": state["streak"],
        "message": message, "mood": info["mood"], "t": time.time(),
        "media": {"has": False}, "audio": {"active": False, "peak": 0.0}, "focus": None, "art_img": None, "vmsg": {},
        "verifying": False,
        "sys": {"cpu": 0.0, "ram": 0.0, "disk": 0.0, "bat": None},
    }
    if extra:
        ctx.update(extra)
    return ctx


_TILE_CACHE = {}


def _widget_state_key(wid, wcfg, ctx, dark, info, level, sc, edit):
    """Deterministic cache key so static widgets consume 0% CPU when unchanged."""
    now = ctx["now"]
    base = (wid, wcfg["style"], round(sc, 3), dark, tuple(info["accent"]), info["muted"],
            level, edit)
    if wid == "clock":
        t_key = (now.hour, now.minute, now.second if ctx.get("live") else 0, ctx["clock_24h"])
        return base + t_key
    if wid in ("calendar", "moon"):
        return base + (now.year, now.month, now.day, now.hour)
    if wid in ("sprint", "sprintmap"):
        return base + (ctx["day_idx"], tuple(sorted(ctx["completed"])))
    if wid == "status":
        return base + (int(ctx["remaining_sec"] // 60), ctx["xp"], ctx["streak"], ctx["message"])
    if wid == "quests":
        q_key = tuple((q["key"], q["done"], (ctx.get("vmsg") or {}).get(q["key"]))
                      for q in ctx["quests"])
        return base + (q_key, bool(ctx.get("verifying")))
    if wid == "waveplate":
        done_n = sum(1 for q in ctx["quests"] if not q["bonus"] and q["done"])
        return base + (done_n, len(ctx["quests"]))
    if wid == "sysmon":
        st = ctx.get("sys") or {}
        bat = st.get("bat") or {}
        return base + (int(st.get("cpu", 0)), int(st.get("ram", 0)),
                       int(st.get("disk", 0)), bat.get("pct"), bat.get("charging"),
                       now.second // 2)
    if wid == "music":
        m = ctx.get("media") or {}
        playing = bool(m.get("has")) and m.get("status") == "Playing"
        t_step = int(ctx.get("t", 0.0)) if playing else 0
        return base + (m.get("has"), m.get("title"), m.get("artist"), m.get("status"),
                       int(m.get("pos") or 0) if playing else 0, int(m.get("dur") or 0), t_step)
    if wid == "wave":
        m = ctx.get("media") or {}
        aud = ctx.get("audio") or {}
        live_aud = bool(aud.get("active")) and float(aud.get("peak", 0.0)) > 0.005
        playing = live_aud or (bool(m.get("has")) and m.get("status") == "Playing")
        t_step = round(float(ctx.get("t", 0.0)), 2) if live_aud else (int(ctx.get("t", 0.0)) if playing else 0)
        return base + (live_aud, aud.get("peak", 0.0), aud.get("phase", 0.0),
                       m.get("status"), m.get("title"), t_step)
    if wid == "focus":
        fo = ctx.get("focus") or {}
        return base + (fo.get("mode"), fo.get("running"), int(fo.get("remaining") or 0),
                       fo.get("sessions"))
    return base + (int(ctx.get("t", 0.0)),)


def build_tiles(widgets, ctx, size, gray, info, level, s, dark_flags, edit=False, skip=()):
    """Draw enabled widgets using per-widget dirty-state caching."""
    W, H = size
    drawn = {}
    for wid in WIDGET_ORDER:
        w = widgets[wid]
        if not w["enabled"] or wid in skip:
            continue
        sc = s * float(w["scale"])
        dark = dark_flags.get(wid, info["lum"] < 0.45)
        key = _widget_state_key(wid, w, ctx, dark, info, level, sc, edit)
        cached = _TILE_CACHE.get(wid)
        if cached and cached["key"] == key:
            drawn[wid] = [cached["content"], cached["hits"], dark, sc, key, cached["tile"],
                          cached["M"], False]
        else:
            content, hits = draw_widget(wid, w["style"], ctx, make_theme(dark, info, level), sc)
            drawn[wid] = [content, hits, dark, sc, key, None, None, True]
    pos, autos = {}, {}
    need = [wid for wid in drawn if widgets[wid].get("fx") is None]
    if need:
        auto = auto_place({wid: drawn[wid][0].size for wid in need}, gray, W, H, s)
        for wid in need:
            pos[wid] = auto[wid]
            autos[wid] = (auto[wid][0] / float(W), auto[wid][1] / float(H))
    for wid in drawn:
        if widgets[wid].get("fx") is not None:
            pos[wid] = (int(round(widgets[wid]["fx"] * W)), int(round(widgets[wid]["fy"] * H)))
    flags = dict(dark_flags)
    tiles = []
    for wid, (content, hits, dark, sc, key, c_tile, c_M, dirty) in drawn.items():
        x, y = pos[wid]
        cw, ch = content.size
        nd = region_stats(gray, W, H, x, y, cw, ch)[1] < 150
        if nd != dark:
            dark = nd
            key = _widget_state_key(wid, widgets[wid], ctx, dark, info, level, sc, edit)
            content, hits = draw_widget(wid, widgets[wid]["style"], ctx,
                                        make_theme(dark, info, level), sc)
            c_tile = None
            dirty = True
        flags[wid] = dark
        if c_tile is None:
            theme = make_theme(dark, info, level)
            c_tile, c_M = widget_tile(content, theme, sc, WIDGET_NAMES[wid], edit)
            _TILE_CACHE[wid] = {"key": key, "content": content, "hits": hits,
                                "tile": c_tile, "M": c_M}
        tx, ty = x - c_M, y - c_M
        last_xy = _TILE_CACHE[wid].get("xy")
        if last_xy != (tx, ty):
            dirty = True
            _TILE_CACHE[wid]["xy"] = (tx, ty)
        tiles.append({"wid": wid, "tile": c_tile, "x": tx, "y": ty, "M": c_M, "dirty": dirty,
                      "hits": [(n, (r[0] + c_M, r[1] + c_M, r[2] + c_M, r[3] + c_M))
                               for n, r in hits.items()]})
    return tiles, autos, flags


# ==================================================================================
# CUSTOM WIDGETS  -  pictures / animated GIF / WebP / APNG you downloaded from the internet
# ==================================================================================
CUSTOM_LIMIT = 12
CUSTOM_MAX_BYTES = 30 * 1024 * 1024
CUSTOM_MAX_PIXELS = 36_000_000
CUSTOM_FRAME_BUDGET = 16_000_000          # total pixels kept in memory for one animation
CUSTOM_FORMATS = {"PNG": ".png", "GIF": ".gif", "WEBP": ".webp", "JPEG": ".jpg", "BMP": ".bmp"}
CUSTOM_FILE_TYPES = "*.png *.gif *.webp *.jpg *.jpeg *.bmp *.zip"
CUSTOM_BOX = 360                          # px at 1080p a new widget is fitted into
CUSTOM_PAD = 40                           # transparent margin (room for the edit frame)
_ASSET_CACHE = collections.OrderedDict()
_ASSET_LOCK = threading.Lock()


def prepare_custom_bytes(data):
    """Validate bytes from a file or a download. Returns (image_bytes, extension)."""
    if data[:2] == b"PK":                                   # a zip: take the biggest image in it
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise ValueError("That zip file is damaged.")
        best = None
        for zi in zf.infolist():
            if (not zi.is_dir() and zi.file_size <= CUSTOM_MAX_BYTES
                    and os.path.splitext(zi.filename)[1].lower() in
                    (".png", ".gif", ".webp", ".jpg", ".jpeg", ".bmp")):
                if best is None or zi.file_size > best.file_size:
                    best = zi
        if best is None:
            raise ValueError("No PNG / GIF / WebP / JPG image was found inside that zip.")
        data = zf.read(best)
    head = data[:64].lstrip().lower()
    if head[:1] == b"<":
        raise ValueError("That is a web page or SVG, not an image file. On the web page, "
                         "right-click the picture and choose 'Copy image address', then paste "
                         "that link. HTML / Rainmeter widgets are not supported.")
    try:
        im = Image.open(io.BytesIO(data))
        fmt, (w, h) = im.format, im.size
        im.load()
    except Exception:
        raise ValueError("Could not read that as an image (PNG, GIF, WebP, JPG or BMP).")
    if fmt not in CUSTOM_FORMATS:
        raise ValueError(f"{fmt or 'That'} images are not supported. Use PNG, GIF, WebP, JPG or BMP.")
    if w * h > CUSTOM_MAX_PIXELS:
        raise ValueError("That image is too large (more than about 36 megapixels).")
    return data, CUSTOM_FORMATS[fmt]


def download_custom(url, timeout=25):
    """Download a widget image over http(s). Returns raw bytes (validated by the caller)."""
    p = urllib.parse.urlparse(url.strip())
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("Paste the full link, starting with https://")
    req = urllib.request.Request(url.strip(), headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ShadowSystemHUD/2.1",
        "Accept": "image/*,application/zip,*/*;q=0.5"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(CUSTOM_MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise ValueError(f"The server answered {e.code} {e.reason}. Some sites block downloads from "
                         f"programs: save the file in your browser and use 'From file' instead.")
    except urllib.error.URLError as e:
        raise ValueError(f"Could not reach that address ({e.reason}).")
    except Exception as e:
        raise ValueError(f"Download failed: {e}")
    if len(data) > CUSTOM_MAX_BYTES:
        raise ValueError("That file is larger than 30 MB.")
    return data


def name_from_url(url):
    base = os.path.splitext(os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(url).path)))[0]
    return (base or "Custom widget")[:24]


class CustomAsset:
    """Decoded frames of one widget image (kept in memory once, shared by every size)."""

    def __init__(self, frames, durs):
        self.frames, self.durs = frames, durs
        self.size = frames[0].size
        acc, cum = 0.0, []
        for d in durs:
            acc += d
            cum.append(acc)
        self.cum, self.total = cum, (acc or 1.0)


def load_custom_asset(path):
    key = (path, os.path.getmtime(path))
    with _ASSET_LOCK:
        hit = _ASSET_CACHE.get(key)
        if hit is not None:
            _ASSET_CACHE.move_to_end(key)
            return hit
    im = Image.open(path)
    w, h = im.size
    if w * h > CUSTOM_MAX_PIXELS:
        raise ValueError("image too large")
    n = max(1, int(getattr(im, "n_frames", 1)))
    k = min(1.0, (2400 if n == 1 else 640) / float(max(w, h)))
    tw, th = max(1, int(round(w * k))), max(1, int(round(h * k)))
    step = 1
    if n > 1:
        step = int(math.ceil(n / float(max(2, min(240, CUSTOM_FRAME_BUDGET // (tw * th))))))
    frames, durs = [], []
    for i, fr in enumerate(ImageSequence.Iterator(im)):
        d = fr.info.get("duration") or 100
        d = (d if d >= 20 else 100) / 1000.0
        if i % step == 0:
            rgba = fr.convert("RGBA")
            if rgba.size != (tw, th):
                rgba = rgba.resize((tw, th), Image.LANCZOS)
            frames.append(rgba)
            durs.append(d)
        else:
            durs[-1] += d
    im.close()
    if not frames:
        raise ValueError("empty image")
    asset = CustomAsset(frames, durs)
    with _ASSET_LOCK:
        _ASSET_CACHE[key] = asset
        while len(_ASSET_CACHE) > 6:
            _ASSET_CACHE.popitem(last=False)
    return asset


def drop_custom_asset(path):
    with _ASSET_LOCK:
        for k in [k for k in _ASSET_CACHE if k[0] == path]:
            _ASSET_CACHE.pop(k, None)


def custom_geometry(asset, scale, sH):
    """(factor, width, height) a custom widget is drawn at. scale 1.0 = fitted into a 360 px box."""
    w0, h0 = asset.size
    base = min(sH, CUSTOM_BOX * sH / float(max(w0, h0)))
    f = max(0.01, base * float(scale))
    return f, max(1, int(w0 * f)), max(1, int(h0 * f))


def _scaled_frame(fr, tw, th, f, opacity):
    im = fr if fr.size == (tw, th) else fr.resize((tw, th), Image.LANCZOS if f < 1 else Image.BICUBIC)
    if opacity < 100:
        im = im.copy()
        im.putalpha(im.getchannel("A").point(lambda v, o=int(opacity): v * o // 100))
    return im


def paste_alpha(base, tile, x, y):
    """alpha-composite `tile` onto `base` at (x, y), clipped, in place (no full-size layers)."""
    W, H = base.size
    tw, th = tile.size
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + tw), min(H, y + th)
    if x1 <= x0 or y1 <= y0:
        return
    if (x0, y0, x1, y1) != (x, y, x + tw, y + th):
        tile = tile.crop((x0 - x, y0 - y, x1 - x, y1 - y))
    base.alpha_composite(tile, (x0, y0))


def custom_edit_overlay(canvas, M, tw, th, label, accent, sc):
    pad = int(10 * sc)
    box = (M - pad, M - pad, M + tw + pad, M + th + pad)
    ov = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(ov).rounded_rectangle(box, radius=int(10 * sc), fill=tuple(accent) + (34,))
    canvas.alpha_composite(ov)
    d = ImageDraw.Draw(canvas)
    dashed_rect(d, box, tuple(accent) + (255,), max(2, int(2 * sc)), int(12 * sc), int(7 * sc))
    lf = font(int(13 * sc), "sansb")
    text = label.upper()
    tag = (box[0], box[1] - int(26 * sc), box[0] + tracked_w(lf, text, 2.6 * sc) + int(24 * sc), box[1])
    d.rounded_rectangle(tag, radius=int(8 * sc), fill=tuple(accent) + (255,))
    tracked(d, (tag[0] + int(12 * sc), tag[1] + int(5 * sc)), text, lf, (20, 18, 18, 255), 2.6 * sc)


def build_custom_frames(path, scale, opacity, sH, edit, label, accent):
    """Everything a live custom widget needs, as premultiplied BGRA bytes ready for the window."""
    asset = load_custom_asset(path)
    f, tw, th = custom_geometry(asset, scale, sH)
    M = int(CUSTOM_PAD * sH)
    cw, ch = tw + 2 * M, th + 2 * M
    if edit:
        lf = font(int(13 * sH), "sansb")
        cw = max(cw, (M - int(10 * sH)) + int(tracked_w(lf, label.upper(), 2.6 * sH)) + int(34 * sH))
    src = asset.frames[:1] if edit else asset.frames
    durs = asset.durs[:1] if edit else asset.durs
    out = []
    for fr in src:
        canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        canvas.paste(_scaled_frame(fr, tw, th, f, opacity), (M, M))
        if edit:
            custom_edit_overlay(canvas, M, tw, th, label, accent, sH)
        out.append(premultiplied_bgra(canvas))
    cum, acc = [], 0.0
    for d in durs:
        acc += d
        cum.append(acc)
    return {"frames": out, "cum": cum, "total": acc or 1.0, "size": (cw, ch), "M": M}


def bake_custom(out_rgba, cfg, size):
    """Baked mode: stamp the first frame of every enabled custom widget into the wallpaper."""
    W, H = size
    sH = H / 1080.0
    for c in cfg.get("custom_widgets") or []:
        if not c.get("enabled"):
            continue
        try:
            asset = load_custom_asset(os.path.join(CUSTOM_DIR, c.get("file", "")))
            f, tw, th = custom_geometry(asset, c.get("scale", 1.0), sH)
            im = _scaled_frame(asset.frames[0], tw, th, f, int(c.get("opacity", 100)))
            paste_alpha(out_rgba, im, int(float(c.get("fx", 0.4)) * W), int(float(c.get("fy", 0.3)) * H))
        except Exception:
            continue


def merge_custom(saved):
    """Clean up the saved custom-widget list (drops broken entries, fills defaults)."""
    out = []
    for i, c in enumerate(saved if isinstance(saved, list) else []):
        if not isinstance(c, dict) or not c.get("id") or not c.get("file"):
            continue
        d = {"id": str(c["id"]), "name": str(c.get("name") or "Custom widget")[:24],
             "file": os.path.basename(str(c["file"])), "enabled": bool(c.get("enabled", True)),
             "scale": min(8.0, max(0.1, float(c.get("scale") or 1.0))),
             "opacity": int(min(100, max(10, int(c.get("opacity") or 100)))),
             "fx": c.get("fx") if c.get("fx") is not None else round(0.38 + 0.03 * (i % 6), 3),
             "fy": c.get("fy") if c.get("fy") is not None else round(0.28 + 0.04 * (i % 6), 3),
             "src": str(c.get("src") or "")[:200]}
        out.append(d)
    return out[:CUSTOM_LIMIT]


def composite_tiles(base_rgba, tiles):
    """Blend tiles onto base_rgba in place (clipped paste, no full-screen layer per tile)."""
    for t in tiles:
        paste_alpha(base_rgba, t["tile"], t["x"], t["y"])
    return base_rgba


_BAKED_FLAGS = {}        # per-widget dark/light choice, kept between renders so the tile cache can hit
_RENDER_CACHE = {}


def render_frame(bg_path, state, cfg, now, size, quests, day_info, level, remaining_sec):
    """BAKED mode: wallpaper in -> wallpaper with static widgets out (no music/focus)."""
    W, H = size
    raw, note = load_background(bg_path, now, size)
    ce = _RENDER_CACHE
    if (ce.get("raw") is raw and ce.get("size") == size and ce.get("level") == level):
        info, bg, gray = ce["info"], ce["bg"], ce["gray"]          # same picture as last minute
    else:
        orig = ImageOps.fit(raw, size, Image.LANCZOS)
        info = analyze_bg(orig)
        bg = apply_effect(orig, level)
        gray = bg.convert("L").resize((max(1, W // 4), max(1, H // 4)))
        ce.clear()
        ce.update(raw=raw, size=size, level=level, info=info, bg=bg, gray=gray)
    message = pick_message(level, info, cfg, bg_path, now)
    ctx = build_ctx(state, cfg, now, quests, day_info, level, remaining_sec, info, message,
                    live=False)
    tiles, autos, flags = build_tiles(cfg["widgets"], ctx, size, gray, info, level,
                                      H / 1080.0, _BAKED_FLAGS, False, skip=("music", "focus"))
    _BAKED_FLAGS.update(flags)
    out = composite_tiles(bg.convert("RGBA"), tiles)
    bake_custom(out, cfg, size)
    out = out.convert("RGB")
    info = {**info, "panel_dark": flags.get("status", True), "accent_ui": ui_accent(info)}
    return out, info, message, note, autos


def ui_accent(info):
    return (224, 78, 64) if info["muted"] else fit_accent(info["accent"], True)


def vignette(img, color, strength):
    mask = Image.radial_gradient("L").resize(img.size, Image.BICUBIC)
    k = strength * 255 / 155.0
    mask = mask.point(lambda v: int(min(255, max(0, v - 100) * k)))
    return Image.composite(Image.new("RGB", img.size, color), img, mask)


def apply_effect(img, level):
    if level == "CLEARED":
        return img.copy()
    sat = {"ACTIVE": 0.90, "URGENT": 0.80, "OVERDUE": 0.65}[level]
    strength = {"ACTIVE": 0.30, "URGENT": 0.42, "OVERDUE": 0.55}[level]
    color = {"ACTIVE": (28, 16, 14), "URGENT": (62, 24, 14), "OVERDUE": (112, 10, 16)}[level]
    return vignette(ImageEnhance.Color(img).enhance(sat), color, strength)


LEVEL_HEX = {"URGENT": "#e8b04a", "OVERDUE": "#e65a50", "CLEARED": "#6cc48e"}
XP_FOCUS = 10


class App:
    BG, PANEL, FG, MUTED = "#14110f", "#1f1a17", "#efe7d8", "#9a9086"

    def __init__(self, root, allow_exit=False):
        self.root, self.allow_exit = root, allow_exit
        self.cfg = load_json(CONFIG_PATH, DEFAULT_CONFIG)
        self.cfg["widgets"] = merge_widgets(self.cfg.get("widgets"))
        self.cfg["custom_widgets"] = merge_custom(self.cfg.get("custom_widgets"))
        self.state = roll_state(load_json(STATE_PATH, DEFAULT_STATE), dt.date.today())
        save_json(STATE_PATH, self.state)
        save_json(CONFIG_PATH, self.cfg)
        self.size = screen_size()
        self.q = queue.Queue()
        self.rendering = self.verifying = False
        self.windows = {}
        self.cwin = {}                  # live custom-widget windows, by 'custom:<id>'
        self._custom_delay = 300
        self._custom_errs = set()
        self._persist_job = None
        self.ws_scanning = False
        self._ui_cache = {}
        self._bar_key = None
        self.layout_win = None
        self.custom_frame = None
        self.overlay_failed = False
        self.overlay_busy = False
        self.edit_mode = False
        self.tile_meta = {}
        self.dark_flags = {}
        self.analyzing = False
        self.analysis = fallback_analysis(self.size)
        self.analysis_key = None
        self.art_cache = {"path": None, "mtime": None, "img": None}
        self.verify_msgs = {}
        self.shot_fail_ts = 0.0
        self.sys_prev = None
        self.sys_stats = {"cpu": 0.0, "ram": 0.0, "disk": 0.0, "bat": None}
        self.media = MediaMonitor(os.path.join(APP_DIR, "art.jpg")) if IS_WIN else None
        self.audio = AudioMonitor()
        if self.cfg["widgets"]["wave"]["enabled"]:
            self.audio.start()
        rebuild_sprint(self.cfg)
        if not self.state.get("plan_fed"):          # progress made on the removed built-in plan
            own = self.cfg.get("custom_plan_file") and os.path.isfile(self.cfg["custom_plan_file"])
            if not own:
                self.state["completed"], self.state["awarded"] = [], []
            self.state["plan_fed"] = True
            save_json(STATE_PATH, self.state)
        self.last_overlay = 0.0
        self.last_key = None
        self.last_scan = 0.0
        self.last_ws_scan = 0.0
        self.ws_sig = None
        self.lively_flag = False
        self.scanned = False
        self.hide_today = False
        self.last_err = ""
        self.level = "ACTIVE"
        self.accent = "#d9483b"
        today = dt.date.today().isoformat()
        fs = self.state.get("focus") or {}
        self.focus = {"mode": "focus", "running": False, "end": 0.0, "remaining": 0,
                      "total": 0, "sessions": fs.get("count", 0) if fs.get("date") == today else 0}
        self.focus_reset("focus")
        self.reload_quests()
        self.build_ui()
        self.build_quests()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.log(f"Engine: {self.cfg.get('engine') or 'not set'}  |  overlay mode: "
                 f"{self.cfg['overlay_mode']}  |  layer: {self.cfg['overlay_layer']}")
        self.log("Widgets button: pick clock presets, music player, focus timer, sizes. "
                 "Edit layout: drag widgets, mouse wheel resizes.")
        self.capture_original_wallpaper()
        self.tick()
        self.custom_tick()
        if SPRINT_DAYS == 0 and not self.cfg.get("plan_prompted"):
            self.root.after(900, self._first_plan_prompt)

    # ---- data ------------------------------------------------------------------
    def reload_quests(self):
        self.quests, self.day_info = quests_for(dt.date.today(), set(self.state["completed"]))

    def done(self, q):
        return q["key"] in self.state["completed"]

    def engine_lively(self):
        return self.cfg.get("engine") == "lively" or self.lively_flag

    def use_live(self):
        if not IS_WIN or self.overlay_failed:
            return False
        if self.cfg.get("no_wallpaper"):      # nothing to bake into: float over the user's desktop
            return True
        m = self.cfg.get("overlay_mode", "auto")
        if m == "live":
            return True
        if m == "baked":
            return False
        return (self.engine_lively()
                or os.path.splitext(self.cfg["wallpaper"])[1].lower() in ANIMATED_EXT)

    def wcfg(self, wid):
        return self.cfg["widgets"][wid]

    def all_windows(self):
        return list(self.windows.values()) + [st["win"] for st in self.cwin.values()]

    def _set(self, w, **kw):
        """Configure a Tk widget only when a value really changed (saves redraws every tick)."""
        c = self._ui_cache.setdefault(id(w), {})
        ch = {k: v for k, v in kw.items() if c.get(k) != v}
        if ch:
            c.update(ch)
            w.config(**ch)

    # ---- UI --------------------------------------------------------------------
    def build_ui(self):
        r = self.root
        r.title("SHADOW SYSTEM")
        r.configure(bg=self.BG)
        sc = r.winfo_fpixels("1i") / 96.0
        self.sc = sc
        W = int(560 * sc)
        H = min(int(700 * sc), self.size[1] - int(80 * sc))
        r.geometry(f"{W}x{H}+{max(0, self.size[0] - W - 16)}+8")
        r.deiconify()
        r.lift()
        r.attributes("-topmost", True)
        r.focus_force()
        r.after(1500, lambda: r.attributes("-topmost", False))
        head = tk.Frame(r, bg=self.BG)
        head.pack(fill="x", padx=18, pady=(10, 0))
        self.title_lbl = tk.Label(head, text="S H A D O W   S Y S T E M", bg=self.BG,
                                  fg=self.accent, font=("Segoe UI Semibold", 10))
        self.title_lbl.pack(side="left")
        self.badge = tk.Label(head, text="PENALTY MODE", bg=self.BG, fg=self.accent,
                              font=("Segoe UI Semibold", 9))
        self.badge.pack(side="right")
        self.verify_btn = tk.Button(r, text="VERIFY QUESTS", command=self.run_verify,
                                    bg=self.accent, fg="#14110f", relief="flat",
                                    font=("Segoe UI Semibold", 13))
        self.verify_btn.pack(fill="x", padx=18, pady=(8, 4), ipady=5)
        mk = lambda **kw: tk.Label(r, bg=self.BG, **kw)
        self.day_lbl = mk(fg=self.accent, font=("Segoe UI Semibold", 9))
        self.day_lbl.pack()
        self.dtitle_lbl = mk(fg=self.FG, font=("Georgia", 12, "italic"),
                             wraplength=int(450 * sc))
        self.dtitle_lbl.pack()
        self.prog_lbl = mk(fg=self.FG, font=("Georgia", 11))
        self.prog_lbl.pack(pady=(4, 2))
        self.bar = tk.Canvas(r, width=int(460 * sc), height=int(7 * sc), bg=self.PANEL,
                             highlightthickness=0)
        self.bar.pack()
        self.time_lbl = mk(fg=self.MUTED, font=("Segoe UI", 9))
        self.time_lbl.pack(pady=(2, 0))
        self.qframe = tk.Frame(r, bg=self.BG)
        self.qframe.pack(fill="x", padx=int(18 * sc), pady=4)
        self.msg_lbl = mk(fg=self.accent, font=("Georgia", 11, "italic"),
                          wraplength=int(450 * sc), justify="left")
        self.msg_lbl.pack(padx=18, anchor="w")
        self.tone_lbl = mk(fg=self.MUTED, font=("Segoe UI", 8), wraplength=int(450 * sc),
                           justify="left")
        self.tone_lbl.pack(anchor="w", padx=18)
        bf = tk.Frame(r, bg=self.BG)
        bf.pack(pady=4, padx=18, fill="x")
        self.edit_btn = None
        btns = [("Set wallpaper", self.choose_wallpaper),
                ("Remove wallpaper", self.remove_wallpaper),
                ("Add custom widget", self.add_custom_menu), ("Widgets...", self.open_layout),
                ("Edit layout", self.toggle_edit), ("Import plan", self.open_plan_import),
                ("Edit plan", self.open_custom_plan),
                ("Workspace", self.choose_workspace), ("Deadline", self.set_deadline),
                ("Custom text", self.custom_text), ("Test sound", self.test_audio_sync),
                ("Locate GCC", self.locate_compiler), ("Overlay mode", self.cycle_mode),
                ("Overlay layer", self.cycle_layer), ("Locate Lively", self.locate_lively),
                ("Open hub", self.open_hub), ("Install app", lambda: open_installer_gui(self.root)),
                ("Remove overlay", self.restore)]
        for i, (t, c) in enumerate(btns):
            b = tk.Button(bf, text=t, command=c, bg=self.PANEL, fg=self.FG, relief="flat",
                          activebackground="#2b2420", activeforeground=self.FG,
                          font=("Segoe UI", 9))
            b.grid(row=i // 4, column=i % 4, sticky="ew", padx=3, pady=1)
            if t == "Edit layout":
                self.edit_btn = b
            if t == "Add custom widget":
                self.custom_btn = b
        bf.columnconfigure((0, 1, 2, 3), weight=1)
        # one always-visible status strip (the old 4-line log was squeezed to ~5 px on 1080p);
        # click it to read the full history
        self.log_lines = collections.deque(maxlen=400)
        self.log_win = None
        self.log_box = tk.Label(r, text="", bg=self.PANEL, fg=self.MUTED, anchor="nw", justify="left",
                                font=("Consolas", 9), wraplength=int(520 * sc), height=2,
                                cursor="hand2")
        self.log_box.pack(fill="x", padx=18, pady=(4, 8))
        self.log_box.bind("<Button-1>", lambda e: self.open_log())

    def log(self, text):
        line = f"[{dt.datetime.now():%H:%M:%S}] {text}"
        self.log_lines.append(line)
        self.log_box.config(text=line)
        win = self.log_win
        try:
            if win is not None and win.winfo_exists():
                box = win.winfo_children()[0]
                box.config(state="normal")
                box.insert("end", line + "\n")
                box.see("end")
                box.config(state="disabled")
        except Exception:
            pass

    def open_log(self):
        try:
            if self.log_win is not None and self.log_win.winfo_exists():
                self.log_win.lift()
                return
        except Exception:
            pass
        top = tk.Toplevel(self.root)
        self.log_win = top
        top.title("Shadow System log")
        top.configure(bg=self.BG)
        top.geometry(f"{int(640 * self.sc)}x{int(360 * self.sc)}+{int(80 * self.sc)}+{int(80 * self.sc)}")
        box = tk.Text(top, bg=self.PANEL, fg=self.FG, relief="flat", font=("Consolas", 9), wrap="word")
        box.pack(fill="both", expand=True, padx=8, pady=8)
        box.insert("end", "\n".join(self.log_lines) + "\n")
        box.see("end")
        box.config(state="disabled")

    def build_quests(self):
        for w in self.qframe.winfo_children():
            w.destroy()
        self.qwidgets = {}
        self.qvars = {}
        self._ui_cache = {}
        for qu in self.quests:
            if qu["kind"] == "manual":
                var = tk.BooleanVar(value=self.done(qu))
                w = tk.Checkbutton(self.qframe, variable=var, bg=self.BG, anchor="w",
                                   activebackground=self.BG, selectcolor=self.PANEL,
                                   fg=self.FG, activeforeground=self.FG,
                                   font=("Georgia", 10), justify="left", pady=0,
                                   command=lambda q=qu, v=var: self.toggle_manual(q, v))
                self.qvars[qu["key"]] = var
            else:
                w = tk.Label(self.qframe, bg=self.BG, anchor="w", justify="left",
                             font=("Georgia", 10))
            w.pack(fill="x", pady=0)
            self.qwidgets[qu["key"]] = w

    def update_quests(self):
        today_idx = day_index(dt.date.today())
        for qu in self.quests:
            w = self.qwidgets.get(qu["key"])
            if not w:
                continue
            done = self.done(qu)
            carry = f"  [D{qu['day']}]" if qu["day"] != today_idx and not qu["bonus"] else ""
            bonus = "  +bonus" if qu["bonus"] else ""
            dot = "\u25cf" if done else "\u25cb"
            if qu["kind"] == "code":
                text = f"{dot}  {qu['file']}  \u2014 {qu['label']}{carry}"
            elif qu["kind"] == "check":
                text = f"{dot}  {qu['label']}{carry}{bonus}"
            else:
                text = f" {qu['label']}{carry}"
            if qu["kind"] == "manual":
                if self.qvars[qu["key"]].get() != done:
                    self.qvars[qu["key"]].set(done)
                self._set(w, text=text, fg=self.MUTED if done else self.FG)
            else:
                self._set(w, text=text, fg="#6cc48e" if done else self.FG)

    # ---- actions ---------------------------------------------------------------
    def persist(self):
        if self._persist_job is not None:
            try:
                self.root.after_cancel(self._persist_job)
            except Exception:
                pass
            self._persist_job = None
        save_json(STATE_PATH, self.state)
        save_json(CONFIG_PATH, self.cfg)

    def persist_soon(self, ms=600):
        """Debounced save for sliders / dragging (one disk write instead of dozens)."""
        if self._persist_job is None:
            self._persist_job = self.root.after(ms, self.persist)

    def poke(self):
        """Redraw the HUD now (live widgets or baked wallpaper)."""
        if self.use_live():
            self.last_overlay = 0.0
        else:
            self.refresh_wallpaper(True)

    def choose_wallpaper(self):
        p = filedialog.askopenfilename(
            title="Choose wallpaper (image, GIF or video)",
            filetypes=[("Images / GIF / video / HTML",
                        "*.jpg *.jpeg *.png *.bmp *.webp *.gif *.mp4 *.mkv *.webm *.mov "
                        "*.avi *.html"), ("All files", "*.*")])
        if not p:
            return
        ext = os.path.splitext(p)[1].lower()
        self.capture_original_wallpaper(force=True)
        self.cfg["wallpaper"] = p
        self.cfg["no_wallpaper"] = False
        self.analysis_key = None
        if ext in ANIMATED_EXT:
            self.cfg["engine"] = "lively"
            self.log(f"Setting {os.path.basename(p)} through Lively...")
            threading.Thread(target=self._lively_set_worker, args=(p,), daemon=True).start()
        else:
            self.cfg["engine"] = "windows"
            if self.use_live():
                set_wallpaper(p)
            self.log(f"Wallpaper: {os.path.basename(p)}")
        self.persist()
        self.poke()

    def _lively_set_worker(self, p):
        exe = find_lively(self.cfg.get("lively_exe", ""))
        if not exe:
            self.q.put(("need_lively", p))
            return
        ok, msg = lively_set(exe, p)
        self.q.put(("lively_set", ok, msg, exe))

    def locate_lively(self, then_set=None):
        p = filedialog.askopenfilename(
            title="Find Lively.exe (usually C:\\Program Files\\Lively Wallpaper)",
            filetypes=[("Lively", "*.exe"), ("All files", "*.*")])
        if not p:
            return
        self.cfg["lively_exe"] = p
        self.persist()
        self.log(f"Lively set to: {p}")
        self.analysis_key = None
        if isinstance(then_set, str):
            threading.Thread(target=self._lively_set_worker, args=(then_set,),
                             daemon=True).start()

    def ensure_video_support(self):
        if have_cv2():
            return
        if messagebox.askyesno("Video support",
                               "To read frames from a video file the HUD needs 'opencv-python'.\n"
                               "Install it now? (about 1 minute)"):
            self.log("Installing opencv-python...")
            threading.Thread(target=lambda: self.q.put(("cv2", *install_opencv())),
                             daemon=True).start()

    def choose_workspace(self):
        p = filedialog.askdirectory(title="Folder where your .c files live (VS Code workspace)")
        if p:
            self.cfg["workspace"] = p
            self.persist()
            c_files = list_workspace_c_files(p)
            self.log(f"Workspace set: {p} ({len(c_files)} .c files found). Verifying now...")
            self.run_verify()

    def locate_compiler(self):
        p = filedialog.askopenfilename(
            title="Find gcc.exe or clang.exe (e.g. C:\\msys64\\mingw64\\bin\\gcc.exe)",
            filetypes=[("Compiler", "*.exe"), ("All files", "*.*")])
        if p and os.path.isfile(p):
            self.cfg["compiler_exe"] = p
            self.persist()
            self.log(f"Compiler set to: {p}")
            self.run_verify()

    def test_audio_sync(self):
        if not self.cfg["widgets"]["wave"]["enabled"]:
            self.cfg["widgets"]["wave"]["enabled"] = True
            self.persist()
        self.audio.trigger_test(6.0)
        snap = self.audio.snapshot()
        self.log(f"Resonance Wave enabled & synced! Audio engine: {snap['backend']} "
                 f"(play any music/video or watch the 6s test pulse on desktop).")
        self.poke()

    def open_custom_plan(self):
        if getattr(self, "plan_win", None) is not None:
            try:
                if self.plan_win.winfo_exists():
                    self.plan_win.destroy()          # always reopen on the plan that is active now
            except Exception:
                pass
        top = tk.Toplevel(self.root)
        self.plan_win = top
        top.title("Custom Plan Studio")
        top.configure(bg=self.BG)
        W_p = int(680 * self.sc)
        H_p = min(int(640 * self.sc), self.size[1] - int(80 * self.sc))
        top.geometry(f"{W_p}x{H_p}+{int(80 * self.sc)}+30")

        plan_data = export_plan_dict()

        hdr = tk.Frame(top, bg=self.BG)
        hdr.pack(fill="x", padx=16, pady=(10, 4))
        tk.Label(hdr, text="CUSTOM PLAN STUDIO", bg=self.BG, fg=self.accent,
                 font=("Segoe UI Semibold", 11)).pack(side="left")
        tk.Label(hdr, text=f"({len(plan_data['days'])} days active)", bg=self.BG, fg=self.MUTED,
                 font=("Segoe UI", 9)).pack(side="left", padx=8)

        r1 = tk.Frame(top, bg=self.BG)
        r1.pack(fill="x", padx=16, pady=4)
        tk.Label(r1, text="Start Date (YYYY-MM-DD):", bg=self.BG, fg=self.FG,
                 font=("Segoe UI", 9)).pack(side="left")
        start_var = tk.StringVar(value=plan_data["start_date"])
        tk.Entry(r1, textvariable=start_var, width=12, bg=self.PANEL, fg=self.FG,
                 insertbackground=self.FG, relief="flat", font=("Consolas", 10)).pack(side="left", padx=6)

        def set_start_today():
            start_var.set(dt.date.today().isoformat())

        tk.Button(r1, text="Start Today (Day 1)", command=set_start_today, bg=self.PANEL,
                  fg=self.accent, relief="flat", font=("Segoe UI", 8)).pack(side="left", padx=4)

        tk.Label(r1, text="   Edit Day:", bg=self.BG, fg=self.FG,
                 font=("Segoe UI", 9)).pack(side="left", padx=(10, 4))
        cur_idx = max(1, min(day_index(dt.date.today()), len(plan_data["days"])))
        day_var = tk.StringVar(value=str(cur_idx))
        day_spin = tk.Spinbox(r1, from_=1, to=max(99, len(plan_data["days"])), textvariable=day_var,
                              width=5, bg=self.PANEL, fg=self.FG, buttonbackground=self.PANEL,
                              relief="flat", font=("Consolas", 10))
        day_spin.pack(side="left")

        r2 = tk.Frame(top, bg=self.BG)
        r2.pack(fill="x", padx=16, pady=4)
        tk.Label(r2, text="Day Title:", bg=self.BG, fg=self.FG,
                 font=("Segoe UI", 9)).pack(side="left")
        title_var = tk.StringVar(value="")
        tk.Entry(r2, textvariable=title_var, bg=self.PANEL, fg=self.FG,
                 insertbackground=self.FG, relief="flat", font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True, padx=6)

        help_txt = (
            "One quest per line. Formats:\n"
            "  code: filename.c | Task description | input1 => expected1 ; input2 => expected2 | must: regex\n"
            "  manual: Watch lecture, solve quiz, or complete lab\n"
            "  check: git_commit | Commit today's code to git | bonus"
        )
        tk.Label(top, text=help_txt, bg=self.BG, fg=self.MUTED, justify="left", anchor="w",
                 font=("Consolas", 8)).pack(fill="x", padx=16, pady=(2, 4))

        q_box = tk.Text(top, height=13, bg=self.PANEL, fg=self.FG, insertbackground=self.FG,
                        relief="flat", font=("Consolas", 9), wrap="none")
        q_box.pack(fill="both", expand=True, padx=16, pady=4)

        loaded_day = [cur_idx]

        def store_current_buffer():
            d_no = loaded_day[0]
            lines = [ln.strip() for ln in q_box.get("1.0", "end").splitlines() if ln.strip() and not ln.strip().startswith("#")]
            found = False
            for d_obj in plan_data["days"]:
                if int(d_obj["day"]) == d_no:
                    d_obj["title"] = title_var.get().strip() or f"Day {d_no}"
                    d_obj["quests"] = lines
                    found = True
                    break
            if not found:
                plan_data["days"].append({
                    "day": d_no,
                    "title": title_var.get().strip() or f"Day {d_no}",
                    "phase": 1,
                    "quests": lines,
                })
                plan_data["days"].sort(key=lambda x: int(x["day"]))

        def load_day_into_ui(*_):
            try:
                d_no = int(day_var.get())
            except ValueError:
                return
            if d_no != loaded_day[0]:
                store_current_buffer()
                loaded_day[0] = d_no
            target = next((d for d in plan_data["days"] if int(d["day"]) == d_no), None)
            title_var.set(target["title"] if target else f"Day {d_no}: Custom Tasks")
            q_box.delete("1.0", "end")
            if target and target.get("quests"):
                q_box.insert("1.0", "\n".join(target["quests"]) + "\n")
            else:
                q_box.insert("1.0", "# one task per line, e.g.:\n# manual: Watch the lecture\n"
                                    "# code: task1.c | Write the program | 5 => 120\n")

        day_spin.config(command=load_day_into_ui)
        day_var.trace_add("write", lambda *_: load_day_into_ui())
        load_day_into_ui()

        def save_and_apply():
            store_current_buffer()
            plan_data["start_date"] = start_var.get().strip() or dt.date.today().isoformat()
            save_json(CUSTOM_PLAN_PATH, plan_data)
            self.cfg["custom_plan_file"] = CUSTOM_PLAN_PATH
            self.persist()
            rebuild_sprint(self.cfg)
            self.reload_quests()
            self.build_quests()
            self.poke()
            self.log(f"Custom plan saved ({len(SPRINT)} days, start {START_DATE}) -> {CUSTOM_PLAN_PATH}")

        def open_in_external_editor():
            save_and_apply()
            try:
                os.startfile(CUSTOM_PLAN_PATH) if IS_WIN else subprocess.Popen(["xdg-open", CUSTOM_PLAN_PATH])
            except Exception as e:
                self.log(f"Saved {CUSTOM_PLAN_PATH} (open it in VS Code): {e}")

        def load_json_file():
            p = filedialog.askopenfilename(
                title="Select a custom_plan.json file",
                filetypes=[("JSON plan", "*.json"), ("All files", "*.*")],
                parent=top
            )
            if not p:
                return
            self.cfg["custom_plan_file"] = p
            self.persist()
            rebuild_sprint(self.cfg)
            self.reload_quests()
            self.build_quests()
            self.poke()
            self.log(f"Loaded custom plan from {p} ({len(SPRINT)} days)")
            top.destroy()

        def reset_default_plan():
            if not messagebox.askyesno("Clear plan", "Remove the current plan? (XP and streak are kept; "
                                                     "task progress is cleared.)", parent=top):
                return
            self.clear_plan()
            top.destroy()

        bar = tk.Frame(top, bg=self.BG)
        bar.pack(fill="x", padx=16, pady=(6, 12))
        for text, cmd, col in (
            ("Save & Apply Plan", save_and_apply, self.accent),
            ("Edit JSON in VS Code", open_in_external_editor, self.PANEL),
            ("Import plan...", lambda: (top.destroy(), self.open_plan_import()), self.PANEL),
            ("Clear plan", reset_default_plan, self.PANEL),
            ("Close", top.destroy, self.PANEL),
        ):
            fg_c = "#14110f" if col == self.accent else self.FG
            tk.Button(bar, text=text, command=cmd, bg=col, fg=fg_c, relief="flat",
                      font=("Segoe UI Semibold" if col == self.accent else "Segoe UI", 9),
                      padx=8).pack(side="left", padx=3, ipady=3)

    def open_hub(self):
        p = self.cfg.get("hub_file", "")
        if not p or not os.path.isfile(p):
            p = filedialog.askopenfilename(title="Pick november_c_mastery_certificate_hub.html",
                                           filetypes=[("HTML", "*.html"), ("All files", "*.*")])
            if not p:
                return
            self.cfg["hub_file"] = p
            self.persist()
        try:
            os.startfile(p) if IS_WIN else subprocess.Popen(["xdg-open", p])
        except Exception as e:
            self.log(f"Could not open hub: {e}")

    def set_deadline(self):
        v = simpledialog.askstring("Daily deadline", "Finish quests by (HH:MM, 24h):",
                                   initialvalue=self.cfg["deadline"], parent=self.root)
        if not v:
            return
        try:
            parse_deadline(v, dt.date.today())
        except Exception:
            messagebox.showerror("Invalid", "Use HH:MM, e.g. 21:30")
            return
        self.cfg["deadline"] = v.strip()
        self.persist()
        self.poke()

    def custom_text(self):
        wp = self.cfg["wallpaper"]
        cur = " | ".join(self.cfg["custom_messages"].get(wp, []))
        v = simpledialog.askstring(
            "Custom warning text for THIS wallpaper",
            "Your own reminder lines, separated by |  (empty = built-in tone lines):",
            initialvalue=cur, parent=self.root)
        if v is None:
            return
        lines = [m.strip() for m in v.split("|") if m.strip()]
        if lines:
            self.cfg["custom_messages"][wp] = lines
        else:
            self.cfg["custom_messages"].pop(wp, None)
        self.persist()
        self.poke()

    def cycle_mode(self):
        order = ["auto", "live", "baked"]
        cur = self.cfg.get("overlay_mode", "auto")
        self.cfg["overlay_mode"] = order[(order.index(cur) + 1) % 3]
        self.overlay_failed = False
        self.persist()
        self.log({"auto": "Overlay mode: auto (live over Lively/video, baked into plain images)",
                  "live": "Overlay mode: live (floating widgets, works over any wallpaper)",
                  "baked": "Overlay mode: baked (drawn into the Windows wallpaper image; "
                           "hidden by Lively; no music/focus widgets)"}[self.cfg["overlay_mode"]])
        self.last_key = None
        self.poke()

    def cycle_layer(self):
        order = ["normal", "desktop", "top"]
        cur = self.cfg.get("overlay_layer", "normal")
        self.cfg["overlay_layer"] = order[(order.index(cur) + 1) % 3]
        self.persist()
        for win in self.all_windows():
            win.layer = self.cfg["overlay_layer"]
            win.apply_layer()
        self.log({"normal": "Layer: normal (like a window; click another app to cover it)",
                  "desktop": "Layer: desktop (pinned under all apps, over the wallpaper)",
                  "top": "Layer: top (always above every app)"}[self.cfg["overlay_layer"]])

    def restore(self):
        if self.level != "CLEARED":
            messagebox.showinfo("Locked", "The overlay stays until today's quests are cleared.")
            return
        if self.use_live() and self.windows:
            self.hide_today = True
            self.apply_hidden()
            self.log("Widgets hidden. They return with the next penalty.")
            return
        wp = self.cfg["wallpaper"]
        if wp and os.path.splitext(wp)[1].lower() not in ANIMATED_EXT:
            set_wallpaper(wp)
            self.log("Overlay removed (original wallpaper restored).")
        else:
            self.log("Pick your wallpaper again to remove the overlay.")

    def apply_hidden(self):
        vis = self.edit_mode or not (self.hide_today and self.level == "CLEARED")
        for win in self.all_windows():
            win.set_visible(vis)

    def set_manual(self, q, value):
        key = q["key"]
        if value:
            if key not in self.state["completed"]:
                self.state["completed"].append(key)
                gain = self.award(q)
                self.log(f"Checked: {q['label']}  (+{gain} xp)")
        elif key in self.state["completed"]:
            self.state["completed"].remove(key)
        self.persist()
        self.after_progress()

    def toggle_manual(self, q, var):
        self.set_manual(q, bool(var.get()))

    def after_progress(self):
        if self.is_cleared() and self.level != "CLEARED":
            messagebox.showinfo("QUESTS CLEARED", "Everything required is done. Penalty lifted.")
        self.poke()

    # ---- widget manager ----------------------------------------------------------
    def toggle_edit(self):
        if not self.use_live():
            messagebox.showinfo("Edit layout",
                                "Dragging needs the live overlay (Overlay mode = auto/live "
                                "with Lively or a video wallpaper).")
            return
        self.edit_mode = not self.edit_mode
        if self.edit_btn:
            self.edit_btn.config(text="Done editing" if self.edit_mode else "Edit layout",
                                 fg=self.accent if self.edit_mode else self.FG)
        self.apply_hidden()
        self.log("EDIT: drag any widget; mouse wheel over it resizes. Click 'Done editing' to lock."
                 if self.edit_mode else "Layout locked and saved.")
        self.last_overlay = 0.0

    def set_widget(self, wid, **kw):
        self.cfg["widgets"][wid].update(kw)
        self.persist_soon()
        self.poke()
        if wid == "music" and kw.get("enabled") and self.media:
            self.media.start()
        if wid == "wave" and kw.get("enabled"):
            self.audio.start()

    def open_layout(self):
        if self.layout_win is not None:
            try:
                if self.layout_win.winfo_exists():
                    self.layout_win.lift()
                    return
            except Exception:
                pass
        sc = self.sc
        top = tk.Toplevel(self.root)
        self.layout_win = top
        top.title("Widgets")
        top.configure(bg=self.BG)
        top.geometry(f"{int(720 * sc)}x{min(int(700 * sc), self.size[1] - int(90 * sc))}"
                     f"+{int(60 * sc)}+30")
        tk.Label(top, text="WIDGETS", bg=self.BG, fg=self.accent,
                 font=("Segoe UI Semibold", 11)).pack(pady=(10, 0))
        tk.Label(top, text="Tick to show, pick a preset, set the size. Drag them with "
                           "'Edit layout'.", bg=self.BG, fg=self.MUTED,
                 font=("Segoe UI", 9)).pack(pady=(0, 6))
        # buttons are packed first (bottom) so they can never be pushed off a small screen
        bar = tk.Frame(top, bg=self.BG)
        bar.pack(side="bottom", pady=8)
        for text, cmd in (("Edit layout (drag)", self.toggle_edit),
                          ("Auto-place all", self.auto_place_all),
                          ("Close", top.destroy)):
            tk.Button(bar, text=text, command=cmd, bg=self.PANEL, fg=self.FG, relief="flat",
                      font=("Segoe UI", 9), padx=10).pack(side="left", padx=5, ipady=3)
        body = tk.Frame(top, bg=self.BG)
        body.pack(fill="both", expand=True)
        cv = tk.Canvas(body, bg=self.BG, highlightthickness=0)
        sb = tk.Scrollbar(body, orient="vertical", command=cv.yview)
        inner = tk.Frame(cv, bg=self.BG)
        wid_ = cv.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfigure(wid_, width=e.width))
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        top.bind("<MouseWheel>", lambda e: cv.yview_scroll(int(-e.delta / 120), "units"))
        for wid in WIDGET_ORDER:
            w = self.cfg["widgets"][wid]
            row = tk.Frame(inner, bg=self.BG)
            row.pack(fill="x", padx=16, pady=1)
            var = tk.BooleanVar(value=w["enabled"])
            tk.Checkbutton(row, text=WIDGET_NAMES[wid], variable=var, width=18, anchor="w",
                           bg=self.BG, fg=self.FG, selectcolor=self.PANEL,
                           activebackground=self.BG, activeforeground=self.FG,
                           font=("Segoe UI", 10),
                           command=lambda wid=wid, v=var: self.set_widget(wid, enabled=v.get())
                           ).pack(side="left")
            if wid in STYLE_CHOICES:
                sv = tk.StringVar(value=w["style"])
                om = tk.OptionMenu(row, sv, *STYLE_CHOICES[wid],
                                   command=lambda val, wid=wid: self.set_widget(wid, style=val))
                om.config(bg=self.PANEL, fg=self.FG, activebackground="#2b2420",
                          activeforeground=self.FG, relief="flat", highlightthickness=0, width=9,
                          font=("Segoe UI", 9))
                om["menu"].config(bg=self.PANEL, fg=self.FG)
                om.pack(side="left", padx=6)
            else:
                tk.Label(row, text="", width=11, bg=self.BG).pack(side="left", padx=6)
            sl = tk.Scale(row, from_=50, to=200, orient="horizontal", length=int(150 * sc),
                          bg=self.BG, fg=self.FG, troughcolor=self.PANEL, highlightthickness=0,
                          showvalue=True, font=("Segoe UI", 8))
            sl.set(int(w["scale"] * 100))             # set first, then attach the callback
            sl.config(command=lambda val, wid=wid: self.set_widget(wid, scale=int(val) / 100.0))
            sl.pack(side="left", padx=6)
            tk.Button(row, text="Reset position", bg=self.PANEL, fg=self.FG, relief="flat",
                      font=("Segoe UI", 8),
                      command=lambda wid=wid: self.set_widget(wid, fx=None, fy=None)
                      ).pack(side="left", padx=4)
        # ---- custom widgets (pictures / GIFs from the internet) ----
        tk.Frame(inner, bg=self.PANEL, height=2).pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(inner, text="CUSTOM WIDGETS", bg=self.BG, fg=self.accent,
                 font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=16)
        tk.Label(inner, text="Pictures or animated GIF / WebP you downloaded: use a file or paste a "
                             "link. They float like the built-in widgets (live overlay).",
                 bg=self.BG, fg=self.MUTED, font=("Segoe UI", 9), wraplength=int(660 * sc),
                 justify="left").pack(anchor="w", padx=16, pady=(0, 4))
        ab = tk.Frame(inner, bg=self.BG)
        ab.pack(anchor="w", padx=16, pady=2)
        for text, cmd in (("+ From file...", self.add_custom_file), ("+ From link...", self.add_custom_url)):
            tk.Button(ab, text=text, command=cmd, bg=self.PANEL, fg=self.FG, relief="flat",
                      font=("Segoe UI", 9), padx=10).pack(side="left", padx=(0, 6), ipady=2)
        self.custom_frame = tk.Frame(inner, bg=self.BG)
        self.custom_frame.pack(fill="x", padx=16, pady=(4, 10))
        self.refresh_custom_rows()

    def refresh_custom_rows(self):
        cf = self.custom_frame
        try:
            if cf is None or not cf.winfo_exists():
                return
        except Exception:
            return
        for ch in cf.winfo_children():
            ch.destroy()
        sc = self.sc
        items = self.cfg.get("custom_widgets") or []
        if not items:
            tk.Label(cf, text="None yet.", bg=self.BG, fg=self.MUTED,
                     font=("Segoe UI", 9)).pack(anchor="w")
            return
        for c in items:
            row = tk.Frame(cf, bg=self.BG)
            row.pack(fill="x", pady=1)
            var = tk.BooleanVar(value=c["enabled"])
            tk.Checkbutton(row, text=c["name"], variable=var, width=16, anchor="w",
                           bg=self.BG, fg=self.FG, selectcolor=self.PANEL,
                           activebackground=self.BG, activeforeground=self.FG,
                           font=("Segoe UI", 10),
                           command=lambda cid=c["id"], v=var: self.set_custom(cid, enabled=v.get())
                           ).pack(side="left")
            for label, lo, hi, val, key, conv in (
                    ("size", 10, 600, int(c["scale"] * 100), "scale", lambda v: int(v) / 100.0),
                    ("opacity", 10, 100, int(c["opacity"]), "opacity", int)):
                tk.Label(row, text=label, bg=self.BG, fg=self.MUTED,
                         font=("Segoe UI", 8)).pack(side="left", padx=(6, 0))
                sl = tk.Scale(row, from_=lo, to=hi, orient="horizontal", length=int(100 * sc),
                              bg=self.BG, fg=self.FG, troughcolor=self.PANEL, highlightthickness=0,
                              showvalue=True, font=("Segoe UI", 8))
                sl.set(val)
                sl.config(command=lambda v, cid=c["id"], key=key, conv=conv:
                          self.set_custom(cid, **{key: conv(v)}))
                sl.pack(side="left", padx=2)
            tk.Button(row, text="Centre", bg=self.PANEL, fg=self.FG, relief="flat", font=("Segoe UI", 8),
                      command=lambda cid=c["id"]: self.centre_custom(cid)).pack(side="left", padx=3)
            tk.Button(row, text="Remove", bg=self.PANEL, fg="#e65a50", relief="flat",
                      font=("Segoe UI", 8),
                      command=lambda cid=c["id"]: self.remove_custom(cid)).pack(side="left", padx=3)

    def auto_place_all(self):
        for wid in WIDGET_ORDER:
            self.cfg["widgets"][wid]["fx"] = None
            self.cfg["widgets"][wid]["fy"] = None
        for i, c in enumerate(self.cfg.get("custom_widgets") or []):
            c["fx"], c["fy"] = round(0.38 + 0.03 * (i % 6), 3), round(0.28 + 0.04 * (i % 6), 3)
        self.persist()
        self.poke()
        self.log("Positions reset; widgets will be auto-placed on the calmest side.")

    def apply_autos(self, autos):
        if not autos:
            return
        for wid, (fx, fy) in autos.items():
            w = self.cfg["widgets"][wid]
            if w.get("fx") is None:
                w["fx"], w["fy"] = fx, fy
        self.persist()

    # ---- remove wallpaper ---------------------------------------------------------
    def capture_original_wallpaper(self, force=False):
        """Remember the user's own desktop wallpaper before the HUD ever replaces it."""
        if not IS_WIN:
            return
        old = self.cfg.get("orig_wallpaper")
        if old and os.path.isfile(old):
            return
        if not force and self.cfg.get("wallpaper"):
            return                          # the HUD already changed it in an earlier session
        cur = get_system_wallpaper(max_age=0)
        if cur and os.path.isfile(cur) and not in_app_dir(cur):
            self.cfg["orig_wallpaper"] = cur
            save_json(CONFIG_PATH, self.cfg)

    def remove_wallpaper(self):
        if not self.cfg.get("wallpaper") and not self.cfg.get("engine"):
            self.log("No wallpaper is set in the HUD.")
            if not self.cfg.get("no_wallpaper"):
                self.cfg["no_wallpaper"] = True
                self.persist()
                self.analysis_key = None
                self.poke()
            return
        if self.level != "CLEARED" and not self.use_live():
            messagebox.showinfo("Locked", "In baked mode the wallpaper IS the penalty, so it stays "
                                          "until today's quests are cleared.\n\nSwitch 'Overlay mode' "
                                          "to live to float the widgets over your own desktop instead.")
            return
        orig = self.cfg.get("orig_wallpaper") or ""
        has_orig = bool(orig) and os.path.isfile(orig)
        lively = self.cfg.get("engine") == "lively"
        msg = ("Remove the HUD wallpaper?\n\n"
               "\u2022 The HUD forgets its wallpaper and stops drawing on it.\n"
               "\u2022 " + ("Windows goes back to your original wallpaper.\n" if has_orig else
                            "Windows is set to a plain desktop colour (your original wallpaper was "
                            "never recorded; pick one in Settings > Personalization).\n") +
               "\u2022 Your widgets keep floating over the desktop.")
        if not messagebox.askyesno("Remove wallpaper", msg):
            return
        close_lively = False
        if lively:
            close_lively = messagebox.askyesno("Lively Wallpaper",
                                               "Also close the animated wallpaper running in Lively?")
        self.cfg.update(wallpaper="", engine="", no_wallpaper=True)
        self.analysis_key = None
        self.last_key = None
        self.persist()
        if IS_WIN:
            set_wallpaper(orig if has_orig else "")
            _SYSW["ts"] = 0.0
        for n in (0, 1):
            try:
                os.remove(os.path.join(APP_DIR, f"wall_{n}.bmp"))
            except OSError:
                pass
        if close_lively:
            exe = find_lively(self.cfg.get("lively_exe", ""))
            if exe:
                def _close():
                    try:
                        r = subprocess.run([exe, "closewp", "--monitor", "-1"], capture_output=True,
                                           text=True, errors="replace", timeout=20,
                                           creationflags=NO_WINDOW)
                        self.q.put(("lively_closed", r.returncode == 0,
                                    (r.stderr or r.stdout or "").strip()[:160]))
                    except Exception as e:
                        self.q.put(("lively_closed", False, str(e)))
                threading.Thread(target=_close, daemon=True).start()
            else:
                self.log("Lively.exe not found; close the wallpaper from the Lively window.")
        self.log("Wallpaper removed. Widgets now float over your own desktop"
                 + (" (original wallpaper restored)." if has_orig else "."))
        self.poke()

    # ---- custom widgets -----------------------------------------------------------
    def custom_conf(self, cid):
        for c in self.cfg.get("custom_widgets") or []:
            if c["id"] == cid:
                return c
        return None

    def set_custom(self, cid, **kw):
        c = self.custom_conf(cid)
        if c:
            c.update(kw)
            self.persist_soon()
            if not self.use_live():
                self.poke()

    def add_custom_menu(self):
        m = tk.Menu(self.root, tearoff=0, bg=self.PANEL, fg=self.FG, activebackground="#2b2420",
                    activeforeground=self.FG, font=("Segoe UI", 9))
        m.add_command(label="From a file on this PC...", command=self.add_custom_file)
        m.add_command(label="From a link (URL)...", command=self.add_custom_url)
        b = getattr(self, "custom_btn", None)
        x, y = (b.winfo_rootx(), b.winfo_rooty() + b.winfo_height()) if b else (
            self.root.winfo_pointerx(), self.root.winfo_pointery())
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    def _custom_room(self):
        if len(self.cfg.get("custom_widgets") or []) >= CUSTOM_LIMIT:
            messagebox.showinfo("Custom widgets", f"The limit is {CUSTOM_LIMIT} custom widgets. "
                                                  "Remove one first.")
            return False
        return True

    def add_custom_file(self):
        if not self._custom_room():
            return
        p = filedialog.askopenfilename(
            parent=self.root, title="Choose a widget picture (PNG / GIF / WebP / JPG, or a .zip with one)",
            filetypes=[("Widget pictures", CUSTOM_FILE_TYPES), ("All files", "*.*")])
        if not p:
            return
        try:
            with open(p, "rb") as f:
                data = f.read(CUSTOM_MAX_BYTES + 1)
            if len(data) > CUSTOM_MAX_BYTES:
                raise ValueError("That file is larger than 30 MB.")
            data, ext = prepare_custom_bytes(data)
        except Exception as e:
            messagebox.showerror("Add custom widget", str(e))
            return
        self._register_custom(data, ext, os.path.splitext(os.path.basename(p))[0][:24], p)

    def add_custom_url(self):
        if not self._custom_room():
            return
        url = simpledialog.askstring(
            "Add widget from link",
            "Paste a direct link to the picture.\n(On the web page: right-click the image > "
            "'Copy image address'.)\nPNG, GIF, WebP, JPG, or a .zip containing one.",
            parent=self.root)
        if not url or not url.strip():
            return
        self.log("Downloading widget...")
        threading.Thread(target=self._custom_download_worker, args=(url.strip(),), daemon=True).start()

    def _custom_download_worker(self, url):
        try:
            data, ext = prepare_custom_bytes(download_custom(url))
            self.q.put(("custom_dl", True, data, ext, name_from_url(url), url))
        except Exception as e:
            self.q.put(("custom_dl", False, str(e)))

    def _register_custom(self, data, ext, name, src):
        try:
            os.makedirs(CUSTOM_DIR, exist_ok=True)
            cid = uuid.uuid4().hex[:8]
            fname = cid + ext
            with open(os.path.join(CUSTOM_DIR, fname), "wb") as f:
                f.write(data)
            n = len(self.cfg["custom_widgets"])
            self.cfg["custom_widgets"].append({
                "id": cid, "name": (name or "Custom widget")[:24], "file": fname, "enabled": True,
                "scale": 1.0, "opacity": 100, "fx": round(0.38 + 0.03 * (n % 6), 3),
                "fy": round(0.28 + 0.04 * (n % 6), 3), "src": src[:200]})
            self.persist()
        except Exception as e:
            messagebox.showerror("Add custom widget", f"Could not save the widget: {e}")
            return
        self.log(f"Custom widget added: {name}. Use 'Edit layout' to drag it (wheel resizes).")
        if not self.use_live():
            self.log("Note: in baked mode it is stamped into the wallpaper (no animation or "
                     "dragging). Set Overlay mode to live for that.")
        self.refresh_custom_rows()
        self.poke()

    def remove_custom(self, cid):
        c = self.custom_conf(cid)
        if not c:
            return
        if not messagebox.askyesno("Remove widget", f"Remove '{c['name']}' and delete its saved copy?"):
            return
        st = self.cwin.pop("custom:" + cid, None)
        if st:
            st["win"].close()
        path = os.path.join(CUSTOM_DIR, c["file"])
        drop_custom_asset(path)
        try:
            os.remove(path)
        except OSError:
            pass
        self.cfg["custom_widgets"] = [x for x in self.cfg["custom_widgets"] if x["id"] != cid]
        self.persist()
        self.log(f"Removed widget: {c['name']}")
        self.refresh_custom_rows()
        self.poke()

    def centre_custom(self, cid):
        self.set_custom(cid, fx=0.4, fy=0.3)

    def custom_built(self, wid, key, res, err):
        st = self.cwin.get(wid)
        if not st:
            return
        st["building"] = False
        st["key"] = key
        if err or not res:
            if err and (wid, err) not in self._custom_errs:
                self._custom_errs.add((wid, err))
                self.log(f"Custom widget problem: {err}")
            st["frames"] = []
            return
        st.update(frames=res["frames"], cum=res["cum"], total=res["total"], size=res["size"],
                  M=res["M"], idx=-1, t0=time.time())

    def _custom_build_worker(self, wid, key, path, scale, opacity, sH, edit, label, accent):
        try:
            res = build_custom_frames(path, scale, opacity, sH, edit, label, accent)
            self.q.put(("custom_built", wid, key, res, None))
        except Exception as e:
            self.q.put(("custom_built", wid, key, None, str(e)))

    def custom_tick(self):
        """Own fast loop: animated GIF/WebP widgets need ~30 fps, the main overlay only 1 fps."""
        try:
            self._custom_step()
        except Exception as e:
            if ("step", repr(e)) not in self._custom_errs:
                self._custom_errs.add(("step", repr(e)))
                self.log(f"custom widgets: {e}")
        self.root.after(self._custom_delay, self.custom_tick)

    def _custom_step(self):
        live = self.use_live()
        want = {"custom:" + c["id"]: c for c in self.cfg.get("custom_widgets") or []
                if c.get("enabled")} if live else {}
        for wid in [w for w in self.cwin if w not in want]:
            self.cwin.pop(wid)["win"].close()
        self._custom_delay = 400
        if not want:
            return
        W, H = self.size
        sH = H / 1080.0
        edit = self.edit_mode
        accent = ui_accent(self.analysis["info"])
        now = time.time()
        for wid, c in want.items():
            path = os.path.join(CUSTOM_DIR, c["file"])
            if not os.path.isfile(path):
                if (wid, "missing") not in self._custom_errs:
                    self._custom_errs.add((wid, "missing"))
                    self.log(f"Custom widget file missing: {c['name']} (remove it in Widgets...)")
                continue
            st = self.cwin.get(wid)
            if st is None:
                try:
                    win = WidgetWindow(wid, self.cfg.get("overlay_layer", "normal"), self.q)
                except Exception as e:
                    if (wid, "win") not in self._custom_errs:
                        self._custom_errs.add((wid, "win"))
                        self.log(f"Custom widget window failed: {e}")
                    continue
                win.set_visible(self.edit_mode or not (self.hide_today and self.level == "CLEARED"))
                st = self.cwin[wid] = {"win": win, "key": None, "frames": [], "cum": [], "total": 1.0,
                                       "size": (0, 0), "M": 0, "idx": -1, "t0": now, "building": False,
                                       "pos": None}
            key = (c["file"], os.path.getmtime(path), round(c["scale"], 3), int(c["opacity"]),
                   edit, H, tuple(accent) if edit else None, c["name"] if edit else None)
            if st["key"] != key and not st["building"]:
                st["building"] = True
                threading.Thread(target=self._custom_build_worker, daemon=True,
                                 args=(wid, key, path, c["scale"], int(c["opacity"]), sH, edit,
                                       c["name"], accent)).start()
            frames = st["frames"]
            if not frames:
                continue
            st["win"].set_mode(edit, False)
            n = len(frames)
            idx = 0 if (edit or n == 1) else min(n - 1, bisect.bisect_right(st["cum"],
                                                                           (now - st["t0"]) % st["total"]))
            M = st["M"]
            x, y = int(float(c["fx"]) * W) - M, int(float(c["fy"]) * H) - M
            if idx != st["idx"] or st["pos"] != (x, y):
                st["win"].update_raw(frames[idx], st["size"][0], st["size"][1], x, y)
                st["idx"], st["pos"] = idx, (x, y)
            if n > 1 and not edit:
                self._custom_delay = 33

    # ---- plan import ----------------------------------------------------------------
    def reset_progress(self):
        self.state["completed"], self.state["awarded"] = [], []
        self.state["plan_fed"] = True
        self.verify_msgs = {}

    def _plan_changed(self):
        _TILE_CACHE.clear()                      # widget tiles are keyed by quest ids, which repeat
        self.reload_quests()
        self.build_quests()
        self.last_key = None
        self.last_overlay = 0.0
        self.poke()

    def apply_plan(self, plan, label=""):
        plan = {k: v for k, v in plan.items() if not k.startswith("_")}
        save_json(CUSTOM_PLAN_PATH, plan)
        self.cfg["custom_plan_file"] = CUSTOM_PLAN_PATH
        self.cfg["plan_prompted"] = True
        self.reset_progress()
        self.persist()
        rebuild_sprint(self.cfg)
        self._plan_changed()
        self.log(f"Plan loaded{' from ' + label if label else ''}: {len(SPRINT)} days, "
                 f"{sum(len(d['quests']) for d in SPRINT)} quests, Day 1 = {START_DATE:%d %b %Y}.")

    def clear_plan(self):
        try:
            if os.path.isfile(CUSTOM_PLAN_PATH):
                os.remove(CUSTOM_PLAN_PATH)
        except OSError:
            pass
        self.cfg["custom_plan_file"] = ""
        self.reset_progress()
        self.persist()
        rebuild_sprint(self.cfg)
        self._plan_changed()
        self.log("Plan cleared. Click 'Import plan' to feed me a new one.")

    def _first_plan_prompt(self):
        if SPRINT_DAYS == 0 and not self.cfg.get("plan_prompted"):
            self.cfg["plan_prompted"] = True
            self.persist()
            self.open_plan_import()

    def open_plan_import(self):
        try:
            if getattr(self, "import_win", None) is not None and self.import_win.winfo_exists():
                self.import_win.lift()
                return
        except Exception:
            pass
        sc = self.sc
        top = tk.Toplevel(self.root)
        self.import_win = top
        top.title("Import plan")
        top.configure(bg=self.BG)
        top.geometry(f"{int(760 * sc)}x{min(int(760 * sc), self.size[1] - int(80 * sc))}"
                     f"+{int(70 * sc)}+24")
        src = {"data": None, "name": "", "ctype": ""}
        result = {"plan": None}
        lab = dict(bg=self.BG, fg=self.MUTED, font=("Segoe UI", 9))
        btn = dict(bg=self.PANEL, fg=self.FG, relief="flat", font=("Segoe UI", 9), padx=10)

        bar = tk.Frame(top, bg=self.BG)
        bar.pack(side="bottom", fill="x", padx=16, pady=(4, 12))
        tk.Label(top, text="IMPORT YOUR PLAN", bg=self.BG, fg=self.accent,
                 font=("Segoe UI Semibold", 11)).pack(pady=(10, 0))
        tk.Label(top, text="Give me your plan in any form: a file (txt, md, html, docx, csv, json, pdf), "
                           "a link (web page, GitHub, Google Doc / Sheet shared as 'anyone with the "
                           "link'), or just paste the text. I turn it into days and tasks.",
                 wraplength=int(720 * sc), justify="left", **lab).pack(padx=16, pady=(2, 6), anchor="w")

        r1 = tk.Frame(top, bg=self.BG)
        r1.pack(fill="x", padx=16, pady=2)
        status = tk.Label(r1, text="nothing loaded yet", anchor="w", **lab)
        tk.Button(r1, text="Choose file...", command=lambda: pick_file(), **btn).pack(side="left", ipady=2)
        status.pack(side="left", padx=10)

        r2 = tk.Frame(top, bg=self.BG)
        r2.pack(fill="x", padx=16, pady=4)
        tk.Label(r2, text="Link:", **lab).pack(side="left")
        url_var = tk.StringVar()
        ent = tk.Entry(r2, textvariable=url_var, bg=self.PANEL, fg=self.FG, insertbackground=self.FG,
                       relief="flat", font=("Segoe UI", 10))
        ent.pack(side="left", fill="x", expand=True, padx=6, ipady=3)
        tk.Button(r2, text="Fetch", command=lambda: fetch(), **btn).pack(side="left", ipady=2)

        tk.Label(top, text="...or paste your plan here:", anchor="w", **lab).pack(fill="x", padx=16)
        paste = tk.Text(top, height=7, bg=self.PANEL, fg=self.FG, insertbackground=self.FG,
                        relief="flat", font=("Consolas", 9), wrap="word")
        paste.pack(fill="x", padx=16, pady=4)

        r3 = tk.Frame(top, bg=self.BG)
        r3.pack(fill="x", padx=16, pady=2)
        tk.Label(r3, text="Day 1 date (blank = from plan / today):", **lab).pack(side="left")
        start_var = tk.StringVar()
        tk.Entry(r3, textvariable=start_var, width=12, bg=self.PANEL, fg=self.FG,
                 insertbackground=self.FG, relief="flat", font=("Consolas", 10)).pack(side="left", padx=6)
        code_var = tk.BooleanVar(value=True)
        tk.Checkbutton(r3, text="tasks naming a .c file = auto-verified", variable=code_var,
                       bg=self.BG, fg=self.FG, selectcolor=self.PANEL, activebackground=self.BG,
                       activeforeground=self.FG, font=("Segoe UI", 9)).pack(side="left", padx=10)
        r4 = tk.Frame(top, bg=self.BG)
        r4.pack(fill="x", padx=16, pady=2)
        tk.Label(r4, text="Plain list without day headings: tasks per day (0 = all on day 1):", **lab).pack(side="left")
        per_var = tk.StringVar(value="0")
        tk.Spinbox(r4, from_=0, to=50, textvariable=per_var, width=4, bg=self.PANEL, fg=self.FG,
                   buttonbackground=self.PANEL, relief="flat", font=("Consolas", 10)).pack(side="left", padx=6)
        tk.Button(r4, text="Read plan", command=lambda: do_read(), bg=self.accent, fg="#14110f",
                  relief="flat", font=("Segoe UI Semibold", 9), padx=14).pack(side="right", ipady=2)

        prev = tk.Text(top, height=10, bg=self.PANEL, fg=self.FG, relief="flat", font=("Consolas", 9),
                       wrap="none", state="disabled")
        prev.pack(fill="both", expand=True, padx=16, pady=(6, 4))

        def show(text):
            prev.config(state="normal")
            prev.delete("1.0", "end")
            prev.insert("1.0", text)
            prev.config(state="disabled")

        use_btn = tk.Button(bar, text="Use this plan", state="disabled", command=lambda: use(False),
                            bg=self.accent, fg="#14110f", relief="flat", font=("Segoe UI Semibold", 9),
                            padx=12)
        edit_btn = tk.Button(bar, text="Use + edit in Plan Studio", state="disabled",
                             command=lambda: use(True), **btn)
        use_btn.pack(side="left", padx=3, ipady=3)
        edit_btn.pack(side="left", padx=3, ipady=3)
        tk.Button(bar, text="Close", command=top.destroy, **btn).pack(side="right", padx=3, ipady=3)
        show("Load a file / link or paste text, then press 'Read plan'. You get a preview before "
             "anything changes.\n\nTip: lines such as  code: sum.c | Sum digits | 12 => 3  keep your own "
             "tests; every other task becomes a tick-it-yourself quest.")

        def set_src(data, name, ctype=""):
            src.update(data=data, name=name, ctype=ctype)
            status.config(text=f"loaded: {name}  ({max(1, len(data) // 1024)} KB)")
            paste.delete("1.0", "end")
            do_read()

        def pick_file():
            p = filedialog.askopenfilename(parent=top, title="Choose your plan", filetypes=[
                ("Plans", "*.txt *.md *.markdown *.html *.htm *.docx *.csv *.tsv *.json *.pdf *.zip"),
                ("All files", "*.*")])
            if not p:
                return
            try:
                with open(p, "rb") as f:
                    data = f.read(PLAN_MAX_BYTES + 1)
                if len(data) > PLAN_MAX_BYTES:
                    raise ValueError("That file is larger than 8 MB.")
            except Exception as e:
                show(f"Could not open that file:\n{e}")
                return
            set_src(data, os.path.basename(p))

        def fetch():
            u = url_var.get().strip()
            if not u:
                return
            status.config(text="downloading...")
            self._plan_cb = on_fetched

            def work():
                try:
                    data, ctype, name = fetch_plan_url(u)
                    self.q.put(("plan_fetch", True, data, name, ctype))
                except Exception as e:
                    self.q.put(("plan_fetch", False, str(e)))
            threading.Thread(target=work, daemon=True).start()

        def on_fetched(ok, *rest):
            try:
                if not top.winfo_exists():
                    return
            except Exception:
                return
            if not ok:
                status.config(text="download failed")
                result["plan"] = None
                use_btn.config(state="disabled")
                edit_btn.config(state="disabled")
                show(f"Could not get that link:\n{rest[0]}")
                return
            set_src(rest[0], rest[1] or url_var.get().strip(), rest[2])

        def do_read():
            pasted = paste.get("1.0", "end").strip()
            if pasted and re.fullmatch(r"https?://\S+", pasted):
                url_var.set(pasted)
                paste.delete("1.0", "end")
                fetch()
                return
            if pasted:
                data, name, ctype = pasted.encode("utf-8"), "pasted text", ""
            elif src["data"]:
                data, name, ctype = src["data"], src["name"], src["ctype"]
            else:
                show("Nothing to read yet: choose a file, paste a link, or paste your plan.")
                return
            start = None
            if start_var.get().strip():
                fd = find_date(start_var.get().strip())
                if not fd:
                    show("I could not understand the Day 1 date. Use YYYY-MM-DD, e.g. 2026-11-08.")
                    return
                start = fd[0]
            try:
                per = max(0, int(per_var.get() or 0))
            except ValueError:
                per = 0
            try:
                plan = import_plan(data, name, ctype, {"start": start, "auto_code": code_var.get(),
                                                       "per_day": per})
            except Exception as e:
                result["plan"] = None
                use_btn.config(state="disabled")
                edit_btn.config(state="disabled")
                show(f"I could not read a plan from that.\n\n{e}")
                return
            result["plan"] = plan
            use_btn.config(state="normal")
            edit_btn.config(state="normal")
            show(plan_summary(plan))

        def use(edit_after):
            plan = result["plan"]
            if not plan:
                return
            if self.state.get("completed") and SPRINT_DAYS:
                if not messagebox.askyesno("Replace plan", "This replaces your current plan and clears "
                                           "its task progress (XP and streak are kept). Continue?",
                                           parent=top):
                    return
            self.apply_plan(plan, src["name"] or "pasted text")
            top.destroy()
            if edit_after:
                self.open_custom_plan()

        ent.focus_set()

    # ---- focus timer -------------------------------------------------------------
    def focus_reset(self, mode=None):
        f = self.focus
        if mode:
            f["mode"] = mode
        mins = self.cfg.get("focus_minutes", 25) if f["mode"] == "focus" \
            else self.cfg.get("break_minutes", 5)
        f.update(running=False, end=0.0, total=int(mins) * 60, remaining=int(mins) * 60)

    def focus_toggle(self):
        f = self.focus
        if f["running"]:
            f["remaining"] = max(0, f["end"] - time.time())
            f["running"] = False
        else:
            f["end"] = time.time() + f["remaining"]
            f["running"] = True

    def focus_finish(self, skipped):
        f = self.focus
        if f["mode"] == "focus":
            if not skipped:
                f["sessions"] += 1
                self.state["xp"] += XP_FOCUS
                self.state["focus"] = {"date": dt.date.today().isoformat(),
                                       "count": f["sessions"]}
                self.persist()
                self.log(f"Focus session {f['sessions']} done (+{XP_FOCUS} xp). Take a break.")
            self.focus_reset("break")
        else:
            self.focus_reset("focus")
        if not skipped and IS_WIN:
            try:
                import winsound
                winsound.MessageBeep()
            except Exception:
                pass

    def focus_snapshot(self):
        f = self.focus
        rem = max(0, f["end"] - time.time()) if f["running"] else f["remaining"]
        return {"mode": f["mode"], "running": f["running"], "remaining": rem,
                "total": f["total"], "sessions": f["sessions"]}

    def widget_action(self, wid, name):
        if wid == "music":
            vk = {"prev": VK_MEDIA_PREV, "play": VK_MEDIA_PLAY, "next": VK_MEDIA_NEXT}.get(name)
            if vk:
                send_media_key(vk)
        elif wid == "quests":
            if name == "verify":
                self.run_verify()
            elif name.startswith("tick:"):
                for q in self.quests:
                    if q["key"] == name[5:] and q["kind"] == "manual":
                        self.set_manual(q, not self.done(q))
        elif wid == "focus":
            if name == "toggle":
                self.focus_toggle()
            elif name == "reset":
                self.focus_reset()
            elif name == "skip":
                self.focus_finish(True)
        self.last_overlay = 0.0

    # ---- live widgets + analysis ---------------------------------------------------
    def sync_windows(self):
        want = [w for w in WIDGET_ORDER if self.cfg["widgets"][w]["enabled"]]
        for wid in list(self.windows):
            if wid not in want:
                self.windows.pop(wid).close()
        for wid in want:
            if wid not in self.windows:
                try:
                    self.windows[wid] = WidgetWindow(wid, self.cfg.get("overlay_layer", "normal"),
                                                     self.q)
                except Exception as e:
                    self.overlay_failed = True
                    self.log(f"Live widgets failed: {e}. Using baked mode instead.")
                    return
        need_media = (self.cfg["widgets"]["music"]["enabled"] or self.cfg["widgets"]["wave"]["enabled"])
        if need_media and self.media and self.use_live():
            self.media.start()
        elif self.media and self.media.proc is not None:
            self.media.stop()
        if self.cfg["widgets"]["wave"]["enabled"] and self.use_live():
            self.audio.start()

    def close_windows(self):
        for win in self.all_windows():
            win.close()
        self.windows = {}
        self.cwin = {}

    def analysis_source(self):
        """Picture the HUD adapts to: its wallpaper, or (after 'Remove wallpaper') the desktop's."""
        wp = self.cfg["wallpaper"]
        if wp or not self.cfg.get("no_wallpaper") or self.engine_lively():
            return wp
        sp = get_system_wallpaper()
        return sp if sp and os.path.isfile(sp) and not in_app_dir(sp) else ""

    def maybe_analyze(self):
        want = self.engine_lively()
        src = self.analysis_source()
        key = (src, want)
        stale = time.time() - self.analysis["ts"] > 1800
        if self.analyzing or (key == self.analysis_key and not stale):
            return
        self.analyzing = True
        self.analysis_key = key
        threading.Thread(target=self._analysis_worker,
                         args=(src, self.size, want,
                               self.cfg.get("lively_exe", "")), daemon=True).start()

    def _analysis_worker(self, wp, size, want_lively, exe):
        try:
            img, note = None, ""
            if wp and os.path.isfile(wp):
                im, n = load_background(wp, dt.datetime.now(), size)
                if n == os.path.basename(wp):
                    img, note = im, n
                else:
                    note = n
            if img is None and want_lively and time.time() - self.shot_fail_ts > 21600:
                exe = find_lively(exe)
                if exe:
                    shot = lively_screenshot(exe, os.path.join(APP_DIR, "wp_shot.jpg"), 8)
                    if shot is not None:
                        img, note = shot, "Lively screenshot"
                    else:
                        self.shot_fail_ts = time.time()
                        note = (note + "; " if note else "") + "Lively screenshot failed"
                else:
                    note = (note + "; " if note else "") + "Lively.exe not found"
            if img is None:
                img, _ = load_background(None, dt.datetime.now(), size)
            orig = ImageOps.fit(img.convert("RGB"), size, Image.LANCZOS)
            gray = orig.convert("L").resize((max(1, size[0] // 4), max(1, size[1] // 4)))
            self.q.put(("analysis", {"info": analyze_bg(orig), "gray": gray,
                                     "ts": time.time(), "wp": wp, "note": note,
                                     "exe": exe or ""}))
        except Exception as e:
            self.q.put(("analysis_err", f"analysis failed: {e}"))

    def get_art(self, path):
        if not path:
            return None
        try:
            mt = os.path.getmtime(path)
            if self.art_cache["path"] != path or self.art_cache["mtime"] != mt:
                img = Image.open(path)
                img.load()
                self.art_cache.update(path=path, mtime=mt, img=img.convert("RGB"))
            return self.art_cache["img"]
        except Exception:
            return None

    def refresh_overlay(self):
        if self.overlay_busy or not self.windows:
            return
        now = dt.datetime.now()
        level, rem = self.snapshot(now)
        if self.hide_today and level == "CLEARED" and not self.edit_mode:
            return
        self.overlay_busy = True
        media = self.media.snapshot() if self.media else {"has": False}
        audio = self.audio.snapshot() if self.audio else {"active": False, "peak": 0.0}
        extra = {"media": media, "audio": audio, "focus": self.focus_snapshot(),
                 "art_img": self.get_art(media.get("art")), "sys": dict(self.sys_stats),
                 "vmsg": {k: v for k, v in self.verify_msgs.items() if v},
                 "verifying": self.verifying}
        state_snap = {**self.state, "completed": list(self.state["completed"])}
        cfg_snap = {**self.cfg, "widgets": {k: dict(v) for k, v in self.cfg["widgets"].items()}}
        args = (state_snap, cfg_snap, now, self.size, list(self.quests), self.day_info, level,
                rem, self.analysis, extra, dict(self.dark_flags), self.edit_mode,
                dict(self.windows))
        threading.Thread(target=self._overlay_worker, args=args, daemon=True).start()

    def _overlay_worker(self, state, cfg, now, size, quests, day_info, level, rem, analysis,
                        extra, flags, edit, windows):
        try:
            info = analysis["info"]
            message = pick_message(level, info, cfg, cfg.get("wallpaper", ""), now)
            ctx = build_ctx(state, cfg, now, quests, day_info, level, rem, info, message,
                            live=True, extra=extra)
            tiles, autos, flags = build_tiles(cfg["widgets"], ctx, size, analysis["gray"], info,
                                              level, size[1] / 1080.0, flags, edit)
            meta = {}
            for t in tiles:
                win = windows.get(t["wid"])
                if not win:
                    continue
                win.set_mode(edit, t["wid"] in INTERACTIVE)
                if t.get("dirty", True) or win.pos is None:
                    win.update(t["tile"], t["x"], t["y"])
                meta[t["wid"]] = {"M": t["M"], "hits": t["hits"]}
            info2 = {**info, "panel_dark": flags.get("status", True),
                     "accent_ui": ui_accent(info)}
            self.q.put(("overlay_ok", info2, message, meta, autos, flags))
        except Exception as e:
            self.q.put(("overlay_err", repr(e)))

    # ---- baked wallpaper rendering ------------------------------------------------
    def is_cleared(self):
        req = gating(self.quests)
        return not req or all(self.done(q) for q in req)

    def snapshot(self, now):
        dl = parse_deadline(self.cfg["deadline"], now.date())
        return (compute_level(set(self.state["completed"]), self.quests, dl, now),
                (dl - now).total_seconds())

    def refresh_wallpaper(self, force=False):
        if self.cfg.get("no_wallpaper"):
            return
        if self.rendering:
            self.last_key = None
            return
        self.rendering = True
        now = dt.datetime.now()
        level, rem = self.snapshot(now)
        args = (self.cfg["wallpaper"], json.loads(json.dumps(self.state)),
                json.loads(json.dumps(self.cfg)), now, self.size, list(self.quests),
                self.day_info, level, rem)
        threading.Thread(target=self._render_worker, args=args, daemon=True).start()

    def _render_worker(self, *args):
        try:
            img, info, msg, note, autos = render_frame(*args)
            os.makedirs(APP_DIR, exist_ok=True)
            path = os.path.join(APP_DIR, f"wall_{args[3].minute % 2}.bmp")
            img.save(path, "BMP")
            set_wallpaper(path)
            self.q.put(("rendered", info, msg, note, autos))
        except Exception as e:
            self.q.put(("error", f"render failed: {e}"))

    # ---- verification -----------------------------------------------------------
    def run_verify(self, auto=False):
        if self.verifying:
            return
        root = self.cfg.get("workspace")
        if not root or not os.path.isdir(root):
            if not auto:
                self.choose_workspace()
            return
        pending = [q for q in self.quests if q["kind"] != "manual" and not self.done(q)]
        if not pending:
            if not auto:
                self.log("All code/disk quests verified! Click manual quests to tick them.")
            return
        cc = find_compiler(self.cfg.get("compiler_exe", ""))
        if not cc and any(q["kind"] == "code" for q in pending):
            self.log("No C compiler (gcc/clang) found. Install MinGW64 or add gcc to PATH.")
        self.verifying = True
        self.verify_btn.config(state="disabled", text="VERIFYING...")
        today = dt.date.today()

        def work():
            try:
                files = list_workspace_c_files(root, max_age=0)      # one disk walk for all quests
                res = [(q, *verify_quest(q, root, cc, today, files)) for q in pending]
            except Exception as e:
                res = [(q, False, f"unexpected error: {e}") for q in pending]
            self.q.put(("verify", res))
        threading.Thread(target=work, daemon=True).start()

    def award(self, q):
        gain = 0
        if q["key"] not in self.state["awarded"]:
            self.state["awarded"].append(q["key"])
            gain += XP_BONUS if q["bonus"] else XP_MANUAL if q["kind"] == "manual" else XP_CODE
        iso = dt.date.today().isoformat()
        if self.is_cleared() and self.state.get("last_clear_date") != iso:
            self.state["streak"] += 1
            self.state["best_streak"] = max(self.state["best_streak"], self.state["streak"])
            self.state["last_clear_date"] = iso
            gain += XP_CLEAR + 10 * min(self.state["streak"], 10)
        self.state["xp"] += gain
        return gain

    # ---- main loop --------------------------------------------------------------
    def show_tone(self, info, msg, note=""):
        self.accent = hex_color(info["accent_ui"])
        self.msg_lbl.config(text=msg, fg=LEVEL_HEX.get(self.level, self.accent))
        src = note or self.analysis.get("note", "")
        self.tone_lbl.config(text=f"wallpaper tone: {info['mood']}  |  "
                                  f"{'dark' if info['panel_dark'] else 'light'} text  |  "
                                  f"source: {src}")
        self.verify_btn.config(bg=self.accent)
        self.title_lbl.config(fg=self.accent)

    def drain(self):
        while True:
            try:
                ev = self.q.get_nowait()
            except queue.Empty:
                return
            kind = ev[0]
            if kind == "rendered":
                self.rendering = False
                self.show_tone(ev[1], ev[2], ev[3])
                self.apply_autos(ev[4])
            elif kind == "overlay_ok":
                self.overlay_busy = False
                self.tile_meta = ev[3]
                self.dark_flags = ev[5]
                self.show_tone(ev[1], ev[2])
                self.apply_autos(ev[4])
            elif kind == "overlay_err":
                self.overlay_busy = False
                if ev[1] != self.last_err:
                    self.last_err = ev[1]
                    self.log(f"overlay error: {ev[1]}")
            elif kind == "wmove":
                _, wid, left, top = ev
                W, H = self.size
                if wid.startswith("custom:"):
                    c = self.custom_conf(wid[7:])
                    M = self.cwin.get(wid, {}).get("M", 0)
                    if c:
                        c["fx"], c["fy"] = round((left + M) / float(W), 4), round((top + M) / float(H), 4)
                else:
                    M = self.tile_meta.get(wid, {}).get("M", 0)
                    w = self.cfg["widgets"][wid]
                    w["fx"], w["fy"] = (left + M) / float(W), (top + M) / float(H)
                self.persist_soon()
            elif kind == "wheel":
                _, wid, delta = ev
                if wid.startswith("custom:"):
                    c = self.custom_conf(wid[7:])
                    if c:
                        c["scale"] = round(min(8.0, max(0.1, c["scale"] * (1.06 if delta > 0 else 1 / 1.06))), 3)
                        self.persist_soon()
                        if getattr(self, "_rows_job", None):
                            self.root.after_cancel(self._rows_job)
                        self._rows_job = self.root.after(500, self.refresh_custom_rows)
                else:
                    w = self.cfg["widgets"][wid]
                    w["scale"] = round(min(2.0, max(0.5, w["scale"] + (0.05 if delta > 0 else -0.05))), 2)
                    self.persist_soon()
                    self.last_overlay = 0.0
            elif kind == "custom_built":
                self.custom_built(*ev[1:])
            elif kind == "custom_dl":
                if ev[1]:
                    self._register_custom(ev[2], ev[3], ev[4], ev[5])
                else:
                    self.log(f"Download failed: {ev[2]}")
                    messagebox.showerror("Add widget from link", ev[2])
            elif kind == "plan_fetch":
                cb = getattr(self, "_plan_cb", None)
                if cb:
                    cb(*ev[1:])
            elif kind == "lively_closed":
                self.log("Lively: wallpaper closed." if ev[1] else f"Lively could not close it: {ev[2]}")
            elif kind == "wsscan":
                self.ws_scanning = False
                if ev[1] != self.ws_sig:
                    self.ws_sig = ev[1]
                    if ev[2] and not self.is_cleared():
                        self.run_verify(auto=True)
            elif kind == "wclick":
                _, wid, x, y = ev
                for name, (x0, y0, x1, y1) in self.tile_meta.get(wid, {}).get("hits", []):
                    if x0 <= x <= x1 and y0 <= y <= y1:
                        self.widget_action(wid, name)
                        break
            elif kind == "analysis":
                self.analysis = ev[1]
                self.analyzing = False
                if ev[1]["exe"] and ev[1]["exe"] != self.cfg.get("lively_exe"):
                    self.cfg["lively_exe"] = ev[1]["exe"]
                    self.persist()
                self.log(f"Adapted to wallpaper: tone {ev[1]['info']['mood']} "
                         f"({ev[1]['note']})")
                self.last_overlay = 0.0
            elif kind == "analysis_err":
                self.analyzing = False
                self.log(ev[1])
            elif kind == "error":
                self.rendering = False
                self.log(ev[1])
            elif kind == "need_lively":
                p = ev[1]
                if messagebox.askyesno(
                        "Lively Wallpaper",
                        "I could not find Lively's command program.\n\nLocate Lively.exe now?\n"
                        "(usually C:\\Program Files\\Lively Wallpaper\\Lively.exe)"):
                    self.locate_lively(then_set=p)
                else:
                    self.log("Without Lively.exe the HUD cannot set videos. Set the video in "
                             "Lively yourself; the widgets still float above it.")
                    self.ensure_video_support()
            elif kind == "lively_set":
                _, ok, msg, exe = ev
                self.log("Lively: wallpaper set." if ok else f"Lively error: {msg}")
                if ok:
                    self.cfg["lively_exe"] = exe
                    self.persist()
                    self.analysis_key = None
            elif kind == "cv2":
                self.log("opencv-python installed." if ev[1] else f"opencv install failed: {ev[2]}")
                self.analysis_key = None
            elif kind == "verify":
                self.verifying = False
                self.verify_btn.config(state="normal", text="VERIFY QUESTS")
                total = 0
                for q, ok, msg in ev[1]:
                    name = q["file"] if q["kind"] == "code" else q["label"]
                    self.log(f"{'PASS' if ok else 'FAIL'}  {name}: {msg}")
                    self.verify_msgs[q["key"]] = None if ok else msg
                    if ok and q["key"] not in self.state["completed"]:
                        self.state["completed"].append(q["key"])
                        total += self.award(q)
                if total:
                    self.log(f"+{total} XP")
                self.persist()
                self.after_progress()
            elif kind == "procs":
                found, lively = ev[1], ev[2]
                self.lively_flag = lively
                self.scanned = True
                if found and self.level != "CLEARED":
                    self.flash(found)

    def flash(self, names):
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.msg_lbl.config(text=f"DISTRACTION DETECTED: {', '.join(names)}\n"
                                 f"Clear your quests first.", fg="#e65a50")
        self._blink(8)

    def _blink(self, n):
        if n <= 0:
            return
        self.badge.config(fg="#e65a50" if n % 2 else self.accent)
        self.root.after(250, lambda: self._blink(n - 1))

    def tick(self):
        now = dt.datetime.now()
        if now.date().isoformat() != self.state["day"]:
            self.state = roll_state(self.state, now.date())
            self.reload_quests()
            self.build_quests()
            self.hide_today = False
            self.focus["sessions"] = 0
            self.persist()
            self.last_key = None
        self.drain()
        if self.focus["running"] and time.time() >= self.focus["end"]:
            self.focus_finish(False)
        level, rem = self.snapshot(now)
        if level != self.level:
            self.level = level
            self.last_key = None
            self.root.attributes("-topmost", False)
            if level != "CLEARED":
                self.hide_today = False
            self.apply_hidden()
        col = LEVEL_HEX.get(level, self.accent)
        self.badge.config(text="  ".join(BADGE[level]), fg=col)
        idx = day_index(now.date())
        if self.day_info:
            self._set(self.day_lbl, text=f"DAY {idx:02d} / {SPRINT_DAYS}   \u00b7   "
                                         f"{PHASES[self.day_info['phase']]}")
            self._set(self.dtitle_lbl, text=self.day_info["title"])
        else:
            self._set(self.day_lbl, text="NO PLAN LOADED" if SPRINT_DAYS == 0 else "NOTHING DUE TODAY")
            self._set(self.dtitle_lbl, text="Click 'Import plan' and feed me your tasks" if SPRINT_DAYS == 0
                      else f"Plan starts {START_DATE:%d %B}" if idx < 1 else "Plan complete. Well fought.")
        req = gating(self.quests)
        done_n = sum(1 for q in req if self.done(q))
        rank, frac, _ = rank_info(self.state["xp"])
        self._set(self.prog_lbl, text=f"{done_n}/{len(req)} quests  \u00b7  Rank {rank}  \u00b7  "
                                     f"{self.state['xp']} xp  \u00b7  {self.state['streak']} day streak")
        bar_fill = col if level == "CLEARED" else self.accent
        bar_key = (done_n, len(req), bar_fill)
        if bar_key != self._bar_key:
            self._bar_key = bar_key
            self.bar.delete("all")
            bw = int(460 * self.sc)
            self.bar.create_rectangle(0, 0, bw * (done_n / float(len(req)) if req else 1.0), 10,
                                      fill=bar_fill, width=0)
        sec = int(abs(rem))
        left = f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"
        if level == "CLEARED":
            self._set(self.time_lbl, text=f"{now:%H:%M:%S}   \u00b7   all cleared")
        else:
            self._set(self.time_lbl, text=f"{now:%H:%M:%S}   \u00b7   due {self.cfg['deadline']}   "
                                          f"\u00b7   {left} {'over' if rem < 0 else 'left'}",
                      fg=col if level != "ACTIVE" else self.MUTED)
        self.update_quests()

        if self.use_live():
            self.sync_windows()
            if self.windows:
                self.maybe_analyze()
                wave_live = (self.cfg["widgets"]["wave"]["enabled"]
                             and self.audio.is_active())
                interval = 0.08 if wave_live else 1.0
                if time.time() - self.last_overlay >= interval:
                    now_ts = time.time()
                    if self.cfg["widgets"]["sysmon"]["enabled"] and (now_ts - getattr(self, "_last_sys_ts", 0.0) >= 2.0):
                        self._last_sys_ts = now_ts
                        self.sys_stats, self.sys_prev = read_sys_stats(self.sys_prev)
                    self.last_overlay = now_ts
                    self.refresh_overlay()
        else:
            if self.windows or self.cwin:
                self.close_windows()
            if self.media is not None and self.media.proc is not None:
                self.media.stop()                 # baked mode has no music widget
            key = (now.date(), now.hour, now.minute // max(1, int(self.cfg["refresh_minutes"])))
            if key != self.last_key and self.scanned and not self.cfg.get("no_wallpaper"):
                self.last_key = key
                self.refresh_wallpaper()

        ws = self.cfg.get("workspace", "")
        if (ws and os.path.isdir(ws) and not self.ws_scanning
                and time.time() - self.last_ws_scan >= 5.0):
            self.last_ws_scan = time.time()
            self.ws_scanning = True               # disk walk runs off the UI thread

            def _ws_scan(root=ws):
                try:
                    cl = list_workspace_c_files(root, max_age=0)
                    self.q.put(("wsscan", (len(cl), cl[0][1] if cl else 0.0), bool(cl)))
                except Exception:
                    self.q.put(("wsscan", self.ws_sig, False))
            threading.Thread(target=_ws_scan, daemon=True).start()

        if time.time() - self.last_scan >= self.cfg["distraction_scan_seconds"]:
            self.last_scan = time.time()
            watch = self.cfg["distraction_processes"]
            threading.Thread(target=lambda: self.q.put(("procs", *scan_processes(watch))),
                             daemon=True).start()
        fast_tick = (self.use_live() and self.cfg["widgets"]["wave"]["enabled"]
                     and self.audio.is_active())
        self.root.after(80 if fast_tick else 450, self.tick)

    def on_close(self):
        if self.allow_exit or self.level == "CLEARED":
            self.persist()
            self.close_windows()
            if self.media:
                self.media.stop()
            if self.audio:
                self.audio.stop()
            self.root.destroy()
        else:
            self.root.iconify()
            self.log("Locked: you cannot close the HUD until quests are cleared.")


def install_startup():
    if not IS_WIN:
        sys.exit("Startup install is Windows-only.")
    startup = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows",
                           "Start Menu", "Programs", "Startup")
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    bat = os.path.join(startup, "shadow_system_hud.bat")
    with open(bat, "w") as f:
        f.write(f'@echo off\r\nstart "" "{pyw}" "{os.path.abspath(__file__)}"\r\n')
    print("Installed:", bat)


def _arg(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


DEMO_AUDIO = {
    "active": True, "peak": 0.78, "left": 0.74, "right": 0.82,
    "bass": 0.88, "mid": 0.72, "high": 0.64, "db": -4.8,
    "hist": [0.25 + 0.65 * abs(math.sin(i * 0.35)) for i in range(64)],
    "bars": [0.20 + 0.75 * abs(math.sin(i * 0.42) * math.cos(i * 0.19)) for i in range(64)],
    "phase": 2.4, "backend": "WASAPI LIVE",
}
DEMO_MEDIA = {"has": True, "title": "Weightless", "artist": "Marconi Union",
              "album": "Weightless", "status": "Playing", "pos": 83.0, "dur": 483.0,
              "app": "Spotify", "art": None}
DEMO_SYS = {"cpu": 37.0, "ram": 62.0, "disk": 71.0, "bat": {"pct": 84, "charging": False}}
DEMO_FOCUS = {"mode": "focus", "running": True, "remaining": 18 * 60 + 42, "total": 25 * 60,
              "sessions": 3}


def _preview_inputs(argv):
    mode = _arg(argv, "--mode", "active").upper()
    day_no = int(_arg(argv, "--day", "1"))
    done_k = int(_arg(argv, "--done", "1"))
    size = (1920, 1080)
    if "--size" in argv:
        w, h = argv[argv.index("--size") + 1].lower().split("x")
        size = (int(w), int(h))
    today = START_DATE + dt.timedelta(days=day_no - 1)
    now = dt.datetime.combine(today, dt.time(15, 42, 7))
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["widgets"] = merge_widgets(None)
    state = json.loads(json.dumps(DEFAULT_STATE))
    state.update(xp=820, streak=5, day=today.isoformat())
    for d in SPRINT[:max(0, day_no - 2)]:
        state["completed"] += [q["key"] for q in d["quests"] if not q["bonus"]]
    quests, info = quests_for(today, set(state["completed"]))
    req = gating(quests)
    state["completed"] += [q["key"] for q in req[:len(req) if mode == "CLEARED" else done_k]]
    quests, info = quests_for(today, set(state["completed"]))
    rem = {"ACTIVE": 6 * 3600 + 18 * 60, "URGENT": 1 * 3600 + 24 * 60,
           "OVERDUE": -(47 * 60), "CLEARED": 3 * 3600}[mode]
    if "--enable" in argv:
        for wid in _arg(argv, "--enable").split(","):
            cfg["widgets"][wid]["enabled"] = True
    if "--only" in argv:
        only = _arg(argv, "--only").split(",")
        for wid in WIDGET_ORDER:
            cfg["widgets"][wid]["enabled"] = wid in only
    for wid in ("clock", "music", "focus"):
        if f"--{wid}" in argv:
            cfg["widgets"][wid]["style"] = _arg(argv, f"--{wid}")
    return mode, size, now, cfg, state, quests, info, rem


def preview(argv):
    out = argv[argv.index("--preview") + 1]
    bg = _arg(argv, "--bg", "")
    mode, size, now, cfg, state, quests, info, rem = _preview_inputs(argv)
    W, H = size
    if "--live" in argv:
        raw, _ = load_background(bg, now, size)
        orig = ImageOps.fit(raw, size, Image.LANCZOS)
        inf = analyze_bg(orig)
        gray = orig.convert("L").resize((max(1, W // 4), max(1, H // 4)))
        msg = pick_message(mode, inf, cfg, bg, now)
        ctx = build_ctx(state, cfg, now, quests, info, mode, rem, inf, msg, live=True,
                        extra={"media": DEMO_MEDIA, "audio": DEMO_AUDIO, "focus": DEMO_FOCUS, "t": 12.0,
                               "sys": DEMO_SYS})
        tiles, autos, flags = build_tiles(cfg["widgets"], ctx, size, gray, inf, mode,
                                          H / 1080.0, {}, "--edit" in argv)
        img = composite_tiles(orig.convert("RGBA"), tiles).convert("RGB")
        note = f"tone={inf['mood']} widgets={[t['wid'] for t in tiles]}"
    else:
        img, i2, msg, _, autos = render_frame(bg, state, cfg, now, size, quests, info, mode, rem)
        note = f"tone={i2['mood']}"
    img.save(out)
    print(f"saved {out} | day {_arg(argv, '--day', '1')} | {note}")


def gallery(argv):
    """Contact sheet of presets on your wallpaper. --set new = ink / futuristic / WuWa extras."""
    out = argv[argv.index("--gallery") + 1]
    bg = _arg(argv, "--bg", "")
    which = _arg(argv, "--set", "core")
    mode, _, now, cfg, state, quests, info, rem = _preview_inputs(argv)
    size = (2560, 1440)
    raw, _ = load_background(bg, now, size)
    orig = ImageOps.fit(raw, size, Image.LANCZOS)
    inf = analyze_bg(orig)
    msg = pick_message(mode, inf, cfg, bg, now)
    ctx = build_ctx(state, cfg, now, quests, info, mode, rem, inf, msg, live=True,
                    extra={"media": DEMO_MEDIA, "audio": DEMO_AUDIO, "focus": DEMO_FOCUS, "t": 12.0,
                           "sys": DEMO_SYS})
    sc = 0.72
    theme = make_theme(inf["lum"] < 0.5, inf, mode)
    if which == "new":
        items = [("clock", "neon"), ("clock", "resonance"), ("calendar", "ink"),
                 ("calendar", "seal"), ("calendar", "grid"), ("moon", "ink"), ("moon", "hud"),
                 ("sysmon", "hud"), ("sysmon", "bars"), ("sprintmap", "hex"),
                 ("sprintmap", "ring"), ("waveplate", "ring"), ("waveplate", "bar"),
                 ("wave", "wave"), ("wave", "ring")]
        cols, cw_, ch_ = 5, 500, 450
    else:
        items = ([("clock", st) for st in STYLE_CHOICES["clock"][:6]] +
                 [("music", st) for st in STYLE_CHOICES["music"]] +
                 [("focus", st) for st in STYLE_CHOICES["focus"]])
        cols, cw_, ch_ = 4, 610, 450
    canvas = orig.convert("RGBA")
    lf = font(int(15 * sc), "sansb")
    for i, (wid, style) in enumerate(items):
        cx, cy = 40 + (i % cols) * cw_, 50 + (i // cols) * ch_
        content, _ = draw_widget(wid, style, ctx, theme, sc)
        w, h = content.size
        x, y = cx + max(0, (cw_ - 60 - w) // 2), cy + max(0, (ch_ - 130 - h) // 2)
        tile, M = widget_tile(content, theme, sc)
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        layer.paste(tile, (x - M, y - M))
        canvas = Image.alpha_composite(canvas, layer)
        tracked(ImageDraw.Draw(canvas), (cx + 20, cy + ch_ - 96), f"{wid.upper()}  \u00b7  {style.upper()}",
                lf, tuple(theme["accent"]) + (255,), 3 * sc)
    canvas.convert("RGB").save(out)
    print(f"saved {out}")




# ==================================================================================
# WINDOWS INSTALLER, ICON GENERATOR, SHORTCUTS & STANDALONE .EXE BUILDER
# ==================================================================================
def generate_app_icon(ico_path):
    """Generate a multi-size Windows .ico file (256..16px) with the Shadow System seal."""
    os.makedirs(os.path.dirname(os.path.abspath(ico_path)), exist_ok=True)
    S = 256
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, S - 9, S - 9), radius=48, fill=(18, 15, 18, 255),
                        outline=(224, 78, 64, 255), width=8)
    ins = 28
    d.rounded_rectangle((ins, ins, S - 1 - ins, S - 1 - ins), radius=32,
                        fill=(198, 52, 42, 255))
    ins2 = 42
    d.rounded_rectangle((ins2, ins2, S - 1 - ins2, S - 1 - ins2), radius=22,
                        outline=(245, 240, 230, 215), width=5)
    cf = cjk_font(124)
    if cf and has_glyph(cf, "罰"):
        d.text((S / 2, S / 2 - 2), "罰", font=cf, fill=(245, 240, 230, 255), anchor="mm")
    else:
        d.text((S / 2, S / 2 - 4), "S", font=font(132, "serifb"),
               fill=(245, 240, 230, 255), anchor="mm")
    img.save(ico_path, format="ICO",
             sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    return ico_path


def default_install_dir():
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Programs", "ShadowSystemHUD")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "ShadowSystemHUD")


def _create_win_shortcut(lnk_path, target_path, args="", work_dir="", icon_path="", desc=""):
    """Create a Windows .lnk shortcut using PowerShell WScript.Shell COM."""
    if not IS_WIN:
        return False
    ps = (
        f"$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{lnk_path.replace(chr(39), chr(39)*2)}'); "
        f"$s.TargetPath = '{target_path.replace(chr(39), chr(39)*2)}'; "
    )
    if args:
        ps += f"$s.Arguments = '{args.replace(chr(39), chr(39)*2)}'; "
    if work_dir:
        ps += f"$s.WorkingDirectory = '{work_dir.replace(chr(39), chr(39)*2)}'; "
    if icon_path and os.path.isfile(icon_path):
        ps += f"$s.IconLocation = '{icon_path.replace(chr(39), chr(39)*2)},0'; "
    if desc:
        ps += f"$s.Description = '{desc.replace(chr(39), chr(39)*2)}'; "
    ps += "$s.Save()"
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    return r.returncode == 0 and os.path.isfile(lnk_path)


def _register_win_uninstaller(install_dir, ico_path, uninst_cmd):
    """Register Shadow System HUD in Windows Settings -> Apps -> Installed Apps (HKCU)."""
    if not IS_WIN:
        return
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ShadowSystemHUD"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, "Shadow System HUD")
            winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, "2.0.0")
            winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, "Shadow Monarch System")
            winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, install_dir)
            winreg.SetValueEx(k, "DisplayIcon", 0, winreg.REG_SZ, ico_path)
            winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ, uninst_cmd)
            winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
    except Exception:
        pass


def perform_installation(install_dir=None, desktop_sc=True, startmenu_sc=True,
                         startup_sc=True, build_exe=False, log_fn=print):
    """Full installation pipeline for Shadow System HUD."""
    install_dir = os.path.abspath(install_dir or default_install_dir())
    os.makedirs(install_dir, exist_ok=True)
    log_fn(f"[1/5] Installing application files to: {install_dir}")

    src_script = os.path.abspath(__file__)
    dst_script = os.path.join(install_dir, "shadow_system_hud.py")
    with open(src_script, "r", encoding="utf-8") as f:
        src_txt = f.read()
    src_txt = re.sub(r"^DEFAULT_LAUNCH_INSTALLER\s*=\s*True", "DEFAULT_LAUNCH_INSTALLER = False", src_txt, flags=re.M)
    with open(dst_script, "w", encoding="utf-8") as f:
        f.write(src_txt)

    ico_path = os.path.join(install_dir, "shadow_hud.ico")
    try:
        generate_app_icon(ico_path)
        log_fn(f"[2/5] Generated custom Windows icon: {ico_path}")
    except Exception as e:
        log_fn(f"[2/5] Icon generation note: {e}")

    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    if not os.path.isfile(pyw):
        pyw = sys.executable

    vbs_launcher = os.path.join(install_dir, "Launch_Shadow_HUD.vbs")
    with open(vbs_launcher, "w", encoding="utf-8") as f:
        f.write(
            'Set WshShell = CreateObject("WScript.Shell")\r\n'
            f'WshShell.CurrentDirectory = "{install_dir}"\r\n'
            f'WshShell.Run """{pyw}"" ""{dst_script}""", 0, False\r\n'
        )

    bat_launcher = os.path.join(install_dir, "Launch_Shadow_HUD.bat")
    with open(bat_launcher, "w", encoding="utf-8") as f:
        f.write(f'@echo off\r\ncd /d "{install_dir}"\r\nstart "" "{pyw}" "{dst_script}" %*\r\n')

    uninst_bat = os.path.join(install_dir, "Uninstall_Shadow_HUD.bat")
    with open(uninst_bat, "w", encoding="utf-8") as f:
        f.write(f'@echo off\r\n"{sys.executable}" "{dst_script}" --uninstall\r\npause\r\n')

    exe_target = None
    if build_exe:
        log_fn("[3/5] Building standalone ShadowSystemHUD.exe via PyInstaller (this takes ~45-90s)...")
        try:
            r_pi = subprocess.run([sys.executable, "-m", "PyInstaller", "--version"],
                                  capture_output=True, text=True, creationflags=NO_WINDOW)
            if r_pi.returncode != 0:
                log_fn("      Installing pyinstaller via pip...")
                subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"],
                               capture_output=True, text=True, timeout=300, creationflags=NO_WINDOW)
            build_tmp = os.path.join(install_dir, "build_tmp")
            cmd = [
                sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--noconsole",
                "--name", "ShadowSystemHUD",
                "--distpath", install_dir,
                "--workpath", build_tmp,
                "--specpath", build_tmp,
            ]
            if os.path.isfile(ico_path):
                cmd.extend(["--icon", ico_path])
            cmd.append(dst_script)
            r_b = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                                 creationflags=NO_WINDOW)
            shutil.rmtree(build_tmp, ignore_errors=True)
            cand_exe = os.path.join(install_dir, "ShadowSystemHUD.exe" if IS_WIN else "ShadowSystemHUD")
            if r_b.returncode == 0 and os.path.isfile(cand_exe):
                exe_target = cand_exe
                log_fn(f"      SUCCESS: Built standalone executable -> {exe_target}")
            else:
                err_tail = (r_b.stderr or r_b.stdout or "")[-250:].strip()
                log_fn(f"      PyInstaller note (using pythonw launcher instead): {err_tail}")
        except Exception as e:
            log_fn(f"      PyInstaller skipped (using pythonw launcher): {e}")
    else:
        log_fn("[3/5] Configured zero-console pythonw.exe launcher.")

    sc_target = exe_target if exe_target else pyw
    sc_args = "" if exe_target else f'"{dst_script}"'

    log_fn("[4/5] Creating Windows shortcuts & registering application...")
    if IS_WIN:
        desktop_dir = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Desktop")
        if not os.path.isdir(desktop_dir):
            od = os.environ.get("OneDrive") or os.path.join(os.environ.get("USERPROFILE", ""), "OneDrive")
            if os.path.isdir(os.path.join(od, "Desktop")):
                desktop_dir = os.path.join(od, "Desktop")
        start_menu_dir = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                                      "Start Menu", "Programs")
        startup_dir = os.path.join(start_menu_dir, "Startup")

        if desktop_sc and os.path.isdir(desktop_dir):
            lnk = os.path.join(desktop_dir, "Shadow System HUD.lnk")
            if _create_win_shortcut(lnk, sc_target, sc_args, install_dir, ico_path,
                                    "Shadow System HUD - C Mastery Accountability Engine"):
                log_fn(f"      + Desktop shortcut created: {lnk}")
        if startmenu_sc and os.path.isdir(start_menu_dir):
            lnk = os.path.join(start_menu_dir, "Shadow System HUD.lnk")
            if _create_win_shortcut(lnk, sc_target, sc_args, install_dir, ico_path,
                                    "Shadow System HUD - C Mastery Accountability Engine"):
                log_fn(f"      + Start Menu shortcut created: {lnk}")
        if startup_sc and os.path.isdir(startup_dir):
            lnk = os.path.join(startup_dir, "Shadow System HUD.lnk")
            _create_win_shortcut(lnk, sc_target, sc_args, install_dir, ico_path,
                                 "Shadow System HUD Auto-Start")
            old_bat = os.path.join(startup_dir, "shadow_system_hud.bat")
            if os.path.isfile(old_bat):
                try:
                    os.remove(old_bat)
                except OSError:
                    pass
            log_fn(f"      + Windows Login Auto-Start enabled: {lnk}")

        _register_win_uninstaller(install_dir, ico_path, f'"{sys.executable}" "{dst_script}" --uninstall')

    cfg = load_json(CONFIG_PATH, DEFAULT_CONFIG)
    cc = find_compiler(cfg.get("compiler_exe", ""))
    if cc:
        cfg["compiler_exe"] = cc
    lv = find_lively(cfg.get("lively_exe", ""))
    if lv:
        cfg["lively_exe"] = lv
    save_json(CONFIG_PATH, cfg)
    log_fn(f"[5/5] Installation complete! Compiler: {cc or 'not detected'} | Lively: {lv or 'not detected'}")
    return dst_script, exe_target


def perform_uninstall(log_fn=print):
    """Remove shortcuts, startup entry, registry key, and program files (keeps player_state.json)."""
    install_dir = default_install_dir()
    if IS_WIN:
        desktop_dir = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Desktop")
        od = os.environ.get("OneDrive") or os.path.join(os.environ.get("USERPROFILE", ""), "OneDrive")
        start_menu_dir = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                                      "Start Menu", "Programs")
        startup_dir = os.path.join(start_menu_dir, "Startup")
        for p in (
            os.path.join(desktop_dir, "Shadow System HUD.lnk"),
            os.path.join(od, "Desktop", "Shadow System HUD.lnk"),
            os.path.join(start_menu_dir, "Shadow System HUD.lnk"),
            os.path.join(startup_dir, "Shadow System HUD.lnk"),
            os.path.join(startup_dir, "shadow_system_hud.bat"),
        ):
            if os.path.isfile(p):
                try:
                    os.remove(p)
                    log_fn(f"Removed shortcut: {p}")
                except OSError:
                    pass
        try:
            import winreg
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ShadowSystemHUD")
            log_fn("Removed Windows Installed Apps registry entry.")
        except Exception:
            pass
    if os.path.isdir(install_dir):
        try:
            shutil.rmtree(install_dir, ignore_errors=True)
            log_fn(f"Removed install directory: {install_dir}")
        except Exception as e:
            log_fn(f"Note: could not fully remove {install_dir}: {e}")
    log_fn(f"Uninstall complete. Your XP & progress are preserved in {APP_DIR}.")


def open_installer_gui(parent=None):
    """Graphical Setup Wizard for installing Shadow System HUD on Windows 11."""
    if tk is None:
        perform_installation()
        return
    own_root = parent is None
    if own_root:
        screen_size()
    print("Opening Shadow System HUD Setup Wizard window...", flush=True)
    win = tk.Tk() if own_root else tk.Toplevel(parent)
    win.title("Shadow System HUD — Setup Wizard")
    BG, PANEL, FG, MUTED, ACC = "#14110f", "#1f1a17", "#efe7d8", "#9a9086", "#d9483b"
    win.configure(bg=BG)
    win.deiconify()
    win.lift()
    win.attributes("-topmost", True)
    win.focus_force()
    win.after(1500, lambda: win.attributes("-topmost", False))
    sc = win.winfo_fpixels("1i") / 96.0
    W, H = int(600 * sc), int(520 * sc)
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry(f"{W}x{H}+{max(0, (sw - W) // 2)}+{max(0, (sh - H) // 2)}")

    tk.Label(win, text="S H A D O W   S Y S T E M   H U D", bg=BG, fg=ACC,
             font=("Segoe UI Semibold", 13)).pack(pady=(14, 2))
    tk.Label(win, text="Windows 11 Desktop Accountability & Audio-Synced Overlay Installer",
             bg=BG, fg=MUTED, font=("Georgia", 10, "italic")).pack(pady=(0, 10))

    frm = tk.Frame(win, bg=BG)
    frm.pack(fill="x", padx=22, pady=4)
    tk.Label(frm, text="Install Folder:", bg=BG, fg=FG, font=("Segoe UI", 9)).pack(anchor="w")
    dir_row = tk.Frame(frm, bg=BG)
    dir_row.pack(fill="x", pady=(2, 8))
    dir_var = tk.StringVar(value=default_install_dir())
    tk.Entry(dir_row, textvariable=dir_var, bg=PANEL, fg=FG, insertbackground=FG,
             relief="flat", font=("Consolas", 9)).pack(side="left", fill="x", expand=True, ipady=4)

    def pick_dir():
        p = filedialog.askdirectory(title="Choose Install Folder", initialdir=dir_var.get(), parent=win)
        if p:
            dir_var.set(p)

    tk.Button(dir_row, text="Browse...", command=pick_dir, bg=PANEL, fg=FG, relief="flat",
              font=("Segoe UI", 9), padx=10).pack(side="left", padx=(6, 0))

    v_desk = tk.BooleanVar(value=True)
    v_start = tk.BooleanVar(value=True)
    v_boot = tk.BooleanVar(value=True)
    v_cv2 = tk.BooleanVar(value=not have_cv2())
    v_exe = tk.BooleanVar(value=False)

    for var, txt in (
        (v_desk, "Create Desktop shortcut (Shadow System HUD.lnk with custom seal icon)"),
        (v_start, "Create Start Menu shortcut & register in Windows Installed Apps"),
        (v_boot, "Launch automatically when Windows starts (Startup folder)"),
        (v_cv2, "Install opencv-python (recommended for animated video wallpaper frame analysis)"),
        (v_exe, "Also compile standalone ShadowSystemHUD.exe via PyInstaller (~60s)"),
    ):
        tk.Checkbutton(frm, text=txt, variable=var, bg=BG, fg=FG, selectcolor=PANEL,
                       activebackground=BG, activeforeground=FG, anchor="w",
                       font=("Segoe UI", 9)).pack(fill="x", pady=1)

    log_box = tk.Text(win, height=8, bg=PANEL, fg=MUTED, relief="flat",
                      font=("Consolas", 9), state="disabled", wrap="word")
    log_box.pack(fill="both", expand=True, padx=22, pady=8)

    def wlog(msg):
        def _append():
            log_box.config(state="normal")
            log_box.insert("end", msg + "\n")
            log_box.see("end")
            log_box.config(state="disabled")
        win.after(0, _append)

    btn_bar = tk.Frame(win, bg=BG)
    btn_bar.pack(fill="x", padx=22, pady=(4, 14))

    install_btn = tk.Button(btn_bar, text="INSTALL & LAUNCH HUD", bg=ACC, fg="#14110f",
                            relief="flat", font=("Segoe UI Semibold", 11), padx=16, ipady=4)
    install_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

    def run_install_thread():
        install_btn.config(state="disabled", text="INSTALLING...")

        def worker():
            try:
                if v_cv2.get() and not have_cv2():
                    wlog("Installing opencv-python via pip...")
                    ok, msg = install_opencv()
                    wlog("opencv-python ready." if ok else f"opencv note: {msg}")
                dst_script, exe_path = perform_installation(
                    install_dir=dir_var.get(),
                    desktop_sc=v_desk.get(),
                    startmenu_sc=v_start.get(),
                    startup_sc=v_boot.get(),
                    build_exe=v_exe.get(),
                    log_fn=wlog,
                )
                wlog("\nREADY! Launching Shadow System HUD...")

                def finish():
                    install_btn.config(state="normal", text="INSTALLED!")
                    if own_root:
                        try:
                            if exe_path and os.path.isfile(exe_path):
                                subprocess.Popen([exe_path], cwd=os.path.dirname(exe_path))
                            else:
                                pyw = sys.executable.replace("python.exe", "pythonw.exe")
                                subprocess.Popen([pyw if os.path.isfile(pyw) else sys.executable, dst_script],
                                                 cwd=os.path.dirname(dst_script))
                        except Exception:
                            pass
                        win.after(800, win.destroy)
                    else:
                        messagebox.showinfo("Installed", "Shadow System HUD is installed on your system!", parent=win)
                win.after(300, finish)
            except Exception as e:
                wlog(f"ERROR: {e}")
                win.after(0, lambda: install_btn.config(state="normal", text="RETRY INSTALL"))

        threading.Thread(target=worker, daemon=True).start()

    install_btn.config(command=run_install_thread)
    tk.Button(btn_bar, text="Uninstall", command=lambda: threading.Thread(target=perform_uninstall, kwargs={"log_fn": wlog}, daemon=True).start(),
              bg=PANEL, fg=FG, relief="flat", font=("Segoe UI", 9), padx=10, ipady=4).pack(side="left", padx=4)
    tk.Button(btn_bar, text="Close", command=win.destroy, bg=PANEL, fg=FG, relief="flat",
              font=("Segoe UI", 9), padx=10, ipady=4).pack(side="left")

    wlog("Click 'INSTALL & LAUNCH HUD' to install shortcuts, custom icon, and startup entry.")
    if own_root:
        win.mainloop()


DEFAULT_LAUNCH_INSTALLER = False


def main():
    argv = sys.argv[1:]
    if "--install" in argv or "--setup" in argv:
        if "--gui" in argv and tk is not None:
            return open_installer_gui()
        dst_script, exe_path = perform_installation(
            build_exe="--build-exe" in argv,
            log_fn=lambda m: print(m, flush=True),
        )
        if "--no-launch" not in argv:
            print("\nLaunching Shadow System HUD now...", flush=True)
            try:
                if exe_path and os.path.isfile(exe_path):
                    subprocess.Popen([exe_path], cwd=os.path.dirname(exe_path))
                else:
                    pyw = sys.executable.replace("python.exe", "pythonw.exe")
                    target_py = pyw if os.path.isfile(pyw) else sys.executable
                    subprocess.Popen([target_py, dst_script, "--no-setup"],
                                     cwd=os.path.dirname(dst_script))
            except Exception as e:
                print(f"Launch note: {e}", flush=True)
        return
    if "--build-exe" in argv:
        perform_installation(build_exe=True)
        return
    if "--uninstall" in argv:
        perform_uninstall()
        return
    if "--install-startup" in argv:
        return install_startup()
    if "--gallery" in argv:
        return gallery(argv)
    if "--preview" in argv:
        return preview(argv)
    if DEFAULT_LAUNCH_INSTALLER and "--no-setup" not in argv:
        dst_script, exe_path = perform_installation(
            build_exe="--build-exe" in argv,
            log_fn=lambda m: print(m, flush=True),
        )
        print("\nLaunching Shadow System HUD GUI...", flush=True)
    if tk is None:
        sys.exit("tkinter is not available in this Python install.")
    screen_size()            # makes the process DPI-aware before any window exists
    root = tk.Tk()
    App(root, allow_exit="--allow-exit" in argv)
    root.mainloop()


if __name__ == "__main__":
    main()
