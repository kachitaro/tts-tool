"""Danh sách engine. Thêm engine mới = thêm 1 dòng "module:Class" vào PLUGINS."""

from __future__ import annotations

import importlib
import logging

from .base import Engine

PLUGINS = [
    "giongviet.engines.edge:EdgeEngine",
    "giongviet.engines.vieneu:VieNeuEngine",
]

ENGINES: dict[str, Engine] = {}
for _spec in PLUGINS:
    _mod, _cls = _spec.split(":")
    try:
        _e = getattr(importlib.import_module(_mod), _cls)()
        ENGINES[_e.id] = _e
    except Exception:  # plugin hỏng không được làm sập server
        logging.exception("Bỏ qua engine %s", _spec)
