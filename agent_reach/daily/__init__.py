"""Agent Reach Daily: a Windows desktop daily-news edition built on the Agent Reach pipeline.

Modules (light imports only; the pipeline is imported lazily by ``refresh``):

    paths       per-user data directory layout (%LOCALAPPDATA%\\AgentReachDaily)
    timeutil    America/Chicago dates, CDT/CST display, fixed-time schedules across DST
    prefs       persisted user preferences -> pipeline Settings
    state       last attempt vs last success, due check, failure backoff
    lock        cross-process refresh lock (OS-released when a worker dies)
    edition     versioned DailyEdition schema, builder and publication eligibility
    store       atomic dated-edition cache, latest pointer, retention, corruption recovery
    render_html standalone escaped HTML export
    prereqs     local Ollama / model checks and optional start
    scheduler   current-user Task Scheduler XML, install/uninstall/status
    refresh     the refresh worker (scheduled, GUI launch or manual)
    app / gui   GUI controller (no Tk) and the tkinter view
"""

APP_NAME = "Agent Reach Daily"
APP_ID = "AgentReachDaily"
#: Release identity of the Daily app (PEP 440). "rc" until the Windows acceptance checks pass.
__version__ = "1.0.0rc11"
VERSION_LABEL = "v1.0 (release candidate 11)"
