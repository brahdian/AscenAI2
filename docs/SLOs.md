# Service Level Objectives (SLOs)

This document defines the performance and reliability targets for the AscenAI platform. These metrics are used to measure production readiness and guide operational improvements.

## 1. Voice Performance

| Metric | Target | measurement |
|---|---|---|
| Voice Call Setup Latency | < 800 ms (p95) | Time from WebSocket connect to first audio frame sent. |
| STT-to-First-Token Latency | < 1.2 s (p95) | Time from end-of-utterance to first generated word audio sent. |
| Session Drop Rate | < 0.1 % | % of sessions terminated due to server errors or pod evictions. |

## 2. API & Infrastructure

| Metric | Target | Measurement |
|---|---|---|
| Webhook Processing Success | > 99.9 % | % of incoming webhooks (Stripe, Twilio) processed successfully. |
| API Availability | > 99.99 % | Uptime of the API Gateway and downstream services. |
| API Latency | < 200 ms (p95) | Latency for core CRUD operations (excluding AI/RAG). |

## 3. Data Integrity & Compliance

| Metric | Target | Measurement |
|---|---|---|
| Billing Dedup Correctness | 100 % | Zero double-billing events due to race conditions. |
| RLS Leakage | 0 % | Zero cross-tenant data access incidents. |
| PII Redaction Coverage | 100 % | Zero unmasked PII in public-facing logs (Loki). |

## 4. Disaster Recovery

| Metric | Target | Measurement |
|---|---|---|
| Recovery Time Objective (RTO) | < 4 hours | Max time to restore service after a full DB failure. |
| Recovery Point Objective (RPO) | < 15 min | Max data loss window (WAL archiving lag). |
