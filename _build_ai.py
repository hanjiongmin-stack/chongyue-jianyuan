
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
os.chdir(r"D:\Claude\制作中心")

css = """
:root{--bg:#fbfbfa;--fg:#1a1a18;--fg2:rgba(26,26,24,.7);--fg3:rgba(26,26,24,.45);--muted:#6b6b66;--border:rgba(26,26,24,.1);--surface:#fff;--accent:#6366f1;--green:#16a34a;--red:#dc2626;--amber:#d97706}
[data-theme=dark]{--bg:#111110;--fg:#f0f0ee;--fg2:rgba(240,240,238,.7);--fg3:rgba(240,240,238,.45);--muted:#8a8a86;--border:rgba(240,240,238,.12);--surface:#1a1a18}
body{font-family:Instrument Sans,system-ui,Microsoft YaHei,sans-serif;background:var(--bg);color:var(--fg);line-height:1.6;-webkit-font-smoothing:antialiased}
"""
print("Script created")
