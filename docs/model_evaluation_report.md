# Model evaluation report

- Data: D:\Projects\AI_POD\data\processed
- Train/test split: 17239 training rows, 11963 held-out rows
- Customers evaluated: 7043
- Feature columns used for content/hybrid: tenure, MonthlyCharges, Contract

## Overall comparison

| Model         | Precision@5 | Recall@5 | NDCG@5 |
| ------------- | ----------: | -------: | -----: |
| content_based |       0.222 |    0.659 |  0.503 |
| collaborative |       0.252 |    0.678 |  0.493 |
| hybrid        |       0.249 |    0.737 |  0.595 |
| ranking       |       0.293 |    0.880 |  0.751 |

**Winner (by NDCG@5):** ranking

## Segment analysis

| Segment     | Content-based           | Collaborative           | Hybrid                  | Ranking                 | Winner        |
| ----------- | ----------------------- | ----------------------- | ----------------------- | ----------------------- | ------------- |
| newer       | P=0.209/R=0.711/N=0.552 | P=0.160/R=0.486/N=0.318 | P=0.225/R=0.767/N=0.604 | P=0.246/R=0.880/N=0.784 | ranking       |
| established | P=0.237/R=0.593/N=0.442 | P=0.369/R=0.922/N=0.716 | P=0.279/R=0.699/N=0.584 | P=0.352/R=0.879/N=0.708 | collaborative |

## Simple chart

```mermaid
xychart-beta
    title Model comparison (NDCG@5)
    x-axis [content_based, collaborative, hybrid, ranking]
    y-axis 0 to 1
    bar [0.503, 0.493, 0.595, 0.751]
```

## Takeaway

The learned ranking model is the shipped primary model because it wins overall on NDCG@5. Hybrid remains the best documented alternative baseline, while collaborative filtering is still competitive for established customers.
