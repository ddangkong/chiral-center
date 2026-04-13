"""Simulation execution routes."""
import asyncio
import json
import pathlib
import re
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from core.session import get_session_id, register_owner, is_owner, filter_owned_ids


# ── Q&A에서 사용하는 외부 검색 헬퍼 ─────────────────────────────────
_WEB_SEARCH_RE = re.compile(r"\[WEB_SEARCH:\s*([^\]\n]{1,200})\]")


def _extract_search_queries(text: str) -> list[str]:
    """LLM 답변에서 [WEB_SEARCH: 쿼리] 토큰을 추출 (중복 제거)."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _WEB_SEARCH_RE.finditer(text or ""):
        q = m.group(1).strip()
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out


async def _run_web_searches(queries: list[str]) -> list[tuple[str, list[dict]]]:
    """DuckDuckGo로 쿼리들을 동시에 검색해서 [(query, hits[]), ...] 반환.

    각 hit: {'title': str, 'url': str, 'snippet': str}
    """
    try:
        from duckduckgo_search import DDGS
    except Exception:
        return []

    loop = asyncio.get_event_loop()

    def _search_one(query: str) -> list[dict]:
        try:
            with DDGS() as ddgs:
                hits = list(ddgs.text(query, region="kr-kr", max_results=5))
            return [
                {
                    "title": h.get("title", ""),
                    "url": h.get("href", ""),
                    "snippet": h.get("body", ""),
                }
                for h in hits
            ]
        except Exception as e:
            print(f"[QA] DDG search error for '{query}': {e}", flush=True)
            return []

    results: list[tuple[str, list[dict]]] = []
    # 동시 실행 (executor)
    tasks = [loop.run_in_executor(None, _search_one, q) for q in queries]
    hits_list = await asyncio.gather(*tasks)
    for q, hits in zip(queries, hits_list):
        if hits:
            results.append((q, hits))
    return results


def _format_search_results(blocks: list[tuple[str, list[dict]]]) -> str:
    """검색 결과를 LLM follow-up 프롬프트에 넣을 텍스트로 직렬화."""
    parts: list[str] = []
    n = 0
    for query, hits in blocks:
        parts.append(f"\n[검색어: {query}]")
        for h in hits:
            n += 1
            snippet = (h.get("snippet") or "").strip().replace("\n", " ")
            if len(snippet) > 350:
                snippet = snippet[:350] + "..."
            parts.append(f"  {n}. {h.get('title','').strip()}")
            parts.append(f"     {h.get('url','').strip()}")
            if snippet:
                parts.append(f"     {snippet}")
    return "\n".join(parts).strip()

_SIM_DIR = pathlib.Path(__file__).parent.parent.parent / "data" / "simulations"
_SIM_DIR.mkdir(parents=True, exist_ok=True)


def _save_sim(sim_result) -> None:
    """Persist a SimResult to disk so report generation survives restarts."""
    path = _SIM_DIR / f"{sim_result.id}.json"
    path.write_text(sim_result.model_dump_json(), encoding="utf-8")


def _load_sim(sim_id: str):
    """Load a SimResult from disk. Returns None if not found."""
    from models.simulation import SimResult
    path = _SIM_DIR / f"{sim_id}.json"
    if not path.exists():
        return None
    try:
        return SimResult.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None

from llm.factory import get_llm_client
from core.simulation_runner import SimulationEngine
from core.persona_factory import PersonaFactory
from core.graph_updater import graph_updater
from core.graph_builder import graph_builder
from models.simulation import SimConfig

router = APIRouter()

# In-memory stores
_engines: dict[str, SimulationEngine] = {}
_persona_factories: dict[str, PersonaFactory] = {}


class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: Optional[str] = None


class RestoreRequest(BaseModel):
    sim_id: str
    topic: str = ""
    total_rounds: int = 0
    events: list[dict] = []


class AgentOverride(BaseModel):
    role: str
    system_prompt: str = ""

class SimRunRequest(BaseModel):
    ontology_id: str
    topic: str = ""
    num_rounds: int = 10
    max_personas: int = 10
    platform: str = "discussion"
    llm: LLMConfig = LLMConfig()
    injection_events: list[dict] = []
    project_id: Optional[str] = None  # DB 에이전트 연동용
    global_directive: Optional[str] = None  # 전체 에이전트 추가 지시
    agent_overrides: list[AgentOverride] = []  # 부서별 추가 프롬프트
    disabled_roles: list[str] = []  # 제외할 부서 역할
    custom_profiles: list[dict] = []  # 프로파일링된 외부 인물
    entity_personas: list[str] = []  # 참여시킬 지식그래프 엔티티 ID 목록
    temperature: Optional[float] = None  # LLM temperature (0.3/0.7/1.0)
    min_chars: Optional[int] = None  # 발언 최소 글자수
    max_chars: Optional[int] = None  # 발언 최대 글자수


@router.get("/list")
async def list_simulations(request: Request):
    """저장된 시뮬레이션 목록 반환 (현재 세션 소유분만)."""
    import json as _json
    sid = get_session_id(request)
    results = []
    if _SIM_DIR.exists():
        for f in sorted(_SIM_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                data = _json.loads(f.read_text(encoding="utf-8"))
                rid = data.get("id", f.stem)
                if not is_owner("simulation", rid, sid):
                    continue
                results.append({
                    "id": rid,
                    "topic": data.get("config", {}).get("topic", ""),
                    "status": data.get("status", ""),
                    "events": len(data.get("events", [])),
                })
                if len(results) >= 20:
                    break
            except:
                pass
    return results


@router.post("/restore")
async def restore_simulation(req: RestoreRequest, request: Request):
    """Restore a simulation from frontend persisted data (survives server restart)."""
    from models.simulation import SimResult, SimConfig, SimEvent, SimStatus

    # Already saved — nothing to do
    if (_SIM_DIR / f"{req.sim_id}.json").exists():
        register_owner("simulation", req.sim_id, get_session_id(request))
        return {"status": "already_exists", "sim_id": req.sim_id}

    config = SimConfig(
        id=req.sim_id,
        ontology_id="",
        topic=req.topic,
        num_rounds=req.total_rounds,
    )
    events = []
    for e in req.events:
        action = e.get("action", "")
        if action in ("post", "reply", "repost", "injection"):
            events.append(SimEvent(
                round_num=e.get("round", 0),
                persona_id=e.get("agentId", ""),
                persona_name=e.get("agentName", ""),
                action_type=action,
                content=e.get("content", ""),
            ))

    sim_result = SimResult(
        id=req.sim_id,
        config=config,
        status=SimStatus.COMPLETED,
        events=events,
        current_round=req.total_rounds,
        total_rounds=req.total_rounds,
    )
    _save_sim(sim_result)
    register_owner("simulation", req.sim_id, get_session_id(request))
    return {"status": "restored", "sim_id": req.sim_id, "events": len(events)}


@router.post("/run")
async def run_simulation(req: SimRunRequest, request: Request):
    """Start a simulation (returns SSE stream)."""
    print(f"[SIM] entity_personas received: {req.entity_personas}", flush=True)
    if not req.llm.api_key:
        raise HTTPException(400, "API key is required")

    # 부모 온톨로지 소유권 체크
    if not is_owner("ontology", req.ontology_id, get_session_id(request)):
        raise HTTPException(404, "Ontology not found")

    req.platform = "discussion"

    llm = get_llm_client(
        provider=req.llm.provider,
        api_key=req.llm.api_key,
        model=req.llm.model,
        base_url=req.llm.base_url,
        feature="simulation",
    )

    # Generate personas from ontology — memory → disk → graph reconstruction
    from api.routes.ontology import _builders, _load_onto_or_reconstruct

    ontology_result = None
    for builder in _builders.values():
        result = builder.get_result(req.ontology_id)
        if result:
            ontology_result = result
            break

    if not ontology_result:
        ontology_result = await _load_onto_or_reconstruct(req.ontology_id)

    if not ontology_result:
        raise HTTPException(404, "Ontology not found. Extract ontology first.")

    # max_personas = 동적(LLM 생성) 역할 수.
    # 고정 역할(core 5 + support 4)·entity·custom 은 모두 사용자가 추가로 켠 만큼 별도 가산된다.
    # → 이중 차감, max(3,..) 강제 최소치, 커스텀 재계산 버그를 모두 제거한다.
    dynamic_slots = max(0, req.max_personas)
    entity_count = len(req.entity_personas) if req.entity_personas else 0
    custom_count = len(req.custom_profiles) if req.custom_profiles else 0
    print(
        f"[SIM] dynamic={dynamic_slots}, entity={entity_count}, custom={custom_count}",
        flush=True,
    )

    factory = PersonaFactory(llm)
    personas: list = []
    if dynamic_slots > 0 or custom_count > 0:
        personas = await factory.generate_personas(
            ontology_result,
            max_personas=dynamic_slots,
            disabled_roles=req.disabled_roles,
            custom_profiles=req.custom_profiles if req.custom_profiles else None,
        )

    # 엔티티 기반 페르소나 생성 (선택된 경우)
    print(f"[SIM] checking entity_personas: {req.entity_personas}, len={len(req.entity_personas)}", flush=True)
    if req.entity_personas:
        print(f"[SIM] generating entity personas for {len(req.entity_personas)} entities", flush=True)
        try:
            entity_personas = await factory.generate_entity_personas(
                entity_ids=req.entity_personas,
                ontology=ontology_result,
                topic=req.topic or ontology_result.topic,
            )
            print(f"[SIM] entity personas generated: {len(entity_personas)}", flush=True)
            personas.extend(entity_personas)
        except Exception as e:
            print(f"[SIM] entity persona generation FAILED: {e}", flush=True)
            import traceback; traceback.print_exc()
            # 엔티티 페르소나 생성 실패 시 기존 페르소나만으로 진행

    config = SimConfig(
        ontology_id=req.ontology_id,
        topic=req.topic or ontology_result.topic,
        platform=req.platform,
        num_rounds=req.num_rounds,
        personas=[p.id for p in personas],
        injection_events=req.injection_events,
    )

    engine = SimulationEngine(llm)
    if req.min_chars is not None:
        engine._min_chars = req.min_chars
    if req.temperature is not None:
        engine._temperature = req.temperature
    _engines[config.id] = engine
    _persona_factories[config.id] = factory

    # 세션 소유권 등록 — 시뮬 시작 시점에 즉시 기록
    register_owner("simulation", config.id, get_session_id(request))

    # Build ontology context — prefer community summaries if available
    ontology_context = ""
    try:
        graph_data = await graph_builder.get_graph_data(req.ontology_id)
        communities = graph_data.get("communities", [])
        has_summaries = any(c.get("summary") for c in communities)

        if has_summaries:
            # Use structured community summaries
            context_parts = ["=== 지식 그래프 커뮤니티 요약 ==="]
            for c in communities:
                if c.get("summary"):
                    members = ", ".join(c.get("member_names", [])[:8])
                    context_parts.append(f"\n[클러스터 {c['id']}] ({members})")
                    context_parts.append(c["summary"])
            ontology_context = "\n".join(context_parts)
        else:
            # Fallback: entity/relation listing
            ontology_lines = []
            for e in ontology_result.entities[:30]:
                desc = f"- {e.name} ({e.type}): {e.description}" if e.description else f"- {e.name} ({e.type})"
                ontology_lines.append(desc)
            for r in ontology_result.relations[:20]:
                src = next((e.name for e in ontology_result.entities if e.id == r.source_id), r.source_id)
                tgt = next((e.name for e in ontology_result.entities if e.id == r.target_id), r.target_id)
                ontology_lines.append(f"- {src} --[{r.relation_type}]--> {tgt}: {r.description}")
            ontology_context = "Key entities and relationships:\n" + "\n".join(ontology_lines) if ontology_lines else ""
    except Exception:
        # Fallback on any error
        ontology_lines = []
        for e in ontology_result.entities[:30]:
            desc = f"- {e.name} ({e.type}): {e.description}" if e.description else f"- {e.name} ({e.type})"
            ontology_lines.append(desc)
        ontology_context = "\n".join(ontology_lines)

    # Build agent prompt overrides map: role_name -> extra system prompt
    prompt_overrides: dict[str, str] = {}
    for ov in req.agent_overrides:
        if ov.system_prompt.strip():
            prompt_overrides[ov.role] = ov.system_prompt.strip()

    # ── 고정 역할 에이전트: 한 번만 생성하고 disabled_roles 필터 일원화 ──
    # 이렇게 해야 프론트에 브로드캐스트하는 agent id와 실제 simulation runner의 id가
    # 일치한다. 이전에는 event_stream 쪽과 _run_discussion_mode 쪽에서 각각
    # create_fixed_role_agents()를 호출해서 UUID가 어긋났다.
    from core.fixed_roles import create_fixed_role_agents as _create_fixed

    def _norm(key: str) -> str:
        return (key or "").strip().lower().replace(" ", "_")

    _disabled_set = {_norm(r) for r in (req.disabled_roles or []) if r and r.strip()}

    def _is_enabled(agent) -> bool:
        return (
            _norm(agent.fixed_role_id or "") not in _disabled_set
            and _norm(agent.role or "") not in _disabled_set
        )

    fixed_core_all, fixed_support_all = _create_fixed(
        topic=config.topic, ontology_context=ontology_context,
    )
    fixed_core = [a for a in fixed_core_all if _is_enabled(a)]
    fixed_support = [a for a in fixed_support_all if _is_enabled(a)]

    total_participants = len(fixed_core) + len(personas)  # fixed_core + (dynamic+custom+entity)
    if total_participants == 0:
        raise HTTPException(
            400,
            "발언할 에이전트가 없습니다. Settings에서 core 역할을 최소 1개 이상 켜거나, 에이전트 수(maxPersonas)를 1 이상으로 설정하세요.",
        )

    async def event_stream():
        """SSE event stream."""
        # Discussion 모드면 고정역할 에이전트 목록을 보냄
        if config.platform == "discussion":
            start_personas = list(fixed_core) + [a for a in fixed_support if a.must_speak]
            # dynamic(LLM) + entity + custom 전부 start 목록에 포함
            extra_agents = [p for p in personas if getattr(p, 'agent_tier', '') in ('entity', 'dynamic')]
            if extra_agents:
                start_personas = start_personas + extra_agents
        else:
            start_personas = personas
        yield f"data: {json.dumps({'type': 'start', 'sim_id': config.id, 'personas': [{'id': p.id, 'name': p.name, 'role': p.role, 'stance': p.stance} for p in start_personas]})}\n\n"

        # temperature/글자수 옵션을 global_directive에 통합
        print(f"[SIM] temperature={req.temperature}, min_chars={req.min_chars}, max_chars={req.max_chars}", flush=True)
        effective_directive = req.global_directive or ""
        if req.temperature is not None:
            temp_label = {0.3: "보수적이고 분석적인", 0.7: "균형 잡힌", 1.0: "창의적이고 자유로운"}.get(req.temperature, "")
            if temp_label:
                effective_directive += f"\n\n발언 스타일: {temp_label} 톤으로 답변하세요."
        if req.min_chars:
            effective_directive += f"\n각 발언은 최소 {req.min_chars}자 이상이어야 합니다."
        if req.max_chars:
            effective_directive += f"\n각 발언은 최대 {req.max_chars}자를 넘지 마세요."

        async for event in engine.run_simulation(
            config, personas,
            project_id=req.project_id,
            ontology_context=ontology_context,
            global_directive=effective_directive,
            prompt_overrides=prompt_overrides,
            disabled_roles=req.disabled_roles,
            fixed_core_agents=fixed_core,
            fixed_support_agents=fixed_support,
        ):
            event_data = {
                "type": "event",
                "round": event.round_num,
                "persona": event.persona_name,
                "persona_id": event.persona_id,
                "action": event.action_type,
                "content": event.content,
                "target": event.target_id,
                "event_id": getattr(event, 'event_id', ''),
                "thread_id": getattr(event, 'thread_id', None),
                "parent_event_id": getattr(event, 'parent_event_id', None),
            }
            yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

            # Update graph with simulation events
            try:
                await graph_updater.process_event(event, req.ontology_id)
            except Exception:
                pass

        # Persist to disk so report generation works after server restart
        try:
            sim_result = engine.get_simulation(config.id)
            if sim_result:
                _save_sim(sim_result)
        except Exception:
            pass

        yield f"data: {json.dumps({'type': 'complete', 'sim_id': config.id})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/{sim_id}")
async def get_simulation(sim_id: str, request: Request):
    """Get simulation status and results."""
    if not is_owner("simulation", sim_id, get_session_id(request)):
        raise HTTPException(404, "Simulation not found")
    for engine in _engines.values():
        sim = engine.get_simulation(sim_id)
        if sim:
            return {
                "id": sim.id,
                "status": sim.status.value,
                "current_round": sim.current_round,
                "total_rounds": sim.total_rounds,
                "events": len(sim.events),
            }
    # Fallback: load from disk (survives server restart)
    sim = _load_sim(sim_id)
    if sim:
        return {
            "id": sim.id,
            "status": sim.status.value,
            "current_round": sim.current_round,
            "total_rounds": sim.total_rounds,
            "events": len(sim.events),
        }
    raise HTTPException(404, "Simulation not found")


@router.post("/stop")
async def stop_simulation(sim_id: str, request: Request):
    """Stop a running simulation."""
    if not is_owner("simulation", sim_id, get_session_id(request)):
        raise HTTPException(404, "Simulation not found")
    for engine in _engines.values():
        sim = engine.get_simulation(sim_id)
        if sim:
            engine.stop_simulation(sim_id)
            return {"status": "stopping", "sim_id": sim_id}
    raise HTTPException(404, "Simulation not found")


class SimQARequest(BaseModel):
    sim_id: str
    question: str
    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: Optional[str] = None


@router.post("/qa")
async def simulation_qa(req: SimQARequest, request: Request):
    """시뮬레이션 토론 내용에 대한 질의응답 (LLM 기반).

    1차 답변에서 LLM이 외부 정보가 필요하다고 판단하면 [WEB_SEARCH: 쿼리] 토큰을
    출력할 수 있고, 이 경우 백엔드가 DuckDuckGo로 실제 검색해서 결과를 컨텍스트에
    덧붙인 뒤 2차 답변을 생성한다. 토론 내 데이터 우선, 외부 검색은 보조 수단.
    """
    if not is_owner("simulation", req.sim_id, get_session_id(request)):
        raise HTTPException(404, "Simulation not found")
    if not req.api_key:
        raise HTTPException(400, "API key is required")

    # 1. 시뮬레이션 결과 로드 (메모리 → 디스크)
    sim = None
    for engine in _engines.values():
        sim = engine.get_simulation(req.sim_id)
        if sim:
            break
    if not sim:
        sim = _load_sim(req.sim_id)
    if not sim:
        raise HTTPException(404, "Simulation not found")

    # 2. 이벤트를 컨텍스트로 구성
    context_parts = []
    context_parts.append(f"토론 주제: {sim.config.topic}")
    context_parts.append(f"총 {sim.total_rounds}라운드, {len(sim.events)}개 발언\n")

    # 참여자 목록
    participants = {}
    for evt in sim.events:
        if evt.persona_id and evt.persona_id not in ("__moderator__", "__db_agent__"):
            if evt.persona_id not in participants:
                participants[evt.persona_id] = evt.persona_name

    if participants:
        context_parts.append("참여자: " + ", ".join(participants.values()))
        context_parts.append("")

    # 이벤트를 라운드별로 구성 (토큰 절약: 각 발언 최대 800자)
    MAX_CHARS_PER_EVENT = 800
    current_round = 0
    for evt in sim.events:
        if evt.round_num != current_round:
            current_round = evt.round_num
            context_parts.append(f"\n--- 라운드 {current_round} ---")

        label = evt.persona_name
        if evt.persona_id == "__moderator__":
            label = "⚖️ 모더레이터"
        elif evt.persona_id == "__db_agent__":
            label = "🗄️ DB 에이전트"

        content = evt.content
        if len(content) > MAX_CHARS_PER_EVENT:
            content = content[:MAX_CHARS_PER_EVENT] + "..."

        action_label = {
            "post": "발언", "reply": "응답", "question": "질문",
            "concede": "양보", "propose": "제안", "cite": "인용",
            "injection": "개입",
        }.get(evt.action_type, evt.action_type)

        context_parts.append(f"[{label}] ({action_label}): {content}")

    discussion_context = "\n".join(context_parts)

    # 3. LLM 호출
    llm = get_llm_client(
        provider=req.provider,
        api_key=req.api_key,
        model=req.model,
        base_url=req.base_url,
        feature="simulation_qa",
    )

    system_prompt = f"""당신은 시뮬레이션 토론 분석 전문가입니다.
