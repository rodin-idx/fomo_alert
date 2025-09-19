import time
import requests
import subprocess
import json
import datetime
from colorama import Fore, Style, init
import os

os.system("clear")
init(autoreset=True)

# === Mode Environment ===
IS_CLOUD = True   # set True kalau di VPS/Google Cloud, False kalau di PC/Termux

# === Parameter ===
BASE_FILTER = "idr"
MAX_PRICE = 1_000_000
MIN_VOL_IDR = 10_000_000
VOL_MULTIPLIER = 1.2
ORDER_IMB_RATIO = 1.1
INTERVAL_SEC = 10
CANDLE_LIMIT = 20
MAX_DEPTH_PAIRS = 12
DEPTH_DELAY = 0.2
PUMP_THRESHOLD = 1.0
HISTORY_LIMIT = 20

# === Telegram ===
TOKEN = "8045460542:AAF_nZp2mcVr-tT80vc150iHITlbAV_-O0I"
CHAT_ID = "6012081416"

vol_history = {}
price_history = {}
loop_count = 0

def format_num(n):
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.1f}B"
    elif n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n/1_000:.1f}K"
    else:
        return str(round(n, 2))

def send_telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=5
        )
    except Exception as e:
        print(Fore.YELLOW + "⚠️ Gagal kirim Telegram:", e)

def safe_get_json(url, desc):
    try:
        r = requests.get(url, timeout=10)
        text = r.text.strip()
        if "too_many_requests_from_your_ip" in text:
            print(Fore.RED + f"⛔ LIMIT API saat ambil {desc}")
            return {}
        try:
            data = r.json()
        except json.JSONDecodeError:
            print(Fore.YELLOW + f"⚠️ RESPON BUKAN JSON saat ambil {desc}: {text[:80]}...")
            return {}
        if isinstance(data, dict) and "error" in data:
            print(Fore.YELLOW + f"⚠️ ERROR API {desc}: {data.get('error_description', data['error'])}")
            return {}
        return data
    except requests.exceptions.RequestException as e:
        print(Fore.YELLOW + f"⚠️ GAGAL KONEKSI saat ambil {desc}: {e}")
        return {}

pairs_info = safe_get_json("https://indodax.com/api/pairs", "daftar pair")
pair_map = {p["ticker_id"]: p["id"] for p in pairs_info if p.get("is_maintenance") == 0}

