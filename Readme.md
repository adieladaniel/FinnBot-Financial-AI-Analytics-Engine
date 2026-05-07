# AI-Powered Analytics Chatbot (Hybrid Rule-Based + LLM)


## Overview

This project is a hybrid analytics chatbot capable of answering natural language questions over uploaded datasets or API-fetched data.

The system combines:

* Rule-based analytics planning
* Dynamic schema understanding
* Measure/dimension detection
* Context-aware follow-up handling
* API-based dataset ingestion
* Gemini fallback for low-confidence queries
* Deterministic Pandas execution engine

The chatbot is designed to work across multiple dataset domains such as:

* School finance analytics
* Attendance analytics
* Sales analytics
* Inventory analytics
* Healthcare analytics
* Generic structured datasets

---

## Key Features

### Dataset Upload Support

Supports:

* CSV
* Excel (.xlsx)
* JSON
* API-based ingestion via cURL

---

### Automatic Schema Understanding

The system automatically detects:

* Measures
* Dimensions
* Numeric columns
* Categorical columns
* Date columns

---

### Hybrid Query Understanding

The bot first attempts:

1. Rule-based query planning
2. Schema-aware resolution
3. Context refinement
4. Gemini fallback only when confidence is low

This makes responses:

* Faster
* More deterministic
* More accurate for analytics

---

### Context Memory

Supports follow-up questions such as:

```txt
Show top 5 students with highest pending fees
Now tell their waiver amount
```

The bot preserves:

* Previous entities
* Grouping context
* Measure context
* Filters
* Ranking intent

---

### Finance-Aware Analytics

Special handling for:

* Outstanding fees
* Pending fees
* Concessions
* Waivers
* Payments
* Aggregated finance filtering

Supports correct grouped filtering such as:

```txt
Count students with outstanding fees = 0
```

using:

```txt
GROUP BY student
→ SUM outstanding
→ FILTER aggregated value
```

instead of incorrect row-level filtering.

---

### Date-Aware Analytics

Supports natural language date filtering:

Examples:

```txt
What was today's collection?
Show total collection this month
Show concession in January 2026
```

Supported date formats:

* today
* yesterday
* this month
* last month
* january / jan
* YYYY-MM-DD
* DD/MM/YYYY
* DD-MM-YYYY

---

### API Data Loading

Users can paste a cURL command.

The system automatically:

* Extracts headers
* Extracts query params
* Fetches API data
* Converts to DataFrame
* Builds measures and dimensions

---

### Visualizations

The frontend automatically generates:

* Bar charts
* Pie charts
* Comparison charts

with dynamic random coloring.

---

## Architecture

```txt
Frontend UI
    ↓
FastAPI Backend
    ↓
Context Engine
    ↓
Rule-Based Planner
    ↓
Gemini Fallback (if needed)
    ↓
Execution Engine (Pandas)
    ↓
Response + Visualization
```

---

# Project Structure

## Main Backend

### `app.py`

Main FastAPI application.

Handles:

* Upload routes
* API ingestion
* Chat endpoint
* Session management
* Context integration
* Gemini fallback routing
* Date filtering integration

---

## Core Engine (`core/`)

### `loader.py`

Loads datasets from:

* CSV
* JSON
* Excel

Converts into Pandas DataFrames.

---

### `api_loader.py`

Processes cURL commands.

Handles:

* Header extraction
* API calling
* Pagination
* JSON parsing
* Data normalization

---

### `profiler.py`

Profiles uploaded datasets.

Detects:

* Numeric columns
* Text columns
* Date columns
* Null percentages
* Cardinality

---

### `schema_builder.py`

Builds dynamic dataset schema.

Creates:

* Dimensions
* Measures
* Metadata

---

### `measures_builder.py`

Automatically creates measures such as:

```txt
Sum amount
Avg amount
Max amount
Min amount
```

---

### `planner.py`

Main rule-based analytics planner.

Converts user queries into structured plans.

Example:

```json
{
  "task": "grouped_table",
  "group_by": ["student_display"],
  "measure": "Sum outstanding_fee",
  "sort_order": "desc",
  "limit": 5
}
```

---

### `executor.py`

Executes structured plans using Pandas.

Supports:

* Single values
* Grouped tables
* Multi-measure comparisons
* Counts
* Aggregated finance filtering
* Date filtering
* Sorting
* Ranking

---

### `context.py`

Context memory engine.

Handles:

* Follow-up questions
* Entity carry-forward
* Context refinement
* Group preservation
* Filter preservation

---

### `memory.py`

Stores conversational session state.

---

### `llm_fallback.py`

Gemini fallback planner.

Used only when:

* Confidence is low
* Rule planner fails
* Query is highly semantic

---

### `date_filter.py`

Date parsing and filtering layer.

Handles:

* Relative dates
* Month parsing
* Date-range extraction
* Date filter injection

---

## Configs (`configs/`)

### `fees.json`

Domain-specific finance semantic mappings.

Contains:

* Semantic aliases
* Zero-value phrases
* Context measure words
* Finance-specific mappings

Example:

```json
"pending fees": "outstanding_fee"
```

---

## Frontend (`frontend/`)

### `index.html`

Main UI page.

---

### `script.js`

Handles:

* Uploading datasets
* API uploads
* Chat requests
* Rendering responses
* Rendering charts
* Loading states

---

### `style.css`

Frontend styling.

---

### `static/`

Stores:

* Logo
* Icons
* Static assets

---

# Example Questions

## Finance Analytics

```txt
Show top 10 students with highest pending fees
Show top 5 students with highest concession amount
Show top 5 students with highest waiver amount
Give count of students having pending fees as 0
Give count of students having outstanding amount as 0
Give count of students having concession amount as 0
Show students with pending fees greater than 50000
Show students with concession amount greater than 10000
```

---

## Date-Based Queries

```txt
What was today's collection?
Show collection this month
Show payments received in March 2026
```

---


## Collection/Revenue-Based Queries

```txt
What was the total collection of today
What was the fees received on 1st april
What is the total fees received on the month of april
Show collection this month
Show monthly collection trend
Show highest collection day this month
Show total collection class-wise
```

---
## Chart-Based Queries

```txt
Show total concession amount this month as a bar chart
Show pending fees class-wise as a pie chart
Show collection month-wise as a line chart
Compare waiver vs concession as a bar chart
```

---



## Context-Aware Queries

```txt
Show top 5 students with highest pending fees
Now tell their waiver amount
```

---

# Running the Project

## Backend

Install dependencies:

```bash
pip install -r requirements.txt
```

Run backend:

```bash
uvicorn app:app --reload
```

Backend runs on:

```txt
http://127.0.0.1:8000
```

---

## Frontend

Frontend is served directly through FastAPI.

Open:

```txt
http://127.0.0.1:8000
```

---

# Deployment Recommendations

Recommended production deployment:

* FastAPI backend on VPS/cloud VM
* Frontend served through FastAPI or CDN
* Redis for session caching
* HTTPS enabled
* API secrets stored in environment variables

Recommended platforms:

* AWS EC2
* Azure VM
* GCP VM
* DigitalOcean
* Hetzner

---

# Future Improvements

Planned improvements:

* Generic query typo correction
* Schema-aware fuzzy matching
* Ollama local query repair
* Advanced date parsing
* Multi-turn analytics memory
* Dashboard embedding widgets
* Authentication and RBAC
* Vector memory
* Streaming responses
* SQL execution backend
* Multi-dataset joins

---

