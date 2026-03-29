"""
TubeBot AI - Voice Agent
Converts scripts to audio using edge-tts (free Microsoft TTS).
"""
import asyncio
import logging
from datetime import datetime
from pathlib import Path

from config.settings import config
from database.models import VideoProject, ProjectStatus, AgentLog

logger = logging.getLogger(__name__)


class VoiceAgent:
    def __init__(self, db_session):
        self.session = db_session
        self.running = False

    async def run(self):
        self.running = True
        logger.info("VoiceAgent started")
        while self.running:
            try:
                await self._process_next()
                await asyncio.sleep(1800)  # 30 min
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"VoiceAgent error: {e}")
                await asyncio.sleep(600)

    def stop(self):
        self.running = False

    async def _process_next(self):
        project = (
            self.session.query(VideoProject)
            .filter(VideoProject.status == ProjectStatus.SCRIPTED)
            .order_by(VideoProject.trend_score.desc())
            .first()
        )
        if not project or not project.script:
            return

        logger.info(f"VoiceAgent: generating audio for project {project.id}")
        try:
            audio_path = await self._synthesise(project.id, project.script)
            project.audio_path = str(audio_path)
            project.status = ProjectStatus.VOICED
            self.session.commit()
            self._log(f"Audio generated for project {project.id}", project.id)
            logger.info(f"VoiceAgent: audio saved → {audio_path}")
        except Exception as e:
            project.error_message = str(e)
            project.status = ProjectStatus.FAILED
            self.session.commit()
            logger.error(f"VoiceAgent failed for project {project.id}: {e}")

    async def _synthesise(self, project_id: int, script: str) -> Path:
        import edge_tts
        audio_dir = Path(config.video.audio_dir)
        audio_dir.mkdir(parents=True, exist_ok=True)
        out_path = audio_dir / f"audio_{project_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.mp3"

        communicate = edge_tts.Communicate(
            text=script,
            voice=config.video.tts_voice,
            rate="+0%",
            volume="+0%",
        )
        await communicate.save(str(out_path))
        return out_path

    def _log(self, message: str, project_id: int = None, status: str = "success"):
        log = AgentLog(agent_name="VoiceAgent", action="synthesise_audio",
                       status=status, message=message, project_id=project_id)
        self.session.add(log)
        self.session.commit()
