# Evaluation Results

- Data source: D:\Projects\AI_POD\data\processed
- Split: 17239 training rows / 11963 held-out rows
- Evaluation customers: 7043
- k: 5
- Content/hybrid features: tenure, MonthlyCharges, SeniorCitizen, Contract, PaperlessBilling, PaymentMethod

## Metrics

| Model | Precision@5 | Recall@5 | NDCG@5 |
| --- | ---: | ---: | ---: |
| content_based | 0.225 | 0.676 | 0.503 |
| collaborative | 0.252 | 0.678 | 0.493 |
| hybrid | 0.250 | 0.748 | 0.599 |
| ranking | 0.291 | 0.873 | 0.743 |

**Overall winner (by NDCG@5):** ranking

## Segment Breakdown

| Segment | Model | Precision@5 | Recall@5 | NDCG@5 | Winner |
| --- | --- | ---: | ---: | ---: | --- |
| newer | content_based | 0.216 | 0.745 | 0.550 |  |
| newer | collaborative | 0.160 | 0.486 | 0.318 |  |
| newer | hybrid | 0.228 | 0.790 | 0.607 |  |
| newer | ranking | 0.245 | 0.875 | 0.781 | ranking |
| established | content_based | 0.236 | 0.589 | 0.442 |  |
| established | collaborative | 0.369 | 0.922 | 0.716 | collaborative |
| established | hybrid | 0.278 | 0.695 | 0.589 |  |
| established | ranking | 0.348 | 0.871 | 0.695 |  |

## Qualitative Examples

### Customer 0003-MKNFE
Profile: tenure=9, MonthlyCharges=59.90, contract=Month-to-month, current_services=['PhoneService', 'MultipleLines']
Current products: Multiple Lines (MultipleLines), Phone Service (PhoneService)
Held-out products: Internet - DSL (InternetService_DSL), Streaming Movies (StreamingMovies)

- content_based: Internet - DSL (InternetService_DSL), Phone Service (PhoneService), Internet - Fiber Optic (InternetService_Fiber), Online Security (OnlineSecurity), Tech Support (TechSupport)
- collaborative: Internet - DSL (InternetService_DSL), Internet - Fiber Optic (InternetService_Fiber), Streaming TV (StreamingTV), Online Backup (OnlineBackup), Tech Support (TechSupport)
- hybrid: Internet - DSL (InternetService_DSL), Internet - Fiber Optic (InternetService_Fiber), Phone Service (PhoneService), Online Security (OnlineSecurity), Streaming TV (StreamingTV)
- ranking: Internet - DSL (InternetService_DSL), Internet - Fiber Optic (InternetService_Fiber), Online Security (OnlineSecurity), Online Backup (OnlineBackup), Device Protection (DeviceProtection)

Why this makes sense: customers with established core services are recommended relevant add-ons or complementary products rather than duplicate core services.

### Customer 0016-QLJIS
Profile: tenure=65, MonthlyCharges=90.45, contract=Two year, current_services=['PhoneService', 'MultipleLines', 'OnlineSecurity', 'OnlineBackup', 'DeviceProtection', 'StreamingTV', 'StreamingMovies']
Current products: Device Protection (DeviceProtection), Multiple Lines (MultipleLines), Online Backup (OnlineBackup), Online Security (OnlineSecurity), Phone Service (PhoneService), Streaming Movies (StreamingMovies), Streaming TV (StreamingTV)
Held-out products: Internet - DSL (InternetService_DSL), Tech Support (TechSupport)

- content_based: Tech Support (TechSupport), Online Security (OnlineSecurity), Device Protection (DeviceProtection), Online Backup (OnlineBackup), Streaming TV (StreamingTV)
- collaborative: Tech Support (TechSupport), Internet - DSL (InternetService_DSL), Internet - Fiber Optic (InternetService_Fiber)
- hybrid: Tech Support (TechSupport), Online Security (OnlineSecurity), Device Protection (DeviceProtection), Online Backup (OnlineBackup), Streaming TV (StreamingTV)
- ranking: Tech Support (TechSupport), Internet - DSL (InternetService_DSL), Internet - Fiber Optic (InternetService_Fiber)

Why this makes sense: customers with established core services are recommended relevant add-ons or complementary products rather than duplicate core services.

### Customer 0017-IUDMW
Profile: tenure=72, MonthlyCharges=116.80, contract=Two year, current_services=['PhoneService', 'MultipleLines', 'OnlineSecurity', 'OnlineBackup', 'StreamingTV', 'StreamingMovies', 'InternetService_Fiber']
Current products: Internet - Fiber Optic (InternetService_Fiber), Multiple Lines (MultipleLines), Online Backup (OnlineBackup), Online Security (OnlineSecurity), Phone Service (PhoneService), Streaming Movies (StreamingMovies), Streaming TV (StreamingTV)
Held-out products: Device Protection (DeviceProtection), Tech Support (TechSupport)

- content_based: Tech Support (TechSupport), Device Protection (DeviceProtection), Online Security (OnlineSecurity), Online Backup (OnlineBackup), Streaming TV (StreamingTV)
- collaborative: Device Protection (DeviceProtection), Tech Support (TechSupport), Internet - DSL (InternetService_DSL)
- hybrid: Tech Support (TechSupport), Device Protection (DeviceProtection), Online Security (OnlineSecurity), Online Backup (OnlineBackup), Streaming TV (StreamingTV)
- ranking: Device Protection (DeviceProtection), Tech Support (TechSupport), Internet - DSL (InternetService_DSL)

Why this makes sense: customers with established core services are recommended relevant add-ons or complementary products rather than duplicate core services.

## Notes

- The ranking model is the strongest overall offline model on NDCG@5.
- Collaborative filtering remains useful for established customers with richer interaction history.
- Content-based and hybrid remain valuable baselines and fallbacks, especially for cold-start cases.