# Evaluation Results (movielens_demo)

- Data source: data/processed/movielens_demo
- Split: 6187 training rows / 1217 held-out rows
- Evaluation customers: 100
- k: 5
- Content/hybrid features: rating_count, avg_rating, favorite_genre

## Metrics

| Model | Precision@5 | Recall@5 | NDCG@5 |
| --- | ---: | ---: | ---: |
| content_based | 0.162 | 0.405 | 0.274 |
| collaborative | 0.394 | 0.985 | 0.951 |
| hybrid | 0.200 | 0.500 | 0.424 |
| ranking | 0.370 | 0.925 | 0.808 |

**Overall winner (by NDCG@5):** collaborative

## Segment Breakdown

### Segment Breakdown (`movielens_demo` - Field: `rating_count`)

| Segment | Model | Precision@5 | Recall@5 | NDCG@5 | Winner |
| --- | --- | ---: | ---: | ---: | --- |
| newer | content_based | 0.193 | 0.481 | 0.309 |  |
| newer | collaborative | 0.389 | 0.972 | 0.910 | collaborative |
| newer | hybrid | 0.241 | 0.602 | 0.499 |  |
| newer | ranking | 0.356 | 0.889 | 0.739 |  |
| established | content_based | 0.126 | 0.315 | 0.232 |  |
| established | collaborative | 0.400 | 1.000 | 0.998 | collaborative |
| established | hybrid | 0.152 | 0.380 | 0.336 |  |
| established | ranking | 0.387 | 0.967 | 0.890 |  |

## Qualitative Examples

### Customer 1
Profile: rating_count=232, avg_rating=4.37, favorite_genre=Action
Current products: action (action), adventure (adventure), animation (animation), children (children), comedy (comedy), crime (crime), drama (drama), fantasy (fantasy), horror (horror), romance (romance), thriller (thriller)
Held-out products: mystery (mystery), sci_fi (sci_fi)

- content_based: sci_fi (sci_fi), horror (horror), animation (animation), children (children), fantasy (fantasy)
- collaborative: sci_fi (sci_fi), mystery (mystery), documentary (documentary)
- hybrid: sci_fi (sci_fi), horror (horror), animation (animation), children (children), fantasy (fantasy)
- ranking: documentary (documentary), mystery (mystery), sci_fi (sci_fi)

Why this makes sense: recommendations prioritize relevant unseen products tailored to customer preferences.

### Customer 10
Profile: rating_count=140, avg_rating=3.28, favorite_genre=Comedy
Current products: action (action), adventure (adventure), children (children), comedy (comedy), crime (crime), fantasy (fantasy), romance (romance), sci_fi (sci_fi), thriller (thriller)
Held-out products: animation (animation), drama (drama)

- content_based: drama (drama), romance (romance), action (action), crime (crime), sci_fi (sci_fi)
- collaborative: drama (drama), animation (animation), mystery (mystery), documentary (documentary), horror (horror)
- hybrid: drama (drama), animation (animation), romance (romance), action (action), crime (crime)
- ranking: animation (animation), documentary (documentary), drama (drama), horror (horror), mystery (mystery)

Why this makes sense: recommendations prioritize relevant unseen products tailored to customer preferences.

### Customer 100
Profile: rating_count=148, avg_rating=3.95, favorite_genre=Comedy
Current products: action (action), adventure (adventure), animation (animation), children (children), comedy (comedy), crime (crime), drama (drama), fantasy (fantasy), horror (horror), mystery (mystery), sci_fi (sci_fi)
Held-out products: romance (romance), thriller (thriller)

- content_based: sci_fi (sci_fi), children (children), animation (animation), action (action), fantasy (fantasy)
- collaborative: thriller (thriller), romance (romance), documentary (documentary)
- hybrid: sci_fi (sci_fi), children (children), animation (animation), action (action), fantasy (fantasy)
- ranking: documentary (documentary), romance (romance), thriller (thriller)

Why this makes sense: recommendations prioritize relevant unseen products tailored to customer preferences.

## Notes

- The collaborative model is the strongest overall offline model on NDCG@5 for tenant 'movielens_demo'.
- Collaborative filtering provides strong personalized recommendations when rich interaction history exists.
- Content-based and hybrid provide robust fallbacks for cold-start and newer customers.
