"""tuvl.main — production entry point. Exposes ``app`` for uvicorn."""

from __future__ import annotations

import importlib.util

import structlog

from tuvl.core.app import app
from tuvl.core.config import settings

logger = structlog.get_logger(__name__)

# Gate on dev mode so the dashboard is never accidentally active in production
# even if a developer has tuvl-insight installed in their production venv.
if settings.tuvl_dev_mode:
    if importlib.util.find_spec("tuvl_insight") is not None:
        try:
            import tuvl_insight

            tuvl_insight.mount(app)
            logger.info("Tuvl Insight developer portal attached (routes: /api/insight/*, /insight)")
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "Tuvl Insight found but failed to mount: %s. To reinstall: pip install tuvl[standard]",
                exc,
            )
    else:
        logger.info(
            "Tuvl Insight not installed. To enable the developer portal: pip install tuvl[standard]"
        )