아래에 주어진 토론 기록을 바탕으로 사용자의 질문에 정확하고 구체적으로 답변하세요.

[답변 규칙]
1. 우선 토론 내용에 근거하여 답변하세요. 토론 내 데이터가 1순위입니다.
2. 특정 참여자의 발언을 인용할 때는 이름을 명시하세요.
3. 토론에서 직접 다루지 않은 외부 사실(시장 데이터, 경쟁사 동향, 최신 통계 등)이
   답변에 결정적으로 필요하다고 판단되면, **답변 본문 시작 전에 별도 줄로**
   다음 형식의 검색 요청을 1~3개까지 출력할 수 있습니다.
   형식: [WEB_SEARCH: 구체적인 한국어 또는 영어 검색 쿼리]
   예: [WEB_SEARCH: 인도 라면 시장 규모 2025]
   - 검색 요청을 출력한 라운드에서는 본문 답변을 생략해도 됩니다.
     백엔드가 검색 결과를 받아서 자동으로 다음 라운드 답변을 요청합니다.
   - 토론 내용만으로 충분히 답할 수 있다면 검색 요청을 출력하지 마세요.
4. 토론에서 직접 다루지 않았고 외부 검색도 필요 없는 사소한 내용은
   "토론에서 직접 다루지 않은 내용입니다"라고 밝히세요.
