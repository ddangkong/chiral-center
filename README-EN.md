<div align="center">

# Chiral Center

**The center between real and simulated communities.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Vue 3](https://img.shields.io/badge/Vue-3.x-4FC08D?logo=vue.js)](https://vuejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org/)

[한국어](README.md) | **English**

**[Live Demo: www.axortex.com](https://www.axortex.com)** | **[Contact: help@axortex.com](mailto:help@axortex.com)**

</div>

---

## ⚡ Overview

**Chiral Center** is an LLM-powered social simulation platform that extracts knowledge graphs from documents, generates AI personas, and runs multi-agent discussion simulations.

Upload papers, reports, or articles — the system automatically extracts key concepts and relationships into a knowledge graph, then various stakeholder agents join a multi-round discussion. Results are compiled into structured analysis reports.

### Use Cases

- Policy impact analysis (stakeholder reaction simulation)
- Market entry strategy validation (competitor/consumer/regulator perspectives)
- Academic paper multi-angle analysis
- Public opinion simulation and risk prediction

## 📸 Screenshots

<table>
  <tr>
    <td><img src="static/screenshots/home.png?v=2" alt="Home" width="400"/></td>
    <td><img src="static/screenshots/graph.png?v=2" alt="Knowledge Graph" width="400"/></td>
  </tr>
  <tr>
    <td><img src="static/screenshots/persona.png?v=2" alt="Persona" width="400"/></td>
    <td><img src="static/screenshots/simulation.png?v=2" alt="Simulation" width="400"/></td>
  </tr>
  <tr>
    <td><img src="static/screenshots/report.png?v=2" alt="Report" width="400"/></td>
    <td><img src="static/screenshots/research.png?v=2" alt="Research" width="400"/></td>
  </tr>
</table>

## 🔄 Workflow

```
1. Upload Documents     PDF, DOCX, TXT, MD files
       ↓
2. Extract Knowledge    LLM extracts concepts/relations → Neo4j graph
       ↓
3. Create Personas      Auto-crawl web/YouTube + LLM profiling
       ↓
4. Run Simulation       Multi-agent discussion (fixed + dynamic + custom personas)
       ↓
5. Generate Report      LangGraph-based structured analysis report
```

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+**
- **Node.js 18+**
- **Neo4j** (optional — needed for persistent knowledge graph storage)
- **OpenAI API Key** or **Anthropic API Key**

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/ddangkong/chiral-center.git
cd chiral-center

# 2. Backend setup
cd backend
python -m venv .venv
source .venv/bin/activate    # macOS/Linux
# .venv\Scripts\activate     # Windows
pip install -r requirements.txt

# 3. Configure environment variables
cp ../.env.example ../.env
# Edit .env and add your API keys

# 4. Start backend
uvicorn main:app --reload --port 8001

# 5. Frontend setup (new terminal)
cd ../frontend
npm install
npm run dev
```

Open `http://localhost:3333` in your browser.

## ⚙️ Environment Variables

Create a `.env` file in the project root:

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_PROVIDER` | LLM provider (`openai` / `anthropic`) | `openai` |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `NEO4J_URI` | Neo4j connection URI | `bolt://localhost:7687` |
| `NEO4J_USER` | Neo4j username | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j password | — |
| `EMBEDDING_MODEL` | Embedding model | `all-MiniLM-L6-v2` |

## 🌐 Multi-Language Support

The UI supports 4 languages, switchable in settings:

- Korean (default)
- English
- Japanese
- Simplified Chinese

## 🛠 Tech Stack

### Frontend
| Technology | Version | Purpose |
|-----------|---------|---------|
| Vue 3 | 3.x | UI framework (Composition API) |
| Pinia | 2.x | State management |
| D3.js | 7.x | Knowledge graph visualization |
| Vite | 5.x | Build tool |
| TypeScript | 5.x | Type safety |

### Backend
| Technology | Version | Purpose |
|-----------|---------|---------|
| FastAPI | 0.115+ | Async web framework |
| LangGraph | 0.2+ | Report generation orchestration |
| Neo4j | 5.x | Knowledge graph storage |
| FAISS | — | Vector search (RAG) |
| Sentence-Transformers | 3.x | Text embeddings |

### Supported LLMs
- **OpenAI** — GPT-4o, GPT-4, etc.
- **Anthropic** — Claude Sonnet, Claude 3.5
- **Google Gemini** — Gemini 2.5 Flash/Pro
- **Alibaba Qwen** — Qwen Plus/Max
- **OpenAI-compatible APIs** — Local LLMs, etc.

## 📁 Project Structure

```
chiral-center/
├── frontend/              # Vue 3 SPA
│   ├── src/
│   │   ├── views/         # Page components
│   │   ├── components/    # Shared components
│   │   ├── stores/        # Pinia state management
│   │   ├── composables/   # Vue composables (i18n, etc.)
│   │   └── router/        # Routing
│   └── package.json
├── backend/               # FastAPI server
│   ├── api/               # API routers
│   ├── core/              # Core logic (simulation, research, reports)
│   ├── llm/               # LLM client abstraction
│   ├── models/            # Pydantic models
│   ├── db/                # FAISS vector DB
│   └── config.py          # Configuration
├── .env.example           # Environment variable template
└── vercel.json            # Vercel deployment config
```

## 🔒 Data Handling

All data (documents, simulation results, research, etc.) is stored in the **user's local browser (localStorage)**. No personal data is permanently stored on the server. API keys are also encrypted and stored only in the browser.

## 🤝 Contributing

This project is still in its early stages. We're looking for people who want to help build better simulations, richer analysis, and more diverse use cases. Ideas, bug reports, and PRs are all welcome. Let's evolve this together!

Contact: **help@axortex.com**

## 📄 License

This project is licensed under the [MIT License](LICENSE).
