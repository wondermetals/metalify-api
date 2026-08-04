import json
import re
import time
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, urlencode, urlparse
import os

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception


HOST = "127.0.0.1"
PORT = 8000
BASE_DIR = Path(__file__).resolve().parent

IBJA_URL = "https://www.ibjarates.com/"
MCX_URL = "https://www.mcxindia.com/market-data/market-watch"
SAFEGOLD_URL = "https://www.safegold.com/"
BTC_URL = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=bitcoin&vs_currencies=inr&include_24hr_change=true"
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)

CACHE_SECONDS = 8
CACHE = {"ts": 0.0, "payload": None}
FUEL_API_KEY = os.environ.get("INDIANAPI_KEY", "")


def get_ist_timezone():
    if ZoneInfo is not None:
        try:
            return ZoneInfo("Asia/Kolkata")
        except ZoneInfoNotFoundError:
            pass
    return timezone(timedelta(hours=5, minutes=30), name="IST")


IST = get_ist_timezone()


def fetch_text(url, timeout=15):
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-IN,en;q=0.9",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def fetch_json(url, timeout=15):
    return json.loads(fetch_text(url, timeout=timeout))


def fetch_json_with_headers(url, headers, timeout=15):
    request = Request(url, headers={**{"User-Agent": USER_AGENT, "Accept": "application/json"}, **headers})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="ignore"))


def handle_extra_api(query):
    action = query.get("action", [""])[0].lower()
    if action == "currencies":
        return {"currencies": fetch_json("https://api.frankfurter.dev/v2/currencies", 10), "source": "Frankfurter / ECB"}
    if action == "exchange":
        base = query.get("base", [""])[0].upper()
        quote = query.get("quote", [""])[0].upper()
        if not re.fullmatch(r"[A-Z]{3}", base) or not re.fullmatch(r"[A-Z]{3}", quote) or base == quote:
            raise ValueError("Choose two different valid currencies.")
        data = fetch_json(f"https://api.frankfurter.dev/v2/rate/{base}/{quote}", 10)
        return {"base": base, "quote": quote, "rate": float(data["rate"]), "date": data.get("date"), "source": "Frankfurter / ECB"}
    if action.startswith("fuel-"):
        if not FUEL_API_KEY:
            raise ValueError("Fuel API is not configured. Set INDIANAPI_KEY on the server.")
        base = "https://fuel.indianapi.in"
        headers = {"x-api-key": FUEL_API_KEY}
        if action == "fuel-states":
            return fetch_json_with_headers(base + "/states", headers)
        state = query.get("state", [""])[0].lower()
        if not re.fullmatch(r"[a-z0-9-]+", state): raise ValueError("Invalid state.")
        if action == "fuel-cities":
            return fetch_json_with_headers(base + "/cities?state=" + state, headers)
        city = query.get("city", [""])[0].lower()
        if not re.fullmatch(r"[a-z0-9-]+", city): raise ValueError("Invalid city.")
        petrol_rows = fetch_json_with_headers(base + "/live_fuel_price?fuel_type=petrol&location_type=city", headers)
        diesel_rows = fetch_json_with_headers(base + "/live_fuel_price?fuel_type=diesel&location_type=city", headers)
        def find(rows):
            for row in rows:
                if row.get("city", "").strip().lower().replace(" ", "-") == city:
                    return row
            return None
        petrol, diesel = find(petrol_rows), find(diesel_rows)
        if not petrol and not diesel: raise ValueError("No live fuel data found for this city.")
        return {"cityName": (petrol or diesel).get("city"), "fuel": {
            "petrol": {"retailPrice": float(petrol["price"]), "retailUnit": "litre", "change": float(petrol.get("change", 0))} if petrol else None,
            "diesel": {"retailPrice": float(diesel["price"]), "retailUnit": "litre", "change": float(diesel.get("change", 0))} if diesel else None,
            "cng": None,
        }, "source": "IndianAPI", "note": "IndianAPI currently provides live petrol and diesel. CNG is not included in its documented API."}
    raise ValueError("Unknown API action.")


