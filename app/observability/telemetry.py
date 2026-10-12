"""OpenTelemetry to Application Insights.

Switched on by setting APPLICATIONINSIGHTS_CONNECTION_STRING. Without it this
does nothing, so local runs and tests send no telemetry.

Rule 8 applies to everything exported here: requests, traces and log lines
carry document ids and step names, never document content. The application's
own log calls follow that rule. HTTP request bodies are not recorded.
"""

import logging

from app.config import Settings

logger = logging.getLogger(__name__)


def configure_telemetry(settings: Settings, *, service_name: str) -> bool:
    """Returns True when telemetry was switched on."""
    logging.basicConfig(level=logging.INFO)
    if not settings.applicationinsights_connection_string:
        return False
    # Imported here: the package is heavy and only needed when telemetry is on.
    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry.sdk.resources import Resource

    configure_azure_monitor(
        connection_string=settings.applicationinsights_connection_string,
        resource=Resource.create({"service.name": service_name}),
        logger_name="app",
    )
    logger.info("telemetry to Application Insights is on")
    return True
