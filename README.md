<div align="center">

# Chiral Center

**실제 커뮤니티와 시뮬레이션 커뮤니티 사이의 중심**

*The center between real and simulated communities.*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Vue 3](https://img.shields.io/badge/Vue-3.x-4FC08D?logo=vue.js)](https://vuejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org/)

[English](README-EN.md) | **한국어**

</div>

---

## ⚡ 프로젝트 소개

**Chiral Center**는 문서를 기반으로 지식 그래프를 추출하고, AI 페르소나를 생성하여 다자간 토론 시뮬레이션을 실행하는 LLM 기반 소셜 시뮬레이션 플랫폼입니다.

논문, 보고서, 기사 등의 문서를 업로드하면 자동으로 핵심 개념과 관계를 추출하여 지식 그래프를 구성하고, 이를 바탕으로 다양한 이해관계자 에이전트가 토론에 참여합니다. 시뮬레이션 결과는 구조화된 분석 보고서로 자동 생성됩니다.

### 주요 활용 사례

- 정책 영향 분석 (이해관계자 반응 시뮬레이션)
- 시장 진입 전략 검증 (경쟁사/소비자/규제기관 관점)
- 학술 논문 다각도 분석
- 여론 시뮬레이션 및 리스크 예측

## 📸 스크린샷

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

## 🔄 워크플로우

```
1. 문서 업로드        PDF, DOCX, TXT, MD 파일 업로드
       ↓
2. 지식 그래프 추출    LLM이 개념/관계를 추출 → Neo4j 그래프 저장
       ↓
3. 페르소나 생성       웹/유튜브 자동 크롤링 + LLM 프로파일링
       ↓
4. 시뮬레이션 실행     다자간 토론 (고정 역할 + 동적 에이전트 + 커스텀 페르소나)
       ↓
5. 보고서 생성        LangGraph 기반 구조화된 분석 보고서 자동 작성
```

## 🚀 빠른 시작

### 사전 요구사항

- **Python 3.11+**
- **Node.js 18+**
- **Neo4j** (선택 — 지식 그래프 영구 저장 시 필요)
- **OpenAI API Key** 또는 **Anthropic API Key**

### 설치

```bash
# 1. 레포 클론
git clone https://github.com/ddangkong/chiral-center.git
cd chiral-center

# 2. 백엔드 설정
cd backend
python -m venv .venv
.venv/Scripts/activate       # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt

# 3. 환경 변수 설정
cp ../.env.example ../.env
# .env 파일을 열어 API 키 입력

# 4. 백엔드 실행
uvicorn main:app --reload --port 8001

# 5. 프론트엔드 설정 (새 터미널)
cd ../frontend
npm install
npm run dev
```

브라우저에서 `http://localhost:3333` 접속

## ⚙️ 환경 변수

`.env` 파일을 프로젝트 루트에 생성하세요:

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `LLM_PROVIDER` | LLM 제공자 (`openai` / `anthropic`) | `openai` |
| `OPENAI_API_KEY` | OpenAI API 키 | — |
| `ANTHROPIC_API_KEY` | Anthropic API 키 | — |
| `NEO4J_URI` | Neo4j 접속 URI | `bolt://localhost:7687` |
| `NEO4J_USER` | Neo4j 사용자명 | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j 비밀번호 | — |
| `EMBEDDING_MODEL` | 임베딩 모델 | `all-MiniLM-L6-v2` |

## 🌐 다국어 지원

UI는 4개 언어를 지원합니다. 설정에서 변경 가능합니다:

- 🇰🇷 한국어 (기본)
- 🇺🇸 English
- 🇯🇵 日本語
- 🇨🇳 简体中文

## 🛠 기술 스택

### Frontend
| 기술 | 버전 | 용도 |
|------|------|------|
| Vue 3 | 3.x | UI 프레임워크 (Composition API) |
| Pinia | 2.x | 상태 관리 |
| D3.js | 7.x | 지식 그래프 시각화 |
| Vite | 5.x | 빌드 도구 |
| TypeScript | 5.x | 타입 안전성 |

### Backend
| 기술 | 버전 | 용도 |
|------|------|------|
| FastAPI | 0.115+ | 비동기 웹 프레임워크 |
| LangGraph | 0.2+ | 보고서 생성 오케스트레이션 |
| Neo4j | 5.x | 지식 그래프 저장소 |
| FAISS | — | 벡터 검색 (RAG) |
| Sentence-Transformers | 3.x | 텍스트 임베딩 |

### LLM 지원
- **OpenAI** — GPT-4o, GPT-4 등
- **Anthropic** — Claude Sonnet, Claude 3.5
- **Google Gemini** — Gemini 2.5 Flash/Pro
- **Alibaba Qwen** — Qwen Plus/Max
- **OpenAI 호환 API** — 로컬 LLM 등

## 📁 프로젝트 구조

```
chiral-center/
├── frontend/              # Vue 3 SPA
│   ├── src/
│   │   ├── views/         # 페이지 컴포넌트
│   │   ├── components/    # 공통 컴포넌트
│   │   ├── stores/        # Pinia 상태 관리
│   │   ├── composables/   # Vue 컴포저블 (i18n 등)
│   │   └── router/        # 라우팅
│   └── package.json
├── backend/               # FastAPI 서버
│   ├── api/               # API 라우터
│   ├── core/              # 핵심 로직 (시뮬레이션, 리서치, 보고서)
│   ├── llm/               # LLM 클라이언트 추상화
│   ├── models/            # Pydantic 모델
│   ├── db/                # FAISS 벡터 DB
│   └── config.py          # 환경 설정
├── .env.example           # 환경 변수 템플릿
└── vercel.json            # Vercel 배포 설정
```

## 📄 라이선스

이 프로젝트는 [MIT License](LICENSE)로 배포됩니다.
