# Evaluation Results (telco_default)

- Data source: data/processed/telco_default
- Split: 17239 training rows / 11963 held-out rows
- Evaluation customers: 100
- k: 5
- Content/hybrid features: gender, SeniorCitizen, Partner, Dependents, tenure, Contract, PaperlessBilling, PaymentMethod, MonthlyCharges, TotalCharges, Churn

## Metrics

| Model | Precision@5 | Recall@5 | NDCG@5 |
| --- | ---: | ---: | ---: |
| content_based | 0.234 | 0.695 | 0.526 |
| collaborative | 0.266 | 0.705 | 0.537 |
| hybrid | 0.250 | 0.735 | 0.592 |
| ranking | 0.304 | 0.875 | 0.607 |

**Overall winner (by NDCG@5):** ranking

## Segment Breakdown

### Segment Breakdown (`telco_default` - Field: `tenure`)

| Segment | Model | Precision@5 | Recall@5 | NDCG@5 | Winner |
| --- | --- | ---: | ---: | ---: | --- |
| newer | content_based | 0.269 | 0.827 | 0.648 |  |
| newer | collaborative | 0.219 | 0.596 | 0.436 |  |
| newer | hybrid | 0.273 | 0.837 | 0.698 | hybrid |
| newer | ranking | 0.288 | 0.865 | 0.573 |  |
| established | content_based | 0.196 | 0.552 | 0.395 |  |
| established | collaborative | 0.317 | 0.823 | 0.646 | collaborative |
| established | hybrid | 0.225 | 0.625 | 0.477 |  |
| established | ranking | 0.321 | 0.885 | 0.644 |  |

## Qualitative Examples

### Customer 0002-ORFBO
Profile: gender=Female, SeniorCitizen=0, Partner=Yes, Dependents=Yes
Current products: Online Backup (OnlineBackup), Streaming TV (StreamingTV), Tech Support (TechSupport)
Held-out products: Internet - DSL (InternetService_DSL), Phone Service (PhoneService)

- content_based: Internet - DSL (InternetService_DSL), Phone Service (PhoneService), Online Security (OnlineSecurity), Tech Support (TechSupport), Multiple Lines (MultipleLines)
- collaborative: Device Protection (DeviceProtection), Online Security (OnlineSecurity), Streaming Movies (StreamingMovies), Internet - DSL (InternetService_DSL), Internet - Fiber Optic (InternetService_Fiber)
- hybrid: Internet - DSL (InternetService_DSL), Phone Service (PhoneService), Internet - Fiber Optic (InternetService_Fiber), Online Security (OnlineSecurity), Multiple Lines (MultipleLines)
- ranking: Device Protection (DeviceProtection), Online Security (OnlineSecurity), Streaming Movies (StreamingMovies), Internet - DSL (InternetService_DSL), Internet - Fiber Optic (InternetService_Fiber)

Why this makes sense: recommendations prioritize relevant unseen products tailored to customer preferences.

### Customer 0003-MKNFE
Profile: gender=Male, SeniorCitizen=0, Partner=No, Dependents=No
Current products: Multiple Lines (MultipleLines), Phone Service (PhoneService)
Held-out products: Internet - DSL (InternetService_DSL), Streaming Movies (StreamingMovies)

- content_based: Internet - DSL (InternetService_DSL), Phone Service (PhoneService), Internet - Fiber Optic (InternetService_Fiber), Multiple Lines (MultipleLines), Tech Support (TechSupport)
- collaborative: Internet - DSL (InternetService_DSL), Internet - Fiber Optic (InternetService_Fiber), Streaming TV (StreamingTV), Online Backup (OnlineBackup), Tech Support (TechSupport)
- hybrid: Internet - DSL (InternetService_DSL), Internet - Fiber Optic (InternetService_Fiber), Phone Service (PhoneService), Multiple Lines (MultipleLines), Tech Support (TechSupport)
- ranking: Internet - DSL (InternetService_DSL), Internet - Fiber Optic (InternetService_Fiber), Device Protection (DeviceProtection), Online Backup (OnlineBackup), Online Security (OnlineSecurity)

Why this makes sense: recommendations prioritize relevant unseen products tailored to customer preferences.

### Customer 0004-TLHLJ
Profile: gender=Male, SeniorCitizen=0, Partner=No, Dependents=No
Current products: Phone Service (PhoneService)
Held-out products: Device Protection (DeviceProtection), Internet - Fiber Optic (InternetService_Fiber)

- content_based: Phone Service (PhoneService), Internet - Fiber Optic (InternetService_Fiber), Internet - DSL (InternetService_DSL), Streaming Movies (StreamingMovies), Multiple Lines (MultipleLines)
- collaborative: Internet - DSL (InternetService_DSL), Internet - Fiber Optic (InternetService_Fiber), Online Security (OnlineSecurity), Tech Support (TechSupport), Streaming TV (StreamingTV)
- hybrid: Internet - Fiber Optic (InternetService_Fiber), Internet - DSL (InternetService_DSL), Multiple Lines (MultipleLines), Phone Service (PhoneService), Streaming Movies (StreamingMovies)
- ranking: Internet - DSL (InternetService_DSL), Internet - Fiber Optic (InternetService_Fiber), Multiple Lines (MultipleLines), Device Protection (DeviceProtection), Online Backup (OnlineBackup)

Why this makes sense: recommendations prioritize relevant unseen products tailored to customer preferences.

## Notes

- The ranking model is the strongest overall offline model on NDCG@5 for tenant 'telco_default'.
- Collaborative filtering provides strong personalized recommendations when rich interaction history exists.
- Content-based and hybrid provide robust fallbacks for cold-start and newer customers.
