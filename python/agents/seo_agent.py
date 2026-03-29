"""
TubeBot AI - SEO Agent
Writes optimised YouTube titles, descriptions, and tags using GPT-4.
"""
import asyncio
import json
import logging

import openai

from config.settings import config
from database.models import VideoProject, ProjectStatus, AgentLog

logger = logging.getLogger(__name__)

SEO_PROMPT = """You are a YouTube SEO expert for the senior health niche.
Given a video script, return a JSON object with:
- "title": string, max 100 chars, compelling and keyword-rich
- "description": string, 400-500 words, includes keywords, timestamps placeholder, and CTA
- "tags": list of 15-20 strings, mix of broad and specific keywords

Rules:
- Title must include a number or power word (e.g. "7 Things", "Complete Guide", "Warning")
- Description starts with the most important keyword in the first sentence
- Tags include variations: singular/plural, short-tail and long-tail

Return ONLY valid JSON, no markdown, no explanation."""


class SEOAgent:
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
        logger.info("SEOAgent started")
        while self.running:
            try:
                await self._process_next()
                await asyncio.sleep(1800)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"SEOAgent error: {e}")
                await asyncio.sleep(600)

    def stop(self):
        self.running = False

    async def _process_next(self):
        if not config.openai.is_configured:
            return

        # Process voiced projects that have no SEO yet
        project = (
            self.session.query(VideoProject)
            .filter(
                VideoProject.status == ProjectStatus.VOICED,
                VideoProject.yt_title.is_(None),
            )
            .order_by(VideoProject.trend_score.desc())
            .first()
        )
        if not project or not project.script:
            return

        logger.info(f"SEOAgent: writing SEO for project {project.id}")
        try:
            seo = await self._generate_seo(project.topic, project.script)
            project.yt_title       = seo["title"]
            project.yt_description = seo["description"]
            project.yt_tags        = seo["tags"]
            project.status         = ProjectStatus.SEOD
            self.session.commit()
            self._log(f"SEO written for project {project.id}: {seo['title']}", project.id)
            logger.info(f"SEOAgent: title → {seo['title']}")
        except Exception as e:
            logger.error(f"SEOAgent failed for project {project.id}: {e}")

    async def _generate_seo(self, topic: str, script: str) -> dict:
        # Use first 2000 chars of script for context
        script_excerpt = script[:2000]
        response = await self._get_client().chat.completions.create(
            model=config.openai.model,
            messages=[
                {"role": "system", "content": SEO_PROMPT},
                {"role": "user",   "content": f"Topic: {topic}\n\nScript excerpt:\n{script_excerpt}"},
            ],
            temperature=0.5,
            max_tokens=1000,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)

    def _log(self, message: str, project_id: int = None, status: str = "success"):
        log = AgentLog(agent_name="SEOAgent", action="write_seo",
                       status=status, message=message, project_id=project_id)
        self.session.add(log)
        self.session.commit()
