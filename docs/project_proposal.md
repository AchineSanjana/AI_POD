# Customer Product Recommendation Engine — Project Proposal

_In-repo reference copy for the completed prototype._

## Executive Summary

This project delivers a recommendation engine prototype for the public Telco Customer Churn dataset. The final scope focused on a reproducible data pipeline, multiple recommender models, offline evaluation, and a CLI for retrieving recommendations. No third-party API, company integration, or agent-facing integration was included in the shipped phase.

## Objectives

- Build a reproducible recommendation pipeline from raw customer and product data
- Compare content-based, collaborative-filtering, hybrid, and learned ranking approaches
- Measure recommendation quality with offline ranking metrics
- Deliver a prototype that can be run locally and inspected through the repository artifacts

## Scope

**In scope:** data ingestion and preprocessing, exploratory analysis, model training and evaluation, documentation, and a CLI-based recommendation workflow.

**Out of scope for this phase:** third-party enrichment, company API integration, and customer-agent integration. The integration scaffolding in [src/integrations](src/integrations) remains inactive and is not part of the final delivered workflow.

## Methodology

1. **Data Pipeline** — ingest the Telco dataset and generate processed customer, product, and interaction tables
2. **Baseline Models** — fit content-based, collaborative-filtering, and hybrid recommenders
3. **Learned Ranking Model** — fit a gradient-boosted ranking model for top-k recommendation generation
4. **Evaluation** — create a customer-wise held-out split and measure precision@5, recall@5, and NDCG@5
5. **Delivery** — package the workflow into reusable scripts and document the results in the repository

## Final Results

The final offline evaluation used a held-out split with 17,239 training rows and 11,963 test rows across 7,043 customers.

- Ranking model: precision@5 = 0.293, recall@5 = 0.880, NDCG@5 = 0.751
- Hybrid model: precision@5 = 0.249, recall@5 = 0.737, NDCG@5 = 0.595
- Content-based model: precision@5 = 0.222, recall@5 = 0.659, NDCG@5 = 0.503
- Collaborative-filtering model: precision@5 = 0.252, recall@5 = 0.678, NDCG@5 = 0.493

Segment analysis showed that the ranking model was strongest for newer customers (NDCG@5 = 0.784), while collaborative filtering was strongest for established customers (NDCG@5 = 0.716).

## Success Metrics

- Offline ranking quality for the shipped learned ranking model: precision@5 = 0.293, recall@5 = 0.880, NDCG@5 = 0.751
- Stronger-than-baseline performance on the held-out split: hybrid reached 0.595 NDCG@5, while content-based and collaborative filtering reached 0.503 and 0.493 respectively
- Reproducibility: the pipeline and evaluation scripts run from the repository without manual intervention
- Usability: recommendations can be retrieved for a specific customer through the CLI

## Risks & Open Items

- The current prototype is intentionally scoped to an offline, local workflow; broader production integration remains out of scope for this phase
- Future adoption will depend on whether the team wants to expand the evaluation beyond offline ranking metrics and into business-facing validation
- Data availability and model artifact maintenance should be preserved so the repository remains runnable end to end

## Next Steps

- Harden the local prototype into a more polished demo workflow with clearer run instructions and example outputs
- Extend the evaluation suite if a future business case requires richer validation beyond offline ranking metrics
- Revisit company API and agent integration only as a future phase if the prototype is adopted for a broader deployment journey

## Current Status

The project is now implemented as a local prototype using the public Telco dataset. The primary shipped recommender is the learned ranking model, and the other models remain available as baselines and fallbacks. The current repository state is documented in [README.md](README.md) and [docs/evaluation_results.md](docs/evaluation_results.md).