def parse_ibja(html):
    row_pattern = re.compile(
        r'<td[^>]*data-label="(?P<session>AM|PM)"[^>]*>\s*<strong>(?P<date>\d{2}/\d{2}/\d{4})</strong>\s*</td>\s*'
        r'<td[^>]*data-label="Gold 999">(?P<gold999>[\d. ]+)</td>\s*'
        r'<td[^>]*data-label="Gold 995">(?P<gold995>[\d. ]+)</td>\s*'
        r'<td[^>]*data-label="Gold 916">(?P<gold916>[\d. ]+)</td>\s*'
        r'<td[^>]*data-label="Gold 750">(?P<gold750>[\d. ]+)</td>\s*'
        r'<td[^>]*data-label="Gold 585">(?P<gold585>[\d. ]+)</td>\s*'
        r'<td[^>]*data-label="Silver 999">(?P<silver999>[\d. ]+)</td>\s*'
        r'<td[^>]*data-label="Platinum 999">(?P<platinum999>[\d. ]+)</td>',
        re.IGNORECASE | re.DOTALL,
    )

    rows = {"AM": None, "PM": None}
    for match in row_pattern.finditer(html):
        session = match.group("session").upper()
        if rows[session] is None:
            rows[session] = {
                "date": match.group("date"),
                "gold999": int(match.group("gold999").strip()),
                "gold995": int(match.group("gold995").strip()),
                "gold916": int(match.group("gold916").strip()),
                "gold750": int(match.group("gold750").strip()),
                "gold585": int(match.group("gold585").strip()),
                "silver999": int(match.group("silver999").strip()),
                "platinum999": int(match.group("platinum999").strip()),
            }

    if not rows["AM"] or not rows["PM"]:
        raise ValueError("Could not parse the latest IBJA AM/PM tables.")

    return {"am": rows["AM"], "pm": rows["PM"]}


def fetch_ibja_payload():
    html = fetch_text(IBJA_URL)
    ibja = parse_ibja(html)
    pm = ibja["pm"]
    am = ibja["am"]

    gold_pm_per_g = round(pm["gold999"] / 10, 2)
    silver_pm_per_g = round(pm["silver999"] / 1000, 3)
    sterling_pm_per_g = round(silver_pm_per_g * 0.925, 3)
    platinum_pm_per_g = round(pm["platinum999"] / 10, 2)

    return {
        "source": "IBJA",
        "am": am,
        "pm": pm,
        "derived": {
            "gold_999_per_g": gold_pm_per_g,
            "silver_999_per_g": silver_pm_per_g,
            "silver_sterling_per_g": sterling_pm_per_g,
            "platinum_999_per_g": platinum_pm_per_g,
        },
    }


def fetch_bitcoin_payload():
    data = fetch_json(BTC_URL)
    btc = data.get("bitcoin", {})
    if "inr" not in btc:
        raise ValueError("CoinGecko response did not include the INR price.")
    return {
        "source": "CoinGecko",
        "inr": float(btc["inr"]),
        "change_24h": float(btc.get("inr_24h_change", 0.0)),
    }


def check_mcx():
    try:
        fetch_text(MCX_URL, timeout=10)
        return {
            "label": "MCX",
            "status": "limited",
            "message": "The public market-watch page loaded, but its live contract table is not exposed in stable HTML here.",
        }
    except HTTPError as exc:
        if exc.code == 403:
            return {
                "label": "MCX",
                "status": "blocked",
                "message": "MCX returned HTTP 403 for scripted access, so this dashboard does not guess at MCX contract prices.",
            }
        return {
            "label": "MCX",
            "status": "error",
            "message": f"MCX returned HTTP {exc.code} while checking the public market-watch page.",
        }
    except URLError as exc:
        return {
            "label": "MCX",
            "status": "error",
            "message": f"MCX request failed: {exc.reason}",
        }
    except Exception as exc:  # pragma: no cover
        return {
            "label": "MCX",
            "status": "error",
            "message": f"MCX request failed: {exc}",
        }


