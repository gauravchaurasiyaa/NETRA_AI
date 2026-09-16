"""
NETRA-AI — Step 2: Real Diabetic Retinopathy Model Training

Dataset structure expected:

NETRA-AI/
└── dataset/
    └── APTOS2019/
        └── train_images/
            ├── No_DR/
            ├── Mild/
            ├── Moderate/
            ├── Severe/
            └── Proliferate_DR/

Class mapping:
    No_DR            -> 0
    Mild             -> 1
    Moderate         -> 2
    Severe           -> 3
    Proliferate_DR   -> 4

This script:
1. Reads real retinal images from class folders.
2. Creates a stratified train/validation split.
3. Uses ImageNet-pretrained EfficientNet-B0.
4. Fine-tunes it for 5-class DR grading.
5. Uses class-weighted loss for the imbalanced dataset.
6. Supports Apple MPS, NVIDIA CUDA, or CPU.
7. Saves the best trained model.
8. Saves training metrics.
9. Saves classification report.
10. Saves confusion matrix.
11. Saves training history.
12. Creates a dataset manifest for traceability.

IMPORTANT:
This is a research/hackathon model.
It is NOT a clinically validated diagnostic system.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import random
import time
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageFile

import torch
import torch.nn as nn
from torch.optim import AdamW
from torch.optim.lr_scheduler import ReduceLROnPlateau
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms

from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split


# ============================================================
# BASIC SETTINGS
# ============================================================

ImageFile.LOAD_TRUNCATED_IMAGES = True

SEED = 42
NUM_CLASSES = 5

CLASS_NAMES = [
    "No DR",
    "Mild DR",
    "Moderate DR",
    "Severe DR",
    "Proliferative DR",
]

FOLDER_TO_LABEL = {
    "No_DR": 0,
    "Mild": 1,
    "Moderate": 2,
    "Severe": 3,
    "Proliferate_DR": 4,
}

SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".JPG",
    ".JPEG",
    ".PNG",
}


# ============================================================
# PROJECT PATHS
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent

DATASET_DIR = SCRIPT_DIR / "dataset" / "APTOS2019"
IMAGE_DIR = DATASET_DIR / "train_images"

MODEL_DIR = SCRIPT_DIR / "models"
OUTPUT_DIR = SCRIPT_DIR / "training_outputs"

MODEL_PATH = MODEL_DIR / "netra_dr_efficientnet_b0.pth"
METRICS_PATH = MODEL_DIR / "training_metrics.json"
REPORT_PATH = MODEL_DIR / "classification_report.txt"

CONFUSION_PATH = OUTPUT_DIR / "confusion_matrix.csv"
HISTORY_PATH = OUTPUT_DIR / "training_history.csv"
MANIFEST_PATH = OUTPUT_DIR / "dataset_manifest.csv"


# ============================================================
# RANDOM SEED
# ============================================================

def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

    os.environ["PYTHONHASHSEED"] = str(seed)


# ============================================================
# DEVICE
# ============================================================

def get_device() -> torch.device:
    """
    Select the fastest available device.

    Priority:
        Apple MPS
        CUDA
        CPU
    """

    if torch.backends.mps.is_available():
        return torch.device("mps")

    if torch.cuda.is_available():
        return torch.device("cuda")

    return torch.device("cpu")


# ============================================================
# DATASET VALIDATION
# ============================================================

def validate_dataset_structure() -> None:
    """
    Check that the folder-based dataset exists.
    """

    print("Checking dataset structure...")

    if not DATASET_DIR.is_dir():
        raise FileNotFoundError(
            f"\nDataset directory not found:\n{DATASET_DIR}\n\n"
            "Expected:\n"
            "dataset/APTOS2019/"
        )

    if not IMAGE_DIR.is_dir():
        raise FileNotFoundError(
            f"\nImage directory not found:\n{IMAGE_DIR}\n\n"
            "Expected:\n"
            "dataset/APTOS2019/train_images/"
        )

    missing_folders = []

    for folder_name in FOLDER_TO_LABEL:
        folder = IMAGE_DIR / folder_name

        if not folder.is_dir():
            missing_folders.append(folder_name)

    if missing_folders:
        raise FileNotFoundError(
            "\nMissing class folders:\n"
            + "\n".join(f"  - {folder}" for folder in missing_folders)
            + "\n\nExpected folders:\n"
            + "\n".join(
                f"  - {IMAGE_DIR / folder}"
                for folder in FOLDER_TO_LABEL
            )
        )

    print("✓ Dataset structure looks correct.")
    print()


# ============================================================
# COLLECT IMAGES
# ============================================================

def collect_dataset() -> pd.DataFrame:
    """
    Read all retinal images from class folders.

    Labels are determined from folder names.
    """

    rows = []

    print("Scanning retinal image folders...")
    print()

    for folder_name, label in FOLDER_TO_LABEL.items():

        class_dir = IMAGE_DIR / folder_name

        files = [
            path
            for path in class_dir.rglob("*")
            if path.is_file()
            and path.suffix in SUPPORTED_EXTENSIONS
        ]

        files = sorted(files)

        print(
            f"{label} — "
            f"{CLASS_NAMES[label]:18s} : "
            f"{len(files):5d} images"
        )

        for image_path in files:
            rows.append(
                {
                    "path": str(image_path),
                    "label": label,
                    "class_name": CLASS_NAMES[label],
                    "folder": folder_name,
                    "filename": image_path.name,
                }
            )

    if not rows:
        raise RuntimeError(
            f"\nNo images found inside:\n{IMAGE_DIR}\n\n"
            "Make sure the five class folders contain images."
        )

    df = pd.DataFrame(rows)

    return df


# ============================================================
# IMAGE VALIDATION
# ============================================================

def validate_images(df: pd.DataFrame) -> pd.DataFrame:
    """
    Verify that images can actually be opened.

    Invalid images are removed from the dataset.
    """

    print()
    print("Validating image files...")
    print()

    valid_rows = []
    invalid_count = 0

    total = len(df)

    for index, row in enumerate(df.itertuples(index=False), start=1):

        path = Path(row.path)

        try:
            with Image.open(path) as image:
                image.verify()

            valid_rows.append(
                {
                    "path": row.path,
                    "label": int(row.label),
                    "class_name": row.class_name,
                    "folder": row.folder,
                    "filename": row.filename,
                }
            )

        except Exception:
            invalid_count += 1

        if index % 250 == 0 or index == total:
            print(
                f"\rChecked {index:,}/{total:,} images",
                end="",
                flush=True,
            )

    print()
    print()

    if invalid_count:
        print(
            f"⚠ Removed {invalid_count} invalid/unreadable images."
        )
    else:
        print("✓ All discovered images passed validation.")

    print()

    clean_df = pd.DataFrame(valid_rows)

    if clean_df.empty:
        raise RuntimeError(
            "No valid retinal images remain after validation."
        )

    return clean_df.reset_index(drop=True)


# ============================================================
# CREATE DATASET MANIFEST
# ============================================================

def save_dataset_manifest(df: pd.DataFrame) -> None:
    """
    Save the exact dataset inventory used by training.
    """

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest = df.copy()

    manifest.to_csv(
        MANIFEST_PATH,
        index=False,
    )

    print(f"Dataset manifest saved to:")
    print(f"  {MANIFEST_PATH}")
    print()


# ============================================================
# SMALL STRATIFIED SUBSET
# ============================================================

def create_subset(
    df: pd.DataFrame,
    max_samples: int,
) -> pd.DataFrame:

    if max_samples <= 0:
        return df.copy()

    if max_samples >= len(df):
        return df.copy()

    print(
        f"Creating stratified test subset "
        f"of approximately {max_samples} images..."
    )

    available_classes = df["label"].unique()

    if len(available_classes) < NUM_CLASSES:
        raise RuntimeError(
            "Not all five classes are present in the dataset."
        )

    # First attempt: exact stratified sampling.
    try:
        subset, _ = train_test_split(
            df,
            train_size=max_samples,
            random_state=SEED,
            stratify=df["label"],
        )

        subset = subset.sample(
            frac=1.0,
            random_state=SEED,
        ).reset_index(drop=True)

        return subset

    except ValueError:
        # Fallback for very small requested samples.
        sampled_parts = []

        per_class = max(
            max_samples // NUM_CLASSES,
            1,
        )

        for label in range(NUM_CLASSES):

            class_df = df[df["label"] == label]

            if len(class_df) == 0:
                continue

            sample_count = min(
                per_class,
                len(class_df),
            )

            sampled_parts.append(
                class_df.sample(
                    n=sample_count,
                    random_state=SEED,
                )
            )

        subset = (
            pd.concat(sampled_parts)
            .sample(
                frac=1.0,
                random_state=SEED,
            )
            .reset_index(drop=True)
        )

        return subset


# ============================================================
# DATASET CLASS
# ============================================================

class RetinalDataset(Dataset):

    def __init__(
        self,
        dataframe: pd.DataFrame,
        transform=None,
    ):
        self.df = dataframe.reset_index(drop=True)
        self.transform = transform

    def __len__(self) -> int:
        return len(self.df)

    def __getitem__(self, index: int):

        row = self.df.iloc[index]

        path = row["path"]
        label = int(row["label"])

        try:
            image = Image.open(path).convert("RGB")

        except Exception as exc:
            raise RuntimeError(
                f"Could not read retinal image:\n{path}"
            ) from exc

        if self.transform:
            image = self.transform(image)

        return image, label


# ============================================================
# TRANSFORMS
# ============================================================

def build_transforms():

    # Training augmentation
    train_transform = transforms.Compose(
        [
            transforms.Resize(
                (256, 256)
            ),

            transforms.RandomResizedCrop(
                224,
                scale=(0.80, 1.0),
                ratio=(0.95, 1.05),
            ),

            transforms.RandomHorizontalFlip(
                p=0.5
            ),

            transforms.RandomRotation(
                degrees=12
            ),

            transforms.ColorJitter(
                brightness=0.15,
                contrast=0.15,
                saturation=0.10,
                hue=0.02,
            ),

            transforms.ToTensor(),

            transforms.Normalize(
                mean=[
                    0.485,
                    0.456,
                    0.406,
                ],
                std=[
                    0.229,
                    0.224,
                    0.225,
                ],
            ),
        ]
    )

    # Validation preprocessing
    val_transform = transforms.Compose(
        [
            transforms.Resize(
                (256, 256)
            ),

            transforms.CenterCrop(
                224
            ),

            transforms.ToTensor(),

            transforms.Normalize(
                mean=[
                    0.485,
                    0.456,
                    0.406,
                ],
                std=[
                    0.229,
                    0.224,
                    0.225,
                ],
            ),
        ]
    )

    return train_transform, val_transform


# ============================================================
# MODEL
# ============================================================

def build_model(
    device: torch.device,
) -> nn.Module:

    print("Loading ImageNet-pretrained EfficientNet-B0...")

    weights = models.EfficientNet_B0_Weights.DEFAULT

    model = models.efficientnet_b0(
        weights=weights
    )

    in_features = (
        model.classifier[1].in_features
    )

    model.classifier[1] = nn.Linear(
        in_features,
        NUM_CLASSES,
    )

    model = model.to(device)

    print("✓ EfficientNet-B0 ready.")
    print()

    return model


# ============================================================
# CLASS WEIGHTS
# ============================================================

def calculate_class_weights(
    labels: np.ndarray,
) -> torch.Tensor:

    counts = np.bincount(
        labels,
        minlength=NUM_CLASSES,
    ).astype(np.float64)

    total = counts.sum()

    weights = np.zeros(
        NUM_CLASSES,
        dtype=np.float32,
    )

    for cls in range(NUM_CLASSES):

        if counts[cls] > 0:

            weights[cls] = (
                total
                / (
                    NUM_CLASSES
                    * counts[cls]
                )
            )

        else:
            weights[cls] = 1.0

    return torch.tensor(
        weights,
        dtype=torch.float32,
    )


# ============================================================
# ONE TRAINING / VALIDATION EPOCH
# ============================================================

def run_epoch(
    model,
    loader,
    criterion,
    optimizer,
    device,
    training: bool,
):

    if training:
        model.train()
    else:
        model.eval()

    total_loss = 0.0

    all_targets = []
    all_predictions = []

    for images, targets in loader:

        images = images.to(device)
        targets = targets.to(device)

        if training:
            optimizer.zero_grad(
                set_to_none=True
            )

        with torch.set_grad_enabled(
            training
        ):

            logits = model(images)

            loss = criterion(
                logits,
                targets,
            )

            if training:

                loss.backward()

                optimizer.step()

        total_loss += (
            loss.item()
            * images.size(0)
        )

        predictions = torch.argmax(
            logits,
            dim=1,
        )

        all_targets.extend(
            targets.detach()
            .cpu()
            .numpy()
            .tolist()
        )

        all_predictions.extend(
            predictions.detach()
            .cpu()
            .numpy()
            .tolist()
        )

    targets_np = np.asarray(
        all_targets
    )

    predictions_np = np.asarray(
        all_predictions
    )

    avg_loss = (
        total_loss
        / max(
            len(loader.dataset),
            1,
        )
    )

    metrics = {
        "loss": float(avg_loss),

        "accuracy": float(
            accuracy_score(
                targets_np,
                predictions_np,
            )
        ),

        "balanced_accuracy": float(
            balanced_accuracy_score(
                targets_np,
                predictions_np,
            )
        ),

        "macro_f1": float(
            f1_score(
                targets_np,
                predictions_np,
                average="macro",
                zero_division=0,
            )
        ),

        "macro_precision": float(
            precision_score(
                targets_np,
                predictions_np,
                average="macro",
                zero_division=0,
            )
        ),

        "macro_recall": float(
            recall_score(
                targets_np,
                predictions_np,
                average="macro",
                zero_division=0,
            )
        ),
    }

    return (
        metrics,
        targets_np,
        predictions_np,
    )


# ============================================================
# SAVE MODEL
# ============================================================

def save_checkpoint(
    model,
    optimizer,
    epoch,
    val_metrics,
    dataframe_info,
):

    checkpoint = {
        "model_name": "EfficientNet-B0",

        "num_classes": NUM_CLASSES,

        "class_names": CLASS_NAMES,

        "class_mapping": FOLDER_TO_LABEL,

        "epoch": epoch,

        "val_metrics": val_metrics,

        "dataset": (
            "APTOS-derived "
            "224x224 Gaussian Filtered"
        ),

        "seed": SEED,

        "model_state_dict":
            model.state_dict(),

        "optimizer_state_dict":
            optimizer.state_dict(),

        "created_at":
            time.strftime(
                "%Y-%m-%dT%H:%M:%S"
            ),

        "data_info":
            dataframe_info,

        "clinical_validation": False,

        "xai_available": False,

        "note": (
            "Research/hackathon model. "
            "Not clinically validated."
        ),
    }

    torch.save(
        checkpoint,
        MODEL_PATH,
    )


# ============================================================
# PRINT DATASET DISTRIBUTION
# ============================================================

def print_distribution(
    df: pd.DataFrame,
    title: str,
) -> None:

    print(title)
    print("-" * 50)

    distribution = (
        df["label"]
        .value_counts()
        .sort_index()
    )

    for cls in range(NUM_CLASSES):

        count = int(
            distribution.get(
                cls,
                0,
            )
        )

        print(
            f"{cls} — "
            f"{CLASS_NAMES[cls]:18s}: "
            f"{count:5d}"
        )

    print()


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Train NETRA-AI using "
            "folder-based retinal images."
        )
    )

    parser.add_argument(
        "--epochs",
        type=int,
        default=10,
        help="Number of training epochs.",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=16,
        help="Training batch size.",
    )

    parser.add_argument(
        "--num-workers",
        type=int,
        default=0,
        help="DataLoader workers.",
    )

    parser.add_argument(
        "--val-size",
        type=float,
        default=0.20,
        help="Validation fraction.",
    )

    parser.add_argument(
        "--lr",
        type=float,
        default=1e-4,
        help="Initial learning rate.",
    )

    parser.add_argument(
        "--head-only-epochs",
        type=int,
        default=2,
        help=(
            "Number of initial epochs "
            "with EfficientNet backbone frozen."
        ),
    )

    parser.add_argument(
        "--max-samples",
        type=int,
        default=0,
        help=(
            "Small test run. "
            "0 means use the complete dataset."
        ),
    )

    args = parser.parse_args()

    # --------------------------------------------------------
    # Validate arguments
    # --------------------------------------------------------

    if args.epochs < 1:
        raise ValueError(
            "--epochs must be at least 1."
        )

    if args.batch_size < 1:
        raise ValueError(
            "--batch-size must be at least 1."
        )

    if not (
        0.05
        <= args.val_size
        <= 0.50
    ):
        raise ValueError(
            "--val-size should be between 0.05 and 0.50."
        )

    # --------------------------------------------------------
    # Seed
    # --------------------------------------------------------

    seed_everything()

    # --------------------------------------------------------
    # Create output directories
    # --------------------------------------------------------

    MODEL_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Header
    # --------------------------------------------------------

    print()
    print("=" * 72)
    print(
        "NETRA-AI — REAL DR MODEL TRAINING"
    )
    print("=" * 72)
    print()

    print(
        "Dataset :",
        DATASET_DIR,
    )

    print(
        "Images  :",
        IMAGE_DIR,
    )

    print(
        "Model   :",
        MODEL_PATH,
    )

    print()

    # --------------------------------------------------------
    # Validate dataset
    # --------------------------------------------------------

    validate_dataset_structure()

    # --------------------------------------------------------
    # Device
    # --------------------------------------------------------

    device = get_device()

    print(
        f"Device  : {device}"
    )

    if device.type == "mps":

        print(
            "Using Apple Metal (MPS) acceleration."
        )

    elif device.type == "cuda":

        print(
            "Using NVIDIA CUDA acceleration."
        )

    else:

        print(
            "Using CPU. Training will be slower."
        )

    print()

    # --------------------------------------------------------
    # Collect dataset
    # --------------------------------------------------------

    df = collect_dataset()

    print()

    print(
        f"Total discovered images: "
        f"{len(df):,}"
    )

    print()

    print_distribution(
        df,
        "Class distribution:",
    )

    # --------------------------------------------------------
    # Validate images
    # --------------------------------------------------------

    df = validate_images(df)

    print(
        f"Valid images: "
        f"{len(df):,}"
    )

    print()

    print_distribution(
        df,
        "Validated class distribution:",
    )

    # --------------------------------------------------------
    # Optional small test subset
    # --------------------------------------------------------

    if (
        args.max_samples > 0
        and args.max_samples < len(df)
    ):

        df = create_subset(
            df,
            args.max_samples,
        )

        print(
            f"Using subset: "
            f"{len(df):,} images"
        )

        print()

        print_distribution(
            df,
            "Subset class distribution:",
        )

    # --------------------------------------------------------
    # Save manifest
    # --------------------------------------------------------

    save_dataset_manifest(df)

    # --------------------------------------------------------
    # Stratified train/validation split
    # --------------------------------------------------------

    print(
        "Creating stratified "
        "train/validation split..."
    )

    train_df, val_df = train_test_split(
        df,
        test_size=args.val_size,
        random_state=SEED,
        stratify=df["label"],
    )

    train_df = (
        train_df
        .reset_index(drop=True)
    )

    val_df = (
        val_df
        .reset_index(drop=True)
    )

    print()

    print(
        f"Training images  : "
        f"{len(train_df):,}"
    )

    print(
        f"Validation images: "
        f"{len(val_df):,}"
    )

    print()

    print_distribution(
        train_df,
        "Training distribution:",
    )

    print_distribution(
        val_df,
        "Validation distribution:",
    )

    # --------------------------------------------------------
    # Transforms
    # --------------------------------------------------------

    train_transform, val_transform = (
        build_transforms()
    )

    # --------------------------------------------------------
    # Dataset objects
    # --------------------------------------------------------

    train_dataset = RetinalDataset(
        train_df,
        train_transform,
    )

    val_dataset = RetinalDataset(
        val_df,
        val_transform,
    )

    # --------------------------------------------------------
    # DataLoaders
    # --------------------------------------------------------

    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.num_workers,
        pin_memory=False,
    )

    val_loader = DataLoader(
        val_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=False,
    )

    # --------------------------------------------------------
    # Build model
    # --------------------------------------------------------

    model = build_model(
        device
    )

    # --------------------------------------------------------
    # Freeze EfficientNet backbone
    # --------------------------------------------------------

    for parameter in model.features.parameters():

        parameter.requires_grad = False

    print(
        "EfficientNet backbone initially frozen."
    )

    print(
        "Classification head will train first."
    )

    print()

    # --------------------------------------------------------
    # Class weights
    # --------------------------------------------------------

    class_weights = (
        calculate_class_weights(
            train_df["label"].to_numpy()
        )
        .to(device)
    )

    print("Class weights:")

    for cls, weight in enumerate(
        class_weights
        .detach()
        .cpu()
        .numpy()
    ):

        print(
            f"  {cls} — "
            f"{CLASS_NAMES[cls]:18s}: "
            f"{weight:.4f}"
        )

    print()

    # --------------------------------------------------------
    # Loss
    # --------------------------------------------------------

    criterion = nn.CrossEntropyLoss(
        weight=class_weights
    )

    # --------------------------------------------------------
    # Optimizer
    # --------------------------------------------------------

    optimizer = AdamW(
        filter(
            lambda p:
            p.requires_grad,
            model.parameters(),
        ),
        lr=args.lr,
        weight_decay=1e-4,
    )

    scheduler = ReduceLROnPlateau(
        optimizer,
        mode="max",
        factor=0.5,
        patience=1,
    )

    # --------------------------------------------------------
    # Best model tracking
    # --------------------------------------------------------

    best_score = -1.0

    best_state = None

    best_epoch = 0

    history = []

    total_start = time.time()

    # --------------------------------------------------------
    # TRAINING LOOP
    # --------------------------------------------------------

    for epoch in range(
        1,
        args.epochs + 1,
    ):

        # ----------------------------------------------------
        # Unfreeze after head-only stage
        # ----------------------------------------------------

        if (
            epoch
            == args.head_only_epochs + 1
        ):

            print()
            print(
                "Unfreezing EfficientNet "
                "backbone for fine-tuning..."
            )
            print()

            for parameter in (
                model.features.parameters()
            ):

                parameter.requires_grad = True

            optimizer = AdamW(
                model.parameters(),
                lr=args.lr * 0.25,
                weight_decay=1e-4,
            )

            scheduler = ReduceLROnPlateau(
                optimizer,
                mode="max",
                factor=0.5,
                patience=1,
            )

        epoch_start = time.time()

        # ----------------------------------------------------
        # Training
        # ----------------------------------------------------

        train_metrics, _, _ = run_epoch(
            model,
            train_loader,
            criterion,
            optimizer,
            device,
            training=True,
        )

        # ----------------------------------------------------
        # Validation
        # ----------------------------------------------------

        (
            val_metrics,
            val_targets,
            val_predictions,
        ) = run_epoch(
            model,
            val_loader,
            criterion,
            optimizer,
            device,
            training=False,
        )

        # ----------------------------------------------------
        # Scheduler
        # ----------------------------------------------------

        scheduler.step(
            val_metrics["macro_f1"]
        )

        current_lr = (
            optimizer
            .param_groups[0]["lr"]
        )

        epoch_seconds = (
            time.time()
            - epoch_start
        )

        # ----------------------------------------------------
        # History row
        # ----------------------------------------------------

        row = {
            "epoch": epoch,

            "train_loss":
                train_metrics["loss"],

            "train_accuracy":
                train_metrics["accuracy"],

            "train_macro_f1":
                train_metrics["macro_f1"],

            "val_loss":
                val_metrics["loss"],

            "val_accuracy":
                val_metrics["accuracy"],

            "val_balanced_accuracy":
                val_metrics[
                    "balanced_accuracy"
                ],

            "val_macro_f1":
                val_metrics["macro_f1"],

            "val_macro_precision":
                val_metrics[
                    "macro_precision"
                ],

            "val_macro_recall":
                val_metrics[
                    "macro_recall"
                ],

            "learning_rate":
                current_lr,

            "epoch_seconds":
                epoch_seconds,
        }

        history.append(row)

        # ----------------------------------------------------
        # Console output
        # ----------------------------------------------------

        print(
            f"Epoch {epoch:02d}/{args.epochs} | "
            f"train loss "
            f"{train_metrics['loss']:.4f} | "
            f"train acc "
            f"{train_metrics['accuracy']:.4f} | "
            f"val loss "
            f"{val_metrics['loss']:.4f} | "
            f"val acc "
            f"{val_metrics['accuracy']:.4f} | "
            f"val macro-F1 "
            f"{val_metrics['macro_f1']:.4f} | "
            f"{epoch_seconds:.0f}s"
        )

        # ----------------------------------------------------
        # Save best model
        # ----------------------------------------------------

        if (
            val_metrics["macro_f1"]
            > best_score
        ):

            best_score = (
                val_metrics["macro_f1"]
            )

            best_epoch = epoch

            best_state = copy.deepcopy(
                model.state_dict()
            )

            distribution = (
                df["label"]
                .value_counts()
                .sort_index()
            )

            dataframe_info = {
                "total_images":
                    int(len(df)),

                "train_images":
                    int(len(train_df)),

                "validation_images":
                    int(len(val_df)),

                "class_distribution": {
                    str(k): int(v)
                    for k, v in
                    distribution
                    .to_dict()
                    .items()
                },

                "dataset_directory":
                    str(DATASET_DIR),

                "image_directory":
                    str(IMAGE_DIR),
            }

            save_checkpoint(
                model,
                optimizer,
                epoch,
                val_metrics,
                dataframe_info,
            )

            print(
                f"  ✓ Best model saved "
                f"(validation "
                f"macro-F1="
                f"{best_score:.4f})"
            )

    # ========================================================
    # RESTORE BEST MODEL
    # ========================================================

    if best_state is not None:

        model.load_state_dict(
            best_state
        )

    # ========================================================
    # FINAL VALIDATION
    # ========================================================

    (
        final_metrics,
        val_targets,
        val_predictions,
    ) = run_epoch(
        model,
        val_loader,
        criterion,
        optimizer,
        device,
        training=False,
    )

    # ========================================================
    # CONFUSION MATRIX
    # ========================================================

    cm = confusion_matrix(
        val_targets,
        val_predictions,
        labels=list(
            range(NUM_CLASSES)
        ),
    )

    cm_df = pd.DataFrame(
        cm,
        index=CLASS_NAMES,
        columns=CLASS_NAMES,
    )

    cm_df.to_csv(
        CONFUSION_PATH
    )

    # ========================================================
    # CLASSIFICATION REPORT
    # ========================================================

    report = classification_report(
        val_targets,
        val_predictions,
        labels=list(
            range(NUM_CLASSES)
        ),
        target_names=CLASS_NAMES,
        digits=4,
        zero_division=0,
    )

    REPORT_PATH.write_text(
        report,
        encoding="utf-8",
    )

    # ========================================================
    # TRAINING HISTORY
    # ========================================================

    history_df = pd.DataFrame(
        history
    )

    history_df.to_csv(
        HISTORY_PATH,
        index=False,
    )

    # ========================================================
    # FINAL METRICS
    # ========================================================

    elapsed = (
        time.time()
        - total_start
    )

    final_summary = {

        "model":
            "EfficientNet-B0",

        "dataset":
            "APTOS-derived "
            "224x224 Gaussian Filtered",

        "dataset_structure":
            "Folder-based",

        "class_mapping":
            FOLDER_TO_LABEL,

        "classes":
            CLASS_NAMES,

        "best_epoch":
            int(best_epoch),

        "best_validation_macro_f1":
            float(best_score),

        "final_validation_metrics":
            final_metrics,

        "training_images":
            int(len(train_df)),

        "validation_images":
            int(len(val_df)),

        "total_usable_images":
            int(len(df)),

        "device":
            str(device),

        "epochs_requested":
            int(args.epochs),

        "batch_size":
            int(args.batch_size),

        "learning_rate":
            float(args.lr),

        "seed":
            SEED,

        "training_time_minutes":
            float(elapsed / 60),

        "clinical_validation":
            False,

        "note":
            (
                "Research/hackathon "
                "training result only. "
                "Not a clinically validated "
                "diagnostic model."
            ),
    }

    METRICS_PATH.write_text(
        json.dumps(
            final_summary,
            indent=2,
        ),
        encoding="utf-8",
    )

    # ========================================================
    # FINAL OUTPUT
    # ========================================================

    print()
    print("=" * 72)
    print(
        "TRAINING COMPLETE"
    )
    print("=" * 72)

    print(
        f"Best epoch       : "
        f"{best_epoch}"
    )

    print(
        f"Best validation  : "
        f"{best_score:.4f} macro-F1"
    )

    print(
        f"Validation acc   : "
        f"{final_metrics['accuracy']:.4f}"
    )

    print(
        f"Balanced accuracy: "
        f"{final_metrics['balanced_accuracy']:.4f}"
    )

    print(
        f"Macro precision  : "
        f"{final_metrics['macro_precision']:.4f}"
    )

    print(
        f"Macro recall     : "
        f"{final_metrics['macro_recall']:.4f}"
    )

    print(
        f"Macro F1         : "
        f"{final_metrics['macro_f1']:.4f}"
    )

    print(
        f"Training time    : "
        f"{elapsed / 60:.1f} minutes"
    )

    print()
    print(
        "Classification report:"
    )

    print(report)

    print(
        "Saved files:"
    )

    print(
        f"  {MODEL_PATH}"
    )

    print(
        f"  {METRICS_PATH}"
    )

    print(
        f"  {REPORT_PATH}"
    )

    print(
        f"  {HISTORY_PATH}"
    )

    print(
        f"  {CONFUSION_PATH}"
    )

    print(
        f"  {MANIFEST_PATH}"
    )

    print()
    print(
        "IMPORTANT:"
    )

    print(
        "These validation metrics come "
        "from this training run and do "
        "not establish clinical performance."
    )

    print()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()