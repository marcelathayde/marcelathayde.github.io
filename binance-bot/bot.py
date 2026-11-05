#!/usr/bin/env python3
"""Bot de cruzamento de médias móveis (SMA) para a Binance Spot TESTNET.

Comandos:
  backtest  simula a estratégia em candles históricos (dados públicos, sem chave)
  run       roda o bot em tempo real
              (padrão: simulação local; --testnet envia ordens à testnet)

Estratégia: cruzamento de SMAs rápida/lenta + filtro RSI na entrada
+ stop-loss e take-profit (% sobre o preço de entrada).

Só a testnet é suportada de propósito: a URL das ordens é fixa.
Sem dependências externas (apenas biblioteca padrão do Python 3.9+).
"""
import argparse
import hashlib
import hmac
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

TESTNET_URL = "https://testnet.binance.vision"
PUBLIC_DATA_URL = "https://data-api.binance.vision"  # só dados de mercado, sem conta
FEE = 0.001  # 0,1% por operação (taxa spot padrão)


# ---------- HTTP ----------
def http(method, base, path, params=None, api_key=None, secret=None):
    params = dict(params or {})
    headers = {}
    if secret:
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = 5000
        query = urlencode(params)
        sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        query += "&signature=" + sig
    else:
        query = urlencode(params)
    if api_key:
        headers["X-MBX-APIKEY"] = api_key
    url = f"{base}{path}" + (f"?{query}" if query and method == "GET" else "")
    data = query.encode() if method != "GET" and query else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Erro da Binance {e.code}: {e.read().decode()}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Sem acesso à rede/host ({base}): {e.reason}")


def klines(base, symbol, interval, limit):
    rows = http("GET", base, "/api/v3/klines",
                {"symbol": symbol, "interval": interval, "limit": limit})
    # cada linha: [open_time, open, high, low, close, volume, close_time, ...]
    return [(int(r[0]), float(r[4]), int(r[6])) for r in rows]


# ---------- estratégia ----------
def sma(values, n, i):
    """Média simples dos n valores que terminam no índice i (inclusive)."""
    if i + 1 < n:
        return None
    return sum(values[i + 1 - n:i + 1]) / n


def signal(closes, fast, slow, i):
    """'buy' no cruzamento para cima, 'sell' para baixo, senão None."""
    f0, s0 = sma(closes, fast, i - 1), sma(closes, slow, i - 1)
    f1, s1 = sma(closes, fast, i), sma(closes, slow, i)
    if None in (f0, s0, f1, s1):
        return None
    if f0 <= s0 and f1 > s1:
        return "buy"
    if f0 >= s0 and f1 < s1:
        return "sell"
    return None


def rsi(closes, n, i):
    """RSI simples (média aritmética de ganhos/perdas nas últimas n variações)."""
    if n <= 0 or i < n:
        return None
    ch = [closes[k] - closes[k - 1] for k in range(i - n + 1, i + 1)]
    gain = sum(c for c in ch if c > 0) / n
    loss = -sum(c for c in ch if c < 0) / n
    return 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)


def risk_exit(price, entry, args):
    """Saída por stop-loss / take-profit; None se nenhuma foi atingida."""
    if entry is None:
        return None
    if args.stop and price <= entry * (1 - args.stop / 100):
        return "stop-loss"
    if args.take and price >= entry * (1 + args.take / 100):
        return "take-profit"
    return None


def decide(closes, i, args, entry):
    """Decisão em um candle fechado. Retorna (ação, motivo); ação 'buy'/'sell'/None."""
    if entry is not None:  # posicionado
        why = risk_exit(closes[i], entry, args)
        if why:
            return "sell", why
        if signal(closes, args.fast, args.slow, i) == "sell":
            return "sell", "cruzamento"
        return None, None
    if signal(closes, args.fast, args.slow, i) == "buy":
        r = rsi(closes, args.rsi_period, i)
        if args.rsi_max and r is not None and r > args.rsi_max:
            return None, f"compra ignorada (RSI {r:.0f} > {args.rsi_max:g})"
        return "buy", "cruzamento"
    return None, None


# ---------- backtest ----------
def simulate(closes, args):
    cash, coin, entry, trades = 1000.0, 0.0, None, 0
    start = cash
    peak, max_dd = start, 0.0
    reasons = {}
    for i in range(1, len(closes)):
        act, why = decide(closes, i, args, entry)
        if act == "buy":
            coin, cash, entry, trades = cash * (1 - FEE) / closes[i], 0.0, closes[i], trades + 1
        elif act == "sell":
            cash, coin, entry, trades = coin * closes[i] * (1 - FEE), 0.0, None, trades + 1
            reasons[why] = reasons.get(why, 0) + 1
        equity = cash + coin * closes[i]
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
    final = cash + coin * closes[-1]
    return start, final, trades, max_dd, reasons


def backtest(args):
    candles = klines(PUBLIC_DATA_URL, args.symbol, args.interval, args.limit)
    closes = [c[1] for c in candles]
    start, final, trades, max_dd, reasons = simulate(closes, args)
    hold = start / closes[0] * closes[-1]
    print(f"{args.symbol} {args.interval} | {len(closes)} candles | SMA {args.fast}/{args.slow} | "
          f"RSI<={args.rsi_max:g} | stop {args.stop:g}% | take {args.take:g}%")
    print(f"Estratégia : {final:9.2f} USDT ({(final / start - 1) * 100:+.1f}%)")
    print(f"Buy & hold : {hold:9.2f} USDT ({(hold / start - 1) * 100:+.1f}%)")
    print(f"Operações  : {trades} | Drawdown máx.: {max_dd * 100:.1f}% | Saídas: {reasons or '-'}")
    print("Atenção: stop/take avaliados no fechamento do candle; ignora slippage e liquidez.")


