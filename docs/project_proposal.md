# Customer Product Recommendation Engine — Project Proposal

_In-repo reference copy. See the full formatted version shared with your
supervisor for the presentation-ready doc/deck._

## Executive Summary

This proposal outlines the design and delivery plan for a product
recommendation engine that will surface personalized product and plan
suggestions for both new and existing customers. The engine is built on
internal customer/product data, extended with a third-party API, and
designed to complement the company's existing customer-facing agent.

## Objectives

- Design and build a recommendation engine using current and new customer data
- Integrate a third-party API to extend and support the recommendation pipeline
- Address the cold-start problem for new customers with limited history
- Establish a clear, measurable evaluation framework (offline and business metrics)
- Determine and formalize how the engine interoperates with the existing agent
- Deliver a working prototype suitable for stakeholder review

## Scope

**In scope:** data collection & preprocessing, exploratory data analysis,
a hybrid recommendation approach (rule-based / content-based / collaborative
filtering), offline evaluation, and documentation.

**Out of scope (this phase):** full production deployment / live A-B
testing, and changes to the existing agent's core functionality.

## Methodology

1. **Discovery** — finalize business objective, data access, agent integration
2. **Data Pipeline** — ingest, clean, join internal + third-party data
3. **Baseline Model** — rule-based / content-based recommender
4. **Iteration** — collaborative filtering / hybrid ranking model
5. **Evaluation** — offline metrics + business-relevant review
6. **Handoff** — present findings, propose integration path

## Success Metrics

- Offline: precision@k, recall@k, NDCG
- Business alignment with the finalized objective (upsell / cross-sell / retention)
- System quality: pipeline reliability, reproducibility
- Stakeholder validation / sign-off

## Risks & Open Items

- Exact relationship to the existing agent — still being finalized
- Primary business objective and where recommendations surface — pending confirmation
- Data privacy/compliance constraints on customer usage data — still under review
- Third-party API capabilities/limitations — to be assessed during Phase 1

## Current Status

Prototyping against the public Telco Customer Churn dataset (see main
README.md). Company API and agent integrations are scaffolded in
`src/integrations/` but intentionally not active yet.

The primary shipped recommendation model is the learned ranking model; the
hybrid, content-based, and collaborative-filtering models remain documented
alternatives and baselines.
