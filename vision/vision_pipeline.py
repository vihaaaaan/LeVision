#!/usr/bin/env python3
"""Main vision pipeline for LeVision.

The script does the following:
- Player/number detection
- SAM2 mask tracking
- Team classification
- Jersey number OCR + temporal validation
- Player identity overlay
- Court keypoint projection and map rendering
- Trajectory cleaning
- Shot event detection

The script prioritizes correctness over speed for now

TODO: Add flags for GPU architecture. Need to find solution for cloud gpu for inference
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np
import torch
from tqdm import tqdm

import supervision as sv
from inference import get_model
from sports import (
    ConsecutiveValueTracker,
    MeasurementUnit,
    TeamClassifier,
    ViewTransformer,
    clean_paths,
)
from sports.basketball import (
    CourtConfiguration,
    League,
    ShotEventTracker,
    draw_court,
    draw_made_and_miss_on_court,
    draw_paths_on_court,
    draw_points_on_court,
)

LOGGER = logging.getLogger("fresh_vision_pipeline")

# Rosters are hardcoded for now
# TODO: Script to pull rosters
TEAM_ROSTERS: Dict[str, Dict[str, str]] = {
    # "New York Knicks": {
    #     "55": "Hukporti",
    #     "1": "Payne",
    #     "0": "Wright",
    #     "11": "Brunson",
    #     "3": "Hart",
    #     "32": "Towns",
    #     "44": "Shamet",
    #     "25": "Bridges",
    #     "2": "McBride",
    #     "23": "Robinson",
    #     "8": "Anunoby",
    #     "4": "Dadiet",
    #     "5": "Achiuwa",
    #     "13": "Kolek",
    # },
    # "Boston Celtics": {
    #     "42": "Horford",
    #     "55": "Scheierman",
    #     "9": "White",
    #     "20": "Davison",
    #     "7": "Brown",
    #     "0": "Tatum",
    #     "27": "Walsh",
    #     "4": "Holiday",
    #     "8": "Porzingis",
    #     "40": "Kornet",
    #     "88": "Queta",
    #     "11": "Pritchard",
    #     "30": "Hauser",
    #     "12": "Craig",
    #     "26": "Tillman",
    # },
    "Golden State Warriors": {
        "30": "Stephen Curry", "23": "Draymond Green", "22": "Andrew Wiggins",
        "32": "Trayce Jackson-Davis", "71": "Dennis Schroder", "7": "Buddy Hield",
        "00": "Jonathan Kuminga", "5": "Kevon Looney", "2": "Brandin Podziemski",
        "0": "Gary Payton II", "1": "Kyle Anderson", "4": "Moses Moody"
    },
    "Los Angeles Lakers": {
        "23": "LeBron James", "3": "Anthony Davis", "15": "Austin Reaves",
        "28": "Rui Hachimura", "12": "Max Christie", "7": "Gabe Vincent",
        "4": "Dalton Knecht", "5": "Cam Reddish", "1": "D'Angelo Russell", "9": "Bronny James"
    }
}

# Hardcoded team info
TEAM_COLORS: Dict[str, str] = {
    # "New York Knicks": "#006BB6",
    # "Boston Celtics": "#007A33",
    "Golden State Warriors": "#1D428A",
    "Los Angeles Lakers": "#552583",
}

TEAM_NAMES: Dict[int, str] = {
    # 0: "Boston Celtics",
    # 1: "New York Knicks",
    0: "Golden State Warriors",
    1: "Los Angeles Lakers"
}

@dataclass(frozen=True)
class PipelineConfig:
    home: Path
    source_video_directory: Path
    # source_video_name: str = "boston-celtics-new-york-knicks-game-1-q1-04.28-04.20.mp4"
    # shot_video_name: str = "boston-celtics-new-york-knicks-game-1-q1-03.16-03.11.mp4"
    source_video_name: str = "lakers_warriors_christmas_trimmed.mp4"
    shot_video_name: str = "lakers_warriors_christmas_trimmed.mp4"
    output_directory: Path = Path("fresh_vision_outputs")
    fonts_directory: Path = Path("fonts")

    # Model config
    player_detection_model_id: str = "basketball-player-detection-3-ycjdo/4"
    player_detection_confidence: float = 0.4
    player_detection_iou_threshold: float = 0.9

    number_recognition_model_id: str = "basketball-jersey-numbers-ocr/3"
    number_recognition_prompt: str = "Read the number."

    keypoint_detection_model_id: str = "basketball-court-detection-2/14"
    keypoint_detection_confidence: float = 0.3
    keypoint_anchor_confidence: float = 0.5

    # SAM2
    sam2_repo_path: Path = Path("segment-anything-2-real-time")
    sam2_checkpoint: str = "sam2.1_hiera_large.pt"
    sam2_config: str = "configs/sam2.1/sam2.1_hiera_l.yaml"
    sam2_device: str = "cuda"

    # Processing
    team_crop_stride: int = 30
    number_refresh_stride: int = 5
    path_clean_jump_sigma: float = 3.5
    path_clean_min_jump_dist: float = 0.6
    path_clean_max_jump_run: int = 18
    path_clean_pad_around_runs: int = 2
    path_clean_smooth_window: int = 9
    path_clean_smooth_poly: int = 2

    # Robustness
    sam2_track_recovery_frames: int = 3
    continue_on_stage_error: bool = False

    # Optional runtime limit for debugging
    max_frames: Optional[int] = None

    @property
    def source_video_path(self) -> Path:
        return self.source_video_directory / self.source_video_name

    @property
    def shot_video_path(self) -> Path:
        return self.source_video_directory / self.shot_video_name

    @property
    def resolved_output_dir(self) -> Path:
        if self.output_directory.is_absolute():
            return self.output_directory
        return self.home / self.output_directory

    @property
    def resolved_fonts_dir(self) -> Path:
        if self.fonts_directory.is_absolute():
            return self.fonts_directory
        return self.home / self.fonts_directory

    @property
    def resolved_sam2_repo(self) -> Path:
        if self.sam2_repo_path.is_absolute():
            return self.sam2_repo_path
        return self.home / self.sam2_repo_path

    @property
    def sam2_checkpoint_path(self) -> Path:
        return self.resolved_sam2_repo / "checkpoints" / self.sam2_checkpoint

    def validate(self) -> None:
        if not self.source_video_directory.exists():
            raise FileNotFoundError(f"Source video directory not found: {self.source_video_directory}")
        if not self.source_video_path.exists():
            raise FileNotFoundError(f"Primary source video not found: {self.source_video_path}")

# Sets up logging at debug or info level based on the verbose flag.
def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s | %(levelname)s | %(message)s")

# Creates a directory and all parent directories if they don't already exist.
def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)

# Writes a dictionary as a formatted JSON file, creating parent directories as needed.
def write_json(path: Path, payload: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

# Saves an image to disk, creating parent directories as needed.
def save_image(path: Path, image: np.ndarray) -> None:
    ensure_dir(path.parent)
    ok = cv2.imwrite(str(path), image)
    if not ok:
        raise RuntimeError(f"Failed to write image: {path}")

# Re-encodes a video with ffmpeg using H.264 compression to reduce file size.
def compress_video(source: Path, target: Path, crf: int = 28) -> Path:
    if not source.exists():
        raise FileNotFoundError(f"Cannot compress missing video: {source}")

    ensure_dir(target.parent)
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        LOGGER.warning("ffmpeg not found; skipping compression for %s", source)
        return source

    cmd = [
        ffmpeg_path,
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-vcodec",
        "libx264",
        "-crf",
        str(crf),
        str(target),
    ]
    subprocess.run(cmd, check=True)
    return target

# Scans a directory and returns all video files sorted by name.
def collect_video_files(directory: Path) -> List[Path]:
    exts = {".mp4", ".avi", ".mov"}
    files = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in exts]
    return sorted(files)

# Arranges a list of images into a grid canvas with optional title text on each cell.
def build_image_grid(
    images: Sequence[np.ndarray],
    grid_size: Tuple[int, int],
    cell_size: Tuple[int, int] = (224, 224),
    titles: Optional[Sequence[str]] = None,
) -> np.ndarray:
    rows, cols = grid_size
    target_w, target_h = cell_size
    canvas = np.zeros((rows * target_h, cols * target_w, 3), dtype=np.uint8)

    max_cells = rows * cols
    for idx in range(min(len(images), max_cells)):
        image = images[idx]
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        resized = cv2.resize(image, (target_w, target_h), interpolation=cv2.INTER_AREA)

        r = idx // cols
        c = idx % cols
        y0 = r * target_h
        y1 = y0 + target_h
        x0 = c * target_w
        x1 = x0 + target_w
        canvas[y0:y1, x0:x1] = resized

        if titles is not None and idx < len(titles):
            title = str(titles[idx])
            cv2.putText(
                canvas,
                title,
                (x0 + 8, y0 + 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

    return canvas

# Returns all (row, col) positions in a matrix where the value exceeds a threshold, sorted by value.
def coords_above_threshold(
    matrix: np.ndarray,
    threshold: float,
    sort_desc: bool = True,
) -> List[Tuple[int, int]]:
    arr = np.asarray(matrix)
    rows, cols = np.where(arr > threshold)
    pairs = list(zip(rows.tolist(), cols.tolist()))
    if sort_desc:
        pairs.sort(key=lambda rc: arr[rc[0], rc[1]], reverse=True)
    return pairs

# Splits a coordinate array into separate segments wherever consecutive True values are interrupted.
def split_true_runs(mask: np.ndarray, coords: np.ndarray) -> List[np.ndarray]:
    squeezed_mask = mask.squeeze()
    idx = np.flatnonzero(squeezed_mask)
    if idx.size == 0:
        return []
    splits = np.where(np.diff(idx) > 1)[0] + 1
    groups = np.split(idx, splits)
    return [coords[g, 0, :] for g in groups]

# Returns a bfloat16 autocast context on CUDA, or a no-op context on CPU.
def get_autocast_context() -> contextlib.AbstractContextManager[Any]:
    if torch.cuda.is_available():
        return torch.autocast("cuda", dtype=torch.bfloat16)
    return contextlib.nullcontext()

# Converts a raw model inference result into a supervision Detections object.
def infer_to_detections(result: Any) -> sv.Detections:
    return sv.Detections.from_inference(result)

# Maps tracker IDs to team values from the initial seed frame, using a default for any IDs that fall out of range.
def safe_custom_lookup_from_tracker_ids(
    tracker_ids: Optional[np.ndarray],
    values_by_seed_index: np.ndarray,
    default_value: int = 0,
) -> np.ndarray:
    if tracker_ids is None:
        return np.array([], dtype=int)

    tracker_ids = np.asarray(tracker_ids, dtype=int)
    out = np.full(len(tracker_ids), default_value, dtype=int)
    valid = (tracker_ids >= 1) & (tracker_ids <= len(values_by_seed_index))
    if np.any(valid):
        out[valid] = values_by_seed_index[tracker_ids[valid] - 1]

    if np.any(~valid):
        invalid_ids = tracker_ids[~valid].tolist()
        LOGGER.warning("Tracker IDs out of initial range. Using default team for IDs: %s", invalid_ids)

    return out

# Packages raw bounding box, mask, and tracker ID arrays into a supervision Detections object.
def detections_to_basic(
    xyxy: np.ndarray,
    masks: Optional[np.ndarray],
    tracker_ids: np.ndarray,
) -> sv.Detections:
    return sv.Detections(
        xyxy=xyxy.astype(np.float32),
        mask=masks.astype(bool) if masks is not None else None,
        tracker_id=tracker_ids.astype(np.int32),
    )

class SAM2Tracker:
    """SAM2 wrapper with ID-drop resistance. We basically try to remember which player is which if we didnt detect them in the previous frame but did earlier."""

    def __init__(self, predictor: Any, max_recovery_frames: int = 3) -> None:
        self.predictor = predictor
        self.max_recovery_frames = max_recovery_frames
        self._prompted = False

        # tracker_id -> (xyxy, mask, missing_age)
        self._track_cache: Dict[int, Tuple[np.ndarray, np.ndarray, int]] = {}

    def prompt_first_frame(self, frame: np.ndarray, detections: sv.Detections) -> None:
        if len(detections) == 0:
            raise ValueError("detections must contain at least one box")

        if detections.tracker_id is None:
            detections.tracker_id = np.arange(1, len(detections) + 1, dtype=np.int32)

        with torch.inference_mode(), get_autocast_context():
            self.predictor.load_first_frame(frame)
            for xyxy, obj_id in zip(detections.xyxy, detections.tracker_id):
                bbox = np.asarray([xyxy], dtype=np.float32)
                self.predictor.add_new_prompt(frame_idx=0, obj_id=int(obj_id), bbox=bbox)

        self._prompted = True
        self._refresh_cache_from_detections(detections)

    def propagate(self, frame: np.ndarray) -> sv.Detections:
        if not self._prompted:
            raise RuntimeError("Call prompt_first_frame before propagate")

        with torch.inference_mode(), get_autocast_context():
            tracker_ids_raw, mask_logits = self.predictor.track(frame)

        tracker_ids = np.asarray(tracker_ids_raw, dtype=np.int32)
        if tracker_ids.size == 0:
            return self._recover_missing_tracks()

        masks = (mask_logits > 0.0).cpu().numpy()
        masks = np.squeeze(masks).astype(bool)

        if masks.ndim == 2:
            masks = masks[None, ...]

        if masks.shape[0] != tracker_ids.shape[0]:
            raise RuntimeError(
                f"SAM2 output mismatch: {masks.shape[0]} masks for {tracker_ids.shape[0]} tracker IDs"
            )

        filtered_masks = np.array(
            [sv.filter_segments_by_distance(mask, relative_distance=0.03, mode="edge") for mask in masks]
        )
        xyxy = sv.mask_to_xyxy(masks=filtered_masks)
        current = detections_to_basic(xyxy=xyxy, masks=filtered_masks, tracker_ids=tracker_ids)

        self._refresh_cache_from_detections(current)
        recovered = self._recover_missing_tracks(include_existing=True)
        if len(recovered) > len(current):
            return recovered
        return current

    def reset(self) -> None:
        self._prompted = False
        self._track_cache.clear()

    def _refresh_cache_from_detections(self, detections: sv.Detections) -> None:
        # age existing tracks
        aged_cache: Dict[int, Tuple[np.ndarray, np.ndarray, int]] = {}
        for track_id, (xyxy, mask, age) in self._track_cache.items():
            aged_cache[track_id] = (xyxy, mask, age + 1)

        # refresh current tracks
        if detections.tracker_id is not None and detections.mask is not None:
            for xyxy, mask, track_id in zip(detections.xyxy, detections.mask, detections.tracker_id):
                aged_cache[int(track_id)] = (xyxy.copy(), mask.copy(), 0)

        # prune stale tracks
        pruned: Dict[int, Tuple[np.ndarray, np.ndarray, int]] = {}
        for track_id, payload in aged_cache.items():
            if payload[2] <= self.max_recovery_frames:
                pruned[track_id] = payload

        self._track_cache = pruned

    def _recover_missing_tracks(self, include_existing: bool = False) -> sv.Detections:
        if not self._track_cache:
            return sv.Detections.empty()

        rows_xyxy: List[np.ndarray] = []
        rows_mask: List[np.ndarray] = []
        rows_track_id: List[int] = []

        for track_id, (xyxy, mask, age) in self._track_cache.items():
            if include_existing and age == 0:
                rows_xyxy.append(xyxy)
                rows_mask.append(mask)
                rows_track_id.append(track_id)
            elif (not include_existing) and 0 < age <= self.max_recovery_frames:
                rows_xyxy.append(xyxy)
                rows_mask.append(mask)
                rows_track_id.append(track_id)
            elif include_existing and 0 < age <= self.max_recovery_frames:
                rows_xyxy.append(xyxy)
                rows_mask.append(mask)
                rows_track_id.append(track_id)

        if not rows_track_id:
            return sv.Detections.empty()

        return detections_to_basic(
            xyxy=np.stack(rows_xyxy, axis=0),
            masks=np.stack(rows_mask, axis=0),
            tracker_ids=np.array(rows_track_id, dtype=np.int32),
        )

@dataclass
class ModelBundle:
    player_detection: Any
    number_recognition: Any
    keypoint_detection: Any

@dataclass
class PipelineState:
    artifacts: Dict[str, str] = field(default_factory=dict)
    team_classifier: Optional[TeamClassifier] = None
    seed_teams: Optional[np.ndarray] = None
    court_config: CourtConfiguration = field(
        default_factory=lambda: CourtConfiguration(league=League.NBA, measurement_unit=MeasurementUnit.FEET)
    )

class FreshVisionPipeline:
    NUMBER_CLASS_ID = 2
    PLAYER_CLASS_IDS = np.array([3, 4, 5, 6, 7], dtype=int)
    PLAYER_JUMP_SHOT_CLASS_ID = 5
    BALL_IN_BASKET_CLASS_ID = 1
    LAYUP_DUNK_CLASS_ID = 6

    def __init__(self, config: PipelineConfig, skip_sam2: bool = False) -> None:
        self.config = config
        self.skip_sam2 = skip_sam2
        self.config.validate()

        ensure_dir(self.config.resolved_output_dir)
        os.environ.setdefault("ONNXRUNTIME_EXECUTION_PROVIDERS", "[CUDAExecutionProvider]")

        self.color_palette = sv.ColorPalette.from_hex(
            [
                "#ffff00",
                "#ff9b00",
                "#ff66ff",
                "#3399ff",
                "#ff66b2",
                "#ff8080",
                "#b266ff",
                "#9999ff",
                "#66ffff",
                "#33ff99",
                "#66ff66",
                "#99ff00",
            ]
        )
        self.keypoint_color = sv.Color.from_hex("#FF1493")

        self.models = self._load_models()
        self.state = PipelineState()

    # Loads the player detection, jersey number OCR, and court keypoint models from Roboflow.
    def _load_models(self) -> ModelBundle:
        LOGGER.info("Loading models...")
        player_model = get_model(model_id=self.config.player_detection_model_id)
        number_model = get_model(model_id=self.config.number_recognition_model_id)
        keypoint_model = get_model(model_id=self.config.keypoint_detection_model_id)
        LOGGER.info("Models loaded successfully")
        return ModelBundle(
            player_detection=player_model,
            number_recognition=number_model,
            keypoint_detection=keypoint_model,
        )

    # Loads the SAM2 real-time camera predictor from the local fork, requiring a CUDA GPU.
    def _get_sam2_predictor(self) -> Any:
        if self.skip_sam2:
            raise RuntimeError("SAM2 stage requested but --skip-sam2 is enabled")
        if self.config.sam2_device != "cuda" or not torch.cuda.is_available():
            raise RuntimeError(
                "SAM2 camera predictor requires CUDA-enabled PyTorch/GPU. "
                "Use --skip-sam2 on CPU-only environments."
            )

        repo_path = self.config.resolved_sam2_repo
        if not repo_path.exists():
            raise FileNotFoundError(
                f"SAM2 repo path not found: {repo_path}. Clone the segment-anything-2-real-time repo first."
            )

        if str(repo_path) not in sys.path:
            sys.path.insert(0, str(repo_path))
        else:
            # Keep repo path first so the fork wins over any preinstalled sam2 package.
            sys.path.remove(str(repo_path))
            sys.path.insert(0, str(repo_path))

        # If sam2 was already imported from a different location, clear it and re-import.
        for module_name in list(sys.modules):
            if module_name == "sam2" or module_name.startswith("sam2."):
                del sys.modules[module_name]

        try:
            from sam2.build_sam import build_sam2_camera_predictor
        except Exception as exc:
            raise ImportError(
                "Could not import build_sam2_camera_predictor from sam2.build_sam. "
                "Use the segment-anything-2-real-time fork."
            ) from exc

        checkpoint = self.config.sam2_checkpoint_path
        if not checkpoint.exists():
            raise FileNotFoundError(
                f"SAM2 checkpoint not found: {checkpoint}. "
                "Run segment-anything-2-real-time/checkpoints/download_ckpts.sh"
            )

        LOGGER.info("Loading SAM2 camera predictor...")
        predictor = build_sam2_camera_predictor(
            self.config.sam2_config,
            str(checkpoint),
            device=self.config.sam2_device,
        )
        LOGGER.info("SAM2 predictor loaded")
        return predictor

    # Stores the path to a pipeline output file under a descriptive key for later reference.
    def _record_artifact(self, key: str, path: Path) -> None:
        self.state.artifacts[key] = str(path)

    # Runs the player detection model on a single frame and returns the resulting detections.
    def _infer_player_detections(
        self,
        frame: np.ndarray,
        class_agnostic_nms: bool = False,
    ) -> sv.Detections:
        result = self.models.player_detection.infer(
            frame,
            confidence=self.config.player_detection_confidence,
            iou_threshold=self.config.player_detection_iou_threshold,
            class_agnostic_nms=class_agnostic_nms,
        )[0]
        return infer_to_detections(result)

    # Runs the court keypoint detection model on a single frame and returns the keypoints.
    def _infer_keypoints(self, frame: np.ndarray) -> sv.KeyPoints:
        result = self.models.keypoint_detection.infer(
            frame,
            confidence=self.config.keypoint_detection_confidence,
        )[0]
        return sv.KeyPoints.from_inference(result)

    # Returns a boolean mask indicating which detected court keypoints exceed the confidence threshold.
    def _is_valid_landmark_set(self, key_points: sv.KeyPoints) -> np.ndarray:
        return key_points.confidence[0] > self.config.keypoint_anchor_confidence

    # Wraps a frame iterable so it stops after the configured max_frames limit.
    def _with_frame_limit(self, iterable: Iterable[np.ndarray]) -> Iterable[np.ndarray]:
        if self.config.max_frames is None:
            return iterable

        def _generator() -> Iterable[np.ndarray]:
            for idx, frame in enumerate(iterable):
                if idx >= self.config.max_frames:
                    break
                yield frame

        return _generator()

    # Builds a two-color palette using the configured team colors.
    def _team_palette(self) -> sv.ColorPalette:
        return sv.ColorPalette.from_hex([TEAM_COLORS[TEAM_NAMES[0]], TEAM_COLORS[TEAM_NAMES[1]]])

    # Predicts which team each detected player belongs to by running the fitted team classifier on their crops.
    def _predict_seed_teams(self, frame: np.ndarray, detections: sv.Detections) -> np.ndarray:
        if len(detections) == 0:
            raise ValueError("Cannot predict teams with zero detections")
        if self.state.team_classifier is None:
            raise RuntimeError("Team classifier has not been fitted")

        boxes = sv.scale_boxes(xyxy=detections.xyxy, factor=0.4)
        crops = [sv.crop_image(frame, box) for box in boxes]
        teams = np.asarray(self.state.team_classifier.predict(crops), dtype=int)
        return teams

    # Runs OCR on a single player crop and returns the detected jersey number as a string.
    def _recognize_single_number(self, crop: np.ndarray) -> str:
        prediction = self.models.number_recognition.infer(
            crop,
            prompt=self.config.number_recognition_prompt,
        )
        if isinstance(prediction, list) and prediction:
            first = prediction[0]
            if hasattr(first, "response"):
                return str(first.response)
            return str(first)
        return str(prediction)

    # Runs OCR on all number detection crops in a frame and returns the recognized strings.
    def _recognize_numbers(self, frame: np.ndarray, number_detections: sv.Detections) -> List[str]:
        frame_h, frame_w = frame.shape[:2]
        boxes = sv.clip_boxes(
            sv.pad_boxes(xyxy=number_detections.xyxy, px=10, py=10),
            (frame_w, frame_h),
        )
        crops = [sv.crop_image(frame, xyxy) for xyxy in boxes]

        numbers: List[str] = []
        for crop in crops:
            try:
                numbers.append(self._recognize_single_number(crop))
            except Exception as exc:
                LOGGER.warning("Number OCR failed on crop: %s", exc)
                numbers.append("")

        return numbers

    # Builds display labels combining jersey number and player name for each detected player.
    def _build_labels(self, numbers: Sequence[Optional[str]], teams: Sequence[Optional[int]]) -> List[str]:
        labels: List[str] = []
        for number_raw, team_raw in zip(numbers, teams):
            number = "" if number_raw is None else str(number_raw)
            if team_raw is None:
                labels.append(f"#{number}".strip())
                continue

            team = int(team_raw)
            team_name = TEAM_NAMES.get(team)
            if team_name is None:
                labels.append(f"#{number}")
                continue

            player_name = TEAM_ROSTERS[team_name].get(number)
            if player_name is None:
                labels.append(f"#{number}")
            else:
                labels.append(f"#{number} {player_name}")
        return labels

    # Processes a video frame-by-frame through a callback and writes the result to disk, respecting the max_frames limit.
    def _process_video(
        self,
        source_path: Path,
        target_path: Path,
        callback: Any,
    ) -> None:
        ensure_dir(target_path.parent)
        if self.config.max_frames is None:
            sv.process_video(
                source_path=source_path,
                target_path=target_path,
                callback=callback,
                show_progress=True,
            )
            return

        video_info = sv.VideoInfo.from_video_path(source_path)
        video_info.total_frames = min(video_info.total_frames, self.config.max_frames)
        frame_generator = sv.get_video_frames_generator(source_path)
        with sv.VideoSink(target_path, video_info) as sink:
            for index, frame in tqdm(
                enumerate(frame_generator),
                total=video_info.total_frames,
                desc=f"Processing video ({target_path.name})",
            ):
                if index >= self.config.max_frames:
                    break
                sink.write_frame(callback(frame, index))

    # Detects players on the first frame, seeds the SAM2 tracker with their bounding boxes, and returns the tracker and seed state.
    def _seed_tracker_on_first_frame(self, predictor: Any) -> Tuple[SAM2Tracker, np.ndarray, sv.Detections]:
        frame_generator = sv.get_video_frames_generator(self.config.source_video_path)
        first_frame = next(frame_generator)

        detections = self._infer_player_detections(first_frame)
        detections = detections[np.isin(detections.class_id, self.PLAYER_CLASS_IDS)]
        detections.tracker_id = np.arange(1, len(detections.class_id) + 1, dtype=np.int32)

        tracker = SAM2Tracker(predictor, max_recovery_frames=self.config.sam2_track_recovery_frames)
        tracker.prompt_first_frame(first_frame, detections)

        return tracker, first_frame, detections

    # Saves annotated preview images showing all detections, number-only detections, and player-only detections on the first frame.
    def preview_detections(self) -> None:
        source = self.config.source_video_path
        frame = next(sv.get_video_frames_generator(source))

        box_annotator = sv.BoxAnnotator(color=self.color_palette, thickness=2)
        label_annotator = sv.LabelAnnotator(color=self.color_palette, text_color=sv.Color.BLACK)

        all_detections = self._infer_player_detections(frame)
        all_img = label_annotator.annotate(
            scene=box_annotator.annotate(scene=frame.copy(), detections=all_detections),
            detections=all_detections,
        )
        all_path = self.config.resolved_output_dir / "all_detections_preview.jpg"
        save_image(all_path, all_img)
        self._record_artifact("all_detections_preview", all_path)

        number_detections = all_detections[all_detections.class_id == self.NUMBER_CLASS_ID]
        number_img = label_annotator.annotate(
            scene=box_annotator.annotate(scene=frame.copy(), detections=number_detections),
            detections=number_detections,
        )
        number_path = self.config.resolved_output_dir / "number_detections_preview.jpg"
        save_image(number_path, number_img)
        self._record_artifact("number_detections_preview", number_path)

        player_detections = all_detections[np.isin(all_detections.class_id, self.PLAYER_CLASS_IDS)]
        player_img = label_annotator.annotate(
            scene=box_annotator.annotate(scene=frame.copy(), detections=player_detections),
            detections=player_detections,
        )
        player_path = self.config.resolved_output_dir / "player_detections_preview.jpg"
        save_image(player_path, player_img)
        self._record_artifact("player_detections_preview", player_path)

    # Produces a full annotated detection video and a compressed copy showing all detected classes.
    def render_detection_video(self) -> None:
        source = self.config.source_video_path
        raw_video = self.config.resolved_output_dir / f"{source.stem}-detection{source.suffix}"
        compressed_video = self.config.resolved_output_dir / f"{source.stem}-detection-compressed{source.suffix}"

        box_annotator = sv.BoxAnnotator(color=self.color_palette, thickness=2)
        label_annotator = sv.LabelAnnotator(color=self.color_palette, text_color=sv.Color.BLACK)

        def callback(frame: np.ndarray, index: int) -> np.ndarray:
            detections = self._infer_player_detections(frame)
            annotated = box_annotator.annotate(scene=frame.copy(), detections=detections)
            annotated = label_annotator.annotate(scene=annotated, detections=detections)
            return annotated

        self._process_video(source, raw_video, callback)
        compressed = compress_video(raw_video, compressed_video)
        self._record_artifact("detection_video_raw", raw_video)
        self._record_artifact("detection_video_compressed", compressed)

    # Runs SAM2 mask tracking across the full video and saves a mask-overlay video with per-player color coding.
    def render_mask_video(self, predictor: Any) -> None:
        source = self.config.source_video_path
        raw_video = self.config.resolved_output_dir / f"{source.stem}-mask{source.suffix}"
        compressed_video = self.config.resolved_output_dir / f"{source.stem}-mask-compressed{source.suffix}"

        tracker, first_frame, seed_detections = self._seed_tracker_on_first_frame(predictor)

        init_box_annotator = sv.BoxAnnotator(
            color=self.color_palette,
            color_lookup=sv.ColorLookup.TRACK,
            thickness=2,
        )
        seed_img = init_box_annotator.annotate(scene=first_frame.copy(), detections=seed_detections)
        seed_path = self.config.resolved_output_dir / "mask_seed_prompt_boxes.jpg"
        save_image(seed_path, seed_img)
        self._record_artifact("mask_seed_prompt_boxes", seed_path)

        mask_annotator = sv.MaskAnnotator(
            color=self.color_palette,
            color_lookup=sv.ColorLookup.TRACK,
            opacity=0.5,
        )
        box_annotator = sv.BoxAnnotator(
            color=self.color_palette,
            color_lookup=sv.ColorLookup.TRACK,
            thickness=2,
        )

        def callback(frame: np.ndarray, index: int) -> np.ndarray:
            detections = tracker.propagate(frame)
            annotated = mask_annotator.annotate(scene=frame.copy(), detections=detections)
            annotated = box_annotator.annotate(scene=annotated, detections=detections)
            return annotated

        self._process_video(source, raw_video, callback)
        compressed = compress_video(raw_video, compressed_video)
        self._record_artifact("mask_video_raw", raw_video)
        self._record_artifact("mask_video_compressed", compressed)

    # Collects player crops from all source videos and trains the team classifier, saving crop grids for both teams.
    def fit_team_classifier(self) -> None:
        source_videos = collect_video_files(self.config.source_video_directory)
        if not source_videos:
            raise RuntimeError(f"No videos found in {self.config.source_video_directory}")

        crops: List[np.ndarray] = []
        for video_path in source_videos:
            frame_generator = sv.get_video_frames_generator(source_path=video_path, stride=self.config.team_crop_stride)
            for frame in tqdm(self._with_frame_limit(frame_generator), desc=f"Team crops: {video_path.name}"):
                detections = self._infer_player_detections(frame, class_agnostic_nms=True)
                detections = detections[np.isin(detections.class_id, self.PLAYER_CLASS_IDS)]
                boxes = sv.scale_boxes(xyxy=detections.xyxy, factor=0.4)
                for box in boxes:
                    crops.append(sv.crop_image(frame, box))

        if not crops:
            raise RuntimeError("No crops were collected for team classifier fitting")

        crop_grid = build_image_grid(crops[:100], grid_size=(10, 10), cell_size=(96, 96))
        crop_grid_path = self.config.resolved_output_dir / "team_training_crops_grid.jpg"
        save_image(crop_grid_path, crop_grid)
        self._record_artifact("team_training_crops_grid", crop_grid_path)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        classifier = TeamClassifier(device=device)
        classifier.fit(crops)
        self.state.team_classifier = classifier

        teams = np.asarray(classifier.predict(crops), dtype=int)
        team_0 = [crop for crop, team in zip(crops, teams) if team == 0]
        team_1 = [crop for crop, team in zip(crops, teams) if team == 1]

        team0_grid = build_image_grid(team_0[:50], grid_size=(5, 10), cell_size=(96, 96))
        team1_grid = build_image_grid(team_1[:50], grid_size=(5, 10), cell_size=(96, 96))

        team0_path = self.config.resolved_output_dir / "team0_grid.jpg"
        team1_path = self.config.resolved_output_dir / "team1_grid.jpg"
        save_image(team0_path, team0_grid)
        save_image(team1_path, team1_grid)
        self._record_artifact("team0_grid", team0_path)
        self._record_artifact("team1_grid", team1_path)

    # Saves a quick preview image strip of the top player crops classified into each team.
    def preview_team_classifications(self) -> None:
        if self.state.team_classifier is None:
            raise RuntimeError("Team classifier not fitted yet")

        frame = next(sv.get_video_frames_generator(self.config.source_video_path))
        detections = self._infer_player_detections(frame, class_agnostic_nms=True)
        detections = detections[np.isin(detections.class_id, self.PLAYER_CLASS_IDS)]

        boxes = sv.scale_boxes(xyxy=detections.xyxy, factor=0.4)
        crops = [sv.crop_image(frame, box) for box in boxes]
        teams = np.asarray(self.state.team_classifier.predict(crops), dtype=int)

        team_0 = [crop for crop, team in zip(crops, teams) if team == 0]
        team_1 = [crop for crop, team in zip(crops, teams) if team == 1]

        team0_preview = build_image_grid(team_0[:10], grid_size=(1, 10), cell_size=(160, 160))
        team1_preview = build_image_grid(team_1[:10], grid_size=(1, 10), cell_size=(160, 160))

        team0_path = self.config.resolved_output_dir / "team0_preview.jpg"
        team1_path = self.config.resolved_output_dir / "team1_preview.jpg"
        save_image(team0_path, team0_preview)
        save_image(team1_path, team1_preview)
        self._record_artifact("team0_preview", team0_path)
        self._record_artifact("team1_preview", team1_path)

    # Produces a full video with player masks colored by team assignment using SAM2 tracking.
    def render_team_video(self, predictor: Any) -> None:
        if self.state.team_classifier is None:
            raise RuntimeError("Team classifier not fitted yet")

        source = self.config.source_video_path
        raw_video = self.config.resolved_output_dir / f"{source.stem}-teams{source.suffix}"
        compressed_video = self.config.resolved_output_dir / f"{source.stem}-teams-compressed{source.suffix}"

        tracker, first_frame, seed_detections = self._seed_tracker_on_first_frame(predictor)
        seed_teams = self._predict_seed_teams(first_frame, seed_detections)
        self.state.seed_teams = seed_teams

        team_colors = self._team_palette()
        team_mask_annotator = sv.MaskAnnotator(
            color=team_colors,
            opacity=0.5,
            color_lookup=sv.ColorLookup.INDEX,
        )
        team_box_annotator = sv.BoxAnnotator(
            color=team_colors,
            thickness=2,
            color_lookup=sv.ColorLookup.INDEX,
        )

        def callback(frame: np.ndarray, index: int) -> np.ndarray:
            detections = tracker.propagate(frame)
            lookup = safe_custom_lookup_from_tracker_ids(
                tracker_ids=detections.tracker_id,
                values_by_seed_index=seed_teams,
                default_value=0,
            )
            annotated = team_mask_annotator.annotate(
                scene=frame.copy(),
                detections=detections,
                custom_color_lookup=lookup,
            )
            annotated = team_box_annotator.annotate(
                scene=annotated,
                detections=detections,
                custom_color_lookup=lookup,
            )
            return annotated

        self._process_video(source, raw_video, callback)
        compressed = compress_video(raw_video, compressed_video)
        self._record_artifact("team_video_raw", raw_video)
        self._record_artifact("team_video_compressed", compressed)

    # Saves a preview image of jersey number bounding boxes and a grid of the cropped numbers with their OCR results.
    def preview_number_detection(self) -> None:
        frame = next(sv.get_video_frames_generator(self.config.source_video_path))
        frame_h, frame_w = frame.shape[:2]

        detections = self._infer_player_detections(frame)
        detections = detections[detections.class_id == self.NUMBER_CLASS_ID]

        box_annotator = sv.BoxAnnotator(color=self.color_palette, thickness=2)
        label_annotator = sv.LabelAnnotator(color=self.color_palette, text_color=sv.Color.BLACK)

        annotated = box_annotator.annotate(scene=frame.copy(), detections=detections)
        annotated = label_annotator.annotate(scene=annotated, detections=detections)
        det_path = self.config.resolved_output_dir / "number_boxes_preview.jpg"
        save_image(det_path, annotated)
        self._record_artifact("number_boxes_preview", det_path)

        crops = [
            sv.resize_image(sv.crop_image(frame, xyxy), resolution_wh=(224, 224))
            for xyxy in sv.clip_boxes(sv.pad_boxes(xyxy=detections.xyxy, px=10, py=10), (frame_w, frame_h))
        ]
        numbers = [self._recognize_single_number(crop) for crop in crops]

        grid = build_image_grid(crops[:10], grid_size=(1, 10), cell_size=(224, 224), titles=numbers[:10])
        grid_path = self.config.resolved_output_dir / "number_crops_ocr_preview.jpg"
        save_image(grid_path, grid)
        self._record_artifact("number_crops_ocr_preview", grid_path)

    # Detects jersey numbers and converts their bounding boxes to full-frame masks for IoU matching.
    def _detect_numbers_with_masks(self, frame: np.ndarray) -> sv.Detections:
        frame_h, frame_w = frame.shape[:2]
        number_detections = self._infer_player_detections(frame)
        number_detections = number_detections[number_detections.class_id == self.NUMBER_CLASS_ID]
        number_detections.mask = sv.xyxy_to_mask(boxes=number_detections.xyxy, resolution_wh=(frame_w, frame_h))
        return number_detections

    # Saves debug images showing all player and number masks overlaid, and which number boxes matched which players.
    def debug_number_player_matching(self, predictor: Any) -> None:
        frame_generator = sv.get_video_frames_generator(self.config.source_video_path)
        prompt_frame = next(frame_generator)

        detections = self._infer_player_detections(prompt_frame)
        detections = detections[np.isin(detections.class_id, self.PLAYER_CLASS_IDS)]
        detections.tracker_id = np.arange(1, len(detections.class_id) + 1, dtype=np.int32)

        tracker = SAM2Tracker(predictor, max_recovery_frames=self.config.sam2_track_recovery_frames)
        tracker.prompt_first_frame(prompt_frame, detections)

        box_annotator = sv.BoxAnnotator(color=self.color_palette, thickness=4, color_lookup=sv.ColorLookup.TRACK)
        player_mask_annotator = sv.MaskAnnotator(color=self.color_palette.by_idx(3), opacity=0.8, color_lookup=sv.ColorLookup.INDEX)
        number_mask_annotator = sv.MaskAnnotator(color=self.color_palette.by_idx(0), opacity=0.8, color_lookup=sv.ColorLookup.INDEX)

        for index, frame in enumerate(frame_generator):
            if index > 0:
                break

            player_detections = tracker.propagate(frame)
            number_detections = self._detect_numbers_with_masks(frame)

            if len(player_detections) == 0 or len(number_detections) == 0:
                LOGGER.warning("No detections available for number-player matching debug")
                break

            iou = sv.mask_iou_batch(
                masks_true=player_detections.mask,
                masks_detection=number_detections.mask,
                overlap_metric=sv.OverlapMetric.IOS,
            )
            pairs = coords_above_threshold(iou, 0.9)

            all_mask_img = frame.copy()
            all_mask_img = player_mask_annotator.annotate(scene=all_mask_img, detections=player_detections)
            all_mask_img = number_mask_annotator.annotate(scene=all_mask_img, detections=number_detections)
            all_mask_path = self.config.resolved_output_dir / "number_player_masks_debug.jpg"
            save_image(all_mask_path, all_mask_img)
            self._record_artifact("number_player_masks_debug", all_mask_path)

            if not pairs:
                LOGGER.warning("No IoS pairs above threshold for number-player matching debug")
                break

            player_idx, number_idx = zip(*pairs)
            matched_players = player_detections[np.asarray(player_idx, dtype=int)]
            matched_numbers = number_detections[np.asarray(number_idx, dtype=int)]
            matched_numbers.tracker_id = matched_players.tracker_id

            matched_img = frame.copy()
            matched_img = box_annotator.annotate(scene=matched_img, detections=matched_players)
            matched_img = box_annotator.annotate(scene=matched_img, detections=matched_numbers)
            matched_path = self.config.resolved_output_dir / "number_player_matched_boxes_debug.jpg"
            save_image(matched_path, matched_img)
            self._record_artifact("number_player_matched_boxes_debug", matched_path)
            break

    # Produces a video with player masks and temporally-validated jersey number labels overlaid.
    def render_validated_numbers_video(self, predictor: Any) -> None:
        source = self.config.source_video_path
        raw_video = self.config.resolved_output_dir / f"{source.stem}-validated-numbers{source.suffix}"
        compressed_video = self.config.resolved_output_dir / f"{source.stem}-validated-numbers-compressed{source.suffix}"

        number_validator = ConsecutiveValueTracker(n_consecutive=3)

        tracker, _, _ = self._seed_tracker_on_first_frame(predictor)

        mask_annotator = sv.MaskAnnotator(
            color=self.color_palette,
            color_lookup=sv.ColorLookup.TRACK,
            opacity=0.7,
        )
        box_annotator = sv.BoxAnnotator(
            color=self.color_palette,
            color_lookup=sv.ColorLookup.TRACK,
            thickness=2,
        )
        label_annotator = sv.LabelAnnotator(
            color=self.color_palette,
            color_lookup=sv.ColorLookup.TRACK,
            text_color=sv.Color.BLACK,
            text_scale=0.8,
        )

        def callback(frame: np.ndarray, index: int) -> np.ndarray:
            player_detections = tracker.propagate(frame)

            if index % self.config.number_refresh_stride == 0 and len(player_detections) > 0:
                number_detections = self._detect_numbers_with_masks(frame)
                if len(number_detections) > 0:
                    numbers = self._recognize_numbers(frame, number_detections)
                    iou = sv.mask_iou_batch(
                        masks_true=player_detections.mask,
                        masks_detection=number_detections.mask,
                        overlap_metric=sv.OverlapMetric.IOS,
                    )
                    pairs = coords_above_threshold(iou, 0.9)
                    if pairs:
                        player_idx, number_idx = zip(*pairs)
                        player_ids = [int(player_detections.tracker_id[int(i)]) for i in player_idx]
                        matched_numbers = [numbers[int(i)] for i in number_idx]
                        number_validator.update(tracker_ids=player_ids, values=matched_numbers)

            annotated = mask_annotator.annotate(scene=frame.copy(), detections=player_detections)
            annotated = box_annotator.annotate(scene=annotated, detections=player_detections)
            labels = number_validator.get_validated(tracker_ids=player_detections.tracker_id)
            annotated = label_annotator.annotate(scene=annotated, detections=player_detections, labels=labels)
            return annotated

        self._process_video(source, raw_video, callback)
        compressed = compress_video(raw_video, compressed_video)
        self._record_artifact("validated_numbers_video_raw", raw_video)
        self._record_artifact("validated_numbers_video_compressed", compressed)

    # Tracks all players with SAM2, validates jersey numbers and team assignments, then renders the final identification video with player names and team colors.
    def render_player_identification_video(self, predictor: Any) -> None:
        if self.state.team_classifier is None:
            raise RuntimeError("Team classifier not fitted yet")

        source = self.config.source_video_path
        raw_video = self.config.resolved_output_dir / f"{source.stem}-result{source.suffix}"
        compressed_video = self.config.resolved_output_dir / f"{source.stem}-result-compressed{source.suffix}"

        frames_history: List[np.ndarray] = []
        detections_history: List[sv.Detections] = []

        number_validator = ConsecutiveValueTracker(n_consecutive=3)
        team_validator = ConsecutiveValueTracker(n_consecutive=1)

        prompt_generator = sv.get_video_frames_generator(source)
        prompt_frame = next(prompt_generator)

        seed_detections = self._infer_player_detections(prompt_frame)
        seed_detections = seed_detections[np.isin(seed_detections.class_id, self.PLAYER_CLASS_IDS)]
        seed_detections.tracker_id = np.arange(1, len(seed_detections.class_id) + 1, dtype=np.int32)

        seed_teams = self._predict_seed_teams(prompt_frame, seed_detections)
        team_validator.update(tracker_ids=seed_detections.tracker_id.tolist(), values=seed_teams.tolist())
        self.state.seed_teams = seed_teams

        tracker = SAM2Tracker(predictor, max_recovery_frames=self.config.sam2_track_recovery_frames)
        tracker.prompt_first_frame(prompt_frame, seed_detections)

        frame_generator = sv.get_video_frames_generator(source)
        iterable = self._with_frame_limit(frame_generator)

        for index, frame in enumerate(tqdm(iterable, desc="Tracking + validators")):
            player_detections = tracker.propagate(frame)
            frames_history.append(frame)
            detections_history.append(player_detections)

            if index % self.config.number_refresh_stride == 0 and len(player_detections) > 0:
                number_detections = self._detect_numbers_with_masks(frame)
                if len(number_detections) == 0:
                    continue

                numbers = self._recognize_numbers(frame, number_detections)
                iou = sv.mask_iou_batch(
                    masks_true=player_detections.mask,
                    masks_detection=number_detections.mask,
                    overlap_metric=sv.OverlapMetric.IOS,
                )
                pairs = coords_above_threshold(iou, 0.9)
                if not pairs:
                    continue

                player_idx, number_idx = zip(*pairs)
                player_ids = [int(player_detections.tracker_id[int(i)]) for i in player_idx]
                matched_numbers = [numbers[int(i)] for i in number_idx]
                number_validator.update(tracker_ids=player_ids, values=matched_numbers)

        if not frames_history:
            raise RuntimeError("No frames were processed for final identification video")

        video_info = sv.VideoInfo.from_video_path(source)
        if self.config.max_frames is not None:
            video_info.total_frames = min(video_info.total_frames, self.config.max_frames)

        team_colors = self._team_palette()
        team_mask_annotator = sv.MaskAnnotator(
            color=team_colors,
            opacity=0.5,
            color_lookup=sv.ColorLookup.INDEX,
        )

        font_path = self.config.resolved_fonts_dir / "Staatliches-Regular.ttf"
        if font_path.exists():
            team_label_annotator: Any = sv.RichLabelAnnotator(
                font_path=str(font_path),
                font_size=40,
                color=team_colors,
                text_color=sv.Color.WHITE,
                text_position=sv.Position.BOTTOM_CENTER,
                text_offset=(0, 10),
                color_lookup=sv.ColorLookup.INDEX,
            )
        else:
            LOGGER.warning("Rich label font missing (%s); using fallback LabelAnnotator", font_path)
            team_label_annotator = sv.LabelAnnotator(
                color=team_colors,
                text_color=sv.Color.WHITE,
                color_lookup=sv.ColorLookup.INDEX,
            )

        with sv.VideoSink(raw_video, video_info) as sink:
            for frame, detections in tqdm(
                zip(frames_history, detections_history),
                total=len(frames_history),
                desc="Rendering identified players",
            ):
                detections = detections[detections.area > 100]

                teams_validated = team_validator.get_validated(tracker_ids=detections.tracker_id)
                teams_list = [int(t) if t is not None else 0 for t in teams_validated]
                teams = np.asarray(teams_list, dtype=int)

                numbers_validated = number_validator.get_validated(tracker_ids=detections.tracker_id)
                labels = self._build_labels(numbers=numbers_validated, teams=teams_list)

                annotated = team_mask_annotator.annotate(
                    scene=frame.copy(),
                    detections=detections,
                    custom_color_lookup=teams,
                )
                annotated = team_label_annotator.annotate(
                    scene=annotated,
                    detections=detections,
                    labels=labels,
                    custom_color_lookup=teams,
                )
                sink.write_frame(annotated)

        compressed = compress_video(raw_video, compressed_video)
        self._record_artifact("player_identification_video_raw", raw_video)
        self._record_artifact("player_identification_video_compressed", compressed)

    # Saves preview images showing all detected court keypoints and then only the high-confidence ones.
    def preview_court_keypoints(self) -> None:
        frame = next(sv.get_video_frames_generator(self.config.source_video_path))
        vertex_annotator = sv.VertexAnnotator(color=self.keypoint_color, radius=8)

        key_points_all = self._infer_keypoints(frame)
        all_img = vertex_annotator.annotate(scene=frame.copy(), key_points=key_points_all)
        all_path = self.config.resolved_output_dir / "court_keypoints_all.jpg"
        save_image(all_path, all_img)
        self._record_artifact("court_keypoints_all", all_path)

        key_points_filtered = key_points_all[:, key_points_all.confidence[0] > self.config.keypoint_anchor_confidence]
        filtered_img = vertex_annotator.annotate(scene=frame.copy(), key_points=key_points_filtered)
        filtered_path = self.config.resolved_output_dir / "court_keypoints_filtered.jpg"
        save_image(filtered_path, filtered_img)
        self._record_artifact("court_keypoints_filtered", filtered_path)

    # Projects player positions from a single frame onto a top-down court diagram and saves the result.
    def preview_court_projection(self) -> None:
        if self.state.team_classifier is None:
            raise RuntimeError("Team classifier not fitted yet")

        frame = next(sv.get_video_frames_generator(self.config.source_video_path))

        team_colors = self._team_palette()
        team_box_annotator = sv.BoxAnnotator(
            color=team_colors,
            thickness=2,
            color_lookup=sv.ColorLookup.INDEX,
        )

        detections = self._infer_player_detections(frame)
        detections = detections[np.isin(detections.class_id, self.PLAYER_CLASS_IDS)]
        detections.tracker_id = np.arange(1, len(detections.class_id) + 1, dtype=np.int32)

        teams = self._predict_seed_teams(frame, detections)
        self.state.seed_teams = teams

        team_img = team_box_annotator.annotate(
            scene=frame.copy(),
            detections=detections,
            custom_color_lookup=safe_custom_lookup_from_tracker_ids(detections.tracker_id, teams),
        )
        team_img_path = self.config.resolved_output_dir / "single_frame_team_boxes.jpg"
        save_image(team_img_path, team_img)
        self._record_artifact("single_frame_team_boxes", team_img_path)

        key_points = self._infer_keypoints(frame)
        landmarks_mask = self._is_valid_landmark_set(key_points)
        if np.count_nonzero(landmarks_mask) < 4:
            raise RuntimeError("Not enough high-confidence court landmarks for homography")

        court_landmarks = np.asarray(self.state.court_config.vertices)[landmarks_mask]
        frame_landmarks = key_points[:, landmarks_mask].xy[0]
        transformer = ViewTransformer(source=frame_landmarks, target=court_landmarks)

        frame_xy = detections.get_anchors_coordinates(anchor=sv.Position.BOTTOM_CENTER)
        if len(frame_xy) == 0:
            raise RuntimeError("No player anchors found for court projection")

        court_xy = transformer.transform_points(points=frame_xy)

        court = draw_court(config=self.state.court_config)
        court = draw_points_on_court(
            config=self.state.court_config,
            xy=court_xy[teams == 0],
            fill_color=sv.Color.from_hex(TEAM_COLORS[TEAM_NAMES[0]]),
            court=court,
        )
        court = draw_points_on_court(
            config=self.state.court_config,
            xy=court_xy[teams == 1],
            fill_color=sv.Color.from_hex(TEAM_COLORS[TEAM_NAMES[1]]),
            court=court,
        )

        court_path = self.config.resolved_output_dir / "single_frame_court_projection.jpg"
        save_image(court_path, court)
        self._record_artifact("single_frame_court_projection", court_path)

    # Transforms player positions frame-by-frame to court coordinates, renders raw and cleaned map videos, and saves path comparison previews and coordinate arrays.
    def render_court_map_pipeline(self, predictor: Any) -> None:
        if self.state.team_classifier is None:
            raise RuntimeError("Team classifier not fitted yet")

        source = self.config.source_video_path
        tracker, first_frame, seed_detections = self._seed_tracker_on_first_frame(predictor)
        teams = self._predict_seed_teams(first_frame, seed_detections)
        self.state.seed_teams = teams

        video_xy: List[np.ndarray] = []

        frame_generator = sv.get_video_frames_generator(source)
        _ = next(frame_generator)  # skip first frame; tracker was already seeded on it

        for frame_idx, frame in enumerate(tqdm(self._with_frame_limit(frame_generator), desc="Court coordinate transform")):
            detections = tracker.propagate(frame)

            key_points = self._infer_keypoints(frame)
            landmarks_mask = self._is_valid_landmark_set(key_points)
            if np.count_nonzero(landmarks_mask) < 4:
                continue

            court_landmarks = np.asarray(self.state.court_config.vertices)[landmarks_mask]
            frame_landmarks = key_points[:, landmarks_mask].xy[0]
            transformer = ViewTransformer(source=frame_landmarks, target=court_landmarks)

            frame_xy = detections.get_anchors_coordinates(anchor=sv.Position.BOTTOM_CENTER)
            if len(frame_xy) == 0:
                continue

            court_xy = transformer.transform_points(points=frame_xy)
            video_xy.append(court_xy)

        if not video_xy:
            raise RuntimeError("No transformed court coordinates were produced")

        video_xy_np = np.asarray(video_xy)

        raw_map_video = self.config.resolved_output_dir / f"{source.stem}-map-raw{source.suffix}"
        raw_map_compressed = self.config.resolved_output_dir / f"{source.stem}-map-raw-compressed{source.suffix}"

        court = draw_court(config=self.state.court_config)
        court_h, court_w, _ = court.shape
        map_info = sv.VideoInfo.from_video_path(source)
        map_info.width = court_w
        map_info.height = court_h
        map_info.total_frames = len(video_xy_np)

        with sv.VideoSink(raw_map_video, map_info) as sink:
            for frame_xy in tqdm(video_xy_np, desc="Rendering raw map"):
                canvas = draw_court(config=self.state.court_config)
                team_mask = teams[: len(frame_xy)] if len(frame_xy) <= len(teams) else np.pad(
                    teams,
                    (0, len(frame_xy) - len(teams)),
                    mode="edge",
                )
                canvas = draw_points_on_court(
                    config=self.state.court_config,
                    xy=frame_xy[team_mask == 0],
                    fill_color=sv.Color.from_hex(TEAM_COLORS[TEAM_NAMES[0]]),
                    court=canvas,
                )
                canvas = draw_points_on_court(
                    config=self.state.court_config,
                    xy=frame_xy[team_mask == 1],
                    fill_color=sv.Color.from_hex(TEAM_COLORS[TEAM_NAMES[1]]),
                    court=canvas,
                )
                sink.write_frame(canvas)

        raw_map_compressed_path = compress_video(raw_map_video, raw_map_compressed)
        self._record_artifact("court_map_video_raw", raw_map_video)
        self._record_artifact("court_map_video_compressed", raw_map_compressed_path)

        raw_path_img = draw_paths_on_court(config=self.state.court_config, paths=[video_xy_np[:, 0, :]])
        raw_path_path = self.config.resolved_output_dir / "player_raw_path_preview.jpg"
        save_image(raw_path_path, raw_path_img)
        self._record_artifact("player_raw_path_preview", raw_path_path)

        cleaned_xy, edited_mask = clean_paths(
            video_xy_np,
            jump_sigma=self.config.path_clean_jump_sigma,
            min_jump_dist=self.config.path_clean_min_jump_dist,
            max_jump_run=self.config.path_clean_max_jump_run,
            pad_around_runs=self.config.path_clean_pad_around_runs,
            smooth_window=self.config.path_clean_smooth_window,
            smooth_poly=self.config.path_clean_smooth_poly,
        )

        path_compare = draw_paths_on_court(
            config=self.state.court_config,
            paths=[video_xy_np[:, 0, :]],
            color=sv.Color.GREEN,
        )
        path_compare = draw_paths_on_court(
            config=self.state.court_config,
            paths=split_true_runs(edited_mask[:, 0], video_xy_np),
            color=sv.Color.RED,
            court=path_compare,
        )
        path_compare_path = self.config.resolved_output_dir / "path_clean_comparison.jpg"
        save_image(path_compare_path, path_compare)
        self._record_artifact("path_clean_comparison", path_compare_path)

        cleaned_path_img = draw_paths_on_court(config=self.state.court_config, paths=[cleaned_xy[:, 0, :]])
        cleaned_path_path = self.config.resolved_output_dir / "player_cleaned_path_preview.jpg"
        save_image(cleaned_path_path, cleaned_path_img)
        self._record_artifact("player_cleaned_path_preview", cleaned_path_path)

        cleaned_map_video = self.config.resolved_output_dir / f"{source.stem}-map-cleaned{source.suffix}"
        cleaned_map_compressed = self.config.resolved_output_dir / f"{source.stem}-map-cleaned-compressed{source.suffix}"

        map_info.total_frames = len(cleaned_xy)
        with sv.VideoSink(cleaned_map_video, map_info) as sink:
            for frame_xy in tqdm(cleaned_xy, desc="Rendering cleaned map"):
                canvas = draw_court(config=self.state.court_config)
                team_mask = teams[: len(frame_xy)] if len(frame_xy) <= len(teams) else np.pad(
                    teams,
                    (0, len(frame_xy) - len(teams)),
                    mode="edge",
                )
                canvas = draw_points_on_court(
                    config=self.state.court_config,
                    xy=frame_xy[team_mask == 0],
                    fill_color=sv.Color.from_hex(TEAM_COLORS[TEAM_NAMES[0]]),
                    court=canvas,
                )
                canvas = draw_points_on_court(
                    config=self.state.court_config,
                    xy=frame_xy[team_mask == 1],
                    fill_color=sv.Color.from_hex(TEAM_COLORS[TEAM_NAMES[1]]),
                    court=canvas,
                )
                sink.write_frame(canvas)

        cleaned_map_compressed_path = compress_video(cleaned_map_video, cleaned_map_compressed)
        self._record_artifact("court_map_cleaned_video_raw", cleaned_map_video)
        self._record_artifact("court_map_cleaned_video_compressed", cleaned_map_compressed_path)

        np.save(self.config.resolved_output_dir / "court_coordinates_raw.npy", video_xy_np)
        np.save(self.config.resolved_output_dir / "court_coordinates_cleaned.npy", cleaned_xy)
        np.save(self.config.resolved_output_dir / "court_coordinates_edit_mask.npy", edited_mask)
        self._record_artifact("court_coordinates_raw", self.config.resolved_output_dir / "court_coordinates_raw.npy")
        self._record_artifact("court_coordinates_cleaned", self.config.resolved_output_dir / "court_coordinates_cleaned.npy")
        self._record_artifact("court_coordinates_edit_mask", self.config.resolved_output_dir / "court_coordinates_edit_mask.npy")

    # Detects jump-shot poses on a specific frame of the shot video, then projects those positions onto a court diagram.
    def preview_shot_projections(self) -> None:
        source = self.config.shot_video_path
        if not source.exists():
            LOGGER.warning("Shot demo video not found, skipping shot-frame projection stages: %s", source)
            return

        frame_idx = 65
        box_annotator = sv.BoxAnnotator(color=self.color_palette, thickness=2)
        label_annotator = sv.LabelAnnotator(color=self.color_palette, text_color=sv.Color.BLACK)

        frame = next(sv.get_video_frames_generator(source, start=frame_idx, iterative_seek=True))
        jump_detections = self._infer_player_detections(frame)
        jump_detections = jump_detections[jump_detections.class_id == self.PLAYER_JUMP_SHOT_CLASS_ID]

        annotated = box_annotator.annotate(scene=frame.copy(), detections=jump_detections)
        annotated = label_annotator.annotate(scene=annotated, detections=jump_detections)
        shot_boxes_path = self.config.resolved_output_dir / "jump_shot_boxes_preview.jpg"
        save_image(shot_boxes_path, annotated)
        self._record_artifact("jump_shot_boxes_preview", shot_boxes_path)

        key_points = self._infer_keypoints(frame)
        landmarks_mask = self._is_valid_landmark_set(key_points)
        if np.count_nonzero(landmarks_mask) < 4:
            LOGGER.warning("Not enough keypoints for shot court projection")
            return

        court_landmarks = np.asarray(self.state.court_config.vertices)[landmarks_mask]
        frame_landmarks = key_points[:, landmarks_mask].xy[0]
        transformer = ViewTransformer(source=frame_landmarks, target=court_landmarks)

        frame_xy = jump_detections.get_anchors_coordinates(anchor=sv.Position.BOTTOM_CENTER)
        if len(frame_xy) == 0:
            LOGGER.warning("No jump-shot detections to project")
            return

        court_xy = transformer.transform_points(points=frame_xy)
        shot_court = draw_made_and_miss_on_court(
            config=self.state.court_config,
            made_xy=court_xy,
            made_size=25,
            made_color=sv.Color.from_hex("#007A33"),
            made_thickness=6,
            line_thickness=4,
        )
        shot_court_path = self.config.resolved_output_dir / "shot_court_projection.jpg"
        save_image(shot_court_path, shot_court)
        self._record_artifact("shot_court_projection", shot_court_path)

    # Scans the shot video frame-by-frame to detect shot events and saves annotated event frames and a JSON log.
    def run_shot_event_tracker(self) -> None:
        source = self.config.shot_video_path
        if not source.exists():
            LOGGER.warning("Shot demo video not found, skipping shot-event stage: %s", source)
            return

        event_frames_dir = self.config.resolved_output_dir / "shot_event_frames"
        ensure_dir(event_frames_dir)

        box_annotator = sv.BoxAnnotator(color=self.color_palette, thickness=2)
        label_annotator = sv.LabelAnnotator(color=self.color_palette, text_color=sv.Color.BLACK)

        frame_generator = sv.get_video_frames_generator(source)
        video_info = sv.VideoInfo.from_video_path(source)

        shot_event_tracker = ShotEventTracker(
            reset_time_frames=int(video_info.fps * 1.7),
            minimum_frames_between_starts=int(video_info.fps * 0.5),
            cooldown_frames_after_made=int(video_info.fps * 0.5),
        )

        event_log: List[Dict[str, Any]] = []
        for frame_index, frame in enumerate(self._with_frame_limit(frame_generator)):
            detections = self._infer_player_detections(frame)

            has_jump_shot = len(detections[detections.class_id == self.PLAYER_JUMP_SHOT_CLASS_ID]) > 0
            has_layup_dunk = len(detections[detections.class_id == self.LAYUP_DUNK_CLASS_ID]) > 0
            has_ball_in_basket = len(detections[detections.class_id == self.BALL_IN_BASKET_CLASS_ID]) > 0

            events = shot_event_tracker.update(
                frame_index=frame_index,
                has_jump_shot=has_jump_shot,
                has_layup_dunk=has_layup_dunk,
                has_ball_in_basket=has_ball_in_basket,
            )

            if events:
                event_entry = {"frame_index": frame_index, "events": events}
                event_log.append(event_entry)

                annotated = box_annotator.annotate(scene=frame.copy(), detections=detections)
                annotated = label_annotator.annotate(scene=annotated, detections=detections)
                frame_path = event_frames_dir / f"frame_{frame_index:06d}.jpg"
                save_image(frame_path, annotated)

        events_json = self.config.resolved_output_dir / "shot_events.json"
        write_json(events_json, {"events": event_log})
        self._record_artifact("shot_events_json", events_json)
        self._record_artifact("shot_event_frames_dir", event_frames_dir)

    # Runs every pipeline stage in sequence and saves an artifact index file.
    def run_all(self) -> Dict[str, str]:
        predictor: Optional[Any] = None
        if not self.skip_sam2:
            try:
                predictor = self._get_sam2_predictor()
            except Exception as exc:
                if not self.config.continue_on_stage_error:
                    raise
                LOGGER.error("SAM2 unavailable; skipping SAM2-dependent stages: %s", exc)
                self.state.artifacts["warning_sam2_unavailable"] = str(exc)
                self.skip_sam2 = True

        stages: List[Tuple[str, Any, bool]] = [
            ("preview_detections", self.preview_detections, False),
            ("render_detection_video", self.render_detection_video, False),
            (
                "render_mask_video",
                lambda: self.render_mask_video(predictor),
                True,
            ),
            ("fit_team_classifier", self.fit_team_classifier, False),
            ("preview_team_classifications", self.preview_team_classifications, False),
            ("render_team_video", lambda: self.render_team_video(predictor), True),
            ("preview_number_detection", self.preview_number_detection, False),
            (
                "debug_number_player_matching",
                lambda: self.debug_number_player_matching(predictor),
                True,
            ),
            (
                "render_validated_numbers_video",
                lambda: self.render_validated_numbers_video(predictor),
                True,
            ),
            (
                "render_player_identification_video",
                lambda: self.render_player_identification_video(predictor),
                True,
            ),
            ("preview_court_keypoints", self.preview_court_keypoints, False),
            ("preview_court_projection", self.preview_court_projection, False),
            (
                "render_court_map_pipeline",
                lambda: self.render_court_map_pipeline(predictor),
                True,
            ),
            ("preview_shot_projections", self.preview_shot_projections, False),
            ("run_shot_event_tracker", self.run_shot_event_tracker, False),
        ]

        for stage_name, stage_fn, needs_sam2 in stages:
            if needs_sam2 and self.skip_sam2:
                LOGGER.info("Skipping %s because SAM2 was disabled", stage_name)
                continue

            LOGGER.info("Running stage: %s", stage_name)
            try:
                stage_fn()
            except Exception as exc:
                LOGGER.exception("Stage failed: %s", stage_name)
                if not self.config.continue_on_stage_error:
                    raise
                self.state.artifacts[f"error_{stage_name}"] = str(exc)

        artifact_path = self.config.resolved_output_dir / "fresh_vision_artifacts.json"
        write_json(artifact_path, self.state.artifacts)
        self._record_artifact("artifacts_index", artifact_path)
        return self.state.artifacts

    # Runs a fast subset of stages to verify all three models and video I/O work end-to-end.
    def run_smoke(self) -> Dict[str, str]:
        LOGGER.info("Running smoke mode")
        self.preview_detections()
        self.render_detection_video()
        self.preview_number_detection()
        self.preview_court_keypoints()
        self.preview_shot_projections()
        self.run_shot_event_tracker()

        artifact_path = self.config.resolved_output_dir / "fresh_vision_artifacts_smoke.json"
        write_json(artifact_path, self.state.artifacts)
        self._record_artifact("artifacts_index_smoke", artifact_path)
        return self.state.artifacts

# Parses command-line arguments for configuring video paths, model settings, and run mode.
def parse_args() -> argparse.Namespace:
    default_home = Path.cwd()
    parser = argparse.ArgumentParser(description="Basketball AI vision pipeline")
    parser.add_argument("--source-video-directory", type=Path, default=default_home / "source")
    parser.add_argument(
        "--source-video-name",
        type=str,
        default="lakers_warriors_christmas_trimmed.mp4",
    )
    parser.add_argument(
        "--shot-video-name",
        type=str,
        default="lakers_warriors_christmas_trimmed.mp4",
    )
    parser.add_argument("--output-directory", type=Path, default=default_home / "fresh_vision_outputs")
    parser.add_argument("--fonts-directory", type=Path, default=default_home / "fonts")

    parser.add_argument("--sam2-repo-path", type=Path, default=default_home / "segment-anything-2-real-time")
    parser.add_argument("--sam2-checkpoint", type=str, default="sam2.1_hiera_large.pt")
    parser.add_argument("--sam2-config", type=str, default="configs/sam2.1/sam2.1_hiera_l.yaml")
    parser.add_argument("--sam2-device", type=str, default="cuda")
    parser.add_argument("--skip-sam2", action="store_true")

    parser.add_argument("--mode", choices=["all", "smoke"], default="all")
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--continue-on-stage-error", action="store_true")
    parser.add_argument("--verbose", action="store_true")

    return parser.parse_args()

# Entry point: parses args, builds the pipeline config, and runs either all stages or smoke mode.
def main() -> None:
    args = parse_args()
    configure_logging(verbose=args.verbose)

    if not os.environ.get("ROBOFLOW_API_KEY"):
        raise EnvironmentError(
            "ROBOFLOW_API_KEY is not set. Export your key before running this pipeline."
        )

    cfg = PipelineConfig(
        home=Path.cwd(),
        source_video_directory=args.source_video_directory,
        source_video_name=args.source_video_name,
        shot_video_name=args.shot_video_name,
        output_directory=args.output_directory,
        fonts_directory=args.fonts_directory,
        sam2_repo_path=args.sam2_repo_path,
        sam2_checkpoint=args.sam2_checkpoint,
        sam2_config=args.sam2_config,
        sam2_device=args.sam2_device,
        max_frames=args.max_frames,
        continue_on_stage_error=args.continue_on_stage_error,
    )

    pipeline = FreshVisionPipeline(config=cfg, skip_sam2=args.skip_sam2)

    if args.mode == "smoke":
        artifacts = pipeline.run_smoke()
    else:
        artifacts = pipeline.run_all()

    LOGGER.info("Pipeline completed. Artifacts saved under: %s", cfg.resolved_output_dir)
    LOGGER.info("Artifact count: %d", len(artifacts))


if __name__ == "__main__":
    main()