5. 간결하면서도 핵심을 잘 전달하세요.
6. 한국어로 답변하세요.
7. 필요 시 표, 리스트 등 구조화된 형식을 활용하세요.

=== 토론 기록 ===
{discussion_context}
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": req.question},
    ]

    try:
        answer = await llm.complete(messages, temperature=0.3, max_tokens=3000)
    except Exception as e:
        raise HTTPException(500, f"LLM 호출 실패: {str(e)}")

    # 3-2. 1차 답변에 [WEB_SEARCH: 쿼리] 토큰이 있으면 DDG 검색 후 2차 답변
    web_sources: list[dict] = []
    search_queries = _extract_search_queries(answer)
    if search_queries:
        try:
            search_blocks = await _run_web_searches(search_queries[:3])
            if search_blocks:
                web_sources = [
                    {"query": q, "results": [{"title": h["title"], "url": h["url"]} for h in hits]}
                    for q, hits in search_blocks
                ]
                external_context = _format_search_results(search_blocks)
                followup_messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": req.question},
                    {"role": "assistant", "content": answer},
                    {
                        "role": "user",
                        "content": (
                            "[검색 결과 — 백엔드가 자동 수집]\n\n"
                            f"{external_context}\n\n"
                            "위 외부 검색 결과를 토론 내용과 결합해서 최종 답변을 다시 작성하세요. "
                            "이번에는 [WEB_SEARCH: ...] 토큰을 출력하지 마세요. "
                            "외부 정보를 인용한 부분에는 (출처: 검색결과 N번) 형태로 표시하세요."
                        ),
                    },
                ]
                try:
                    answer = await llm.complete(followup_messages, temperature=0.3, max_tokens=3000)
                except Exception as e:
                    # 2차 답변 실패 시 1차 답변에 검색 노트만 덧붙여 그대로 반환
                    answer = answer + f"\n\n[검색 결과 첨부]\n{external_context}"
                    print(f"[QA] followup LLM call failed: {e}", flush=True)
        except Exception as e:
            print(f"[QA] web search failed: {e}", flush=True)

    # 4. 참조된 라운드와 에이전트 추출
    referenced_rounds = []
    referenced_agents = []
    for r in range(1, sim.total_rounds + 1):
        if f"라운드 {r}" in answer or f"Round {r}" in answer or f"R{r}" in answer:
            referenced_rounds.append(r)
    for name in participants.values():
        if name in answer:
            referenced_agents.append(name)

    return {
        "answer": answer,
        "referenced_rounds": referenced_rounds,
        "referenced_agents": referenced_agents,
        "web_sources": web_sources,
    }


