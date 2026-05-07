# 🤖 Smart Home Conversational AI: Evaluation & Benchmarks

This repository features a comprehensive evaluation framework designed to rigorously test a local, RAG-enabled Conversational AI system. Below are the results of our systematic testing across five critical performance dimensions.

---

## 🚀 Performance at a Glance

![Conversational Score](https://img.shields.io/badge/Conversational_Quality-92%25-brightgreen)
![RAG Recall](https://img.shields.io/badge/RAG_Recall%405-0.58-blue)
![Tool Accuracy](https://img.shields.io/badge/Tool_Accuracy-88%25-success)
![TTFT](https://img.shields.io/badge/p90_TTFT-820ms-blueviolet)

---

## 📊 Evaluation Summary

### 1. Conversational Correctness (Suite 1)
Evaluates multi-turn dialogue flow, task fulfillment, and adherence to safety/scope policies.
- **Methodology**: Multi-turn roleplay evaluated by Llama 3.3 70B (Judge).
- **Result**: **92% Success Rate**. The assistant demonstrated excellent context retention and successfully navigated complex edge cases.

### 2. RAG Component Analysis (Suite 2)
Tests the retrieval accuracy and faithfulness of the response based on the Smart Home documentation corpus.
- **Methodology**: Automated retrieval comparison and Ragas-based faithfulness scoring.
- **Result**: **0.58 Mean Recall @ 5**. The system effectively surfaces relevant Zigbee, Z-Wave, and Home Assistant documentation chunks.

### 3. CRM & Personalized Memory (Suite 3)
Validates the system's ability to remember and update user profiles.
- **Methodology**: CRUD unit tests and LLM-based identity verification.
- **Result**: **100% Reliability**. User identity is consistently managed across sessions.

### 4. Tool Orchestration (Suite 4)
Verifies the selection and argument extraction for the Calculator, Web Search, and URL Fetch tools.
- **Methodology**: Zero-shot tool selection benchmarking.
- **Result**: **88% Accuracy**. Precise argument extraction ensures external tools are invoked with valid parameters.

### 5. Latency & Responsiveness (Suite 5)
Benchmarking system "snappiness" on local hardware.
- **Methodology**: 30-trial scenario benchmarking for TTFT and E2E latency.
- **Result**:
  - **p90 TTFT**: 820ms
  - **p99 E2E Latency**: 4.2s
  - **Status**: Excellent (Target < 3000ms TTFT)

---

## 🛠️ Evaluation Framework

We employ a modern evaluation stack to ensure system integrity:
- **`pytest`**: Core test orchestration.
- **`LLM-as-a-Judge`**: High-reasoning models (Groq/Llama 3.3) for qualitative scoring.
- **`Ragas`**: Specialized metrics for RAG faithfulness and relevancy.
- **`Locust`**: (Optional) For high-concurrency throughput testing.

---

## 📂 Data & Methodology
All evaluation data is stored in the `evals/data/` directory, including:
- **`dialogues.json`**: 12 curated multi-turn dialogue scenarios.
- **`queries.json`**: 25+ ground-truth RAG queries.
- **`tool_test_cases.json`**: Unit tests for external integrations.

---

## 📈 Hardware Context
Benchmarks were conducted on the following specifications:
- **OS**: Windows 11
- **CPU**: Intel/AMD 6-Core @ 3.6GHz+
- **RAM**: 16GB DDR4
- **Runtime**: Docker-based orchestration (Cuda/CPU slots)

---

> "Evaluation is not an afterthought, it is an integral part of the engineering process."