while True:
    try:
        os.system("clear")
        msgs = []
        loop_count += 1
        now = datetime.datetime.now().strftime("%H:%M:%S")
        print(Fore.GREEN + Style.BRIGHT + "  <<< ✓✓ BOT FOMO INDODAX ✓✓ >>>")
        print(Fore.YELLOW + f"\n  [{now}] Loop ke-{loop_count}")

        tickers_data = safe_get_json("https://indodax.com/api/summaries", "summaries")
        tickers = tickers_data.get("tickers", {})

        candidates = []
        for pair, d in tickers.items():
            if BASE_FILTER and not pair.endswith(f"_{BASE_FILTER}"):
                continue

            last = float(d["last"])
            vol_idr = float(d.get("vol_idr", 0))

            if last > MAX_PRICE or vol_idr < MIN_VOL_IDR:
                continue

            # Simpan histori harga
            if pair not in price_history:
                price_history[pair] = []
            price_history[pair].append(last)
            if len(price_history[pair]) > HISTORY_LIMIT:
                price_history[pair].pop(0)

            # Hitung kenaikan
            if len(price_history[pair]) >= 2:
                old_price = price_history[pair][0]
                pct_1h = ((last - old_price) / old_price * 100) if old_price > 0 else 0
                pump_1h = pct_1h >= PUMP_THRESHOLD
            else:
                pump_1h = False
                pct_1h = 0

            if pump_1h:
                candidates.append((pair, vol_idr, last, pct_1h))

        candidates.sort(key=lambda x: x[1], reverse=True)
        selected_pairs = candidates[:MAX_DEPTH_PAIRS]
        durasi_menit = (HISTORY_LIMIT * INTERVAL_SEC) / 60

        print(Fore.BLUE + Style.BRIGHT + "\n" + "=" * 50)
        print(f"  Kandidat awal FOMO (kenaikan {durasi_menit:.0f} menit ≥{PUMP_THRESHOLD}%):")

        signals_found = 0

        for idx, (pair, vol_idr, last, pct) in enumerate(selected_pairs, start=1):
            print(Fore.BLUE + f"    [{idx}/{len(selected_pairs)}] {pair}: {format_num(last)} IDR (+{pct:.2f}%)")

            vol_idr = float(vol_idr)

            if pair not in vol_history:
                vol_history[pair] = []
            vol_history[pair].append(vol_idr)
            if len(vol_history[pair]) > CANDLE_LIMIT:
                vol_history[pair].pop(0)

            vol_history[pair] = [float(v) for v in vol_history[pair]]
            avg_vol = sum(vol_history[pair]) / len(vol_history[pair])
            vol_signal = vol_idr > avg_vol * VOL_MULTIPLIER

            if vol_signal:
                print(Fore.GREEN + f"     ✅ Volume spike OK ({vol_idr/avg_vol:.2f}x > {VOL_MULTIPLIER}x)")
            else:
                print(Fore.RED + f"     ❌ Volume spike kurang ({vol_idr/avg_vol:.2f}x < {VOL_MULTIPLIER}x)")

            ob = safe_get_json(f"https://indodax.com/api/depth/{pair_map.get(pair, '')}", f"orderbook {pair}")
            buy_orders = ob.get("buy", [])
            sell_orders = ob.get("sell", [])

            buy_total = sum(float(b[0]) * float(b[1]) for b in buy_orders)
            sell_total = sum(float(s[0]) * float(s[1]) for s in sell_orders)
            ob_signal = buy_total > sell_total * ORDER_IMB_RATIO
            ratio_ob = (buy_total / sell_total) if sell_total > 0 else 0

            if ob_signal:
                print(Fore.GREEN + f"     ✅ Orderbook imbalance OK (ratio {ratio_ob:.2f} > {ORDER_IMB_RATIO})")
            else:
                print(Fore.RED + f"     ❌ Orderbook imbalance kurang (ratio {ratio_ob:.2f} < {ORDER_IMB_RATIO})")

            if vol_signal and ob_signal:
                signals_found += 1
                msg = (f"  🚨 AWAL FOMO DETECTED [{pair.upper()}]\n"
                       f"     Harga: {format_num(last)} (+{pct:.2f}% dalam 1 jam)\n"
                       f"     Volume: {format_num(vol_idr)}\n"
                       f"     Buy/Sell: {format_num(buy_total)} / {format_num(sell_total)}")
                msgs.append(msg)

                if not IS_CLOUD:
                    try:
                        subprocess.Popen(["python", "sound.py", f"FOMO {pair.upper()}"])
                    except Exception as e:
                        print(Fore.YELLOW + "⚠️ Gagal play suara:", e)
                else:
                    print(Fore.CYAN + f"🔔 ALERT FOMO {pair.upper()} (skip sound di cloud)")

                send_telegram(msg)

            time.sleep(DEPTH_DELAY)

        print(Fore.BLUE + Style.BRIGHT + "=" * 50 + "\n")

        # Statistik loop
        total_checked = len(tickers)
        pump_count = len(candidates)
        vol_spike_count = 0
        ob_imb_count = 0

        for pair, vol_idr, last, pct in selected_pairs:
            avg_vol = sum(vol_history[pair]) / len(vol_history[pair])
            if vol_idr > avg_vol * VOL_MULTIPLIER:
                vol_spike_count += 1

            ob = safe_get_json(f"https://indodax.com/api/depth/{pair_map.get(pair, '')}", f"orderbook {pair}")
            buy_orders = ob.get("buy", [])
            sell_orders = ob.get("sell", [])
            buy_total = sum(float(b[0]) * float(b[1]) for b in buy_orders)
            sell_total = sum(float(s[0]) * float(s[1]) for s in sell_orders)
            if buy_total > sell_total * ORDER_IMB_RATIO:
                ob_imb_count += 1

        print(f"    📊 Statistik loop:")
        print(f"       Total pair dicek: {total_checked}")
        print(f"       Naik ≥{PUMP_THRESHOLD}%: {pump_count}")
        print(f"       Lolos volume spike: {vol_spike_count}")
        print(f"       Lolos orderbook imbalance: {ob_imb_count}")
        print(f"       Sinyal aktif: {signals_found}")

        print(Fore.BLUE + Style.BRIGHT + "\n" + "=" * 50)
        print(f"  Kandidat akhir FOMO:")
        for m in msgs:
            print(Fore.GREEN + Style.BRIGHT + m)
        print(Fore.BLUE + Style.BRIGHT + "=" * 50 + "\n")
        print(Fore.YELLOW + f"  ✅ Loop selesai — {signals_found} sinyal aktif\n")

        time.sleep(INTERVAL_SEC)

    except Exception as e:
        print(Fore.YELLOW + f"⚠️ Error loop utama: {e}")
        time.sleep(2)
