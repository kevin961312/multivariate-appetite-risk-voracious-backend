"""Adaptadores de ``JobQueue``."""

from voracious.infrastructure.jobs.inline import InlineJobQueue, JobHandler

__all__ = ["InlineJobQueue", "JobHandler"]
