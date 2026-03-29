"""
TubeBot AI - Trend Agent
Scans trending senior health / Medicare topics daily using Google Trends
and Reddit, scores them, and stores new VideoProject records.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict

import aiohttp
from bs4 import BeautifulSoup

from config.settings import config
from database.models import VideoProject, ProjectStatus, AgentLog, get_session

logger = logging.getLogger(__name__)


class TrendScorer:
    """Score a topic for senior-health relevance."""

    SENIOR_KEYWORDS = [
        "medicare", "senior", "elderly", "retirement", "social security",
        "aging", "supplement", "medicaid", "pension", "65+", "retiree",
        "health insurance", "prescription", "caregiver", "nursing home",
        "assisted living", "aarp", "ssa", "cms",
    ]

    def score(self, topic: str) -> float:
        topic_lower = topic.lower()
        hits = sum(1 for kw in self.SENIOR_KEYWORDS if kw in topic_lower)
        return min(1.0, hits * 0.25 + 0.1)


class TrendAgent:
    def __init__(self, db_session):
        self.session = db_session
        self.running = False
        self.scorer = TrendScorer()
        self.last_run: datetime | None = None

    async def run(self):
        self.running = True
        logger.info("TrendAgent started")
        while self.running:
            try:
                await self._scan_trends()
                interval = config.trend.scan_interval_hours * 3600
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"TrendAgent error: {e}")
                await asyncio.sleep(3600)

    def stop(self):
        self.running = False

    async def _scan_trends(self):
        logger.info("TrendAgent: scanning trends…")
        topics: List[Dict] = []
        topics += await self._fetch_google_trends()
        topics += await self._fetch_reddit_topics()
        topics += self._niche_seed_topics()

        new_count = 0
        for item in topics:
            score = self.scorer.score(item["topic"])
            if score < config.trend.min_trend_score:
                continue
            exists = (
                self.session.query(VideoProject)
                .filter(VideoProject.topic == item["topic"])
                .first()
            )
            if exists:
                continue
            project = VideoProject(
                topic=item["topic"],
                niche=item.get("niche", "senior health"),
                trend_score=score,
                status=ProjectStatus.TRENDING,
            )
            self.session.add(project)
            new_count += 1

        self.session.commit()
        self.last_run = datetime.utcnow()
        self._log(f"Scan complete — {new_count} new topics queued")
        logger.info(f"TrendAgent: {new_count} new topics added")

    async def _fetch_google_trends(self) -> List[Dict]:
        """Fetch trending searches via pytrends."""
        topics = []
        try:
            from pytrends.request import TrendReq
            pt = TrendReq(hl="en-US", tz=360)
            for niche in config.trend.niches[:4]:
                try:
                    pt.build_payload([niche], cat=45, timeframe="now 7-d")  # cat 45 = Health
                    related = pt.related_queries()
                    if niche in related and related[niche]["top"] is not None:
                        for _, row in related[niche]["top"].head(5).iterrows():
                            topics.append({"topic": row["query"], "niche": niche})
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"pytrends unavailable: {e}")
        return topics

    async def _fetch_reddit_topics(self) -> List[Dict]:
        """Scrape hot posts from Medicare/senior subreddits."""
        topics = []
        subreddits = ["Medicare", "SeniorLiving", "retirement"]
        headers = {"User-Agent": "TubeBot/1.0"}
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                for sub in subreddits:
                    url = f"https://www.reddit.com/r/{sub}/hot.json?limit=10"
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for post in data["data"]["children"][:5]:
                                title = post["data"]["title"]
                                topics.append({"topic": title, "niche": "Medicare"})
        except Exception as e:
            logger.warning(f"Reddit fetch error: {e}")
        return topics

    def _niche_seed_topics(self) -> List[Dict]:
        """Always-relevant evergreen topic seeds."""
        seeds = []
        for niche in config.trend.niches:
            seeds.append({"topic": f"What Medicare covers in {datetime.utcnow().year}", "niche": niche})
            seeds.append({"topic": f"{niche} tips for seniors", "niche": niche})
        return seeds

    def _log(self, message: str, status: str = "success"):
        log = AgentLog(agent_name="TrendAgent", action="scan_trends",
                       status=status, message=message)
        self.session.add(log)
        self.session.commit()
