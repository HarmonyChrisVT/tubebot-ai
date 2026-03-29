"""
TubeBot AI - Upload Agent
Uploads completed videos to YouTube and schedules publication.
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from config.settings import config
from database.models import VideoProject, ProjectStatus, AgentLog

logger = logging.getLogger(__name__)


class UploadAgent:
    def __init__(self, db_session):
        self.session = db_session
        self.running = False

    async def run(self):
        self.running = True
        logger.info("UploadAgent started")
        while self.running:
            try:
                await self._process_next()
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"UploadAgent error: {e}")
                await asyncio.sleep(1800)

    def stop(self):
        self.running = False

    async def _process_next(self):
        if not config.youtube.is_configured:
            return

        project = (
            self.session.query(VideoProject)
            .filter(
                VideoProject.status == ProjectStatus.RENDERED,
                VideoProject.yt_title.isnot(None),
            )
            .order_by(VideoProject.trend_score.desc())
            .first()
        )
        if not project:
            return

        logger.info(f"UploadAgent: uploading project {project.id} — {project.yt_title}")
        try:
            # Run blocking upload in thread pool to avoid blocking event loop
            video_id, yt_url = await asyncio.get_event_loop().run_in_executor(
                None, self._upload_to_youtube, project
            )
            scheduled = datetime.utcnow() + timedelta(hours=config.youtube.schedule_hours_ahead)
            project.yt_video_id  = video_id
            project.yt_url       = yt_url
            project.scheduled_at = scheduled
            project.status       = ProjectStatus.UPLOADED
            self.session.commit()
            self._log(f"Uploaded: {yt_url}", project.id)
            logger.info(f"UploadAgent: uploaded → {yt_url}")
        except Exception as e:
            logger.error(f"UploadAgent failed for project {project.id}: {e}")
            project.error_message = str(e)
            self.session.commit()

    def _upload_to_youtube(self, project: VideoProject):
        """Blocking YouTube upload using google-api-python-client."""
        import google.oauth2.credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        creds_data = json.loads(config.youtube.credentials_json)
        credentials = google.oauth2.credentials.Credentials(
            token=creds_data.get("token"),
            refresh_token=creds_data.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=creds_data.get("client_id"),
            client_secret=creds_data.get("client_secret"),
        )
        youtube = build("youtube", "v3", credentials=credentials)

        scheduled_at = datetime.utcnow() + timedelta(hours=config.youtube.schedule_hours_ahead)
        publish_at = scheduled_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        body = {
            "snippet": {
                "title":       project.yt_title,
                "description": project.yt_description or "",
                "tags":        project.yt_tags or [],
                "categoryId":  "26",  # How-to & Style
            },
            "status": {
                "privacyStatus":      "private",
                "publishAt":          publish_at,
                "selfDeclaredMadeForKids": False,
            },
        }

        video_path = project.video_path
        # If it's a manifest (Pictory not configured), skip actual upload
        if video_path.endswith(".json"):
            logger.warning("UploadAgent: video is a manifest — skipping upload")
            return "PLACEHOLDER_ID", "https://youtube.com/watch?v=PLACEHOLDER"

        media = MediaFileUpload(video_path, chunksize=-1, resumable=True,
                                mimetype="video/mp4")
        request = youtube.videos().insert(part="snippet,status", body=body,
                                          media_body=media)
        response = None
        while response is None:
            _, response = request.next_chunk()

        video_id = response["id"]
        yt_url = f"https://www.youtube.com/watch?v={video_id}"

        # Upload thumbnail if available
        if project.thumbnail_path and Path(project.thumbnail_path).exists():
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(project.thumbnail_path)
            ).execute()

        return video_id, yt_url

    def _log(self, message: str, project_id: int = None, status: str = "success"):
        log = AgentLog(agent_name="UploadAgent", action="upload_video",
                       status=status, message=message, project_id=project_id)
        self.session.add(log)
        self.session.commit()
