# Model benchmark (tune split = first half)

- model: qwen3:8b
- ollama: 0.40.10
- date: 2026-10-26
- fixture: labeled_transactions.json
- prompts: 100 (58 normalized merchants, 42 raw descriptions)
- schema-valid: 100/100
- throughput: 1.06 prompts/s (94.5s)

## Accuracy vs coverage (normalized merchants with a true category)

| threshold | covered | coverage | correct | precision | unclassifiable accepted |
|---|---|---|---|---|---|
| 0.50 | 49/50 | 98.0% | 44 | 89.8% | 1 |
| 0.60 | 49/50 | 98.0% | 44 | 89.8% | 1 |
| 0.70 | 49/50 | 98.0% | 44 | 89.8% | 1 |
| 0.80 | 49/50 | 98.0% | 44 | 89.8% | 1 |
| 0.90 | 49/50 | 98.0% | 44 | 89.8% | 0 |
| 0.95 | 49/50 | 98.0% | 44 | 89.8% | 0 |

## Accuracy by confidence band

| band | n | correct | accuracy |
|---|---|---|---|
| 0.00 to 0.50 | 1 | 0 | 0.0% |
| 0.50 to 0.70 | 0 | 0 | n/a |
| 0.70 to 0.90 | 0 | 0 | n/a |
| 0.90 to 1.00 | 49 | 44 | 89.8% |