def check_safegold():
    try:
        html = fetch_text(SAFEGOLD_URL, timeout=10)
        if "liveBuyPrice" in html or "liveSellPrice" in html:
            return {
                "label": "SafeGold",
                "status": "partial",
                "message": "SafeGold references live price fields, but the public page does not include a verified anonymous numeric rate in the HTML response.",
            }
        return {
            "label": "SafeGold",
            "status": "unavailable",
            "message": "SafeGold public pages load, but the exact buy rate is hydrated client-side and is not available through a stable public endpoint we could verify here.",
        }
    except HTTPError as exc:
        return {
            "label": "SafeGold",
            "status": "error",
            "message": f"SafeGold returned HTTP {exc.code} while checking the public website.",
        }
    except URLError as exc:
        return {
            "label": "SafeGold",
            "status": "error",
            "message": f"SafeGold request failed: {exc.reason}",
        }
    except Exception as exc:  # pragma: no cover
        return {
            "label": "SafeGold",
            "status": "error",
            "message": f"SafeGold request failed: {exc}",
        }


def build_asset_payload():
    ibja = fetch_ibja_payload()
    btc = fetch_bitcoin_payload()

    gold_rate = ibja["derived"]["gold_999_per_g"]
    silver_rate = ibja["derived"]["silver_999_per_g"]
    sterling_rate = ibja["derived"]["silver_sterling_per_g"]
    platinum_rate = ibja["derived"]["platinum_999_per_g"]

    return {
        "generated_at": datetime.now(IST).isoformat(),
        "refresh_seconds": 10,
        "assets": {
            "gold": {
                "title": "Gold Tracker",
                "subtitle": "Official IBJA benchmark prices, converted from the latest published AM and PM tables into a live-refreshing gold dashboard.",
                "ticker": f"IBJA PM {ibja['pm']['date']} | Gold 999",
                "unit": "g",
                "unit_name": "gram",
                "primary_rate": gold_rate,
                "price_rows": [
                    {"label": f"IBJA 999 PM ({ibja['pm']['date']})", "value": ibja["pm"]["gold999"], "kind": "per_10g"},
                    {"label": "999 per gram (derived)", "value": gold_rate, "kind": "per_g"},
                    {"label": f"IBJA 995 PM ({ibja['pm']['date']})", "value": ibja["pm"]["gold995"], "kind": "per_10g"},
                    {"label": f"IBJA 916 PM ({ibja['pm']['date']})", "value": ibja["pm"]["gold916"], "kind": "per_10g"},
                    {"label": f"IBJA 750 PM ({ibja['pm']['date']})", "value": ibja["pm"]["gold750"], "kind": "per_10g"},
                ],
                "highlights": [
                    {"label": "Official Source", "value": "IBJA"},
                    {"label": "Latest PM", "value": ibja["pm"]["date"]},
                    {"label": "Converter Base", "value": "Gold 999 per gram"},
                ],
                "source_note": "IBJA publishes gold in rupees per 10 grams. The per-gram number shown here is the exact benchmark derived from that official PM value.",
            },
            "silver": {
                "title": "Silver Tracker",
                "subtitle": "Official IBJA silver 999 benchmarks, with per-gram conversion and a sterling 92.5% purity benchmark derived from the same live IBJA base.",
                "ticker": f"IBJA PM {ibja['pm']['date']} | Silver 999",
                "unit": "g",
                "unit_name": "gram",
                "primary_rate": silver_rate,
                "price_rows": [
                    {"label": f"IBJA 999 PM ({ibja['pm']['date']})", "value": ibja["pm"]["silver999"], "kind": "per_kg"},
                    {"label": "999 per gram (derived)", "value": silver_rate, "kind": "per_g"},
                    {"label": "Sterling 92.5% benchmark", "value": sterling_rate, "kind": "per_g"},
                    {"label": f"IBJA 999 AM ({ibja['am']['date']})", "value": ibja["am"]["silver999"], "kind": "per_kg"},
                ],
                "highlights": [
                    {"label": "Official Source", "value": "IBJA"},
                    {"label": "Latest PM", "value": ibja["pm"]["date"]},
                    {"label": "Sterling Basis", "value": "999 x 92.5%"},
                ],
                "source_note": "IBJA publishes silver 999 in rupees per kilogram. Sterling here is a purity-only benchmark, so it is normally lower than 999 silver unless retail premiums or making charges are added.",
            },
            "platinum": {
                "title": "Platinum Tracker",
                "subtitle": "Official IBJA platinum 999 values, converted to exact per-gram pricing for your live tracker, converter, and profit calculator.",
                "ticker": f"IBJA PM {ibja['pm']['date']} | Platinum 999",
                "unit": "g",
                "unit_name": "gram",
                "primary_rate": platinum_rate,
                "price_rows": [
                    {"label": f"IBJA Platinum 999 PM ({ibja['pm']['date']})", "value": ibja["pm"]["platinum999"], "kind": "per_10g"},
                    {"label": "Platinum per gram (derived)", "value": platinum_rate, "kind": "per_g"},
                    {"label": f"IBJA Platinum 999 AM ({ibja['am']['date']})", "value": ibja["am"]["platinum999"], "kind": "per_10g"},
                ],
                "highlights": [
                    {"label": "Official Source", "value": "IBJA"},
                    {"label": "Latest PM", "value": ibja["pm"]["date"]},
                    {"label": "Converter Base", "value": "Platinum 999 per gram"},
                ],
                "source_note": "IBJA publishes platinum in rupees per 10 grams. The per-gram rate in this dashboard is the exact conversion of the published PM figure.",
            },
            "bitcoin": {
                "title": "Bitcoin Tracker",
                "subtitle": "Live INR bitcoin pricing from CoinGecko so the crypto side of the dashboard refreshes alongside the bullion benchmarks.",
                "ticker": "CoinGecko | Bitcoin INR",
                "unit": "btc",
                "unit_name": "BTC",
                "primary_rate": btc["inr"],
                "price_rows": [
                    {"label": "Bitcoin live", "value": btc["inr"], "kind": "per_btc"},
                    {"label": "24h change", "value": btc["change_24h"], "kind": "percent"},
                    {"label": "0.01 BTC", "value": round(btc["inr"] * 0.01, 2), "kind": "inr"},
                ],
                "highlights": [
                    {"label": "Source", "value": "CoinGecko"},
                    {"label": "Refresh", "value": "10 seconds"},
                    {"label": "24h Move", "value": f"{btc['change_24h']:+.2f}%"},
                ],
                "source_note": "Bitcoin is fetched live in INR from CoinGecko and refreshed by the UI every 10 seconds.",
            },
        },
        "overview": {
            "gold": gold_rate,
            "silver": silver_rate,
            "platinum": platinum_rate,
            "bitcoin": btc["inr"],
        },
        "sources": {
            "ibja": {
                "label": "IBJA",
                "status": "ok",
                "message": (
                    f"Latest official IBJA tables parsed successfully. "
                    f"AM: {ibja['am']['date']} | PM: {ibja['pm']['date']}."
                ),
            },
            "mcx": check_mcx(),
            "safegold": check_safegold(),
            "bitcoin": {
                "label": "CoinGecko",
                "status": "ok",
                "message": "Bitcoin INR price fetched successfully from CoinGecko.",
            },
        },
    }


def get_cached_payload():
    now = time.time()
    if CACHE["payload"] and now - CACHE["ts"] < CACHE_SECONDS:
        return CACHE["payload"]
    payload = build_asset_payload()
    CACHE["ts"] = now
    CACHE["payload"] = payload
    return payload


class MetalifyHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if "action" in query:
            try:
                encoded = json.dumps(handle_extra_api(query)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
            except Exception as exc:
                encoded = json.dumps({"error": str(exc)}).encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
            return
        if self.path in ("/api/prices", "/api/prices/"):
            try:
                payload = get_cached_payload()
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
            except Exception as exc:  # pragma: no cover
                encoded = json.dumps({"error": str(exc)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
            return

        if self.path in ("/", "/app.html"):
            self.path = "/index.html"
        super().do_GET()


if __name__ == "__main__":
    print(f"Metalify server running at http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop.")
    server = ThreadingHTTPServer((HOST, PORT), MetalifyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()
