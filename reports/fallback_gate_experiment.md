# Fallback gate experiment (tune split = first half)

- model: qwen3:8b
- merchants: 58 first-half
- bar: precision >= 95% on accepted answers (accepted unclassifiable = wrong)

| variant | accepted | correct | wrong | precision | coverage | seconds |
|---|---|---|---|---|---|---|
| baseline (confidence >= 0.9) | 51/58 | 43 | 8 | 84.3% fail | 43/58 | 123 |
| descriptions | 51/58 | 45 | 6 | 88.2% fail | 45/58 | 117 |
| descriptions + examples | 55/58 | 45 | 10 | 81.8% fail | 45/58 | 117 |
| plain + unsure | 58/58 | 42 | 16 | 72.4% fail | 42/58 | 119 |
| descriptions + unsure | 58/58 | 45 | 13 | 77.6% fail | 45/58 | 117 |
| examples + unsure | 58/58 | 46 | 12 | 79.3% fail | 46/58 | 125 |
| two samples agree (descriptions + alt wording) | 53/58 | 44 | 9 | 83.0% fail | 44/58 | 200 |
| two samples agree + unsure | 55/58 | 44 | 11 | 80.0% fail | 44/58 | 101 |
