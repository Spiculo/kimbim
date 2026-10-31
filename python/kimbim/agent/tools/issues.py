# SPDX-License-Identifier: GPL-3.0-or-later
"""Issue tools (doc 14 §17): BCF topics, viewpoints, comments, import and export (D102).

Issues live in the project settings, so creating or editing one is a project change (a write tool);
listing and exporting only read. Import merges by topic GUID: importing the same file twice updates
the issues instead of duplicating them.
"""
from __future__ import annotations

import json

from ... import bcf as BCF
from ..catalogue import AgentError, ToolResult, bridge, tool

_ISSUE = {"type": "string", "description": "Issue id (issues.list lists them)."}
_STATUS = {"type": "string", "enum": list(BCF.STATUSES)}
_VIEWPOINT = {"type": ["object", "null"], "description":
              "Camera, selected components (IFC GlobalIds) and clipping planes; null clears it."}
_COMMENTS = {"type": ["array", "null"], "items": {"type": "object", "properties": {
    "author": {"type": "string"}, "date": {"type": "string"}, "text": {"type": "string"}},
    "required": ["text"]}, "description": "The issue's comments; null clears them."}
_PATH = {"type": "string", "description": "Path of the .bcfzip file."}


@tool("issues.list", {})
def issues_list(session):
    """List the project's BCF issues: id, title, type, status, priority, assignee, comments and viewpoint."""
    return {"issues": bridge(BCF.list_issues)["issues"]}


@tool("issues.create", {"required": ["title"], "properties": {
    "title": {"type": "string"},
    "description": {"type": "string", "description": "What the issue is about."},
    "type": {"type": "string", "description": "Issue type, e.g. Issue, Clash, Request or Remark."},
    "status": _STATUS, "priority": {"type": "string"},
    "assigned_to": {"type": "string", "description": "Who should resolve it."},
    "viewpoint": _VIEWPOINT, "comments": _COMMENTS}}, writes=True)
def issues_create(session, title, description="", type="", status="Open", priority="",
                  assigned_to="", viewpoint=None, comments=None):
    """Create a BCF issue with a viewpoint (camera, selected elements) and optional comments."""
    payload = {"title": title, "description": description, "type": type, "status": status,
               "priority": priority, "assigned_to": assigned_to}
    if viewpoint is not None:
        payload["viewpoint"] = viewpoint
    if comments is not None:
        payload["comments"] = comments
    issue = bridge(BCF.create_issue, json.dumps(payload))["issue"]
    return {"id": issue["id"], "issue": issue}


@tool("issues.update", {"required": ["issue"], "properties": {
    "issue": _ISSUE, "title": {"type": "string"}, "description": {"type": "string"},
    "type": {"type": "string"}, "status": _STATUS, "priority": {"type": "string"},
    "assigned_to": {"type": "string"}, "viewpoint": _VIEWPOINT, "comments": _COMMENTS}}, writes=True)
def issues_update(session, issue, **changes):
    """Change an issue's title, description, type, status, priority, assignee, viewpoint or comments."""
    if not changes:
        raise AgentError("bad_input", hint="nothing to change")
    return {"issue": bridge(BCF.update_issue, issue, json.dumps(changes))["issue"]}


@tool("issues.comment", {"required": ["issue", "text"], "properties": {
    "issue": _ISSUE, "text": {"type": "string"},
    "author": {"type": "string", "description": "Who wrote it (default KimBim)."}}}, writes=True)
def issues_comment(session, issue, text, author=""):
    """Add a comment to an issue."""
    return {"comment": bridge(BCF.add_comment, issue, text, author)["comment"]}


@tool("issues.export_bcf", {"required": ["path"], "properties": {"path": _PATH}})
def issues_export_bcf(session, path):
    """Export the project's issues as a BCF 2.1 .bcfzip for another BIM tool."""
    out = bridge(BCF.export_bcf, path)
    return {"path": out["path"], "topics": out["topics"]}


@tool("issues.import_bcf", {"required": ["path"], "properties": {"path": _PATH}}, writes=True)
def issues_import_bcf(session, path):
    """Merge a .bcfzip into the project's issues by topic GUID; components are matched by IFC GlobalId."""
    out = bridge(BCF.import_bcf, path)
    result = {key: out[key] for key in ("added", "updated", "topics", "components", "unknown_components")
              if key in out}
    return ToolResult(result, list(out.get("warnings") or []))
