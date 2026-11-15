import os, json, time, requests

POS = json.loads(os.environ["POSITIONS"])
NTFY = "https://ntfy.sh/" + os.environ["NTFY_TOPIC"]
GTA6_MINT = "4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz"
PUMP_MINTS = [
    "De9JHwfE4yrKkxj6BUVCiZyDHcpVHSgq8TwymWj7pump",
    "AdgKxsUpJTq218bbzuSXdXVw5DvgLfM1Q8aNxC7Zpump",
    "5Kjxg6X13axntM98AxJGjNQCB82YZWhSnvJVX78cpump",
    "CfNmk6r5zDChpbmYtqmv5aEcPptqaqh93kBpmbDrpump",
    "nxPqZ4F7ux8Vph5NFu25rEP6Kx9Gr1U6Fmj36Rjpump",
]
SELL_AT = 0.25      # sell signal: 25% above your average (unless a coin has its own "sell" line)
DROP_AT = 0.60      # drop alert: 60% below your average
DIGEST_HOURS = 6


def money(n):
    if n >= 1e6: return f"${n/1e6:.2f}M"
    if n >= 1e3: return f"${n/1e3:.1f}K"
    return f"${n:.0f}"


def sgn(n):
    return f"{n:+.0f}%"


def match_name(sym, nm):
    s, n = (sym or "").upper(), (nm or "").upper()
    for k in POS:
        if s == k or n == k or n.startswith(k):
            return k
    return s or "UNKNOWN"


def get_markets():
    out = []
    try:
        r = requests.get(f"https://stonkfun.xyz/api/public/v1/tokens/{GTA6_MINT}", timeout=20).json()["data"]["token"]["market"]
        out.append(dict(name="GTA6", cap=r["marketCapUsd"], chg=r.get("priceChange24h"), vol=r.get("volume24hUsd"), liq=None))
    except Exception as e:
        print("GTA6 error:", e)
    for mint in PUMP_MINTS:
        try:
            j = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{mint}", timeout=20).json()
            pairs = [p for p in (j.get("pairs") or []) if p.get("chainId") == "solana"]
            pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0, reverse=True)
            if not pairs:
                print("No data for", mint)
                continue
            p = pairs[0]
            t = p.get("baseToken") or {}
            out.append(dict(name=match_name(t.get("symbol"), t.get("name")),
                            cap=p.get("marketCap") or p.get("fdv"),
                            chg=(p.get("priceChange") or {}).get("h24"),
                            vol=(p.get("volume") or {}).get("h24"),
                            liq=(p.get("liquidity") or {}).get("usd")))
        except Exception as e:
            print("Error", mint, e)
    return out


def analyze(m, c):
    ratio = m["cap"] / c["avg"]
    pct = (ratio - 1) * 100
    need = (1 / ratio - 1) * 100
    sell_line = c.get("sell", c["avg"] * (1 + SELL_AT))
    if m["cap"] >= sell_line:
        state = "sell"
    elif ratio <= 1 - DROP_AT:
        state = "drop"
    else:
        state = "mid"
    add = c["cost"] * 0.25 / (0.75 / ratio - 1) if ratio < 0.75 else 0
    if state == "sell":
        lean = f"SELL signal - above your sell line of {money(sell_line)}. Consider taking profit, all or part."
    elif need >= 200:
        lean = (f"Needs {need/100+1:.1f}x just to break even. Adding money rarely fixes a hole this deep - "
                "the numbers favor holding without adding, or cutting losses.")
    elif ratio < 1:
        lean = "Adding lowers your average but raises your risk. If you add, cap it at money you can afford to lose."
    else:
        lean = f"In profit vs your average. Sell line: {money(sell_line)}."
    liq = m.get("liq")
    if liq is not None and liq < 10000:
        lean += " Thin liquidity - selling may move the price a lot."
    return dict(pct=pct, need=need, state=state, add=add, lean=lean)


def detail(name, m, c, a):
    lines = [f"{name} is {money(m['cap'])} ({sgn(a['pct'])} vs your avg {money(c['avg'])})"]
    if a["pct"] < 0:
        lines.append(f"Break-even needs {sgn(a['need'])}.")
    if a["add"]:
        lines.append(f"To cut your avg 25% you'd add about ${a['add']:.0f} ({a['add']/c['cost']*100:.0f}% of what's in).")
    chg = "n/a" if m.get("chg") is None else sgn(m["chg"])
    extra = f", liquidity {money(m['liq'])}" if m.get("liq") is not None else ""
    lines.append(f"24h: {chg}, volume {money(m.get('vol') or 0)}{extra}")
    lines.append(a["lean"])
    lines.append("Not financial advice.")
    return "\n".join(lines)


def send(title, body, priority, tags):
    requests.post(NTFY, data=body.encode("utf-8"),
                  headers={"Title": title, "Priority": priority, "Tags": tags}, timeout=20)


try:
    state = json.load(open("state.json"))
except Exception:
    state = {}
last = state.get("states", {})
lines = []

for m in get_markets():
    c = POS.get(m["name"])
    if not c or not m.get("cap"):
        print("Skipped:", m["name"])
        continue
    a = analyze(m, c)
    tag = "SELL" if a["state"] == "sell" else ("ALERT" if a["state"] == "drop" else "watch")
    chg = "n/a" if m.get("chg") is None else sgn(m["chg"])
    lines.append(f"{m['name']} {money(m['cap'])} {sgn(a['pct'])} vs avg | 24h {chg} | {tag}")
    if a["state"] != "mid" and a["state"] != last.get(m["name"]):
        send(m["name"] + (" - SELL signal" if a["state"] == "sell" else " - DROP alert"),
             detail(m["name"], m, c, a),
             "high" if a["state"] == "sell" else "urgent",
             "moneybag" if a["state"] == "sell" else "rotating_light")
    last[m["name"]] = a["state"]

state["states"] = last
now = time.time()
force = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
if lines and (force or now - state.get("digest", 0) > DIGEST_HOURS * 3600):
    send("Market digest", "\n".join(lines) + "\nNot financial advice.", "default", "chart_with_downwards_trend")
    state["digest"] = now
json.dump(state, open("state.json", "w"))
