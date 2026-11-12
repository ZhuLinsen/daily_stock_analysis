# Dip Scanner

Escaneia um universo fechado de ações americanas à procura de **quedas fortes por causas pontuais** (não estruturais), para swing de 3 a 10 dias.

## Como funciona

1. Descarrega 1 ano de OHLCV diário (yfinance) do universo e dos ETFs de referência (SPY, QQQ, SMH, IGV, XLV).
2. **Gatilho**: queda ≥ `DIP_MIN_DROP_PCT`% ou ≥ `DIP_MIN_ATR_MULT`× ATR(14), com volume ≥ `DIP_MIN_VOLUME_RATIO`× a média de 20 dias. Também dispara com uma queda acumulada ≥ `DIP_MULTIDAY_DROP_PCT`% em 3 sessões.
3. **Técnica** (pontuação 0–100): RSI, distância à MM200, queda relativa ao ETF (contágio ou queda própria), posição do fecho no range do dia e volume de capitulação.
4. **Níveis** calculados de forma determinística: entrada entre o fecho − 0,5×ATR e o fecho; stop na mínima de 5 dias − 0,5×ATR; alvo na recuperação de 50% da queda desde a máxima de 10 dias.
5. **Notícias + IA**: o LLM configurado classifica a causa como `pontual`, `estrutural` ou `incerto` e dá um veredito (`entrar`, `aguardar_estabilizacao` ou `evitar`), o gatilho de entrada, os catalisadores e os riscos.
6. **Relatório HTML** (`site/index.html` e `site/reports/AAAA-MM-DD.html`) e resumo enviado para os canais de notificação já configurados.
7. **Registo** (`site/data/signals.json`): cada sinal guarda o retorno a 3, 5 e 10 sessões e se tocou primeiro no alvo ou no stop. O relatório mostra as estatísticas por tipo de causa.

## Execução

```bash
python -m src.services.dip_scanner              # normal
python -m src.services.dip_scanner --dry-run    # sem IA, notícias nem notificação
python -m src.services.dip_scanner --tickers NVDA:SMH,TTD --force --no-notify
```

## GitHub Actions

O workflow `.github/workflows/dip-scanner.yml` corre de segunda a sexta às 21:35 UTC, depois do fecho de Wall Street, e publica a pasta `site/` no ramo `gh-pages`. Os pregões já processados (feriados, por exemplo) são ignorados.

Para ativar:

1. Corre o workflow uma vez à mão (Actions → Dip Scanner → Run workflow) para criar o ramo `gh-pages`.
2. Em Settings → Pages, escolhe *Deploy from a branch*, depois `gh-pages` e `/ (root)`.
3. O relatório fica em `https://<utilizador>.github.io/<repo>/`.

Usa os mesmos secrets de LLM, notícias e notificação do workflow diário.

## Configuração

| Variável | Default | Descrição |
| --- | --- | --- |
| `DIP_UNIVERSE` | 40 ações internas | `TICKER[:ETF]` separados por vírgula |
| `DIP_MIN_DROP_PCT` | 5 | Queda diária mínima (%) |
| `DIP_MIN_ATR_MULT` | 2.0 | Ou queda ≥ N× ATR(14) |
| `DIP_MIN_VOLUME_RATIO` | 1.3 | Volume vs média de 20d |
| `DIP_MULTIDAY_DROP_PCT` | 10 | Queda em 3 sessões (dispensa o filtro de volume) |
| `DIP_MAX_SIGNALS` | 8 | Máximo de sinais analisados pela IA por execução |
| `DIP_OUTPUT_DIR` | `site` | Pasta do relatório |
| `DIP_REPORT_URL` | URL do Pages | Link enviado na notificação |

Ferramenta de apoio à decisão. Não é aconselhamento financeiro.
