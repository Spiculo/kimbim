# SPDX-License-Identifier: GPL-3.0-or-later
"""BCF 2.1 issue management (doc 14 §17): topics, viewpoints, comments, import and export.

Issues are project settings (`issues`), so they are versioned with the project like IDS files and
clash sets (D72): one dict per issue, with a viewpoint that holds the camera, the selected elements
as IFC GlobalIds and clipping planes. The `.bcfzip` is written with zipfile and xml.etree: BCF 2.1
(`bcf.version` with VersionId 2.1, `project.bcfp`, one folder per topic with `markup.bcf` and
`viewpoint.bcfv`). bcf-client (LGPL, pixi.toml) reads the result; the tests open every export with it.

Import merges by topic GUID, so importing the same file twice updates the issues instead of
duplicating them. Components are matched by IFC GlobalId against the open model; GUIDs that are not
in it are counted as unknown and left out. Same protocol as app_bridge: strings in, JSON out, never
raise.
"""
from __future__ import annotations

import datetime
import json
import math
import pathlib
import uuid
import xml.etree.ElementTree as ET
import zipfile

from . import app_bridge as B
from . import settings

STATUSES = ("Open", "In Progress", "Resolved", "Closed")
DEFAULT_STATUS = "Open"
DEFAULT_AUTHOR = "KimBim"
FIELDS = ("title", "description", "type", "status", "priority", "assigned_to", "viewpoint", "comments")

# Imported BCFs use their own vocabularies; map the common ones onto KimBim's statuses.
_STATUS_ALIASES = {
    "open": "Open", "new": "Open", "active": "In Progress", "in progress": "In Progress",
    "inprogress": "In Progress", "resolved": "Resolved", "done": "Resolved", "closed": "Closed",
}

_EXTENSIONS = b"""<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" elementFormDefault="qualified">
  <xs:element name="TopicType">
    <xs:simpleType>
      <xs:restriction base="xs:string">
        <xs:enumeration value="Issue"/>
        <xs:enumeration value="Clash"/>
        <xs:enumeration value="Request"/>
        <xs:enumeration value="Remark"/>
      </xs:restriction>
    </xs:simpleType>
  </xs:element>
  <xs:element name="TopicStatus">
    <xs:simpleType>
      <xs:restriction base="xs:string">
        <xs:enumeration value="Open"/>
        <xs:enumeration value="In Progress"/>
        <xs:enumeration value="Resolved"/>
        <xs:enumeration value="Closed"/>
      </xs:restriction>
    </xs:simpleType>
  </xs:element>
  <xs:element name="Priority">
    <xs:simpleType>
      <xs:restriction base="xs:string">
        <xs:enumeration value="Low"/>
        <xs:enumeration value="Normal"/>
        <xs:enumeration value="High"/>
      </xs:restriction>
    </xs:simpleType>
  </xs:element>
</xs:schema>
"""


# ---------------------------------------------------------------- small helpers

def _fail(message: str) -> str:
    return B._dump({"ok": False, "error": message})


def _dump(obj) -> str:
    return B._dump(obj)


