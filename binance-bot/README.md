# Bot SMA para Binance Spot **Testnet**

Estratégia: compra quando a média móvel rápida cruza acima da lenta; vende no cruzamento contrário (long-only, ordens a mercado).
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
