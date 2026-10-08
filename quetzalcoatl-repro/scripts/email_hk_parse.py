"""Parse HyperKitty (Mailman 3) message and thread-index pages saved to disk.

Used while drafting the tor-relays follow-up email, to list the public replies in the
existing threads. Standard library only; reads only the files passed on the command line and
treats their content as data.

Usage:
  python3 -I scripts/email_hk_parse.py msg FILE...      # one HyperKitty /message/<ID>/ page each
  python3 -I scripts/email_hk_parse.py index FILE...    # a /YYYY/MM/ archive or latest-threads page
  python3 -I scripts/email_hk_parse.py search FILE...   # a HyperKitty /search?q=... results page

For "msg" it prints, per file: the HyperKitty message id, subject (h1), author, displayed date
and time (HyperKitty shows UTC), the "Sender's time" tooltip, the RFC 5322 Message-ID (taken from
the "Use email software" mailto link, whose In-Reply-To is the message's own Message-ID), and the
plain-text body with quoted blocks marked "> ". For "index" it prints every thread link with its
title as shown.
"""
import html
import re
import sys
import urllib.parse


def text(fragment):
    fragment = re.sub(r"<script.*?</script>", "", fragment, flags=re.S)
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    fragment = re.sub(r"</p>", "\n", fragment)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    fragment = html.unescape(fragment).replace("\xa0", " ")
    fragment = re.sub(r"[ \t]+", " ", fragment)
    return re.sub(r"\n\s*\n+", "\n", fragment).strip()


def parse_msg(path):
    h = open(path, encoding="utf-8", errors="replace").read()
    out = {}
    m = re.search(r'<div id="([A-Z0-9]{32})" class="email-header"', h)
    out["hk_id"] = m.group(1) if m else None
    m = re.search(r"<h1>(.*?)</h1>", h, re.S)
    out["subject"] = text(m.group(1)) if m else None
    m = re.search(r'title="See the profile for [^"]*"\s*>(.*?)</a>', h, re.S)
    if not m:
        m = re.search(r'<h2 class="name">(.*?)</h2>', h, re.S)
    out["author"] = text(m.group(1)) if m else None
    m = re.search(r'<span class="date d-none d-sm-inline">(.*?)</span>', h, re.S)
    out["date"] = " ".join(text(m.group(1)).split()) if m else None
    m = re.search(r'<span title="Sender\'s time: ([^"]*)">([^<]*)</span>', h)
    out["time_utc_displayed"] = m.group(2).strip() if m else None
    out["sender_time"] = m.group(1) if m else None
    m = re.search(r"In-Reply-To=([^\"&]*(?:&lt;|<)[^\"]*?(?:&gt;|>))", h)
    if m:
        out["message_id"] = urllib.parse.unquote(html.unescape(m.group(1)).replace("In-Reply-To=", ""))
    else:
        m = re.search(r"In-Reply-To=([^\"]*)", h)
        out["message_id"] = urllib.parse.unquote(html.unescape(m.group(1))) if m else None
    m = re.search(r'<div class="email-body[^"]*">(.*?)<div class="email-info">', h, re.S)
    body = ""
    if m:
        b = m.group(1)
        b = re.sub(r'<div class="quoted-switch">.*?</div>', "", b, flags=re.S)
        b = re.sub(r"<blockquote[^>]*>(.*?)</blockquote>",
                   lambda q: "\n" + "\n".join("> " + ln for ln in text(q.group(1)).splitlines()) + "\n",
                   b, flags=re.S)
        body = text(b)
    out["body"] = body
    att = re.findall(r'href="([^"]*/attachment/[^"]*)"', h)
    out["attachments"] = sorted(set(att))
    return out


def parse_index(path):
    h = open(path, encoding="utf-8", errors="replace").read()
    seen = []
    for m in re.finditer(r'<a [^>]*href="([^"]*/thread/[A-Z0-9]{32}/)"[^>]*>(.*?)</a>', h, re.S):
        t = " ".join(text(m.group(2)).split())
        if t and (m.group(1), t) not in seen:
            seen.append((m.group(1), t))
    return seen


def parse_search(path):
    """Search-result pages carry the full sender timestamp (UTC, to the second) in a title."""
    h = open(path, encoding="utf-8", errors="replace").read()
    rows = []
    for c in re.split(r'(?=<div class="thread">)', h)[1:]:
        m = re.search(r'<a name="([A-Z0-9]{32})"\s*href="([^"]+)"\s*>(.*?)</a>', c, re.S)
        if not m:
            continue
        a = re.search(r"<!--\s*(.*?)\s*-->", c)
        ts = re.search(r'title="(\w+day, \d+ \w+ \d{4} \d\d:\d\d:\d\d)"', c)
        rows.append((ts.group(1) if ts else None, a.group(1) if a else None, m.group(1),
                     " ".join(text(m.group(3)).split())))
    return rows


def main():
    mode, files = sys.argv[1], sys.argv[2:]
    for f in files:
        print("=" * 30, f)
        if mode == "search":
            for row in parse_search(f):
                print(" | ".join(str(x) for x in row))
        elif mode == "msg":
            r = parse_msg(f)
            for k in ("hk_id", "subject", "author", "date", "time_utc_displayed", "sender_time",
                      "message_id", "attachments"):
                print(f"{k}: {r[k]}")
            print("body:\n" + r["body"])
        else:
            for url, t in parse_index(f):
                print(url, "|", t)


if __name__ == "__main__":
    main()
