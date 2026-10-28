# Results

CR / PSR / SR of eight models before (Base) and after (SFT) fine-tuning on RV-CodeBase, measured on Milk-V Jupiter
(-O3, one warm-up and five timed runs, median). TSVC is evaluated on RVV, Mbed TLS on B, TACLeBench on Zicond and
CMSIS-NN on IME; Overall pools all 209 tasks. CR and PSR are percentages; SR is the geometric-mean speedup with failed
tasks counted as 1 (`--` when no task is correct). Metric definitions: `common/metrics.py`. Best per column in bold.

Regenerate from `<suite>/results/` with `python3 benchmark/table.py > benchmark/results.md`.

| Model | Setting | TSVC CR | TSVC PSR | TSVC SR | Mbed TLS CR | Mbed TLS PSR | Mbed TLS SR | TACLeBench CR | TACLeBench PSR | TACLeBench SR | CMSIS-NN CR | CMSIS-NN PSR | CMSIS-NN SR | Overall CR | Overall PSR | Overall SR |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| DeepSeek-Coder-7B | Base | 0.0 | 0.0 | -- | 0.0 | 0.0 | -- | 0.0 | 0.0 | -- | 0.0 | 0.0 | -- | 0.0 | 0.0 | -- |
|  | SFT | 0.7 | 0.7 | 1.01 | 2.4 | 1.7 | 1.02 | 6.3 | 5.1 | 1.01 | 2.9 | 1.2 | 1.01 | 3.1 | 2.2 | 1.01 |
| DeepSeek-Coder-33B | Base | 2.2 | 1.5 | 1.02 | 11.4 | 8.9 | 1.01 | 24.7 | 19.8 | 0.99 | 12.5 | 6.3 | 1.07 | 12.7 | 9.1 | 1.02 |
|  | SFT | 31.9 | 16.3 | 1.22 | 42.7 | 30.0 | 1.17 | 48.9 | 41.0 | 1.10 | 26.4 | 13.8 | 1.20 | 37.5 | 25.3 | 1.17 |
| CodeLlama-13B | Base | 19.3 | 18.5 | 1.01 | 14.1 | 9.5 | 1.01 | 20.9 | 17.5 | 1.02 | 0.0 | 0.0 | -- | 13.6 | 11.4 | 1.01 |
|  | SFT | 36.3 | 28.9 | 1.23 | 38.8 | 19.2 | 1.03 | 32.3 | 19.8 | 1.07 | 12.5 | 4.1 | 1.05 | 30.0 | 18.0 | 1.09 |
| CodeLlama-34B | Base | 21.1 | 18.7 | 1.17 | 46.6 | 40.8 | 1.05 | 27.8 | 17.4 | 1.03 | 10.0 | 7.2 | 1.05 | 26.4 | 21.0 | 1.07 |
|  | SFT | 47.7 | 32.2 | 1.35 | 72.1 | 60.5 | 1.13 | 53.9 | 38.5 | 1.15 | 47.1 | 29.2 | 1.42 | 55.2 | 40.1 | 1.26 |
| Qwen3.5-9B | Base | 3.0 | 1.5 | 1.00 | 0.0 | 0.0 | -- | 0.0 | 0.0 | -- | 2.4 | 0.0 | 0.95 | 1.4 | 0.4 | 0.99 |
|  | SFT | 43.0 | 32.6 | 1.10 | 34.5 | 28.9 | 1.05 | 25.7 | 21.9 | 1.02 | 15.2 | 10.3 | 1.09 | 29.6 | 23.4 | 1.06 |
| Qwen3.5-27B | Base | 34.1 | 25.9 | 1.09 | 59.2 | 51.3 | 1.06 | 69.3 | 63.3 | 1.10 | 37.7 | 26.0 | 1.23 | 50.1 | 41.6 | 1.12 |
|  | SFT | 50.4 | 42.6 | 1.41 | 82.9 | 71.9 | 1.21 | **81.9** | **72.1** | **1.26** | 49.4 | 41.6 | 1.98 | 66.2 | 57.1 | 1.44 |
| Gemma4-12B | Base | 32.6 | 26.7 | 1.05 | 56.4 | 32.4 | 1.01 | 17.7 | 9.3 | 0.99 | 4.1 | 2.0 | 1.01 | 27.7 | 17.6 | 1.01 |
|  | SFT | 41.8 | 28.9 | 1.16 | 72.6 | 56.5 | 1.15 | 32.5 | 21.7 | 1.02 | 18.8 | 9.3 | 1.09 | 41.4 | 29.1 | 1.10 |
| Gemma4-31B | Base | 53.3 | 36.3 | 1.17 | 79.3 | 74.4 | 1.09 | 44.6 | 36.9 | 1.07 | 57.2 | 44.8 | 1.35 | 58.6 | 48.1 | 1.17 |
|  | SFT | **80.0** | **58.5** | **1.87** | **91.4** | **83.6** | **1.25** | 74.7 | 67.3 | 1.21 | **72.1** | **69.8** | **2.35** | **79.6** | **69.8** | **1.61** |
