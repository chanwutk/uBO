#!/usr/bin/env python3
"""Inspect YouTube's *rendered* DOM to find/verify cosmetic-filter selectors.

YouTube is a JS single-page app: the real elements (and class names like
`media-item-thumbnail-container`) only exist after client-side render, so curl /
view-source only shows a loader shell + a `ghost-*` skeleton. This drives headless
Brave (Chromium) over the DevTools Protocol with an iPhone user-agent (so YouTube
serves m.youtube.com) and reports what your selectors actually match.

`--dump-dom` is deliberately NOT used: YouTube's continuous timers stop Chromium's
virtual-time budget from ever completing, so it hangs. CDP + polling avoids that.

Usage:
  python3 inspect-dom.py [URL] [SELECTOR ...] [--desktop] [--port N]

Examples:
  # default summary (legacy vs lockup, thumbnail + avatar candidates) on a search page
  python3 inspect-dom.py

  # verify a specific selector matches real video items, with its ancestor chain
  python3 inspect-dom.py 'https://m.youtube.com/results?search_query=lofi' \
      'a.media-item-thumbnail-container' \
      'ytm-video-with-context-renderer ytm-channel-thumbnail-with-link-renderer'

  # desktop site
  python3 inspect-dom.py --desktop 'https://www.youtube.com/results?search_query=lofi' \
      'a.ytLockupViewModelContentImage'

Notes:
  * The logged-out *home* feed is empty ("history is off") -> use /results?search_query=...
    or a /watch?v=... page; they render the same video components the home feed uses.
  * Override the browser with BRAVE_BIN=/path/to/chromium-or-brave.
"""
import base64, json, os, socket, struct, subprocess, sys, time, urllib.request, shutil

MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1")
DESKTOP_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
BRAVE = os.environ.get("BRAVE_BIN", "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")


def parse_args(argv):
    desktop = "--desktop" in argv
    argv = [a for a in argv if a != "--desktop"]
    port = 9222
    if "--port" in argv:
        i = argv.index("--port"); port = int(argv[i + 1]); del argv[i:i + 2]
    url, sels = None, []
    for a in argv:
        if a.startswith("http"):
            url = a
        else:
            sels.append(a)
    if not url:
        host = "www.youtube.com" if desktop else "m.youtube.com"
        url = f"https://{host}/results?search_query=lofi+hip+hop"
    return url, sels, desktop, port


