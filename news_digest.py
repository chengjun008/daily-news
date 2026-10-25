"""每天九点 · 微信新闻简报。仅使用 Python 标准库。"""
from __future__ import annotations

import argparse
import ctypes
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CST = timezone(timedelta(hours=8))
SOURCES = [
    ("国内", "中新网·时政", "https://www.chinanews.com.cn/rss/china.xml"),
    ("国内", "中新网·社会", "https://www.chinanews.com.cn/rss/society.xml"),
    ("国际", "中新网·国际", "https://www.chinanews.com.cn/rss/world.xml"),
]


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", value or ""))).strip()


def parse_feed(raw, category, source, now):
    root = ET.fromstring(raw)
    articles = []
    for item in root.findall(".//item"):
        title = clean(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        if not title or urlsplit(link).scheme not in ("https", "http"):
            continue
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "")
            if published.tzinfo is None:
                published = published.replace(tzinfo=CST)
        except (ValueError, TypeError, IndexError):
            continue  # 无法确认日期的条目不能冒充当日新闻。
        if not now - timedelta(hours=24) <= published <= now + timedelta(minutes=5):
            continue
        description = clean(item.findtext("description"))
        # 去掉常见电头，把有限篇幅用于新闻事实。
        description = re.sub(r"^(?:中新网|中新社)[^。]{0,45}?\d+日电\s*", "", description)
        sentences = re.split(r"(?<=[。！？])", description)
        summary = "".join(sentences[:2])[:240]
        if len(description) > len(summary):
            summary += "…"
        articles.append(dict(title=title, link=link, summary=summary,
                             category=category, source=source,
                             published=published.isoformat()))
    return articles


def request(url, data=None):
    req = Request(url, data=data, headers={"User-Agent": "DailyNewsDigest/1.0", "Accept": "*/*"})
    with urlopen(req, timeout=25) as response:
        return response.read(4_000_000)


def collect(now):
    articles, failures = [], []
    for category, source, url in SOURCES:
        try:
            items = parse_feed(request(url), category, source, now)
            if not items:
                failures.append(f"{source}：过去24小时无可用条目")
            articles.extend(items)
        except Exception:
            failures.append(f"{source}：暂时无法获取")
    return articles, failures


def select(articles, count=6):
    selected, seen = [], set()
    for item in sorted(articles, key=lambda a: a["published"], reverse=True):
        key = re.sub(r"\W", "", item["title"]).lower()
        if key in seen:
            continue
        seen.add(key)
        selected.append(item)
        if len(selected) == count:
            break
    return selected


def render(articles, failures, now):
    domestic = select([a for a in articles if a["category"] == "国内"])
    international = select([a for a in articles if a["category"] == "国际"])
    lines = [f"# 国内外新闻早报｜{now:%Y-%m-%d}",
             f"截至北京时间 {now:%m月%d日 %H:%M}，整理过去24小时新闻。", "",
             f"本期收录国内 {len(domestic)} 条、国际 {len(international)} 条，约 3 分钟读完。", "",
             "采用媒体 RSS 原摘要的前两句；无摘要时仅列标题。按发布时间筛选，并非全网热度排名。", ""]
    for category in ("国内", "国际"):
        lines += [f"## {category}新闻", ""]
        group = select([a for a in articles if a["category"] == category])
        if not group:
            lines += ["暂无可核实的新条目。", ""]
        for index, item in enumerate(group, 1):
            # 转义 Markdown 中的方括号，避免标题改变链接结构。
            title = item["title"].replace("[", "（").replace("]", "）")
            lines += [f"{index}. **{title}**", item["summary"] or "该条新闻未提供摘要，请查看原文。",
                      f"来源：{item['source']} · [阅读原文]({item['link']})", ""]
    if failures:
        lines += ["## 数据状态", *[f"- {f}" for f in failures], ""]
    return "\n".join(lines)


class Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.POINTER(ctypes.c_char))]


def protect(raw, decrypt=False):
    """Windows DPAPI：推送密钥只能由当前 Windows 用户解密。"""
    buf = ctypes.create_string_buffer(raw)
    src = Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = Blob()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    function.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
    function.restype = ctypes.c_int
    if not function(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(out)):
        raise OSError("无法处理本机加密凭据")
    try:
        return ctypes.string_at(out.data, out.size)
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(out.data)


def get_key():
    key = os.environ.get("SERVERCHAN_SENDKEY", "").strip()
    if not key and (DATA / "sendkey.bin").exists():
        key = protect((DATA / "sendkey.bin").read_bytes(), decrypt=True).decode()
    if not re.fullmatch(r"SCT[A-Za-z0-9]+", key):
        raise ValueError("未配置有效的 SCT 密钥：GitHub 请设置 SERVERCHAN_SENDKEY Secret；本机可在设置窗口保存")
    return key


def send(title, body):
    key = get_key()
    # 不自动重试：网络超时可能意味着服务端已接收，重试会产生重复消息。
    raw = request(f"https://sctapi.ftqq.com/{key}.send",
                  urlencode(dict(title=title, desp=body)).encode())
    result = json.loads(raw)
    if result.get("code") != 0:
        raise RuntimeError("推送服务未接收消息，请检查通道和额度")
    return result


