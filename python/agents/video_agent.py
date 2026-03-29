"""
TubeBot AI - Video Agent
Assembles the final video using the Pictory API.
Falls back to a simple placeholder video when Pictory is not configured.
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path

import aiohttp

from config.settings import config
from database.models import VideoProject, ProjectStatus, AgentLog

logger = logging.getLogger(__name__)


class VideoAgent:
    def __init__(self, db_session):
        self.session = db_session
        self.running = False

    async def run(self):
        self.running = True
        logger.info("VideoAgent started")
        while self.running:
            try:
                await self._process_next()
                await asyncio.sleep(3600)  # 1 hour
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"VideoAgent error: {e}")
                await asyncio.sleep(1800)

    def stop(self):
        self.running = False

    async def _process_next(self):
        # Need audio + SEO before assembling
        project = (
            self.session.query(VideoProject)
            .filter(
                VideoProject.status == ProjectStatus.SEOD,
                VideoProject.audio_path.isnot(None),
                VideoProject.thumbnail_path.isnot(None),
            )
            .order_by(VideoProject.trend_score.desc())
            .first()
        )
        if not project:
            return

        logger.info(f"VideoAgent: assembling video for project {project.id}")
        try:
            if config.pictory.is_configured:
                video_path = await self._assemble_with_pictory(project)
            else:
                video_path = await self._create_placeholder(project)

            project.video_path = str(video_path)
            project.status = ProjectStatus.RENDERED
            self.session.commit()
            self._log(f"Video rendered for project {project.id}", project.id)
            logger.info(f"VideoAgent: video saved → {video_path}")
        except Exception as e:
            logger.error(f"VideoAgent failed for project {project.id}: {e}")
            project.error_message = str(e)
            self.session.commit()

    async def _assemble_with_pictory(self, project: VideoProject) -> Path:
        """Submit job to Pictory API and poll for completion."""
        video_dir = Path(config.video.video_dir)
        video_dir.mkdir(parents=True, exist_ok=True)

        headers = {
            "X-Pictory-User-Id": "tubebot",
            "Authorization": f"Bearer {config.pictory.api_key}",
            "Content-Type": "application/json",
        }

        # Step 1: create story from script
        story_payload = {
            "videoName": project.yt_title or project.topic,
            "videoDescription": project.yt_description or "",
            "language": "en",
            "videoWidth": "1920",
            "videoHeight": "1080",
            "scenes": self._script_to_scenes(project.script),
            "voiceOver": {
                "enabled": False,  # we supply our own audio
            },
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(
                f"{config.pictory.api_base}/video/storyboard",
                json=story_payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                result = await resp.json()
                job_id = result.get("jobId") or result.get("data", {}).get("jobId")

            if not job_id:
                raise ValueError(f"Pictory did not return a job ID: {result}")

            # Step 2: poll until done
            out_path = video_dir / f"video_{project.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.mp4"
            for _ in range(60):  # max 30 min
                await asyncio.sleep(30)
                async with session.get(
                    f"{config.pictory.api_base}/jobs/{job_id}",
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as poll:
                    poll_data = await poll.json()
                    status = poll_data.get("data", {}).get("status", "")
                    if status == "completed":
                        video_url = poll_data["data"]["videoURL"]
                        async with session.get(video_url) as dl:
                            out_path.write_bytes(await dl.read())
                        return out_path
                    elif status == "failed":
                        raise ValueError(f"Pictory job failed: {poll_data}")

            raise TimeoutError("Pictory video generation timed out after 30 minutes")

    def _script_to_scenes(self, script: str) -> list:
        """Split script into 30-word scenes for Pictory."""
        words = script.split()
        scenes = []
        for i in range(0, len(words), 30):
            chunk = " ".join(words[i:i+30])
            scenes.append({"text": chunk})
        return scenes

    async def _create_placeholder(self, project: VideoProject) -> Path:
        """Write a manifest file when Pictory is not configured."""
        video_dir = Path(config.video.video_dir)
        video_dir.mkdir(parents=True, exist_ok=True)
        out_path = video_dir / f"video_{project.id}_manifest.json"
        manifest = {
            "project_id": project.id,
            "topic": project.topic,
            "audio_path": project.audio_path,
            "thumbnail_path": project.thumbnail_path,
            "note": "Pictory API not configured — configure PICTORY_API_KEY to render video",
        }
        out_path.write_text(json.dumps(manifest, indent=2))
        logger.warning(f"VideoAgent: Pictory not configured — wrote manifest to {out_path}")
        return out_path

    def _log(self, message: str, project_id: int = None, status: str = "success"):
        log = AgentLog(agent_name="VideoAgent", action="assemble_video",
                       status=status, message=message, project_id=project_id)
        self.session.add(log)
        self.session.commit()
