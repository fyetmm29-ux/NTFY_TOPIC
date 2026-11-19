import os, json, math, requests

NTFY = "https://ntfy.sh/" + os.environ["NTFY_TOPIC"]
MINT = "9hjBLBrc7WZW2H8UQvBAvG5WiTZotXUv2Bdcn4f4pump"
STEP = 500000          # alert at every $0.5M level
LOW_ZONE = 11000000    # alert on levels at or below $11M
HIGH_ZONE = 13000000   # alert on levels at or above $13M


def money(n):
    return f"${n/1e6:.2f}M"


def worthy(level):
    return level <= LOW_ZONE or level >= HIGH_ZONE


def send(title, body, priority, tags):
    requests.post(NTFY, data=body.encode("utf-8"),
                  headers={"Title": title, "Priority": priority, "Tags": tags}, timeout=20)


try:
    j = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{MINT}", timeout=20).json()
    pairs = [p for p in (j.get("pairs") or []) if p.get("chainId") == "solana"]
    pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0, reverse=True)
    p = pairs[0]
    cap = p.get("marketCap") or p.get("fdv")
    chg = (p.get("priceChange") or {}).get("h24")
    vol = (p.get("volume") or {}).get("h24")
except Exception as e:
    print("Data error:", e)
    raise SystemExit(0)

try:
    state = json.load(open("dcty_state.json"))
except Exception:
    state = {}

band = math.floor(cap / STEP)
last = state.get("band")
force = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"

if last is not None and band != last:
    if band > last:
        crossed = [i * STEP for i in range(last + 1, band + 1)]
        direction = "UP"
    else:
        crossed = [i * STEP for i in range(band + 1, last + 1)]
        direction = "DOWN"
    hits = [l for l in crossed if worthy(l)]
    if hits:
        level = max(hits) if direction == "UP" else min(hits)
        msg = f"DCTY crossed {money(level)} going {direction.lower()} - now {money(cap)}"
        if len(hits) > 1:
            msg += f" (passed {len(hits)} levels)"
        extra = []
        if chg is not None:
            extra.append(f"24h: {chg:+.0f}%")
        if vol:
            extra.append(f"volume ${vol/1e6:.1f}M")
        if extra:
            msg += "\n" + ", ".join(extra)
        send(f"DCTY {direction} {money(level)}", msg, "high",
             "chart_with_upwards_trend" if direction == "UP" else "chart_with_downwards_trend")

if force:
    nxt = (band + 1) * STEP
    while not worthy(nxt):
        nxt += STEP
    prv = band * STEP
    while not worthy(prv):
        prv -= STEP
    send("DCTY status", f"DCTY is {money(cap)}.\nNext alert up: {money(nxt)}. Next alert down: {money(prv)}.",
         "default", "mag")

state["band"] = band
json.dump(state, open("dcty_state.json", "w"))
