"""Stateful social simulation engine with richer agent behavior.

This file is an alternative to `simulation_runner.py`. It keeps the same broad
contract but adds:
- agent memory and evolving salience
- activity propensity by round
- explicit target selection over recent threads
- reply/repost weighting
- stance drift from repeated exposure
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from llm.base import BaseLLMClient
from models.persona import PersonaProfile
from models.simulation import SimConfig, SimEvent, SimResult, SimStatus
from utils.logger import log


AGENT_DECISION_PROMPT = """You are {name}, participating in a social platform simulation.

Identity:
- role: {role}
- personality: {personality}
- stance: {stance}
- goals: {goals}
- knowledge: {knowledge}

Internal state:
- energy: {energy}
- conviction: {conviction}
- controversy_tolerance: {controversy_tolerance}
- social_pressure: {social_pressure}

Relationship context:
{relationships}

Top memory from previous rounds:
{memory}

Recent platform activity:
{recent_feed}

Task:
Choose exactly one action for this round from:
- post
- reply
- repost
- skip

Guidelines:
- high social pressure makes replies/reposts more likely
- high conviction increases original posting
- low energy increases skip
- if replying or reposting, target a valid post_number from the feed
- keep content plausible and consistent with the persona

Return JSON only:
{{
  "action": "post|reply|repost|skip",
  "target_post": null,
  "content": "text",
  "salience": 0.0,
  "emotion": "calm|tense|confident|uncertain|curious",
  "reasoning": "short hidden rationale"
}}
"""


@dataclass
class AgentState:
    persona: PersonaProfile
    energy: float = 0.8
    conviction: float = 0.7
    controversy_tolerance: float = 0.5
    social_pressure: float = 0.2
    memory: list[str] = field(default_factory=list)
    influence_score: float = 0.0
    received_replies: int = 0
    received_reposts: int = 0


class SimulationEngineGPT:
    """Richer simulation loop intended as a bridge toward OASIS-like behavior."""

    def __init__(self, llm_client: BaseLLMClient):
        self.llm = llm_client
        self._simulations: dict[str, SimResult] = {}
        self._stop_flags: dict[str, bool] = {}

    async def run_simulation(self, config: SimConfig, personas: list[PersonaProfile]):
        sim_id = config.id
        result = SimResult(
            id=sim_id,
            config=config,
            status=SimStatus.RUNNING,
            total_rounds=config.num_rounds,
        )
        self._simulations[sim_id] = result
        self._stop_flags[sim_id] = False

        states = self._initialize_states(personas)
        post_history: list[dict] = []
        log.info("simulation_gpt_start", sim_id=sim_id, personas=len(personas), rounds=config.num_rounds)

        try:
            for round_num in range(1, config.num_rounds + 1):
                if self._stop_flags.get(sim_id):
                    result.status = SimStatus.PAUSED
                    break

                result.current_round = round_num
                self._apply_round_dynamics(states, round_num)
                self._inject_system_events(config, round_num, result, post_history)

                acting_order = self._select_acting_order(states)
                for state in acting_order:
                    if self._stop_flags.get(sim_id):
                        result.status = SimStatus.PAUSED
                        break

                    event = await self._agent_act(state, config.topic, round_num, post_history)
                    if not event or event.action_type == "skip":
                        continue

                    result.events.append(event)
                    post_num = len(post_history) + 1
                    post_record = {
                        "post_num": post_num,
                        "event_id": f"{round_num}:{state.persona.id[:8]}:{post_num}",
                        "author_id": state.persona.id,
                        "author": state.persona.name,
                        "content": event.content,
                        "type": event.action_type,
                        "target": event.target_id,
                        "round_num": round_num,
                        "metadata": event.metadata,
                    }
                    post_history.append(post_record)
                    self._update_state_after_action(states, state, event, post_record, post_history)
                    yield event

            if result.status != SimStatus.PAUSED:
                result.status = SimStatus.COMPLETED
            log.info("simulation_gpt_complete", sim_id=sim_id, events=len(result.events))
        except Exception as exc:
            result.status = SimStatus.ERROR
            log.error("simulation_gpt_error", sim_id=sim_id, error=str(exc))
            raise

    def stop_simulation(self, sim_id: str):
        self._stop_flags[sim_id] = True

    def get_simulation(self, sim_id: str) -> Optional[SimResult]:
        return self._simulations.get(sim_id)

    def get_all_simulations(self) -> list[SimResult]:
        return list(self._simulations.values())

    def _initialize_states(self, personas: list[PersonaProfile]) -> dict[str, AgentState]:
        states: dict[str, AgentState] = {}
        for persona in personas:
            states[persona.id] = AgentState(
                persona=persona,
                energy=random.uniform(0.65, 0.95),
                conviction=random.uniform(0.45, 0.9),
                controversy_tolerance=random.uniform(0.2, 0.9),
                social_pressure=random.uniform(0.05, 0.3),
            )
        return states

    def _apply_round_dynamics(self, states: dict[str, AgentState], round_num: int):
        for state in states.values():
            # Mild recovery plus social escalation over time.
            state.energy = min(1.0, state.energy + 0.08)
            state.social_pressure = min(1.0, state.social_pressure + 0.02)
            if round_num % 3 == 0:
                state.conviction = min(1.0, state.conviction + 0.03)

    def _inject_system_events(self, config: SimConfig, round_num: int, result: SimResult, post_history: list[dict]):
        for injection in config.injection_events:
            if injection.get("round") != round_num:
                continue
            event = SimEvent(
                round_num=round_num,
                timestamp=datetime.now().isoformat(),
                persona_id="__system__",
                persona_name="[System Event]",
                action_type="injection",
                content=injection.get("content", ""),
                metadata={"injection": True},
            )
            result.events.append(event)
            post_history.append(
                {
                    "post_num": len(post_history) + 1,
                    "event_id": f"system:{round_num}:{len(post_history) + 1}",
                    "author_id": "__system__",
                    "author": "[Breaking News]",
                    "content": event.content,
                    "type": "injection",
                    "target": None,
                    "round_num": round_num,
                    "metadata": event.metadata,
                }
            )

    def _select_acting_order(self, states: dict[str, AgentState]) -> list[AgentState]:
        weighted: list[tuple[float, AgentState]] = []
        for state in states.values():
            score = (
                state.energy * 0.45
                + state.conviction * 0.25
                + state.social_pressure * 0.2
                + min(state.influence_score, 1.0) * 0.1
            )
            weighted.append((score + random.random() * 0.15, state))
        weighted.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in weighted]

    async def _agent_act(
        self,
        state: AgentState,
        topic: str,
        round_num: int,
        post_history: list[dict],
    ) -> Optional[SimEvent]:
        recent_feed = self._format_recent_feed(post_history, state.persona.id)
        memory = "\n".join(state.memory[-5:]) if state.memory else "(none)"
        relationships = self._format_relationships(state.persona.relationships)

        prompt = AGENT_DECISION_PROMPT.format(
            name=state.persona.name,
            role=state.persona.role,
            personality=state.persona.personality or "measured",
            stance=state.persona.stance or "undeclared",
            goals=", ".join(getattr(state.persona, "goals", [])) or "participate productively",
            knowledge=", ".join(state.persona.knowledge) or "topic background",
            energy=f"{state.energy:.2f}",
            conviction=f"{state.conviction:.2f}",
            controversy_tolerance=f"{state.controversy_tolerance:.2f}",
            social_pressure=f"{state.social_pressure:.2f}",
            relationships=relationships,
            memory=memory,
            recent_feed=recent_feed,
        )

        response = await self.llm.complete(
            [
                {
                    "role": "system",
                    "content": f"You are simulating {state.persona.name}. Return valid JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
            max_tokens=700,
        )

        try:
            data = self._parse_json(response)
        except Exception as exc:
            log.warning("simulation_gpt_parse_failed", persona=state.persona.name, error=str(exc))
            return None

        action = data.get("action", "skip")
        if action == "skip":
            state.energy = max(0.15, state.energy - 0.05)
            return SimEvent(
                round_num=round_num,
                timestamp=datetime.now().isoformat(),
                persona_id=state.persona.id,
                persona_name=state.persona.name,
                action_type="skip",
            )

        target_post = self._resolve_target(data.get("target_post"), post_history)
        metadata = {
            "reasoning": data.get("reasoning", ""),
            "emotion": data.get("emotion", "calm"),
            "salience": float(data.get("salience", 0.5)),
        }

        return SimEvent(
            round_num=round_num,
            timestamp=datetime.now().isoformat(),
            persona_id=state.persona.id,
            persona_name=state.persona.name,
            action_type=action,
            content=data.get("content", ""),
            target_id=str(target_post["post_num"]) if target_post else None,
            metadata=metadata,
        )

    def _update_state_after_action(
        self,
        states: dict[str, AgentState],
        actor: AgentState,
        event: SimEvent,
        post_record: dict,
        post_history: list[dict],
    ):
        actor.energy = max(0.1, actor.energy - 0.18)
        actor.influence_score += 0.05
        actor.memory.append(f"Round {event.round_num}: chose {event.action_type} ({event.content[:120]})")

        if not event.target_id:
            return

        target = next((item for item in post_history if str(item["post_num"]) == str(event.target_id)), None)
        if not target:
            return

        target_state = states.get(target.get("author_id"))
        if target_state:
            target_state.social_pressure = min(1.0, target_state.social_pressure + 0.12)
            if event.action_type == "reply":
                target_state.received_replies += 1
            elif event.action_type == "repost":
                target_state.received_reposts += 1

        # Repeated engagement slightly hardens stance and memory salience.
        actor.conviction = min(1.0, actor.conviction + 0.04)
        actor.memory.append(f"Engaged with @{target.get('author')}: {target.get('content', '')[:100]}")

    def _format_recent_feed(self, post_history: list[dict], persona_id: str) -> str:
        visible = post_history[-12:]
        if not visible:
            return "(No recent posts)"

        lines = []
        for post in visible:
            marker = "self" if post.get("author_id") == persona_id else "feed"
            lines.append(
                f"[#{post['post_num']}] ({marker}) @{post['author']} [{post['type']}]: {post['content']}"
            )
        return "\n".join(lines)

    def _format_relationships(self, relationships: dict[str, str]) -> str:
        if not relationships:
            return "(none)"
        return "\n".join(f"- {value}" for value in list(relationships.values())[:8])

    def _resolve_target(self, target_post: object, post_history: list[dict]) -> Optional[dict]:
        if target_post is None:
            return None
        for post in reversed(post_history):
            if str(post["post_num"]) == str(target_post):
                return post
        return None

    def _parse_json(self, text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return json.loads(text)
