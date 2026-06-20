import json
import logging
import os
import time
from datetime import datetime, timezone
from functools import wraps
from threading import Lock

from flask import Flask, jsonify, request, render_template, abort
from flask_cors import CORS

from config import (
    FLASK_HOST, FLASK_PORT, FLASK_DEBUG,
    CACHE_TTL_S, MODEL_PATH, FEATURES_PATH,
    BASE_DIR, LOGS_DIR,
)
from scanner import (
    analyze_symbol, run_scan, load_last_signals,
    load_history, load_model,
)

LOGS_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOGS_DIR / "app.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

_cache: dict = {}
_cache_lock  = Lock()


def _cache_get(key: str):
    with _cache_lock:
        entry = _cache.get(key)
        if entry and (time.time() - entry["ts"]) < CACHE_TTL_S:
            return entry["data"]
    return None


def _cache_set(key: str, data):
    with _cache_lock:
        _cache[key] = {"data": data, "ts": time.time()}


WATCHLIST_PATH = BASE_DIR / "data" / "watchlist.json"
WATCHLIST_PATH.parent.mkdir(exist_ok=True)


def _load_watchlist() -> list:
    if WATCHLIST_PATH.exists():
        try:
            return json.loads(WATCHLIST_PATH.read_text())
        except Exception:
            return []
    return []


def _save_watchlist(wl: list):
    WATCHLIST_PATH.write_text(json.dumps(wl, indent=2))


@app.route("/")
def index():
    model_ready = MODEL_PATH.exists() and FEATURES_PATH.exists()
    return render_template("index.html", model_ready=model_ready)


@app.route("/static/sw.js")
def service_worker():
    return app.send_static_file("sw.js"), 200, {
        "Content-Type": "application/javascript",
        "Service-Worker-Allowed": "/"
    }


@app.route("/api/status")
def api_status():
    return jsonify({
        "status":      "ok",
        "model_ready": MODEL_PATH.exists() and FEATURES_PATH.exists(),
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "cache_ttl_s": CACHE_TTL_S,
    })


@app.route("/api/signals")
def api_signals():
    min_prob = float(request.args.get("min_prob", 60)) / 100
    limit    = int(request.args.get("limit", 50))

    cache_key = f"signals_{min_prob:.2f}_{limit}"
    cached_data = _cache_get(cache_key)
    if cached_data is not None:
        return jsonify({"signals": cached_data, "from_cache": True})

    signals  = load_last_signals()
    filtered = [s for s in signals if s.get("prob_raw", 0) >= min_prob][:limit]

    _cache_set(cache_key, filtered)
    return jsonify({
        "signals":    filtered,
        "count":      len(filtered),
        "from_cache": False,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/scan", methods=["POST"])
def api_scan():
    body     = request.get_json(silent=True) or {}
    min_prob = float(body.get("min_prob", 60)) / 100
    top_n    = int(body.get("top_n", 50))

    try:
        results = run_scan(min_prob=min_prob, top_n=top_n, save_csv=True)
        with _cache_lock:
            keys_to_del = [k for k in _cache if k.startswith("signals_")]
            for k in keys_to_del:
                del _cache[k]

        return jsonify({
            "success":   True,
            "count":     len(results),
            "signals":   results,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except FileNotFoundError as e:
        return jsonify({"error": str(e), "hint": "Run train_model.py first."}), 503
    except Exception as e:
        logger.exception("Scan failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/analyze/<coin>")
def api_analyze(coin: str):
    coin = coin.upper().strip()
    if not coin or len(coin) > 20:
        abort(400)

    cache_key = f"analyze_{coin}"
    hit = _cache_get(cache_key)
    if hit is not None:
        return jsonify({**hit, "from_cache": True})

    try:
        result = analyze_symbol(coin)
        if result is None:
            return jsonify({
                "error":  f"Could not fetch or analyse {coin}",
                "symbol": coin,
                "hint":   "Check the symbol is a valid Binance USDT spot pair.",
            }), 404

        _cache_set(cache_key, result)
        return jsonify({**result, "from_cache": False})

    except FileNotFoundError as e:
        return jsonify({"error": str(e), "hint": "Run train_model.py first."}), 503
    except Exception as e:
        logger.exception(f"Analysis failed for {coin}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/watchlist", methods=["GET"])
def api_watchlist_get():
    wl       = _load_watchlist()
    model_ok = MODEL_PATH.exists()
    enriched = []

    for coin in wl:
        entry: dict = {"symbol": coin}
        if model_ok:
            try:
                cache_key = f"analyze_{coin}"
                hit = _cache_get(cache_key)
                if hit:
                    entry.update({
                        "probability": hit.get("probability"),
                        "verdict":     hit.get("verdict"),
                        "rsi":         hit.get("rsi"),
                        "price":       hit.get("price"),
                    })
            except Exception:
                pass
        enriched.append(entry)

    return jsonify({"watchlist": enriched})


@app.route("/api/watchlist", methods=["POST"])
def api_watchlist_add():
    body   = request.get_json(silent=True) or {}
    symbol = body.get("symbol", "").upper().strip()
    if not symbol:
        return jsonify({"error": "symbol required"}), 400

    wl = _load_watchlist()
    if symbol not in wl:
        wl.append(symbol)
        _save_watchlist(wl)
        return jsonify({"success": True, "watchlist": wl}), 201
    return jsonify({"success": True, "watchlist": wl, "note": "already in watchlist"})


@app.route("/api/watchlist/<coin>", methods=["DELETE"])
def api_watchlist_remove(coin: str):
    coin = coin.upper().strip()
    wl   = _load_watchlist()
    if coin in wl:
        wl.remove(coin)
        _save_watchlist(wl)
    return jsonify({"success": True, "watchlist": wl})


@app.route("/api/history")
def api_history():
    limit = int(request.args.get("limit", 200))
    hist  = load_history(limit=limit)
    return jsonify({"history": hist, "count": len(hist)})


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal(e):
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("  HALAL SCAN AI PRO ULTIMATE — Starting")
    logger.info("=" * 60)

    if MODEL_PATH.exists():
        try:
            load_model()
            logger.info("✅ Model pre-loaded successfully.")
        except Exception as e:
            logger.warning(f"Model pre-load failed: {e}")
    else:
        logger.warning("⚠️  Model not found. Run train_model.py before scanning.")

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)