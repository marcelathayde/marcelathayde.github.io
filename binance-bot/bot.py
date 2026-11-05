#!/usr/bin/env python3
"""Bot de cruzamento de médias móveis (SMA) para a Binance Spot TESTNET.

Comandos:
  backtest  simula a estratégia em candles históricos (dados públicos, sem chave)
  run       roda o bot em tempo real
              (padrão: simulação local; --testnet envia ordens à testnet)

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


# ---------- backtest ----------
def backtest(args):
    candles = klines(PUBLIC_DATA_URL, args.symbol, args.interval, args.limit)
    closes = [c[1] for c in candles]
    cash, coin, trades = 1000.0, 0.0, 0
    start = cash
    peak, max_dd = start, 0.0
    for i in range(1, len(closes)):
        s = signal(closes, args.fast, args.slow, i)
        if s == "buy" and cash > 0:
            coin = cash * (1 - FEE) / closes[i]
            cash, trades = 0.0, trades + 1
        elif s == "sell" and coin > 0:
            cash = coin * closes[i] * (1 - FEE)
            coin, trades = 0.0, trades + 1
        equity = cash + coin * closes[i]
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
    final = cash + coin * closes[-1]
    hold = start / closes[0] * closes[-1]
    print(f"{args.symbol} {args.interval} | {len(closes)} candles | SMA {args.fast}/{args.slow}")
    print(f"Estratégia : {final:9.2f} USDT ({(final / start - 1) * 100:+.1f}%)")
    print(f"Buy & hold : {hold:9.2f} USDT ({(hold / start - 1) * 100:+.1f}%)")
    print(f"Operações  : {trades} | Drawdown máx.: {max_dd * 100:.1f}%")
    print("Atenção: resultado passado não garante nada; ignora slippage e liquidez.")


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


def run(args):
    base_asset = args.symbol.replace("USDT", "")
    key = os.environ.get("BINANCE_TESTNET_API_KEY")
    secret = os.environ.get("BINANCE_TESTNET_API_SECRET")
    if args.testnet and not (key and secret):
        raise SystemExit("Defina BINANCE_TESTNET_API_KEY e BINANCE_TESTNET_API_SECRET (veja .env.example).")
    step = step_size(args.symbol) if args.testnet else 0.0
    sim_coin = 0.0  # posição simulada (modo sem --testnet)
    last_bar = None
    mode = "ORDENS NA TESTNET" if args.testnet else "SIMULAÇÃO (nenhuma ordem enviada)"
    print(f"[{mode}] {args.symbol} {args.interval} SMA {args.fast}/{args.slow} | "
          f"{args.quote:g} USDT por compra. Ctrl+C para parar.")
    while True:
        rows = klines(TESTNET_URL, args.symbol, args.interval, args.slow + 3)
        closed = [r for r in rows if r[2] < int(time.time() * 1000)]  # só candles fechados
        if closed and closed[-1][0] != last_bar:
            last_bar = closed[-1][0]
            closes = [r[1] for r in closed]
            s = signal(closes, args.fast, args.slow, len(closes) - 1)
            price = closes[-1]
            print(time.strftime("%F %T"), f"preço {price:.2f} sinal={s}")
            if args.testnet:
                coin = free_balance(base_asset, key, secret)
            else:
                coin = sim_coin
            if s == "buy" and coin * price < 10:
                if args.testnet:
                    o = http("POST", TESTNET_URL, "/api/v3/order",
                             {"symbol": args.symbol, "side": "BUY", "type": "MARKET",
                              "quoteOrderQty": args.quote}, key, secret)
                    print("  COMPRA testnet:", o["orderId"], o["status"])
                else:
                    sim_coin = args.quote / price
                    print(f"  (simulado) compraria {sim_coin:.6f} {base_asset}")
            elif s == "sell" and coin * price >= 10:
                qty = round_down(coin, step)
                if args.testnet:
                    o = http("POST", TESTNET_URL, "/api/v3/order",
                             {"symbol": args.symbol, "side": "SELL", "type": "MARKET",
                              "quantity": f"{qty:.8f}".rstrip("0").rstrip(".")}, key, secret)
                    print("  VENDA testnet:", o["orderId"], o["status"])
                else:
                    print(f"  (simulado) venderia {sim_coin:.6f} {base_asset}")
                    sim_coin = 0.0
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
