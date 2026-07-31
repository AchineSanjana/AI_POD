# Evaluation Results

- Data source: D:\Projects\AI_POD\data\processed
- Split: 17239 training rows / 11963 held-out rows
- Evaluation customers: 7043
- k: 5
- Content/hybrid features: tenure, MonthlyCharges, Contract

## Metrics

| Model | Precision@5 | Recall@5 | NDCG@5 |
| --- | ---: | ---: | ---: |
| content_based | 0.222 | 0.659 | 0.503 |
| collaborative | 0.252 | 0.678 | 0.493 |
| hybrid | 0.249 | 0.737 | 0.595 |
| ranking | 0.293 | 0.880 | 0.751 |

**Overall winner (by NDCG@5):** ranking

## Segment Breakdown

| Segment | Model | Precision@5 | Recall@5 | NDCG@5 | Winner |
| --- | --- | ---: | ---: | ---: | --- |
| newer | content_based | 0.209 | 0.711 | 0.552 |  |
| newer | collaborative | 0.160 | 0.486 | 0.318 |  |
| newer | hybrid | 0.225 | 0.767 | 0.604 |  |
| newer | ranking | 0.246 | 0.880 | 0.784 | ranking |
| established | content_based | 0.237 | 0.593 | 0.442 |  |
| established | collaborative | 0.369 | 0.922 | 0.716 | collaborative |
| established | hybrid | 0.279 | 0.699 | 0.584 |  |
| established | ranking | 0.352 | 0.879 | 0.708 |  |

## Qualitative Examples

### Customer 0003-MKNFE
Profile: tenure=9, MonthlyCharges=59.90, contract=Month-to-month, current_services=['PhoneService', 'MultipleLines']
Current products: Multiple Lines (MultipleLines), Phone Service (PhoneService)
Held-out products: Internet - DSL (InternetService_DSL), Streaming Movies (StreamingMovies)

- content_based: Internet - DSL (InternetService_DSL), Phone Service (PhoneService), Internet - Fiber Optic (InternetService_Fiber), Multiple Lines (MultipleLines), Streaming Movies (StreamingMovies)
- collaborative: Internet - DSL (InternetService_DSL), Internet - Fiber Optic (InternetService_Fiber), Streaming TV (StreamingTV), Online Backup (OnlineBackup), Tech Support (TechSupport)
- hybrid: Internet - DSL (InternetService_DSL), Internet - Fiber Optic (InternetService_Fiber), Phone Service (PhoneService), Streaming Movies (StreamingMovies), Streaming TV (StreamingTV)
- ranking: Internet - DSL (InternetService_DSL), Internet - Fiber Optic (InternetService_Fiber), Online Security (OnlineSecurity), Online Backup (OnlineBackup), Tech Support (TechSupport)

Why this makes sense: a lightweight starting profile often receives core connectivity suggestions first, with add-ons appearing after the base service.

### Customer 0016-QLJIS
Profile: tenure=65, MonthlyCharges=90.45, contract=Two year, current_services=['PhoneService', 'MultipleLines', 'OnlineSecurity', 'OnlineBackup', 'DeviceProtection', 'StreamingTV', 'StreamingMovies']
Current products: Device Protection (DeviceProtection), Multiple Lines (MultipleLines), Online Backup (OnlineBackup), Online Security (OnlineSecurity), Phone Service (PhoneService), Streaming Movies (StreamingMovies), Streaming TV (StreamingTV)
Held-out products: Internet - DSL (InternetService_DSL), Tech Support (TechSupport)

- content_based: Online Security (OnlineSecurity), Tech Support (TechSupport), Device Protection (DeviceProtection), Online Backup (OnlineBackup), Multiple Lines (MultipleLines)
- collaborative: Tech Support (TechSupport), Internet - DSL (InternetService_DSL), Internet - Fiber Optic (InternetService_Fiber)
- hybrid: Online Security (OnlineSecurity), Tech Support (TechSupport), Device Protection (DeviceProtection), Online Backup (OnlineBackup), Multiple Lines (MultipleLines)
- ranking: Tech Support (TechSupport), Internet - DSL (InternetService_DSL), Internet - Fiber Optic (InternetService_Fiber)

Why this makes sense: the models are clustering around products that are commonly co-subscribed with the customer's current package, which is the expected offline behavior.

### Customer 0017-IUDMW
Profile: tenure=72, MonthlyCharges=116.80, contract=Two year, current_services=['PhoneService', 'MultipleLines', 'OnlineSecurity', 'OnlineBackup', 'StreamingTV', 'StreamingMovies', 'InternetService_Fiber']
Current products: Internet - Fiber Optic (InternetService_Fiber), Multiple Lines (MultipleLines), Online Backup (OnlineBackup), Online Security (OnlineSecurity), Phone Service (PhoneService), Streaming Movies (StreamingMovies), Streaming TV (StreamingTV)
Held-out products: Device Protection (DeviceProtection), Tech Support (TechSupport)

- content_based: Device Protection (DeviceProtection), Tech Support (TechSupport), Online Backup (OnlineBackup), Online Security (OnlineSecurity), Streaming TV (StreamingTV)
- collaborative: Device Protection (DeviceProtection), Tech Support (TechSupport), Internet - DSL (InternetService_DSL)
- hybrid: Device Protection (DeviceProtection), Tech Support (TechSupport), Online Backup (OnlineBackup), Online Security (OnlineSecurity), Streaming TV (StreamingTV)
- ranking: Device Protection (DeviceProtection), Tech Support (TechSupport), Internet - DSL (InternetService_DSL)

Why this makes sense: fiber customers and higher-spend profiles should be steered toward add-ons like security, backup, or support rather than being pushed back to basic connectivity.

## Notes

- The ranking model is the strongest overall offline model on NDCG@5.
- Collaborative filtering remains useful for established customers with richer interaction history.
- Content-based and hybrid remain valuable baselines and fallbacks, especially for cold-start cases.