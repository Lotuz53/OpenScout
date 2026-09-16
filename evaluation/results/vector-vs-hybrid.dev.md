# OpenScout evaluation: vector vs hybrid

| Metric | Baseline | Candidate | Delta |
| --- | ---: | ---: | ---: |
| recall_at_5 | 0.908 | 0.900 | -0.008 |
| ndcg_at_10 | 0.891 | 0.905 | 0.014 |
| answer_score | 0.826 | 0.828 | 0.002 |
| citation_score | 0.589 | 0.606 | 0.017 |
| faithfulness_score | 0.495 | 0.514 | 0.019 |
| latency_ms | 0.000 | 0.000 | 0.000 |
| input_tokens | 9.200 | 9.200 | 0.000 |
| output_tokens | 40.833 | 40.767 | -0.067 |

- Questions: baseline 60, candidate 60.
- Measurement status: deterministic lexical proxy over the committed Stage A fixture; this is not production embedding or hybrid quality evidence.
- Promotion decision: Hybrid remains non-default (promotion.default: false) until production measurements and review support promotion.