def _now() -> str:
    """UTC ISO-8601 with seconds, as stored and as BCF writes dates."""
    return datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _iso(value) -> str:
    """An ISO-8601 UTC date from a stored or imported value; now when it cannot be read."""
    if isinstance(value, datetime.datetime):
        dt = value
    else:
        text = str(value or "").strip()
        if not text:
            return _now()
        try:
            dt = datetime.datetime.fromisoformat(text)
        except ValueError:
            return _now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    return dt.astimezone(datetime.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _status(value) -> str:
    text = str(value or "").strip()
    if text in STATUSES:
        return text
    return _STATUS_ALIASES.get(text.lower(), text or DEFAULT_STATUS)


def _number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    return float(value)


def _vec(value, name: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} must be [x, y, z]")
    return [_number(v, name) for v in value]


def _camera(value) -> dict:
    if not isinstance(value, dict):
        raise TypeError("viewpoint.camera must be an object")
    kind = str(value.get("type") or "perspective")
    if kind not in ("perspective", "orthogonal"):
        raise ValueError("viewpoint.camera.type must be perspective or orthogonal")
    fov = _number(value.get("fov", 60.0), "viewpoint.camera.fov")
    scale = _number(value.get("scale", 1.0), "viewpoint.camera.scale")
    if not 1.0 <= fov <= 170.0:
        raise ValueError("viewpoint.camera.fov must be between 1 and 170 degrees")
    if scale <= 0:
        raise ValueError("viewpoint.camera.scale must be positive")
    return {"type": kind, "eye": _vec(value.get("eye"), "viewpoint.camera.eye"),
            "target": _vec(value.get("target"), "viewpoint.camera.target"),
            "up": _vec(value.get("up", [0.0, 0.0, 1.0]), "viewpoint.camera.up"),
            "fov": fov, "scale": scale}


def _viewpoint(value) -> dict:
    """A viewpoint with camera (or None), selected component GlobalIds and clipping planes."""
    if value is None:
        return {"camera": None, "components": [], "clipping": []}
    if not isinstance(value, dict):
        raise TypeError("viewpoint must be an object")
    camera = value.get("camera")
    if camera is not None:
        camera = _camera(camera)
    components = value.get("components") or []
    if not isinstance(components, list) or not all(isinstance(g, str) and g.strip() for g in components):
        raise ValueError("viewpoint.components must be a list of IFC GlobalIds")
    clipping = value.get("clipping") or []
    if not isinstance(clipping, list):
        raise TypeError("viewpoint.clipping must be a list")
    planes = []
    for i, plane in enumerate(clipping):
        if not isinstance(plane, dict):
            raise TypeError(f"viewpoint.clipping[{i}] must be an object")
        planes.append({"point": _vec(plane.get("point"), f"viewpoint.clipping[{i}].point"),
                       "normal": _vec(plane.get("normal"), f"viewpoint.clipping[{i}].normal")})
    return {"camera": camera, "components": list(dict.fromkeys(g.strip() for g in components)),
            "clipping": planes}


def _comments(value) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("comments must be a list")
    out = []
    for comment in value:
        if not isinstance(comment, dict):
            raise TypeError("each comment must be an object")
        text = str(comment.get("text") or "").strip()
        if not text:
            continue
        out.append({"author": str(comment.get("author") or DEFAULT_AUTHOR),
                    "date": _iso(comment.get("date")), "text": text})
    return out


# ---------------------------------------------------------------- settings storage

def _issues() -> list[dict]:
    issues = settings.current().get("issues", [])
    return [i for i in issues if isinstance(i, dict)] if isinstance(issues, list) else []


def _save(issues: list[dict]) -> None:
    out = json.loads(settings.set_project_settings(json.dumps({"issues": issues})))
    if not out.get("ok"):
        raise RuntimeError(out.get("error") or "the project settings could not be saved")


def _index(issues: list[dict], issue_id: str) -> int | None:
    for i, issue in enumerate(issues):
        if issue.get("id") == issue_id:
            return i
    return None


def _new_issue(data: dict) -> dict:
    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("an issue needs a title")
    status = _status(data.get("status"))
    if status not in STATUSES:
        raise ValueError(f"unknown status {status} ({', '.join(STATUSES)})")
    now = _now()
    return {"id": str(uuid.uuid4()), "title": title,
            "description": str(data.get("description") or ""), "type": str(data.get("type") or ""),
            "status": status, "priority": str(data.get("priority") or ""),
            "assigned_to": str(data.get("assigned_to") or ""), "created": now, "modified": now,
            "comments": _comments(data.get("comments")), "viewpoint": _viewpoint(data.get("viewpoint"))}


# ---------------------------------------------------------------- bridge: issues

def list_issues() -> str:
    """The project's issues, newest first -> {"ok": true, "issues": [...]}."""
    try:
        issues = sorted(_issues(), key=lambda i: str(i.get("created") or ""), reverse=True)
        return _dump({"ok": True, "issues": issues})
    except Exception as ex:  # noqa: BLE001  (a bridge function never raises)
        return _fail(f"{type(ex).__name__}: {ex}")


def issue_viewpoint(issue_id: str) -> str:
    """The camera, selected components and clipping planes of one issue (for "Show viewpoint")."""
    try:
        issues = _issues()
        i = _index(issues, issue_id)
        if i is None:
            return _fail(f"no issue with id {issue_id}")
        issue = issues[i]
        viewpoint = issue.get("viewpoint") or {}
        return _dump({"ok": True, "id": issue.get("id"), "title": issue.get("title") or "",
                      "camera": viewpoint.get("camera"), "components": viewpoint.get("components") or [],
                      "clipping": viewpoint.get("clipping") or []})
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")


def create_issue(issue_json: str) -> str:
    """Create an issue from a JSON object (title required; status defaults to Open)."""
    try:
        data = json.loads(issue_json or "{}")
    except ValueError as ex:
        return _fail(f"bad input: {ex}")
    if not isinstance(data, dict):
        return _fail("bad input: expected an object")
    try:
        issue = _new_issue(data)
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    try:
        issues = _issues()
        issues.append(issue)
        _save(issues)
        return _dump({"ok": True, "issue": issue})
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")


def update_issue(issue_id: str, changes_json: str) -> str:
    """Change an issue's title, description, type, status, priority, assignee, viewpoint or comments."""
    try:
        changes = json.loads(changes_json or "{}")
    except ValueError as ex:
        return _fail(f"bad input: {ex}")
    if not isinstance(changes, dict):
        return _fail("bad input: expected an object")
    unknown = sorted(set(changes) - set(FIELDS))
    if unknown:
        return _fail(f"unknown issue field(s): {', '.join(unknown)}")
    try:
        issues = _issues()
        i = _index(issues, issue_id)
        if i is None:
            return _fail(f"no issue with id {issue_id}")
        issue = dict(issues[i])
        if "title" in changes:
            title = str(changes["title"] or "").strip()
            if not title:
                return _fail("an issue needs a title")
            issue["title"] = title
        for key in ("description", "type", "priority", "assigned_to"):
            if key in changes:
                issue[key] = str(changes[key] or "")
        if "status" in changes:
            status = _status(changes["status"])
            if status not in STATUSES:
                return _fail(f"unknown status {status} ({', '.join(STATUSES)})")
            issue["status"] = status
        if "viewpoint" in changes:
            issue["viewpoint"] = _viewpoint(changes["viewpoint"])
        if "comments" in changes:
            issue["comments"] = _comments(changes["comments"])
        issue["modified"] = _now()
        issues[i] = issue
        _save(issues)
        return _dump({"ok": True, "issue": issue})
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")


def delete_issue(issue_id: str) -> str:
    """Delete an issue by id."""
    try:
        issues = _issues()
        i = _index(issues, issue_id)
        if i is None:
            return _fail(f"no issue with id {issue_id}")
        del issues[i]
        _save(issues)
        return _dump({"ok": True, "deleted": issue_id})
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")


def add_comment(issue_id: str, text: str, author: str = "") -> str:
    """Add a comment to an issue -> {"ok": true, "issue", "comment"}."""
    text = str(text or "").strip()
    if not text:
        return _fail("a comment needs some text")
    try:
        issues = _issues()
        i = _index(issues, issue_id)
        if i is None:
            return _fail(f"no issue with id {issue_id}")
        issue = dict(issues[i])
        comment = {"author": str(author or "").strip() or DEFAULT_AUTHOR, "date": _now(), "text": text}
        issue["comments"] = [*_comments(issue.get("comments")), comment]
        issue["modified"] = comment["date"]
        issues[i] = issue
        _save(issues)
        return _dump({"ok": True, "issue": issue, "comment": comment})
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")


# ---------------------------------------------------------------- XML writing

def _xml(root: ET.Element) -> bytes:
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _el(parent: ET.Element, tag: str, text=None, **attrs) -> ET.Element:
    element = ET.SubElement(parent, tag, **{k: str(v) for k, v in attrs.items()})
    if text is not None:
        element.text = str(text)
    return element


def _point(parent: ET.Element, tag: str, values) -> None:
    element = ET.SubElement(parent, tag)
    for axis, value in zip(("X", "Y", "Z"), values):
        _el(element, axis, value)


def _unit(values) -> list[float]:
    length = math.sqrt(sum(float(v) ** 2 for v in values))
    return [float(v) / length for v in values] if length > 1e-12 else [0.0, 0.0, -1.0]


def _direction(eye, target) -> list[float]:
    return _unit([float(t) - float(e) for e, t in zip(eye, target)])


def _project() -> tuple[str, str]:
    """The BCF project's id and name: a stable UUID from the open IFC project, or a KimBim project."""
    if B._model is not None:
        projects = B._model.by_type("IfcProject")
        if projects:
            project_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"kimbim:bcf:project:{projects[0].GlobalId}"))
            return project_id, projects[0].Name or "KimBim project"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "kimbim:bcf:project")), "KimBim project"


