"""TubeBot AI - Main Orchestrator + FastAPI"""
import asyncio
import logging
import signal
import sys
from datetime import datetime
from typing import Dict, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import config, load_config_from_env
from database.models import (
    init_database, get_session, VideoProject, ProjectStatus, AgentLog
)
from agents.trend_agent import TrendAgent
from agents.script_agent import ScriptAgent
from agents.voice_agent import VoiceAgent
from agents.video_agent import VideoAgent
from agents.thumbnail_agent import ThumbnailAgent
from agents.seo_agent import SEOAgent
from agents.upload_agent import UploadAgent
from agents.analytics_agent import AnalyticsAgent

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


class TubeBotOrchestrator:
    def __init__(self):
        load_config_from_env()
        self.engine  = init_database(config.database_path)
        self.session = get_session(self.engine)

        self.trend_agent      = TrendAgent(self.session)
        self.script_agent     = ScriptAgent(self.session)
        self.voice_agent      = VoiceAgent(self.session)
        self.video_agent      = VideoAgent(self.session)
        self.thumbnail_agent  = ThumbnailAgent(self.session)
        self.seo_agent        = SEOAgent(self.session)
        self.upload_agent     = UploadAgent(self.session)
        self.analytics_agent  = AnalyticsAgent(self.session)

        self.running      = False
        self.agent_tasks: List[asyncio.Task] = []

        signal.signal(signal.SIGINT,  self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, *_):
        logger.info("Shutdown signal received")
        self.stop()
        sys.exit(0)

    async def start(self):
        self.running = True
        logger.info("TubeBot AI starting all agents…")

        self.agent_tasks = [
            asyncio.create_task(self.trend_agent.run(),     name="trend"),
            asyncio.create_task(self.script_agent.run(),    name="script"),
            asyncio.create_task(self.voice_agent.run(),     name="voice"),
            asyncio.create_task(self.video_agent.run(),     name="video"),
            asyncio.create_task(self.thumbnail_agent.run(), name="thumbnail"),
            asyncio.create_task(self.seo_agent.run(),       name="seo"),
            asyncio.create_task(self.upload_agent.run(),    name="upload"),
            asyncio.create_task(self.analytics_agent.run(), name="analytics"),
        ]

        logger.info("All 8 agents running.")
        try:
            await asyncio.gather(*self.agent_tasks)
        except asyncio.CancelledError:
            pass

    def stop(self):
        self.running = False
        for agent in [self.trend_agent, self.script_agent, self.voice_agent,
                      self.video_agent, self.thumbnail_agent, self.seo_agent,
                      self.upload_agent, self.analytics_agent]:
            agent.stop()
        for task in self.agent_tasks:
            task.cancel()

    def get_status(self) -> Dict:
        return {
            "running": self.running,
            "agents": {
                "trend":      {"running": self.trend_agent.running,
                               "last_run": self.trend_agent.last_run.isoformat()
                                           if self.trend_agent.last_run else None},
                "script":     {"running": self.script_agent.running},
                "voice":      {"running": self.voice_agent.running},
                "video":      {"running": self.video_agent.running},
                "thumbnail":  {"running": self.thumbnail_agent.running},
                "seo":        {"running": self.seo_agent.running},
                "upload":     {"running": self.upload_agent.running},
                "analytics":  {"running": self.analytics_agent.running},
            },
        }

    def get_pipeline_stats(self) -> Dict:
        counts = {}
        for status in ProjectStatus:
            counts[status.value] = (
                self.session.query(VideoProject)
                .filter(VideoProject.status == status)
                .count()
            )
        return counts

    def get_recent_projects(self, limit: int = 20) -> List[Dict]:
        projects = (
            self.session.query(VideoProject)
            .order_by(VideoProject.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id":            p.id,
                "topic":         p.topic,
                "status":        p.status,
                "trend_score":   p.trend_score,
                "yt_title":      p.yt_title,
                "yt_video_id":   p.yt_video_id,
                "yt_url":        p.yt_url,
                "views":         p.views,
                "ctr":           p.ctr,
                "created_at":    p.created_at.isoformat() if p.created_at else None,
                "published_at":  p.published_at.isoformat() if p.published_at else None,
            }
            for p in projects
        ]

    def get_recent_logs(self, limit: int = 50) -> List[Dict]:
        logs = (
            self.session.query(AgentLog)
            .order_by(AgentLog.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "agent":      l.agent_name,
                "action":     l.action,
                "status":     l.status,
                "message":    l.message,
                "project_id": l.project_id,
                "time":       l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ]


# ── FastAPI ────────────────────────────────────────────────────────────────
app = FastAPI(title="TubeBot AI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator: TubeBotOrchestrator | None = None


@app.on_event("startup")
async def startup():
    global orchestrator
    orchestrator = TubeBotOrchestrator()
    asyncio.create_task(orchestrator.start())


@app.get("/api/status")
async def get_status():
    if orchestrator:
        return orchestrator.get_status()
    return {"error": "not initialized"}


@app.get("/api/pipeline")
async def get_pipeline():
    if orchestrator:
        return orchestrator.get_pipeline_stats()
    return {}


@app.get("/api/projects")
async def get_projects(limit: int = 20):
    if orchestrator:
        return orchestrator.get_recent_projects(limit)
    return []


@app.get("/api/logs")
async def get_logs(limit: int = 50):
    if orchestrator:
        return orchestrator.get_recent_logs(limit)
    return []


@app.get("/api/health")
async def health():
    import aiohttp, time
    results: Dict = {}

    # OpenAI
    if not config.openai.is_configured:
        results["openai"] = {"ok": False, "error": "not configured"}
    else:
        t = time.monotonic()
        try:
            import openai as _openai
            client = _openai.AsyncOpenAI(api_key=config.openai.api_key)
            models = await client.models.list()
            results["openai"] = {"ok": True, "models": len(models.data),
                                 "latency_ms": round((time.monotonic()-t)*1000)}
        except Exception as e:
            results["openai"] = {"ok": False, "error": str(e)}

    # YouTube
    results["youtube"] = {
        "ok": config.youtube.is_configured,
        "error": None if config.youtube.is_configured else "not configured",
    }

    # Pictory
    results["pictory"] = {
        "ok": config.pictory.is_configured,
        "note": "Pictory configured" if config.pictory.is_configured else "not configured — video manifests will be created instead",
    }

    return {"healthy": all(v["ok"] for v in results.values()), "services": results}


def main():
    orchestrator = TubeBotOrchestrator()
    try:
        asyncio.run(orchestrator.start())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
