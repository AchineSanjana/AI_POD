# Model evaluation report

- Data: D:\Projects\AI_POD\data\processed
- Train/test split: 17239 training rows, 11963 held-out rows
- Customers evaluated: 7043
- Feature columns used for content/hybrid: tenure, MonthlyCharges, SeniorCitizen, Contract, PaperlessBilling, PaymentMethod

## Overall comparison

| Model | Precision@5 | Recall@5 | NDCG@5 |
| --- | ---: | ---: | ---: |
| content_based | 0.225 | 0.676 | 0.503 |
| collaborative | 0.252 | 0.678 | 0.493 |
| hybrid | 0.250 | 0.748 | 0.599 |
| ranking | 0.291 | 0.873 | 0.743 |

**Winner (by NDCG@5):** ranking

## Segment analysis

| Segment | Content-based | Collaborative | Hybrid | Ranking | Winner |
| --- | --- | --- | --- | --- | --- |
| newer | P=0.216/R=0.745/N=0.550 | P=0.160/R=0.486/N=0.318 | P=0.228/R=0.790/N=0.607 | P=0.245/R=0.875/N=0.781 | ranking |
| established | P=0.236/R=0.589/N=0.442 | P=0.369/R=0.922/N=0.716 | P=0.278/R=0.695/N=0.589 | P=0.348/R=0.871/N=0.695 | collaborative |

## Simple chart

```mermaid
xychart-beta
    title Model comparison (NDCG@5)
    x-axis [content_based, collaborative, hybrid, ranking]
    y-axis 0 to 1
    bar [0.503, 0.493, 0.599, 0.743]
```

## Takeaway

The report highlights whether a hybrid blend is strongest overall and whether the lead shifts by customer history.