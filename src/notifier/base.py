"""
src/notifier/base.py
=====================
Abstract NotificationChannel and shared result types.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChannelResult:
    channel: str
    success: bool
    partial: bool = False          # some recipients succeeded, some failed
    message: str = ""
    failed_recipients: list[str] = field(default_factory=list)


@dataclass
class DispatchResult:
    success: bool
    partial: bool
    channel_results: list[ChannelResult] = field(default_factory=list)

    @property
    def all_failed(self) -> bool:
        return len(self.channel_results) > 0 and not any(r.success or r.partial for r in self.channel_results)


class NotificationChannel(ABC):
    """Base class for all notification delivery channels."""

    @property
    @abstractmethod
    def enabled(self) -> bool: ...

    @property
    @abstractmethod
    def channel_name(self) -> str: ...

    @abstractmethod
    def send(self, run_result: Any) -> ChannelResult: ...
