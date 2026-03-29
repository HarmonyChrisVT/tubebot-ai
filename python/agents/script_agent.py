"""
TubeBot AI - Script Agent
Picks up trending topics and writes 8-10 minute YouTube scripts using GPT-4.
"""
import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

import openai

from config.settings import config
from database.models import VideoProject, ProjectStatus, AgentLog, get_session

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert YouTube scriptwriter specialising in senior health,
Medicare, and retirement topics. Your scripts are:
- Warm, clear, and easy to follow for viewers aged 60+
- Structured with a hook, main content sections, and a call-to-action
- Factually accurate and never alarmist
- Between {min_words} and {max_words} words (8-10 minutes at ~130 wpm)
- Formatted as plain narration (no stage directions, no [MUSIC], no visual cues)
Output ONLY the script text, nothing else."""

USER_PROMPT = """Write an 8-10 minute YouTube video script on this topic:

"{topic}"

Structure:
1. Hook (30 seconds) — surprising fact or relatable problem
2. Introduction — who this video is for and what they'll learn
3. Main content (3-5 clearly labelled sections)
4. Summary — recap key points
5. Call to action — subscribe, comment with their question

Word count target: {min_words}–{max_words} words."""


class ScriptAgent:
    def __init__(self, db_session):
        self.session = db_session
        self.running = False
        self._client: openai.AsyncOpenAI | None = None

    def _get_client(self):
        if self._client is None:
            self._client = openai.AsyncOpenAI(api_key=config.openai.api_key)
        return self._client

    async def run(self):
        self.running = True
        logger.info("ScriptAgent started")
        while self.running:
            try:
                await self._process_next()
                await asyncio.sleep(1800)  # 30 min
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"ScriptAgent error: {e}")
                await asyncio.sleep(600)

    def stop(self):
        self.running = False

    async def _process_next(self):
        if not config.openai.is_configured:
            return

        project = (
            self.session.query(VideoProject)
            .filter(VideoProject.status == ProjectStatus.TRENDING)
            .order_by(VideoProject.trend_score.desc())
            .first()
        )
        if not project:
            return

        logger.info(f"ScriptAgent: writing script for '{project.topic}'")
        try:
            script = await self._generate_script(project.topic)
            script_dir = Path(config.video.script_dir)
            script_dir.mkdir(parents=True, exist_ok=True)
            script_path = script_dir / f"script_{project.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.txt"
            script_path.write_text(script, encoding="utf-8")

            project.script = script
            project.script_path = str(script_path)
            project.status = ProjectStatus.SCRIPTED
            self.session.commit()
            self._log(f"Script written for project {project.id}", project.id)
            logger.info(f"ScriptAgent: script saved → {script_path}")
        except Exception as e:
            project.error_message = str(e)
            project.status = ProjectStatus.FAILED
            self.session.commit()
            logger.error(f"ScriptAgent failed for project {project.id}: {e}")

    async def _generate_script(self, topic: str) -> str:
        min_w = config.video.script_min_words
        max_w = config.video.script_max_words
        response = await self._get_client().chat.completions.create(
            model=config.openai.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT.format(min_words=min_w, max_words=max_w)},
                {"role": "user",   "content": USER_PROMPT.format(topic=topic, min_words=min_w, max_words=max_w)},
            ],
            temperature=0.7,
            max_tokens=2500,
        )
        return response.choices[0].message.content.strip()

    def _log(self, message: str, project_id: int = None, status: str = "success"):
        log = AgentLog(agent_name="ScriptAgent", action="write_script",
                       status=status, message=message, project_id=project_id)
        self.session.add(log)
        self.session.commit()
