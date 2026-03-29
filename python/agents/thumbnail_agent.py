"""
TubeBot AI - Thumbnail Agent
Generates video thumbnails using DALL-E 3, then adds bold text overlay with Pillow.
"""
import asyncio
import logging
from datetime import datetime
from pathlib import Path

import aiohttp
import openai
from PIL import Image, ImageDraw, ImageFont
import io

from config.settings import config
from database.models import VideoProject, ProjectStatus, AgentLog

logger = logging.getLogger(__name__)


class ThumbnailAgent:
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
        logger.info("ThumbnailAgent started")
        while self.running:
            try:
                await self._process_next()
                await asyncio.sleep(1800)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"ThumbnailAgent error: {e}")
                await asyncio.sleep(600)

    def stop(self):
        self.running = False

    async def _process_next(self):
        if not config.openai.is_configured:
            return

        # Process any scripted project that doesn't have a thumbnail yet
        project = (
            self.session.query(VideoProject)
            .filter(
                VideoProject.status.in_([ProjectStatus.SCRIPTED, ProjectStatus.VOICED]),
                VideoProject.thumbnail_path.is_(None),
            )
            .order_by(VideoProject.trend_score.desc())
            .first()
        )
        if not project:
            return

        logger.info(f"ThumbnailAgent: generating thumbnail for project {project.id}")
        try:
            thumb_path = await self._generate_thumbnail(project)
            project.thumbnail_path = str(thumb_path)
            self.session.commit()
            self._log(f"Thumbnail created for project {project.id}", project.id)
            logger.info(f"ThumbnailAgent: saved → {thumb_path}")
        except Exception as e:
            logger.error(f"ThumbnailAgent failed for project {project.id}: {e}")

    async def _generate_thumbnail(self, project: VideoProject) -> Path:
        thumb_dir = Path(config.video.thumbnail_dir)
        thumb_dir.mkdir(parents=True, exist_ok=True)
        out_path = thumb_dir / f"thumb_{project.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.png"

        # Build DALL-E prompt
        prompt = (
            f"YouTube thumbnail image for a senior health video about: {project.topic}. "
            "Photorealistic, bright and welcoming. A smiling senior (65+) with warm lighting. "
            "Clean background. No text in the image. High quality, professional."
        )

        response = await self._get_client().images.generate(
            model=config.openai.image_model,
            prompt=prompt,
            size="1792x1024",
            quality="standard",
            n=1,
        )
        image_url = response.data[0].url

        # Download the image
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as resp:
                image_bytes = await resp.read()

        # Add bold topic text overlay with Pillow
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        img = self._add_text_overlay(img, project.topic)
        img.convert("RGB").save(str(out_path), "PNG")
        return out_path

    def _add_text_overlay(self, img: Image.Image, topic: str) -> Image.Image:
        draw = ImageDraw.Draw(img)
        w, h = img.size

        # Wrap topic to ~35 chars per line
        words = topic.split()
        lines, line = [], ""
        for word in words:
            if len(line) + len(word) + 1 <= 35:
                line = f"{line} {word}".strip()
            else:
                if line:
                    lines.append(line)
                line = word
        if line:
            lines.append(line)

        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
        except Exception:
            font = ImageFont.load_default()

        # Draw semi-transparent banner at bottom
        text_block_h = len(lines) * 90 + 40
        overlay = Image.new("RGBA", (w, text_block_h), (0, 0, 0, 160))
        img.paste(overlay, (0, h - text_block_h), overlay)

        y = h - text_block_h + 20
        for line in lines:
            # Shadow
            draw.text((22, y + 2), line, fill=(0, 0, 0, 200), font=font)
            # Text
            draw.text((20, y), line, fill=(255, 255, 255, 255), font=font)
            y += 90

        return img

    def _log(self, message: str, project_id: int = None, status: str = "success"):
        log = AgentLog(agent_name="ThumbnailAgent", action="generate_thumbnail",
                       status=status, message=message, project_id=project_id)
        self.session.add(log)
        self.session.commit()