class CDP:
    """Minimal stdlib DevTools-Protocol client (launches + drives headless Brave)."""

    def __init__(self, ua, port):
        self.port = port
        self.profile = f"/tmp/bprof_inspect_{port}"
        shutil.rmtree(self.profile, ignore_errors=True)
        self.proc = subprocess.Popen(
            [BRAVE, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
             f"--user-data-dir={self.profile}", f"--user-agent={ua}", "--window-size=412,915",
             f"--remote-debugging-port={port}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ws = self._wait_ws()
        self.sock = self._connect(ws)
        self._id = 0
        self.cmd("Page.enable"); self.cmd("Runtime.enable"); self.cmd("Network.enable")
        # consent cookie so EU-style interstitials don't block rendering
        self.cmd("Network.setCookie", name="SOCS",
                 value="CAESHAgBEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmVuIAEaBgiAo_CmBg",
                 domain=".youtube.com", path="/")

    def _http(self, path):
        return json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5))

    def _wait_ws(self):
        for _ in range(60):
            try:
                for t in self._http("/json"):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
            except Exception:
                pass
            time.sleep(0.3)
        raise RuntimeError("DevTools endpoint never came up (is Brave installed? set BRAVE_BIN)")

    def _connect(self, ws):
        path = ws.split(f":{self.port}", 1)[1]
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nUpgrade: websocket\r\n"
                   f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                   f"Sec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += s.recv(4096)
        return s

    def _send(self, obj):
        p = json.dumps(obj).encode()
        h = bytearray([0x81]); n = len(p)
        if n < 126:
            h.append(0x80 | n)
        elif n < 65536:
            h.append(0x80 | 126); h += struct.pack(">H", n)
        else:
            h.append(0x80 | 127); h += struct.pack(">Q", n)
        m = os.urandom(4); h += m
        self.sock.sendall(bytes(h) + bytes(b ^ m[i % 4] for i, b in enumerate(p)))

    def _readn(self, n):
        d = b""
        while len(d) < n:
            chunk = self.sock.recv(n - len(d))
            if not chunk:
                raise RuntimeError("socket closed")
            d += chunk
        return d

    def _recv(self):
        frame = b""
        while True:
            b0, b1 = self._readn(2)
            ln = b1 & 0x7f
            if ln == 126:
                ln = struct.unpack(">H", self._readn(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", self._readn(8))[0]
            frame += self._readn(ln)
            if b0 & 0x80:  # FIN
                op = b0 & 0x0f
                if op in (1, 0):
                    return json.loads(frame)
                frame = b""  # ignore non-text control frames

    def cmd(self, method, **params):
        self._id += 1
        i = self._id
        self._send({"id": i, "method": method, "params": params})
        while True:
            m = self._recv()
            if m.get("id") == i:
                return m

    def evaluate(self, expr):
        r = self.cmd("Runtime.evaluate", expression=expr, returnByValue=True)
        try:
            return json.loads(r["result"]["result"]["value"])
        except Exception:
            return None

    def close(self):
        try:
            self.proc.terminate()
        except Exception:
            pass


PROBE = r"""(function(){
function chain(el){var c=[],e=el;for(var k=0;k<8&&e;k++){c.push(e.tagName+(e.className?'.'+(''+e.className).trim().split(/\s+/).join('.'):''));e=e.parentElement;}return c;}
function info(el){return el?{tag:el.tagName,cls:(''+el.className),html:el.outerHTML.replace(/\s+/g,' ').slice(0,300),chain:chain(el)}:null;}
var SELS = __SELS__;
var out={url:location.href,ready:!!document.querySelector('ytm-video-with-context-renderer,ytd-rich-item-renderer,yt-lockup-view-model'),matches:{}};
if(SELS.length){SELS.forEach(function(s){var n=document.querySelectorAll(s);out.matches[s]={count:n.length,first:info(n[0])};});}
else{
 out.lockup_active=!!document.querySelector('yt-lockup-view-model,[class*=ockup-view-model],.ytLockupViewModelContentImage');
 var ref={'thumb (legacy mobile)':'a.media-item-thumbnail-container','thumb (lockup)':'.ytLockupViewModelContentImage,.yt-lockup-view-model__content-image','avatar (mobile)':'ytm-channel-thumbnail-with-link-renderer','avatar (lockup)':'.ytLockupMetadataViewModelAvatar,.yt-lockup-metadata-view-model__avatar'};
 Object.keys(ref).forEach(function(k){out.matches[k]={count:document.querySelectorAll(ref[k]).length,first:info(document.querySelector(ref[k]))};});
}
return JSON.stringify(out);})()"""


def main():
    url, sels, desktop, port = parse_args(sys.argv[1:])
    ua = DESKTOP_UA if desktop else MOBILE_UA
    expr = PROBE.replace("__SELS__", json.dumps(sels))
    cdp = CDP(ua, port)
    try:
        cdp.cmd("Page.navigate", url=url)
        result = None
        for _ in range(35):  # ~25s
            v = cdp.evaluate(expr)
            if v and (v.get("ready") or any(m["count"] for m in v.get("matches", {}).values())):
                result = v
                if not sels or any(m["count"] for m in v["matches"].values()):
                    break
            time.sleep(0.7)
        print(json.dumps(result or {"url": url, "error": "page never rendered video items"}, indent=2))
    finally:
        cdp.close()


if __name__ == "__main__":
    main()
