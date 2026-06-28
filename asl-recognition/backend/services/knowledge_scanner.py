from __future__ import annotations
import datetime
import json
import os
from typing import List

from sqlalchemy.orm import Session

_KB_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "knowledge")
)

_KB_CONFIGS = [
    {
        "slug": "asl-wlasl",
        "name": "ASL – WLASL (Corpus principal)",
        "language_code": "asl",
        "language_name": "American Sign Language",
        "dir": "asl_data",
        "labels_file": "labels.json",
        "description": "Dataset principal WLASL — classes organisées en sous-dossiers",
    },
    {
        "slug": "asl-images",
        "name": "ASL Images (Alphabet)",
        "language_code": "asl",
        "language_name": "American Sign Language",
        "dir": "asl_images",
        "labels_file": None,
        "description": "Images ASL — alphabet et mots",
    },
    {
        "slug": "asl-hands-npy",
        "name": "ASL Hands (MediaPipe NPY)",
        "language_code": "asl",
        "language_name": "American Sign Language",
        "dir": "asl_data_hands",
        "labels_file": None,
        "description": "Keypoints MediaPipe exportés en format NumPy",
    },
    {
        "slug": "asl-videos-wlasl",
        "name": "ASL Videos (WLASL / NSLT)",
        "language_code": "asl",
        "language_name": "American Sign Language",
        "dir": "asl_videos",
        "labels_file": None,
        "description": "Métadonnées vidéos WLASL (NSLT 100/300/1000/2000)",
    },
]

_IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}
_VID_EXTS = {".mp4", ".avi", ".mov", ".webm", ".mkv"}


def _count_dir(path: str) -> dict:
    total_classes = total_images = total_videos = total_files = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False):
                    total_classes += 1
                    try:
                        with os.scandir(entry.path) as sub:
                            for f in sub:
                                if f.is_file(follow_symlinks=False):
                                    ext = os.path.splitext(f.name)[1].lower()
                                    total_files += 1
                                    if ext in _IMG_EXTS:
                                        total_images += 1
                                    elif ext in _VID_EXTS:
                                        total_videos += 1
                    except OSError:
                        pass
                elif entry.is_file(follow_symlinks=False):
                    ext = os.path.splitext(entry.name)[1].lower()
                    total_files += 1
                    if ext in _IMG_EXTS:
                        total_images += 1
                    elif ext in _VID_EXTS:
                        total_videos += 1
    except (OSError, PermissionError):
        pass
    return {
        "total_classes": total_classes,
        "total_images": total_images,
        "total_videos": total_videos,
        "total_files": total_files,
    }


def sync_knowledge_bases(db: Session) -> List:
    from backend.database.models import KnowledgeBase

    created: List = []
    now = datetime.datetime.utcnow()

    for cfg in _KB_CONFIGS:
        root_path = os.path.join(_KB_ROOT, cfg["dir"])
        if not os.path.isdir(root_path):
            continue

        counts = _count_dir(root_path)

        labels_path = None
        if cfg.get("labels_file"):
            lp = os.path.join(_KB_ROOT, cfg["labels_file"])
            if os.path.isfile(lp):
                labels_path = lp
                if counts["total_classes"] == 0:
                    try:
                        with open(lp, encoding="utf-8") as f:
                            labels_data = json.load(f)
                        counts["total_classes"] = len(labels_data)
                    except Exception:
                        pass

        existing = db.query(KnowledgeBase).filter(KnowledgeBase.slug == cfg["slug"]).first()
        if existing:
            existing.total_classes = counts["total_classes"]
            existing.total_images = counts["total_images"]
            existing.total_videos = counts["total_videos"]
            existing.total_files = counts["total_files"]
            existing.labels_file_path = labels_path
            existing.status = "ready"
            existing.last_scanned_at = now
            existing.updated_at = now
            db.commit()
        else:
            kb = KnowledgeBase(
                name=cfg["name"],
                slug=cfg["slug"],
                language_code=cfg["language_code"],
                language_name=cfg["language_name"],
                description=cfg.get("description", ""),
                root_path=root_path,
                labels_file_path=labels_path,
                status="ready",
                total_classes=counts["total_classes"],
                total_images=counts["total_images"],
                total_videos=counts["total_videos"],
                total_files=counts["total_files"],
                last_scanned_at=now,
            )
            db.add(kb)
            db.commit()
            db.refresh(kb)
            created.append(kb)

    return created