def _viewpoint_guid(issue: dict) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"kimbim:bcf:viewpoint:{issue.get('id')}"))


def _markup(issue: dict) -> bytes:
    root = ET.Element("Markup")
    header = ET.SubElement(root, "Header")
    file_el = ET.SubElement(header, "File")
    path = getattr(B, "_path", "") or ""
    _el(file_el, "Filename", pathlib.Path(path).name if path else "model.ifc")
    _el(file_el, "Date", _iso(issue.get("modified")))
    if B._model is not None:
        projects = B._model.by_type("IfcProject")
        if projects:
            file_el.set("IfcProject", projects[0].GlobalId)

    topic_attrs = {"Guid": str(issue["id"]), "TopicStatus": str(issue.get("status") or DEFAULT_STATUS)}
    if issue.get("type"):
        topic_attrs["TopicType"] = str(issue["type"])
    topic = ET.SubElement(root, "Topic", **topic_attrs)
    _el(topic, "Title", issue.get("title") or "")
    if issue.get("priority"):
        _el(topic, "Priority", issue["priority"])
    _el(topic, "CreationDate", _iso(issue.get("created")))
    _el(topic, "CreationAuthor", DEFAULT_AUTHOR)
    if issue.get("modified"):
        _el(topic, "ModifiedDate", _iso(issue.get("modified")))
    if issue.get("assigned_to"):
        _el(topic, "AssignedTo", issue["assigned_to"])
    if issue.get("description"):
        _el(topic, "Description", issue["description"])

    for i, comment in enumerate(issue.get("comments") or []):
        element = ET.SubElement(root, "Comment", Guid=str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"kimbim:bcf:comment:{issue['id']}:{i}")))
        _el(element, "Date", _iso(comment.get("date")))
        _el(element, "Author", comment.get("author") or DEFAULT_AUTHOR)
        _el(element, "Comment", comment.get("text") or "")
        ET.SubElement(element, "Viewpoint", Guid=_viewpoint_guid(issue))

    viewpoints = ET.SubElement(root, "Viewpoints", Guid=_viewpoint_guid(issue))
    _el(viewpoints, "Viewpoint", "viewpoint.bcfv")
    return _xml(root)


