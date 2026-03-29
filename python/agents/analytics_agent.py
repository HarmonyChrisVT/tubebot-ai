"""
TubeBot AI - Analytics Agent
Polls YouTube Analytics API for video performance and feeds insights
back by boosting trend scores of high-performing topics.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta

from config.settings import config
from database.models import VideoProject, ProjectStatus, AgentLog

logger = logging.getLogger(__name__)


class AnalyticsAgent:
    def __init__(self, db_session):
        self.session = db_session
        self.running = False

    async def run(self):
        self.running = True
        logger.info("AnalyticsAgent started")
        while self.running:
            try:
                await self._refresh_all()
                await asyncio.sleep(6 * 3600)  # every 6 hours
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"AnalyticsAgent error: {e}")
                await asyncio.sleep(3600)

    def stop(self):
        self.running = False

    async def _refresh_all(self):
        if not config.youtube.is_configured:
            return

        uploaded = (
            self.session.query(VideoProject)
            .filter(VideoProject.status == ProjectStatus.UPLOADED,
                    VideoProject.yt_video_id.isnot(None))
            .all()
        )
        if not uploaded:
            return

        logger.info(f"AnalyticsAgent: refreshing {len(uploaded)} videos")
        for project in uploaded:
            if project.yt_video_id == "PLACEHOLDER_ID":
                continue
            try:
                stats = await asyncio.get_event_loop().run_in_executor(
                    None, self._fetch_stats, project.yt_video_id
                )
                project.views             = stats.get("views", 0)
                project.watch_time_hours  = stats.get("watch_time_hours", 0.0)
                project.avg_view_duration = stats.get("avg_view_duration", 0.0)
                project.ctr               = stats.get("ctr", 0.0)
                project.likes             = stats.get("likes", 0)
                project.comments          = stats.get("comments", 0)
                project.published_at      = stats.get("published_at") or project.published_at
                self.session.commit()
            except Exception as e:
                logger.warning(f"AnalyticsAgent: failed to fetch stats for {project.yt_video_id}: {e}")

        self._boost_trending_topics()
        self._log(f"Refreshed analytics for {len(uploaded)} videos")

    def _fetch_stats(self, video_id: str) -> dict:
        import google.oauth2.credentials
        from googleapiclient.discovery import build

        creds_data = json.loads(config.youtube.credentials_json)
        credentials = google.oauth2.credentials.Credentials(
            token=creds_data.get("token"),
            refresh_token=creds_data.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=creds_data.get("client_id"),
            client_secret=creds_data.get("client_secret"),
        )

        yt = build("youtube", "v3", credentials=credentials)
        vid_resp = yt.videos().list(
            part="statistics,snippet", id=video_id
        ).execute()

        if not vid_resp.get("items"):
            return {}

        item = vid_resp["items"][0]
        stats = item.get("statistics", {})
        snippet = item.get("snippet", {})

        # YouTube Analytics API for watch time / CTR
        yta = build("youtubeAnalytics", "v2", credentials=credentials)
        today = datetime.utcnow().date().isoformat()
        start = (datetime.utcnow() - timedelta(days=90)).date().isoformat()
        try:
            report = yta.reports().query(
                ids=f"channel=={config.youtube.channel_id}",
                startDate=start,
                endDate=today,
                metrics="views,estimatedMinutesWatched,averageViewDuration,annotationClickThroughRate",
                filters=f"video=={video_id}",
            ).execute()
            row = report.get("rows", [[0, 0, 0, 0]])[0]
            watch_time_hours = row[1] / 60
            avg_dur = row[2]
            ctr = row[3]
        except Exception:
            watch_time_hours = 0.0
            avg_dur = 0.0
            ctr = 0.0

        published = snippet.get("publishedAt")
        pub_dt = None
        if published:
            try:
                pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except Exception:
                pass

        return {
            "views":             int(stats.get("viewCount", 0)),
            "likes":             int(stats.get("likeCount", 0)),
            "comments":          int(stats.get("commentCount", 0)),
            "watch_time_hours":  watch_time_hours,
            "avg_view_duration": avg_dur,
            "ctr":               ctr,
            "published_at":      pub_dt,
        }

    def _boost_trending_topics(self):
        """
        Identify top-performing videos and raise their topic's niche score
        so the TrendAgent favours similar topics in future scans.
        """
        top_videos = (
            self.session.query(VideoProject)
            .filter(VideoProject.status == ProjectStatus.UPLOADED,
                    VideoProject.views > 1000)
            .order_by(VideoProject.views.desc())
            .limit(5)
            .all()
        )
        for video in top_videos:
            logger.info(f"AnalyticsAgent: high performer — {video.topic} ({video.views} views)")
            # Boost: create a new trend entry for the same niche
            from database.models import VideoProject as VP
            similar = (
                self.session.query(VP)
                .filter(VP.niche == video.niche,
                        VP.status == ProjectStatus.TRENDING,
                        VP.trend_score < 1.0)
                .all()
            )
            for p in similar:
                p.trend_score = min(1.0, p.trend_score + 0.1)
        self.session.commit()

    def _log(self, message: str, status: str = "success"):
        log = AgentLog(agent_name="AnalyticsAgent", action="refresh_analytics",
                       status=status, message=message)
        self.session.add(log)
        self.session.commit()
