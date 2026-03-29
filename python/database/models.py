"""TubeBot AI - Database Models"""
import os
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean,
    DateTime, Text, JSON, Enum
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import enum

Base = declarative_base()


class ProjectStatus(str, enum.Enum):
    TRENDING   = "trending"    # Topic identified
    SCRIPTED   = "scripted"    # Script written
    VOICED     = "voiced"      # Audio generated
    THUMBNAILED = "thumbnailed" # Thumbnail created
    SEOD       = "seod"        # SEO data written
    RENDERED   = "rendered"    # Video assembled
    UPLOADED   = "uploaded"    # Live on YouTube
    FAILED     = "failed"


class VideoProject(Base):
    __tablename__ = "video_projects"

    id              = Column(Integer, primary_key=True)
    topic           = Column(String(500), nullable=False)
    niche           = Column(String(200))
    trend_score     = Column(Float, default=0.0)
    status          = Column(String(50), default=ProjectStatus.TRENDING)

    # Content
    script          = Column(Text)
    script_path     = Column(String(500))
    audio_path      = Column(String(500))
    video_path      = Column(String(500))
    thumbnail_path  = Column(String(500))

    # SEO
    yt_title        = Column(String(200))
    yt_description  = Column(Text)
    yt_tags         = Column(JSON)

    # YouTube
    yt_video_id     = Column(String(50))
    yt_url          = Column(String(200))
    scheduled_at    = Column(DateTime)
    published_at    = Column(DateTime)

    # Analytics
    views           = Column(Integer, default=0)
    watch_time_hours = Column(Float, default=0.0)
    avg_view_duration = Column(Float, default=0.0)
    ctr             = Column(Float, default=0.0)
    likes           = Column(Integer, default=0)
    comments        = Column(Integer, default=0)

    # Meta
    error_message   = Column(Text)
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id          = Column(Integer, primary_key=True)
    agent_name  = Column(String(100))
    action      = Column(String(200))
    status      = Column(String(50))   # success / error / info
    message     = Column(Text)
    project_id  = Column(Integer)
    created_at  = Column(DateTime, default=datetime.utcnow)


def init_database(db_path: str):
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return engine


def get_session(engine):
    Session = sessionmaker(bind=engine)
    return Session()
