"""Agent tools exposed by the EcoSeek backend.

These tools wrap AgenticPlug capability calls behind typed Python functions
that the agent (or the FastAPI router) can invoke. They never hold cluster
credentials — all remote work goes through AgenticPlug.
"""