def _visinfo(issue: dict) -> bytes:
    root = ET.Element("VisualizationInfo", Guid=_viewpoint_guid(issue))
    viewpoint = issue.get("viewpoint") or {}
    components = viewpoint.get("components") or []
    if components:
        container = ET.SubElement(root, "Components")
        selection = ET.SubElement(container, "Selection")
        for guid in components:
            ET.SubElement(selection, "Component", IfcGuid=str(guid))
        ET.SubElement(container, "Visibility", DefaultVisibility="false")

    camera = viewpoint.get("camera")
    if camera:
        eye, target, up = camera["eye"], camera["target"], _unit(camera.get("up") or [0.0, 0.0, 1.0])
        direction = _direction(eye, target)
        if camera.get("type") == "orthogonal":
            element = ET.SubElement(root, "OrthogonalCamera")
            _point(element, "CameraViewPoint", eye)
            _point(element, "CameraDirection", direction)
            _point(element, "CameraUpVector", up)
            _el(element, "ViewToWorldScale", max(1e-6, float(camera.get("scale", 1.0))))
        else:
            element = ET.SubElement(root, "PerspectiveCamera")
            _point(element, "CameraViewPoint", eye)
            _point(element, "CameraDirection", direction)
            _point(element, "CameraUpVector", up)
            _el(element, "FieldOfView", min(170.0, max(1.0, float(camera.get("fov", 60.0)))))

    planes = viewpoint.get("clipping") or []
    if planes:
        container = ET.SubElement(root, "ClippingPlanes")
        for plane in planes:
            element = ET.SubElement(container, "ClippingPlane")
            _point(element, "Location", plane["point"])
            _point(element, "Direction", _unit(plane["normal"]))
    return _xml(root)