# ---------- execução ----------
def step_size(symbol):
    info = http("GET", TESTNET_URL, "/api/v3/exchangeInfo", {"symbol": symbol})
    for f in info["symbols"][0]["filters"]:
        if f["filterType"] == "LOT_SIZE":
            return float(f["stepSize"])
    return 0.0


def round_down(qty, step):
    if step <= 0:
        return qty
    return math.floor(qty / step + 1e-9) * step


def free_balance(asset, key, secret):
    acct = http("GET", TESTNET_URL, "/api/v3/account", api_key=key, secret=secret)
    for b in acct["balances"]:
        if b["asset"] == asset:
            return float(b["free"])
    return 0.0


STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")


def load_entry():
    try:
        return json.load(open(STATE_FILE)).get("entry")
    except (OSError, ValueError):
        return None


def save_entry(entry):
    json.dump({"entry": entry}, open(STATE_FILE, "w"))


def order(args, side, key, secret, **extra):
    o = http("POST", TESTNET_URL, "/api/v3/order",
             {"symbol": args.symbol, "side": side, "type": "MARKET", **extra}, key, secret)
    print(f"  {side} testnet: {o['orderId']} {o['status']}")


def run(args):
    base_asset = args.symbol.replace("USDT", "")
    key = os.environ.get("BINANCE_TESTNET_API_KEY")
    secret = os.environ.get("BINANCE_TESTNET_API_SECRET")
    if args.testnet and not (key and secret):
        raise SystemExit("Defina BINANCE_TESTNET_API_KEY e BINANCE_TESTNET_API_SECRET (veja .env.example).")
    step = step_size(args.symbol) if args.testnet else 0.0
    sim_coin, entry, last_bar = 0.0, load_entry(), None
    mode = "ORDENS NA TESTNET" if args.testnet else "SIMULAÇÃO (nenhuma ordem enviada)"
    print(f"[{mode}] {args.symbol} {args.interval} SMA {args.fast}/{args.slow} "
          f"RSI<={args.rsi_max:g} stop {args.stop:g}% take {args.take:g}% | "
          f"{args.quote:g} USDT por compra. Ctrl+C para parar.")

    def sell(price, why):
        nonlocal sim_coin, entry
        if args.testnet:
            qty = round_down(free_balance(base_asset, key, secret), step)
            order(args, "SELL", key, secret, quantity=f"{qty:.8f}".rstrip("0").rstrip("."))
        else:
            print(f"  (simulado) venderia {sim_coin:.6f} {base_asset}")
            sim_coin = 0.0
        entry = None
        save_entry(None)
        print(f"  saída: {why} @ {price:.2f}")

    while True:
        rows = klines(TESTNET_URL, args.symbol, args.interval, args.slow + args.rsi_period + 3)
        live = rows[-1][1]  # preço atual (candle em formação)
        closed = [r for r in rows if r[2] < int(time.time() * 1000)]  # só candles fechados
        if args.testnet:
            held = free_balance(base_asset, key, secret) * live >= 10
        else:
            held = sim_coin * live >= 10
        if held and entry is None:
            entry = live  # posição pré-existente: usa o preço atual como referência
            save_entry(entry)
        if not held:
            entry = None

        why = risk_exit(live, entry, args) if held else None
        if why:  # stop/take checados a cada consulta, sem esperar o candle fechar
            sell(live, why)
        elif closed and closed[-1][0] != last_bar:
            last_bar = closed[-1][0]
            closes = [r[1] for r in closed]
            act, why = decide(closes, len(closes) - 1, args, entry if held else None)
            print(time.strftime("%F %T"), f"preço {closes[-1]:.2f} ação={act} ({why})")
            if act == "buy":
                if args.testnet:
                    order(args, "BUY", key, secret, quoteOrderQty=args.quote)
                else:
                    sim_coin = args.quote / live
                    print(f"  (simulado) compraria {sim_coin:.6f} {base_asset}")
                entry = live
                save_entry(entry)
            elif act == "sell":
                sell(live, why)
        time.sleep(args.poll)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("backtest", "run"):
        sp = sub.add_parser(name)
        sp.add_argument("--symbol", default="BTCUSDT")
        sp.add_argument("--interval", default="1h")
        sp.add_argument("--fast", type=int, default=10)
        sp.add_argument("--slow", type=int, default=30)
        sp.add_argument("--rsi-period", type=int, default=14)
        sp.add_argument("--rsi-max", type=float, default=70, help="não compra se RSI maior que isto (0 desliga)")
        sp.add_argument("--stop", type=float, default=3.0, help="stop-loss em %% (0 desliga)")
        sp.add_argument("--take", type=float, default=6.0, help="take-profit em %% (0 desliga)")
        if name == "backtest":
            sp.add_argument("--limit", type=int, default=1000)
        else:
            sp.add_argument("--quote", type=float, default=100.0, help="USDT por compra")
            sp.add_argument("--poll", type=int, default=60, help="segundos entre consultas")
            sp.add_argument("--testnet", action="store_true", help="enviar ordens à testnet")
    args = p.parse_args()
    if args.fast >= args.slow:
        sys.exit("--fast deve ser menor que --slow")
    try:
        backtest(args) if args.cmd == "backtest" else run(args)
    except KeyboardInterrupt:
        print("\nParado.")


if __name__ == "__main__":
    main()