@router.get("/{sim_id}/personas")
async def get_personas(sim_id: str, request: Request):
    """Get personas for a simulation. Memory first, then disk fallback."""
    if not is_owner("simulation", sim_id, get_session_id(request)):
        raise HTTPException(404, "Simulation not found")
    # 1. 메모리에서 시도
    factory = _persona_factories.get(sim_id)
    if factory:
        personas = factory.get_personas()
        return {
            "count": len(personas),
            "personas": [
                {"id": p.id, "name": p.name, "role": p.role, "personality": p.personality, "stance": p.stance, "goals": p.goals, "knowledge": p.knowledge}
                for p in personas
            ],
        }

    # 2. 디스크에서 시뮬레이션 JSON 로드 → start 이벤트에서 페르소나 추출
    import json as _json
    sim_file = _SIM_DIR / f"{sim_id}.json"
    if sim_file.exists():
        try:
            data = _json.loads(sim_file.read_text(encoding="utf-8"))
            # 이벤트에서 personas 추출 (start 이벤트에 포함됨)
            personas = []
            for evt in data.get("events", []):
                meta = evt.get("metadata", {})
                if meta.get("personas"):
                    personas = meta["personas"]
                    break
            # config에서도 시도
            if not personas:
                config = data.get("config", {})
                persona_ids = config.get("personas", [])
                # persona_id만 있으면 이름으로 변환
                for evt in data.get("events", []):
                    name = evt.get("persona_name", "")
                    pid = evt.get("persona_id", "")
                    if name and pid and pid not in ("__moderator__", "__db_agent__"):
                        if not any(p.get("id") == pid or p.get("name") == name for p in personas):
                            personas.append({"id": pid, "name": name, "role": "", "personality": "", "stance": ""})
            return {"count": len(personas), "personas": personas}
        except Exception as e:
            import traceback; traceback.print_exc()
            return {"count": 0, "personas": [], "error": str(e)}

    raise HTTPException(404, "Simulation not found")