def export_bcf(path: str) -> str:
    """Write the project's issues as a BCF 2.1 .bcfzip -> {"ok": true, "path", "topics"}."""
    try:
        target = pathlib.Path(path)
        issues = _issues()
        project_id, project_name = _project()
        version = ET.Element("Version", VersionId="2.1")
        _el(version, "DetailedVersion", "2.1")
        project = ET.Element("ProjectExtension")
        project_el = ET.SubElement(project, "Project", ProjectId=project_id)
        _el(project_el, "Name", project_name)
        _el(project, "ExtensionSchema", "extensions.xsd")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("bcf.version", _xml(version))
            z.writestr("project.bcfp", _xml(project))
            z.writestr("extensions.xsd", _EXTENSIONS)
            for issue in issues:
                folder = str(issue["id"])
                z.writestr(f"{folder}/", "")
                z.writestr(f"{folder}/markup.bcf", _markup(issue))
                z.writestr(f"{folder}/viewpoint.bcfv", _visinfo(issue))
        return _dump({"ok": True, "path": str(target), "topics": len(issues)})
    except Exception as ex:  # noqa: BLE001  (bad path, unreadable model, anything)
        return _fail(f"{type(ex).__name__}: {ex}")


# ---------------------------------------------------------------- XML reading

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(element, name: str):
    if element is None:
        return None
    for child in list(element):
        if _local(child.tag) == name:
            return child
    return None


def _text(element, name: str, default: str = "") -> str:
    child = _child(element, name)
    return ((child.text or "").strip() if child is not None else "") or default


def _all(element, name: str) -> list:
    return [child for child in element.iter() if _local(child.tag) == name] if element is not None else []


def _read_camera(visinfo) -> dict | None:
    for tag, kind in (("PerspectiveCamera", "perspective"), ("OrthogonalCamera", "orthogonal")):
        element = _child(visinfo, tag)
        if element is None:
            continue
        eye = _read_point(_child(element, "CameraViewPoint"))
        direction = _read_point(_child(element, "CameraDirection"))
        up = _read_point(_child(element, "CameraUpVector")) or [0.0, 0.0, 1.0]
        if eye is None or direction is None:
            continue
        target = [eye[i] + direction[i] * 10.0 for i in range(3)]
        if kind == "orthogonal":
            fov, scale = 60.0, _read_number(_child(element, "ViewToWorldScale"), 1.0)
        else:
            fov, scale = _read_number(_child(element, "FieldOfView"), 60.0), 1.0
        return {"type": kind, "eye": eye, "target": target, "up": up, "fov": fov, "scale": scale}
    return None


def _read_point(element) -> list[float] | None:
    if element is None:
        return None
    try:
        return [float(_text(element, axis, "0")) for axis in ("X", "Y", "Z")]
    except ValueError:
        return None


def _read_number(element, default: float) -> float:
    try:
        return float((element.text or "").strip()) if element is not None else default
    except ValueError:
        return default


def _read_viewpoint(visinfo) -> dict:
    viewpoint = {"camera": _read_camera(visinfo), "components": [], "clipping": []}
    selection = _child(_child(visinfo, "Components"), "Selection")
    for component in _all(selection, "Component"):
        guid = component.attrib.get("IfcGuid") or component.attrib.get("ifcGuid")
        if guid and guid.strip():
            viewpoint["components"].append(guid.strip())
    planes = _child(visinfo, "ClippingPlanes")
    for plane in _all(planes, "ClippingPlane"):
        point = _read_point(_child(plane, "Location"))
        normal = _read_point(_child(plane, "Direction"))
        if point is not None and normal is not None:
            viewpoint["clipping"].append({"point": point, "normal": normal})
    viewpoint["components"] = list(dict.fromkeys(viewpoint["components"]))
    return viewpoint


def _merge_comments(existing, imported) -> list[dict]:
    out = list(_comments(existing))
    seen = {(c["author"], c["date"], c["text"]) for c in out}
    for comment in _comments(imported):
        key = (comment["author"], comment["date"], comment["text"])
        if key not in seen:
            out.append(comment)
            seen.add(key)
    return out


def _resolve(guids) -> tuple[list[str], int]:
    """Keep the component GlobalIds that exist in the open model; count the rest as unknown."""
    if B._model is None:
        return [], len(guids)
    known, unknown = [], 0
    for guid in guids:
        try:
            B._model.by_guid(guid)
            known.append(guid)
        except RuntimeError:
            unknown += 1
    return known, unknown