def run(preview=False):
    DATA.mkdir(exist_ok=True)
    now = datetime.now(CST)
    state_path = DATA / "state.json"
    # 排他锁防止手动运行与计划任务同时推送。
    lock = DATA / "run.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError("另一个任务正在运行；若上次进程被强制结束，请手动删除 data/run.lock")
    try:
        os.close(fd)
        state = json.loads(state_path.read_text("utf-8")) if state_path.exists() else {}
        if not preview and state.get("date") == now.date().isoformat():
            return "今天的早报已经提交过，无需重复发送。"
        if not preview:
            get_key()
        articles, failures = collect(now)
        if not articles:
            raise RuntimeError("所有新闻源均无24小时内有效新闻，本次不发送；请检查网络或 RSS 源")
        body = render(articles, failures, now)
        (DATA / "latest.md").write_text(body, encoding="utf-8")
        if not preview:
            send(f"国内外新闻早报 {now:%m月%d日}", body)
            state = {"date": now.date().isoformat(), "submitted_at": now.isoformat(),
                     "status": "accepted"}
            temp = DATA / "state.tmp"
            temp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            temp.replace(state_path)
        return body
    finally:
        lock.unlink(missing_ok=True)


def gui():
    import tkinter as tk
    from tkinter import messagebox, scrolledtext
    win = tk.Tk()
    win.title("每天九点 · 微信新闻早报")
    win.geometry("800x640")
    tk.Label(win, text="每天九点 · 微信新闻早报", font=("Microsoft YaHei", 20)).pack(pady=16)
    tk.Label(win, text="北京时间 09:00｜国内 + 国际各最多 6 条｜过去 24 小时｜附原文链接").pack()
    tk.Label(win, text="1. 打开 sct.ftqq.com，微信登录并配置接收通道\n2. 将 SCT 开头的 SendKey 填在下方并保存\n3. 测试推送成功后，点击“启用每天 9 点”", justify="left").pack(pady=12)
    key = tk.StringVar()
    tk.Entry(win, textvariable=key, show="*", width=65).pack()
    status = tk.StringVar(value="密钥已保存" if (DATA / "sendkey.bin").exists() else "等待绑定微信接收通道")
    tk.Label(win, textvariable=status).pack(pady=6)
    buttons = tk.Frame(win)
    buttons.pack()
    output = scrolledtext.ScrolledText(win, wrap="word", font=("Microsoft YaHei", 10))
    output.pack(fill="both", expand=True, padx=16, pady=12)

    def save():
        value = key.get().strip()
        if not re.fullmatch(r"SCT[A-Za-z0-9]+", value):
            messagebox.showerror("密钥格式", "请填写 SCT 开头的 Server酱 Turbo SendKey")
            return
        DATA.mkdir(exist_ok=True)
        (DATA / "sendkey.bin").write_bytes(protect(value.encode()))
        key.set("")
        status.set("密钥已加密保存，可进行测试推送")

    def work(action):
        for button in buttons.winfo_children():
            button.config(state="disabled")
        status.set("正在处理，请稍候…")
        def complete(message):
            output.delete("1.0", "end")
            output.insert("end", message)
            status.set("操作完成")
            for button in buttons.winfo_children():
                button.config(state="normal")
        def worker():
            try:
                message = action()
            except Exception as exc:
                # 不显示可能包含密钥的网络异常 URL。
                message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "操作失败，请检查网络、权限及推送通道。"
            win.after(0, complete, str(message))
        threading.Thread(target=worker, daemon=True).start()

    def schedule():
        get_key()
        result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                 "-File", str(ROOT / "schedule.ps1"), "-PythonPath", sys.executable],
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode:
            raise RuntimeError("注册计划任务失败；请参照 README 手动注册，或使用服务器定时任务。")
        return "已启用每天北京时间 9 点任务。\n电脑需开机联网；关机期间不会实时发送，恢复后由系统尝试补跑。\n请在任务计划程序中查看 WeChatDailyNews-0900。"

    for label, action in [("保存密钥", save), ("预览今日早报", lambda: work(lambda: run(True))),
                          ("测试微信推送", lambda: work(lambda: (send("新闻早报连接测试", "绑定成功，每天北京时间9点为你整理国内外新闻。"), "服务端已接收测试消息，请在微信确认实际收到。")[1])),
                          ("立即发送早报", lambda: work(lambda: run())),
                          ("启用每天 9 点", lambda: work(schedule))]:
        tk.Button(buttons, text=label, command=action).pack(side="left", padx=3)
    win.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()
    if not (args.preview or args.send):
        gui()
        return
    try:
        print(run(preview=args.preview))
    except Exception as exc:
        DATA.mkdir(exist_ok=True)
        message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "网络或文件操作失败，请检查连接与配置"
        with (DATA / "errors.log").open("a", encoding="utf-8") as log:
            log.write(f"{datetime.now(CST).isoformat()} {message}\n")
        print(message, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
