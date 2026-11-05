# Bot SMA para Binance Spot **Testnet**

Estratégia: cruzamento de SMA rápida/lenta (compra no cruzamento para cima, vende no contrário), com filtro RSI na entrada e stop-loss/take-profit.
Só a testnet é suportada (URL fixa em `bot.py`). Sem dependências além do Python 3.9+.

## Uso (no seu PC)
```bash
python3 bot.py backtest --symbol BTCUSDT --interval 1h --fast 10 --slow 30   # dados públicos, sem chave
python3 bot.py run                    # simulação em tempo real, não envia ordens
export BINANCE_TESTNET_API_KEY=... BINANCE_TESTNET_API_SECRET=...            # chaves de https://testnet.binance.vision
python3 bot.py run --testnet --quote 100                                     # ordens na testnet
```

## Segurança
- Use apenas chaves da testnet. Nunca coloque chaves da conta real em arquivos nem no GitHub (`.env` está no `.gitignore`).
- Este repositório publica via GitHub Pages: não commite a pasta sem revisar.
- Sem stop-loss, gestão de risco ou tratamento de falhas de rede. É um ponto de partida para estudo, não um sistema pronto para dinheiro real.

## Parâmetros da estratégia
| Flag | Padrão | Efeito |
|---|---|---|
| `--fast` / `--slow` | 10 / 30 | períodos das médias |
| `--rsi-max` | 70 | não compra se RSI(14) estiver acima (0 desliga) |
| `--stop` | 3 | stop-loss em % sobre a entrada (0 desliga) |
| `--take` | 6 | take-profit em % sobre a entrada (0 desliga) |

No modo `run`, stop/take são checados a cada consulta (`--poll`); o cruzamento só é avaliado em candle fechado. O preço de entrada fica em `state.json` (ignorado pelo git). Rode `backtest` com várias combinações antes de confiar nos padrões: eles são chutes razoáveis, não valores otimizados.