def _read_topics(z: zipfile.ZipFile) -> list[dict]:
    topics = []
    names = set(z.namelist())
    for name in sorted(names):
        parts = name.split("/")
        if len(parts) != 2 or parts[1] != "markup.bcf":
            continue
        folder = parts[0]
        try:
            root = ET.fromstring(z.read(name))
        except ET.ParseError as ex:
            raise ValueError(f"{name} is not valid XML: {ex}") from ex
        topic = _child(root, "Topic")
        if topic is None:
            continue
        guid = (topic.attrib.get("Guid") or topic.attrib.get("guid") or folder).strip() or folder
        title = _text(topic, "Title")
        if not title:
            title = f"Imported topic {guid[:8]}"
        comments = []
        for element in _all(root, "Comment"):
            text = _text(element, "Comment")
            if text:
                comments.append({"author": _text(element, "Author", DEFAULT_AUTHOR),
                                 "date": _iso(_text(element, "Date")), "text": text})

        viewpoint = {"camera": None, "components": [], "clipping": []}
        found_viewpoint = False
        for element in (e for e in root.iter() if _local(e.tag) in ("Viewpoints", "ViewPoint")):
            filename = _text(element, "Viewpoint")
            if not filename:
                continue
            path = f"{folder}/{filename}"
            if path not in names:
                continue
            try:
                visinfo = ET.fromstring(z.read(path))
            except ET.ParseError:
                continue
            imported = _read_viewpoint(visinfo)
            found_viewpoint = True
            viewpoint["camera"] = viewpoint["camera"] or imported["camera"]
            viewpoint["components"] = list(dict.fromkeys([*viewpoint["components"], *imported["components"]]))
            viewpoint["clipping"] = [*viewpoint["clipping"], *imported["clipping"]]

        created = _iso(_text(topic, "CreationDate"))
        modified = _iso(_text(topic, "ModifiedDate")) if _text(topic, "ModifiedDate") else created
        topics.append({
            "id": guid, "title": title, "description": _text(topic, "Description"),
            "type": _text(topic, "TopicType") or topic.attrib.get("TopicType", ""),
            "status": _status(topic.attrib.get("TopicStatus") or _text(topic, "TopicStatus")),
            "priority": _text(topic, "Priority"), "assigned_to": _text(topic, "AssignedTo"),
            "created": created, "modified": modified, "comments": comments,
            "viewpoint": viewpoint if found_viewpoint else {"camera": None, "components": [], "clipping": []},
        })
    return topics


def import_bcf(path: str) -> str:
    """Merge a .bcfzip into the project's issues by topic GUID -> {"ok", "added", "updated", ...}."""
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "bcf.version" not in names:
                return _fail("not a BCF file: bcf.version is missing")
            try:
                version = ET.fromstring(z.read("bcf.version"))
            except ET.ParseError as ex:
                return _fail(f"bcf.version is not valid XML: {ex}")
            version_id = (version.attrib.get("VersionId") or "").strip()
            if version_id not in ("2.0", "2.1", "3.0"):
                return _fail(f"unsupported BCF version {version_id or 'unknown'} (2.0, 2.1 or 3.0)")
            topics = _read_topics(z)
    except (OSError, zipfile.BadZipFile) as ex:
        return _fail(f"cannot read {path}: {ex}")
    except ValueError as ex:
        return _fail(f"{path} is not a valid BCF file: {ex}")

    if B._model is None:
        return _fail("no model open: open the IFC model before importing issues")

    try:
        issues = _issues()
        by_id = {issue.get("id"): i for i, issue in enumerate(issues)}
        added = updated = components = unknown = 0
        for topic in topics:
            known, missing = _resolve(topic["viewpoint"]["components"])
            topic["viewpoint"]["components"] = known
            components += len(known)
            unknown += missing
            i = by_id.get(topic["id"])
            if i is None:
                issues.append(topic)
                by_id[topic["id"]] = len(issues) - 1
                added += 1
            else:
                issue = dict(issues[i])
                for key in ("title", "description", "type", "status", "priority", "assigned_to", "modified"):
                    issue[key] = topic[key]
                issue["comments"] = _merge_comments(issue.get("comments"), topic["comments"])
                if topic["viewpoint"]["camera"] or topic["viewpoint"]["components"] or topic["viewpoint"]["clipping"]:
                    issue["viewpoint"] = topic["viewpoint"]
                issues[i] = issue
                updated += 1
        _save(issues)
        result = {"ok": True, "added": added, "updated": updated, "topics": added + updated,
                  "components": components, "unknown_components": unknown}
        if unknown:
            result["warnings"] = [f"{unknown} component(s) are not in the open model and were left out"]
        return _dump(result)
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")
