"""
TubeBot AI - Video Agent
Assembles the final video using FFmpeg and free Pexels stock footage.
No paid services required.

Pipeline:
  1. Extract keyword queries from the script topic + body
  2. Fetch matching stock clips from the Pexels free video API
  3. Trim/scale each clip to 1920x1080 @ 30fps via FFmpeg
  4. Concatenate clips, looping to cover the voiceover duration
  5. Mix in the voiceover audio track
  6. Burn a title card overlay onto the first 5 seconds
  7. Output final MP4

Requirements:
  - ffmpeg and ffprobe installed and on PATH
  - PEXELS_API_KEY env var (free account at pexels.com/api)
"""
import asyncio
import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import aiofiles
import aiohttp

from config.settings import config
from database.models import VideoProject, ProjectStatus, AgentLog

logger = logging.getLogger(__name__)

PEXELS_VIDEO_API = "https://api.pexels.com/videos/search"
CLIP_DURATION = 6       # seconds each raw clip is trimmed to
MAX_CLIPS = 40          # upper bound to avoid runaway downloads


# ─── Pexels client ────────────────────────────────────────────────────────────

class PexelsClient:
    """Downloads free stock video clips from the Pexels API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {"Authorization": api_key}

    async def search_videos(self, query: str, per_page: int = 3) -> List[dict]:
        params = {
            "query": query,
            "per_page": per_page,
            "orientation": "landscape",
            "size": "medium",
        }
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(
                    PEXELS_VIDEO_API,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        return (await resp.json()).get("videos", [])
                    logger.warning(f"Pexels API {resp.status} for query '{query}'")
        except Exception as e:
            logger.warning(f"Pexels search error for '{query}': {e}")
        return []

    async def download_clip(self, video: dict, dest_dir: Path) -> Optional[Path]:
        """Download the highest-resolution MP4 <= 1920px wide."""
        files = [f for f in video.get("video_files", [])
                 if f.get("file_type") == "video/mp4"]
        files.sort(key=lambda f: f.get("width", 0) * f.get("height", 0))

        chosen = None
        for f in reversed(files):
            if f.get("width", 0) <= 1920:
                chosen = f
                break
        if not chosen and files:
            chosen = files[-1]
        if not chosen:
            return None

        out = dest_dir / f"clip_{video['id']}.mp4"
        if out.exists() and out.stat().st_size > 0:
            return out

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    chosen["link"],
                    timeout=aiohttp.ClientTimeout(total=90),
                ) as resp:
                    if resp.status == 200:
                        async with aiofiles.open(out, "wb") as fh:
                            async for chunk in resp.content.iter_chunked(65536):
                                await fh.write(chunk)
                        return out
        except Exception as e:
            logger.warning(f"Failed to download clip {video['id']}: {e}")
        return None


# ─── FFmpeg helper ─────────────────────────────────────────────────────────────

class FFmpegAssembler:
    """Wraps FFmpeg subprocess calls for clip processing and assembly."""

    @staticmethod
    def _run(*args):
        cmd = ["ffmpeg", "-y", "-loglevel", "error"] + [str(a) for a in args]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {result.stderr[-600:]}")

    @staticmethod
    def _probe_duration(path: str) -> float:
        result = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             path],
            capture_output=True, text=True,
        )
        try:
            return float(result.stdout.strip())
        except ValueError:
            return 0.0

    def trim_clip(self, src: Path, dest: Path, duration: float) -> Path:
        """Loop-trim a clip to `duration` seconds, scaled to 1920x1080."""
        self._run(
            "-stream_loop", "-1",
            "-i", src,
            "-t", duration,
            "-vf", (
                "scale=1920:1080:force_original_aspect_ratio=increase,"
                "crop=1920:1080,setsar=1"
            ),
            "-r", "30",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-an",
            dest,
        )
        return dest

    def concatenate_clips(self, clip_paths: List[Path], dest: Path) -> Path:
        """Concatenate same-codec clips via the concat demuxer."""
        list_file = dest.parent / "_concat_list.txt"
        with open(list_file, "w") as f:
            for p in clip_paths:
                f.write(f"file '{p.resolve()}'\n")
        self._run(
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            dest,
        )
        list_file.unlink(missing_ok=True)
        return dest

    def mix_audio(self, video_path: Path, audio_path: str,
                  audio_dur: float, dest: Path) -> Path:
        """Replace video audio with voiceover; trim to audio duration."""
        self._run(
            "-stream_loop", "-1", "-i", video_path,
            "-i", audio_path,
            "-t", audio_dur,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            dest,
        )
        return dest

    def add_title_overlay(self, video_path: Path, title: str, dest: Path) -> Path:
        """Burn a semi-transparent title card onto the opening 5 seconds."""
        safe = title.replace("\\", "").replace("'", "").replace(":", " -")[:72]
        drawtext = (
            f"drawtext=text='{safe}'"
            ":fontcolor=white:fontsize=54"
            ":x=(w-text_w)/2:y=h*0.84"
            ":box=1:boxcolor=black@0.60:boxborderw=14"
            ":enable='between(t,0,5)'"
        )
        self._run(
            "-i", video_path,
            "-vf", drawtext,
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "copy",
            dest,
        )
        return dest

    def make_colour_clip(self, dest: Path, duration: float) -> Path:
        """Fallback: generate a plain dark-blue clip (no stock footage needed)."""
        self._run(
            "-f", "lavfi",
            "-i", "color=c=0x1a3a5c:size=1920x1080:rate=30",
            "-t", min(duration, 10),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            dest,
        )
        return dest


# ─── Main agent ───────────────────────────────────────────────────────────────

class VideoAgent:
    """
    Assembles final YouTube videos using Pexels stock footage + FFmpeg.
    Requires: ffmpeg and ffprobe on PATH; PEXELS_API_KEY env var.
    Falls back gracefully to a solid colour background if Pexels is
    unavailable or the API key is not set.
    """

    def __init__(self, db_session):
        self.session = db_session
        self.running = False
        self.pexels = PexelsClient(config.pexels.api_key) if config.pexels.api_key else None
        self.ffmpeg = FFmpegAssembler()

    async def run(self):
        self.running = True
        logger.info("VideoAgent started (FFmpeg + Pexels)")
        while self.running:
            try:
                await self._process_next()
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"VideoAgent error: {e}")
                await asyncio.sleep(1800)

    def stop(self):
        self.running = False

    # ── Processing ────────────────────────────────────────────────────────────

    async def _process_next(self):
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
            video_path = await self._assemble_video(project)
            project.video_path = str(video_path)
            project.status = ProjectStatus.RENDERED
            self.session.commit()
            self._log(f"Video rendered for project {project.id}", project.id)
            logger.info(f"VideoAgent: saved → {video_path}")
        except Exception as e:
            logger.error(f"VideoAgent failed for project {project.id}: {e}")
            project.error_message = str(e)
            self.session.commit()

    async def _assemble_video(self, project: VideoProject) -> Path:
        video_dir = Path(config.video.video_dir)
        video_dir.mkdir(parents=True, exist_ok=True)
        clips_dir = video_dir / f"clips_{project.id}"
        clips_dir.mkdir(exist_ok=True)

        audio_dur = self.ffmpeg._probe_duration(project.audio_path)
        if audio_dur <= 0:
            raise ValueError(f"Cannot read audio duration: {project.audio_path}")

        # 1. Download Pexels clips
        raw_clips = await self._fetch_clips(project, clips_dir, audio_dur)

        # 2. Fallback to solid-colour clip if nothing downloaded
        if not raw_clips:
            logger.warning("No Pexels clips found — using colour background fallback")
            fallback = clips_dir / "colour_fallback.mp4"
            raw_clips = [self.ffmpeg.make_colour_clip(fallback, CLIP_DURATION)]

        # 3. Trim each clip to CLIP_DURATION seconds @ 1920x1080
        trimmed: List[Path] = []
        for i, clip in enumerate(raw_clips):
            dest = clips_dir / f"t_{i:04d}.mp4"
            try:
                self.ffmpeg.trim_clip(clip, dest, CLIP_DURATION)
                trimmed.append(dest)
            except Exception as e:
                logger.warning(f"Could not trim {clip.name}: {e}")

        if not trimmed:
            raise RuntimeError("All clip trims failed — check FFmpeg installation")

        # 4. Loop clips to cover full audio duration
        needed = int(audio_dur / CLIP_DURATION) + 2
        looped = (trimmed * (needed // len(trimmed) + 1))[:needed]

        # 5. Concatenate → silent video
        silent = clips_dir / "silent.mp4"
        self.ffmpeg.concatenate_clips(looped, silent)

        # 6. Mix voiceover
        mixed = clips_dir / "mixed.mp4"
        self.ffmpeg.mix_audio(silent, project.audio_path, audio_dur, mixed)

        # 7. Burn in title overlay → final output
        title = project.yt_title or project.topic or "TubeBot AI"
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        final = video_dir / f"video_{project.id}_{ts}.mp4"
        self.ffmpeg.add_title_overlay(mixed, title, final)

        # 8. Clean up working directory
        self._cleanup(clips_dir)
        return final

    async def _fetch_clips(self, project: VideoProject,
                           clips_dir: Path, audio_dur: float) -> List[Path]:
        """Search Pexels for clips that cover the script topic."""
        if not self.pexels:
            logger.warning("PEXELS_API_KEY not set — skipping stock footage download")
            return []

        queries = self._extract_queries(project)
        clips: List[Path] = []
        target = min(int(audio_dur / CLIP_DURATION) * 2, MAX_CLIPS)

        for query in queries:
            if len(clips) >= target:
                break
            try:
                videos = await self.pexels.search_videos(query, per_page=3)
                for v in videos:
                    if len(clips) >= target:
                        break
                    p = await self.pexels.download_clip(v, clips_dir)
                    if p:
                        clips.append(p)
                await asyncio.sleep(0.4)   # stay well within rate limits
            except Exception as e:
                logger.warning(f"Pexels query '{query}' error: {e}")

        logger.info(f"VideoAgent: downloaded {len(clips)} Pexels clips")
        return clips

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _extract_queries(self, project: VideoProject) -> List[str]:
        """Build a deduplicated list of search queries from the project."""
        queries: List[str] = []

        if project.topic:
            queries.append(project.topic)

        # Pull capitalised noun phrases from the script every ~150 words
        if project.script:
            words = project.script.split()
            for i in range(0, min(len(words), 3000), 150):
                chunk = " ".join(words[i: i + 150])
                m = re.search(r'\b([A-Z][a-z]+(?: [A-Z][a-z]+)+)\b', chunk)
                if m:
                    queries.append(m.group(1))

        # Evergreen visuals that suit senior-health / informational content
        evergreen = [
            "senior health", "doctor consultation", "healthy lifestyle",
            "medical professional", "retirement lifestyle", "elderly care",
            "nature background", "city timelapse", "office work",
        ]
        queries.extend(evergreen)

        # Deduplicate while preserving order
        seen: set = set()
        unique: List[str] = []
        for q in queries:
            lq = q.lower().strip()
            if lq and lq not in seen:
                seen.add(lq)
                unique.append(q)
        return unique

    @staticmethod
    def _cleanup(clips_dir: Path):
        try:
            for f in clips_dir.iterdir():
                f.unlink(missing_ok=True)
            clips_dir.rmdir()
        except Exception:
            pass

    def _log(self, message: str, project_id: int = None, status: str = "success"):
        log = AgentLog(
            agent_name="VideoAgent",
            action="assemble_video",
            status=status,
            message=message,
            project_id=project_id,
        )
        self.session.add(log)
        self.session.commit()
