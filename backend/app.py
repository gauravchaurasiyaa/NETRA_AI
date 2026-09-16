import os
import io
import csv
import json
import sqlite3
import hashlib
from datetime import datetime
from pathlib import Path

# ============================================================
# PATHS
# ============================================================
BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"
FRONTEND_DIR = BASE_DIR / "frontend"
UPLOAD_DIR = BACKEND_DIR / "uploads"
DATABASE_DIR = BACKEND_DIR / "database"
REPORT_DIR = BACKEND_DIR / "reports"
DATABASE_PATH = DATABASE_DIR / "netra.db"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
from PIL import Image, ImageStat, ImageDraw, ImageFilter

# Real trained model + Grad-CAM engine
try:
    from gradcam import build_model, GradCAM, create_heatmap_image, MODEL_PATH, DEVICE
    REAL_AI_AVAILABLE = MODEL_PATH.exists()
except Exception as _gradcam_import_error:
    build_model = None
    GradCAM = None
    create_heatmap_image = None
    MODEL_PATH = BASE_DIR / "models" / "netra_dr_efficientnet_b0.pth"
    DEVICE = None
    REAL_AI_AVAILABLE = False
    _gradcam_import_error = str(_gradcam_import_error)

REAL_MODEL = None

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        Image as RLImage
    )
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


# ============================================================
# FLASK
# ============================================================

app = Flask(
    __name__,
    static_folder=str(FRONTEND_DIR),
    static_url_path=""
)

CORS(app)

app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024


# ============================================================
# CONSTANTS
# ============================================================

ALLOWED_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg",
    "webp"
}

SEVERITY_NAMES = {
    0: "No DR",
    1: "Mild NPDR",
    2: "Moderate NPDR",
    3: "Severe NPDR",
    4: "Proliferative DR"
}

REVIEW_STATUSES = {
    "Pending",
    "Under Review",
    "Reviewed",
    "Referred",
    "Closed"
}


# ============================================================
# RURAL TELEMEDICINE DEMO NETWORK
# ============================================================

TELEMEDICINE_NETWORK = [
    {
        "node_id": "NETRA-RURAL-01",
        "name": "Rural Screening Centre",
        "route": "Village → District Hospital",
        "status": "Active",
        "patients_today": 18,
        "referrals_today": 4,
        "last_sync": "Just now"
    },
    {
        "node_id": "NETRA-RURAL-02",
        "name": "Community Health Centre",
        "route": "CHC → Vision Centre → Hospital",
        "status": "Active",
        "patients_today": 12,
        "referrals_today": 2,
        "last_sync": "2 min ago"
    },
    {
        "node_id": "NETRA-RURAL-03",
        "name": "Block Health Centre",
        "route": "Block Hospital → District Hospital",
        "status": "Standby",
        "patients_today": 7,
        "referrals_today": 1,
        "last_sync": "5 min ago"
    }
]


# ============================================================
# DATABASE
# ============================================================

def get_db():
    connection = sqlite3.connect(str(DATABASE_PATH))
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():

    connection = get_db()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT,

            patient_name TEXT,
            age TEXT,
            sex TEXT,
            location TEXT,
            notes TEXT,

            filename TEXT,
            image_path TEXT,
            xai_path TEXT,

            severity TEXT,
            level INTEGER,
            confidence REAL,

            image_quality TEXT,
            referral TEXT,

            evidence TEXT,
            explanation TEXT,

            review_status TEXT DEFAULT 'Pending',
            reviewer TEXT,
            reviewer_notes TEXT,

            created_at TEXT,
            updated_at TEXT
        )
    """)

    existing_columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(cases)"
        ).fetchall()
    }

    migrations = {
        "case_id":
            "ALTER TABLE cases ADD COLUMN case_id TEXT",

        "review_status":
            "ALTER TABLE cases ADD COLUMN review_status TEXT DEFAULT 'Pending'",

        "reviewer":
            "ALTER TABLE cases ADD COLUMN reviewer TEXT",

        "reviewer_notes":
            "ALTER TABLE cases ADD COLUMN reviewer_notes TEXT",

        "updated_at":
            "ALTER TABLE cases ADD COLUMN updated_at TEXT",
        "filename":
            "ALTER TABLE cases ADD COLUMN filename TEXT",
        "image_path":
            "ALTER TABLE cases ADD COLUMN image_path TEXT",

        "xai_path":
            "ALTER TABLE cases ADD COLUMN xai_path TEXT",

        "evidence":
            "ALTER TABLE cases ADD COLUMN evidence TEXT",

        "explanation":
            "ALTER TABLE cases ADD COLUMN explanation TEXT",

        "image_quality":
            "ALTER TABLE cases ADD COLUMN image_quality TEXT",

        "referral":
            "ALTER TABLE cases ADD COLUMN referral TEXT",

        "confidence":
            "ALTER TABLE cases ADD COLUMN confidence REAL",

        "level":
            "ALTER TABLE cases ADD COLUMN level INTEGER",

        "severity":
            "ALTER TABLE cases ADD COLUMN severity TEXT"
    }

    for column, sql in migrations.items():

        if column not in existing_columns:
            connection.execute(sql)

    connection.commit()
    connection.close()


# ============================================================
# HELPERS
# ============================================================

def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def allowed_file(filename):

    return (
        filename
        and "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )


def severity_name(level):

    return SEVERITY_NAMES.get(
        int(level),
        "Unknown"
    )


def safe_json_load(value, fallback=None):

    if not value:
        return fallback if fallback is not None else []

    try:
        return json.loads(value)
    except Exception:
        return fallback if fallback is not None else []


def calculate_quality(image):

    width, height = image.size

    gray = image.convert("L")

    statistics = ImageStat.Stat(gray)

    brightness = statistics.mean[0]
    contrast = statistics.stddev[0]

    if width < 256 or height < 256:
        return "Poor"

    if brightness < 35 or brightness > 225:
        return "Poor"

    if contrast < 18:
        return "Fair"

    return "Good"


# ============================================================
# REAL AI MODEL
# ============================================================

def get_real_model():
    """Load the trained EfficientNet-B0 once and reuse it."""
    global REAL_MODEL, REAL_AI_AVAILABLE

    if REAL_MODEL is not None:
        return REAL_MODEL

    if build_model is None or not Path(MODEL_PATH).exists():
        REAL_AI_AVAILABLE = False
        return None

    REAL_MODEL = build_model()
    REAL_AI_AVAILABLE = True
    return REAL_MODEL


def run_real_screening(image):
    """Run the trained classifier and real Grad-CAM on a PIL image."""
    model = get_real_model()

    if model is None:
        raise RuntimeError(
            "Trained NETRA model is not available. "
            f"Expected model at: {MODEL_PATH}"
        )

    cam = GradCAM(model)

    try:
        heatmap, level, confidence, probabilities = cam.generate(image)
        visualization = create_heatmap_image(image, heatmap)

        return {
            "level": int(level),
            "confidence": round(float(confidence), 4),
            "probabilities": {
                SEVERITY_NAMES[index]: round(float(probability), 4)
                for index, probability in enumerate(probabilities)
            },
            "xai": visualization,
            "heatmap": heatmap,
        }
    finally:
        cam.close()


# ============================================================
# DEMO AI ENGINE
# ============================================================

def deterministic_level(image_bytes):

    """
    DEMONSTRATION ONLY.

    This is not a trained medical AI model.
    It provides repeatable prototype output.
    """

    digest = hashlib.sha256(
        image_bytes
    ).hexdigest()

    return int(
        digest[:8],
        16
    ) % 5


def deterministic_confidence(image_bytes, level):

    digest = hashlib.sha256(
        image_bytes
    ).hexdigest()

    value = (
        int(digest[8:16], 16)
        / 0xFFFFFFFF
    )

    confidence = 0.84 + (
        value * 0.13
    )

    if level == 0:
        confidence = min(
            confidence,
            0.96
        )

    return round(
        confidence,
        3
    )


def generate_evidence(image, level):

    statistics = ImageStat.Stat(
        image.convert("RGB")
    )

    red, green, blue = statistics.mean

    evidence = []

    if level == 0:

        evidence.append(
            "No strong abnormality signal detected in the demo analysis."
        )

    elif level == 1:

        evidence.extend([
            "Subtle retinal abnormality pattern highlighted by the prototype.",
            "Low-intensity lesion-like regions may require human review."
        ])

    elif level == 2:

        evidence.extend([
            "Moderate lesion-like signal highlighted by the prototype.",
            "Changes appear more prominent than the mild-risk pattern."
        ])

    elif level == 3:

        evidence.extend([
            "Multiple abnormality-like regions highlighted by the prototype.",
            "Pattern is compatible with a higher-risk screening result."
        ])

    else:

        evidence.extend([
            "Extensive abnormality-like pattern highlighted by the prototype.",
            "Urgent specialist review is recommended in the demo workflow."
        ])

    if red > green + 8:

        evidence.append(
            "Localized red-channel prominence contributes to the visual signal."
        )

    if green > blue + 8:

        evidence.append(
            "Retinal green-channel structure contributes to the visual signal."
        )

    if image.width / max(image.height, 1) > 1.7:

        evidence.append(
            "Wide field-of-view image geometry detected."
        )

    return evidence[:4]


def create_explanation(
    level,
    quality,
    confidence,
    referral
):

    if quality == "Poor":

        quality_text = (
            "Image quality is poor, so the screening result "
            "should be interpreted with additional caution."
        )

    elif quality == "Fair":

        quality_text = (
            "Image quality is acceptable but not optimal; "
            "repeat imaging may improve confidence."
        )

    else:

        quality_text = (
            "Image quality is good for this prototype screening workflow."
        )

    if referral == "REFER":

        action = (
            "The prototype flags this case for referral "
            "and human specialist review."
        )

    else:

        action = (
            "The prototype does not flag this case for referral, "
            "but clinical follow-up should still be decided "
            "by a qualified professional."
        )

    return (
        f"Prototype screening classification: "
        f"{severity_name(level)} (Level {level}). "
        f"Displayed confidence: "
        f"{round(confidence * 100, 1)}%. "
        f"{quality_text} "
        f"{action}"
    )


# ============================================================
# DEMO XAI
# ============================================================

def generate_xai(
    image,
    level,
    evidence
):

    """
    DEMONSTRATION attention map.

    This is NOT actual Grad-CAM from a trained neural network.
    """

    base = image.convert(
        "RGB"
    ).resize(
        (900, 650)
    )

    overlay = Image.new(
        "RGBA",
        base.size,
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(
        overlay
    )

    source = (
        "|".join(evidence)
        + str(level)
    )

    digest = hashlib.sha256(
        source.encode()
    ).hexdigest()

    seeds = [
        int(digest[0:4], 16),
        int(digest[4:8], 16),
        int(digest[8:12], 16),
        int(digest[12:16], 16)
    ]

    count = 2 + level

    for i in range(count):

        x = 90 + (
            seeds[i % 4] % 700
        )

        y = 80 + (
            seeds[(i + 1) % 4] % 480
        )

        rx = 45 + (
            seeds[(i + 2) % 4] % 100
        )

        ry = 35 + (
            seeds[(i + 3) % 4] % 85
        )

        draw.ellipse(
            (
                x - rx,
                y - ry,
                x + rx,
                y + ry
            ),
            fill=(255, 80, 70, 95),
            outline=(255, 230, 120, 150),
            width=3
        )

    overlay = overlay.filter(
        ImageFilter.GaussianBlur(3)
    )

    result = Image.alpha_composite(
        base.convert("RGBA"),
        overlay
    )

    draw_result = ImageDraw.Draw(
        result
    )

    draw_result.rounded_rectangle(
        (20, 20, 315, 68),
        radius=14,
        fill=(0, 0, 0, 165)
    )

    draw_result.text(
        (38, 35),
        "NETRA • Demo attention map",
        fill=(255, 255, 255, 255)
    )

    return result.convert("RGB")


# ============================================================
# CASE HELPERS
# ============================================================

def get_case(case_id):

    connection = get_db()

    row = connection.execute(
        """
        SELECT *
        FROM cases
        WHERE id = ?
        """,
        (case_id,)
    ).fetchone()

    connection.close()

    return row


def row_to_case(row):

    case = dict(row)

    # Keep API case_id compatible with the existing /api/cases/<int:case_id>
    # routes, while retaining the database's separate reference when present.
    case["case_reference"] = case.get("case_id") or f"NETRA-{case.get('id')}"
    case["case_id"] = case.get("id")

    case["level"] = int(
        case.get("level") or 0
    )

    case["confidence"] = float(
        case.get("confidence") or 0
    )

    case["severity"] = (
        case.get("severity")
        or severity_name(case["level"])
    )

    case["review_status"] = (
        case.get("review_status")
        or "Pending"
    )

    case["evidence"] = safe_json_load(
        case.get("evidence"),
        []
    )

    if case.get("filename"):

        case["image_url"] = (
            "/uploads/"
            + case["filename"]
        )

    else:

        case["image_url"] = None

    if case.get("xai_path"):

        case["xai_url"] = (
            "/uploads/"
            + Path(
                case["xai_path"]
            ).name
        )

    else:

        case["xai_url"] = None

    return case


# ============================================================
# REPORT DATA
# ============================================================

def create_report_data(case_id):

    row = get_case(case_id)

    if not row:
        return None

    case = row_to_case(row)

    level = case["level"]

    return {

        "report_title":
            "NETRA — Explainable Retinal AI Screening Report",

        "case_id":
            case["case_id"],

        "patient": {

            "name":
                case.get("patient_name")
                or "Anonymous Patient",

            "age":
                case.get("age")
                or "Not provided",

            "sex":
                case.get("sex")
                or "Not provided",

            "location":
                case.get("location")
                or "Not provided"
        },

        "screening": {

            "severity":
                case["severity"],

            "level":
                level,

            "confidence":
                case["confidence"],

            "image_quality":
                case.get("image_quality")
                or "Unknown",

            "referral":
                case.get("referral")
                or "REVIEW"
        },

        "explainability": {

            "evidence":
                case.get("evidence")
                or [],

            "explanation":
                case.get("explanation")
                or ""
        },

        "clinical_review": {

            "status":
                case.get("review_status")
                or "Pending",

            "reviewer":
                case.get("reviewer")
                or "",

            "notes":
                case.get("reviewer_notes")
                or ""
        },

        "telemedicine": {

            "recommended":
                case.get("referral")
                == "REFER",

            "destination":
                "District / specialist eye-care review",

            "priority":
                (
                    "High"
                    if level >= 3
                    else
                    "Moderate"
                    if level >= 2
                    else
                    "Routine"
                )
        },

        "timestamps": {

            "created_at":
                case.get("created_at"),

            "updated_at":
                case.get("updated_at")
        },

        "files": {

            "image_url":
                case.get("image_url"),

            "xai_url":
                case.get("xai_url")
        },

        "notice":
            (
                "Prototype only. This system is not clinically "
                "validated and must not be used as a standalone "
                "diagnostic device. Final decisions require "
                "qualified clinical review."
            )
    }


# ============================================================
# FRONTEND
# ============================================================

@app.route("/")
def index():

    return send_from_directory(
        FRONTEND_DIR,
        "index.html"
    )


@app.route("/css/<path:filename>")
def css_files(filename):

    return send_from_directory(
        FRONTEND_DIR / "css",
        filename
    )


@app.route("/js/<path:filename>")
def js_files(filename):

    return send_from_directory(
        FRONTEND_DIR / "js",
        filename
    )


@app.route("/uploads/<path:filename>")
def uploads(filename):

    return send_from_directory(
        UPLOAD_DIR,
        filename
    )


# ============================================================
# HEALTH
# ============================================================

@app.route("/api/health")
def health():

    database = False

    try:

        connection = get_db()

        connection.execute(
            "SELECT 1"
        ).fetchone()

        connection.close()

        database = True

    except Exception:

        database = False

    return jsonify({

        "status":
            "online",

        "database":
            database,

        "service":
            "NETRA Explainable Retinal AI",

        "prototype":
            True,

        "clinical_validation":
            False
    })


@app.route("/api/system")
def system():

    connection = get_db()

    total = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM cases
        """
    ).fetchone()["count"]

    connection.close()

    return jsonify({

        "system":
            "NETRA",

        "status":
            "online",

        "database":
            "connected",

        "screening_engine":
            "EfficientNet-B0 trained model",

        "clinical_validation":
            False,

        "cases":
            total,

        "pdf_reports":
            REPORTLAB_AVAILABLE,

        "telemedicine":
            True
    })


@app.route("/api/model")
def model():

    return jsonify({

        "name":
            "NETRA Explainable Retinal AI",

        "mode":
            "prototype",

        "classifier":
            "EfficientNet-B0 trained model",

        "xai":
            "real Grad-CAM",

        "grad_cam":
            bool(REAL_AI_AVAILABLE),

        "model_available":
            bool(REAL_AI_AVAILABLE),

        "device":
            str(DEVICE) if DEVICE is not None else "unavailable",

        "clinical_validation":
            False,

        "note":
            "This is a hackathon prototype using a trained EfficientNet-B0 "
            "model and real Grad-CAM explainability. It is not clinically "
            "validated and must not be used as a standalone diagnostic device."
    })


# ============================================================
# SCREENING
# ============================================================

@app.route(
    "/api/screen",
    methods=["POST"]
)
def screen():
    """
    Main retinal screening endpoint.

    This version is deliberately defensive:
    - accepts the expected multipart field "image"
    - validates the uploaded image before saving
    - converts unusual image modes safely
    - creates the XAI demo image safely
    - verifies the database schema before INSERT
    - rolls back the database if anything fails
    - returns the real server-side error as JSON instead of a blank 500
    """

    try:
        if "image" not in request.files:
            return jsonify({
                "success": False,
                "error": "No image uploaded. The frontend must send the file using the field name 'image'."
            }), 400

        file = request.files["image"]

        if not file or not file.filename:
            return jsonify({
                "success": False,
                "error": "No image selected."
            }), 400

        if not allowed_file(file.filename):
            return jsonify({
                "success": False,
                "error": "Unsupported image format. Use PNG, JPG, JPEG or WEBP."
            }), 400

        image_bytes = file.read()

        if not image_bytes:
            return jsonify({
                "success": False,
                "error": "Uploaded image is empty."
            }), 400

        # Open and fully decode the image.
        try:
            image = Image.open(io.BytesIO(image_bytes))
            image.load()
            image = image.convert("RGB")
        except Exception as error:
            return jsonify({
                "success": False,
                "error": "Invalid or unreadable retinal image.",
                "details": str(error)
            }), 400

        cleanup_paths = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        # Always save a browser/Pillow-friendly JPEG copy.
        filename = f"netra_{timestamp}.jpg"
        image_path = UPLOAD_DIR / filename

        image.save(
            image_path,
            format="JPEG",
            quality=94,
            optimize=True
        )
        cleanup_paths.append(image_path)

        # --------------------------------------------------------
        # REAL MODEL + REAL GRAD-CAM
        # --------------------------------------------------------
        ai_result = run_real_screening(image)

        level = ai_result["level"]
        confidence = ai_result["confidence"]
        probabilities = ai_result["probabilities"]
        xai = ai_result["xai"]

        quality = calculate_quality(image)

        # Keep the existing evidence structure for frontend/report
        # compatibility, but make it clear that the visual explanation
        # comes from the model's Grad-CAM activation map.
        evidence = [
            "Real EfficientNet-B0 model prediction generated from the retinal image.",
            "Grad-CAM highlights image regions that contributed to the predicted class."
        ]

        if quality == "Poor":
            evidence.append(
                "Image quality is poor; the model output should be interpreted cautiously."
            )

        referral = "REFER" if level >= 2 else "ROUTINE"

        explanation = create_explanation(
            level,
            quality,
            confidence,
            referral
        )

        xai_filename = f"netra_{timestamp}_xai.jpg"
        xai_path = UPLOAD_DIR / xai_filename

        xai.save(
            xai_path,
            format="JPEG",
            quality=92,
            optimize=True
        )
        cleanup_paths.append(xai_path)

        patient_name = request.form.get("patient_name", "").strip()
        age = request.form.get("age", "").strip()
        sex = request.form.get("sex", "").strip()
        location = request.form.get("location", "").strip()
        notes = request.form.get("notes", "").strip()

        created_at = now_iso()

        connection = get_db()

        try:
            # Make sure an older netra.db is migrated before INSERT.
            existing_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(cases)"
                ).fetchall()
            }

            required_columns = {
                "case_id":
                    "ALTER TABLE cases ADD COLUMN case_id TEXT",
                "filename":
                    "ALTER TABLE cases ADD COLUMN filename TEXT",
                "image_path":
                    "ALTER TABLE cases ADD COLUMN image_path TEXT",
                "review_status":
                    "ALTER TABLE cases ADD COLUMN review_status TEXT DEFAULT 'Pending'",
                "reviewer":
                    "ALTER TABLE cases ADD COLUMN reviewer TEXT",
                "reviewer_notes":
                    "ALTER TABLE cases ADD COLUMN reviewer_notes TEXT",
                "updated_at":
                    "ALTER TABLE cases ADD COLUMN updated_at TEXT",
                "xai_path":
                    "ALTER TABLE cases ADD COLUMN xai_path TEXT",
                "evidence":
                    "ALTER TABLE cases ADD COLUMN evidence TEXT",
                "explanation":
                    "ALTER TABLE cases ADD COLUMN explanation TEXT",
                "image_quality":
                    "ALTER TABLE cases ADD COLUMN image_quality TEXT",
                "referral":
                    "ALTER TABLE cases ADD COLUMN referral TEXT",
                "confidence":
                    "ALTER TABLE cases ADD COLUMN confidence REAL",
                "level":
                    "ALTER TABLE cases ADD COLUMN level INTEGER",
                "severity":
                    "ALTER TABLE cases ADD COLUMN severity TEXT"
            }

            for column, sql in required_columns.items():
                if column not in existing_columns:
                    connection.execute(sql)

            # Older NETRA databases may contain a separate case_id column
            # declared NOT NULL. Always provide a unique reference value.
            case_reference = f"NETRA-{timestamp}"

            cursor = connection.execute(
                """
                INSERT INTO cases (
                    case_id,
                    patient_name,
                    age,
                    sex,
                    location,
                    notes,
                    filename,
                    image_path,
                    xai_path,
                    severity,
                    level,
                    confidence,
                    image_quality,
                    referral,
                    evidence,
                    explanation,
                    review_status,
                    reviewer,
                    reviewer_notes,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_reference,
                    patient_name,
                    age,
                    sex,
                    location,
                    notes,
                    filename,
                    str(image_path),
                    str(xai_path),
                    severity_name(level),
                    level,
                    confidence,
                    quality,
                    referral,
                    json.dumps(evidence),
                    explanation,
                    "Pending",
                    "",
                    "",
                    created_at,
                    created_at
                )
            )

            case_id = cursor.lastrowid
            connection.commit()

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

        return jsonify({
            "success": True,
            "case_id": case_id,
            "id": case_id,
            "patient": patient_name or "Anonymous Patient",
            "severity": severity_name(level),
            "level": level,
            "confidence": confidence,
            "image_quality": quality,
            "referral": referral,
            "review_status": "Pending",
            "image_url": f"/uploads/{filename}",
            "xai_url": f"/uploads/{xai_filename}",
            "evidence": evidence,
            "explanation": explanation,
            "probabilities": probabilities,
            "created_at": created_at,
            "prototype": True,
            "model": "EfficientNet-B0",
            "xai": "Grad-CAM",
            "clinical_validation": False,
            "notice": (
                "Hackathon prototype result — the model is not clinically validated "
                "and this output is not a clinical diagnosis."
            )
        })

    except Exception as error:
        # Clean up files if analysis/database processing failed.
        for path in locals().get("cleanup_paths", []):
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass

        app.logger.exception("NETRA /api/screen failed")

        return jsonify({
            "success": False,
            "error": "Screening request failed on the server.",
            "details": str(error),
            "endpoint": "/api/screen",
            "prototype": True
        }), 500


# ============================================================
# CASES
# ============================================================

@app.route("/api/cases")
def cases():

    connection = get_db()

    rows = connection.execute(
        """
        SELECT *
        FROM cases
        ORDER BY id DESC
        """
    ).fetchall()

    connection.close()

    return jsonify({

        "success":
            True,

        "count":
            len(rows),

        "cases":
            [
                row_to_case(row)
                for row in rows
            ]
    })


@app.route(
    "/api/cases/<int:case_id>"
)
def case(case_id):

    row = get_case(
        case_id
    )

    if not row:

        return jsonify({
            "error":
                "Case not found."
        }), 404

    return jsonify({

        "success":
            True,

        "case":
            row_to_case(row),

        "report":
            create_report_data(case_id)
    })


# ============================================================
# REVIEW WORKFLOW
# ============================================================

@app.route(
    "/api/cases/<int:case_id>/review",
    methods=["PUT"]
)
def review_case(case_id):

    row = get_case(
        case_id
    )

    if not row:

        return jsonify({
            "error":
                "Case not found."
        }), 404

    data = request.get_json(
        silent=True
    ) or {}

    status = str(
        data.get("status", "")
    ).strip()

    reviewer = str(
        data.get("reviewer", "")
    ).strip()

    notes = str(
        data.get("notes", "")
    ).strip()

    if status not in REVIEW_STATUSES:

        return jsonify({

            "error":
                "Invalid review status.",

            "allowed":
                sorted(
                    REVIEW_STATUSES
                )
        }), 400

    updated_at = now_iso()

    connection = get_db()

    connection.execute(
        """
        UPDATE cases

        SET review_status = ?,
            reviewer = ?,
            reviewer_notes = ?,
            updated_at = ?

        WHERE id = ?
        """,
        (
            status,
            reviewer,
            notes,
            updated_at,
            case_id
        )
    )

    connection.commit()
    connection.close()

    return jsonify({

        "success":
            True,

        "case_id":
            case_id,

        "review_status":
            status,

        "reviewer":
            reviewer,

        "reviewer_notes":
            notes,

        "updated_at":
            updated_at
    })


@app.route(
    "/api/cases/<int:case_id>/notes",
    methods=["PUT"]
)
def update_notes(case_id):

    row = get_case(
        case_id
    )

    if not row:

        return jsonify({
            "error":
                "Case not found."
        }), 404

    data = request.get_json(
        silent=True
    ) or {}

    notes = str(
        data.get("notes", "")
    ).strip()

    updated_at = now_iso()

    connection = get_db()

    connection.execute(
        """
        UPDATE cases

        SET reviewer_notes = ?,
            updated_at = ?

        WHERE id = ?
        """,
        (
            notes,
            updated_at,
            case_id
        )
    )

    connection.commit()
    connection.close()

    return jsonify({

        "success":
            True,

        "case_id":
            case_id,

        "notes":
            notes,

        "updated_at":
            updated_at
    })


@app.route(
    "/api/cases/<int:case_id>",
    methods=["DELETE"]
)
def delete_case(case_id):

    row = get_case(
        case_id
    )

    if not row:

        return jsonify({
            "error":
                "Case not found."
        }), 404

    connection = get_db()

    connection.execute(
        """
        DELETE FROM cases
        WHERE id = ?
        """,
        (case_id,)
    )

    connection.commit()
    connection.close()

    for path in [
        row["image_path"],
        row["xai_path"]
    ]:

        if path:

            try:

                Path(path).unlink(
                    missing_ok=True
                )

            except Exception:

                pass

    return jsonify({

        "success":
            True,

        "case_id":
            case_id,

        "message":
            "Case deleted."
    })


# ============================================================
# ANALYTICS
# ============================================================

@app.route("/api/analytics")
def analytics():

    connection = get_db()

    total = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM cases
        """
    ).fetchone()["count"]

    referable = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM cases
        WHERE level >= 2
        """
    ).fetchone()["count"]

    referred = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM cases
        WHERE referral = 'REFER'
        """
    ).fetchone()["count"]

    reviewed = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM cases
        WHERE review_status IN (
            'Reviewed',
            'Referred',
            'Closed'
        )
        """
    ).fetchone()["count"]

    pending = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM cases
        WHERE review_status IN (
            'Pending',
            'Under Review'
        )
        """
    ).fetchone()["count"]

    average_confidence = connection.execute(
        """
        SELECT AVG(confidence) AS value
        FROM cases
        """
    ).fetchone()["value"]

    severity_rows = connection.execute(
        """
        SELECT severity, COUNT(*) AS count
        FROM cases
        GROUP BY severity
        """
    ).fetchall()

    quality_rows = connection.execute(
        """
        SELECT image_quality, COUNT(*) AS count
        FROM cases
        GROUP BY image_quality
        """
    ).fetchall()

    review_rows = connection.execute(
        """
        SELECT review_status, COUNT(*) AS count
        FROM cases
        GROUP BY review_status
        """
    ).fetchall()

    connection.close()

    return jsonify({

        "success":
            True,

        "screened":
            total,

        "total":
            total,

        "referable":
            referable,

        "referred":
            referred,

        "reviewed":
            reviewed,

        "pending":
            pending,

        "average_confidence":
            round(
                average_confidence or 0,
                3
            ),

        "severity_distribution":
            {
                row["severity"]:
                    row["count"]
                for row in severity_rows
            },

        "image_quality":
            {
                row["image_quality"]:
                    row["count"]
                for row in quality_rows
            },

        "review_status":
            {
                row["review_status"]:
                    row["count"]
                for row in review_rows
            }
    })


# ============================================================
# TELEMEDICINE NETWORK
# ============================================================

@app.route("/api/network")
def network():

    connection = get_db()

    total = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM cases
        """
    ).fetchone()["count"]

    referrals = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM cases
        WHERE referral = 'REFER'
        """
    ).fetchone()["count"]

    pending = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM cases
        WHERE review_status IN (
            'Pending',
            'Under Review'
        )
        """
    ).fetchone()["count"]

    connection.close()

    nodes = [
        dict(node)
        for node in TELEMEDICINE_NETWORK
    ]

    nodes[0]["patients_today"] += total
    nodes[0]["referrals_today"] += referrals

    return jsonify({

        "success":
            True,

        "network":
            nodes,

        "telemedicine_queue":
            {
                "pending_review":
                    pending,

                "referral_cases":
                    referrals,

                "destination":
                    "District / specialist eye-care review",

                "mode":
                    "Prototype simulation"
            },

        "sync":
            {
                "status":
                    "Online",

                "last_sync":
                    "Just now",

                "gps":
                    "Demo"
            }
    })


@app.route("/api/telemedicine")
def telemedicine():

    connection = get_db()

    rows = connection.execute(
        """
        SELECT *
        FROM cases

        WHERE referral = 'REFER'

        ORDER BY
            CASE
                WHEN level = 4 THEN 1
                WHEN level = 3 THEN 2
                WHEN level = 2 THEN 3
                ELSE 4
            END,

            id DESC
        """
    ).fetchall()

    connection.close()

    queue = []

    for row in rows:

        item = row_to_case(
            row
        )

        queue.append({

            "case_id":
                item["case_id"],

            "patient":
                item.get("patient_name")
                or "Anonymous Patient",

            "location":
                item.get("location")
                or "Rural screening centre",

            "severity":
                item["severity"],

            "level":
                item["level"],

            "confidence":
                item["confidence"],

            "review_status":
                item.get("review_status")
                or "Pending",

            "priority":
                (
                    "High"
                    if item["level"] >= 3
                    else "Moderate"
                ),

            "destination":
                "District / specialist eye-care review",

            "created_at":
                item.get("created_at")
        })

    return jsonify({

        "success":
            True,

        "queue":
            queue,

        "count":
            len(queue),

        "workflow":
            [
                "Screened",
                "AI Flagged",
                "Remote Review",
                "Referral",
                "Specialist Follow-up"
            ],

        "prototype":
            True
    })


# ============================================================
# REPORT JSON
# ============================================================

@app.route(
    "/api/reports/<int:case_id>"
)
def report(case_id):

    report_data = create_report_data(
        case_id
    )

    if not report_data:

        return jsonify({
            "error":
                "Case not found."
        }), 404

    return jsonify({

        "success":
            True,

        "report":
            report_data
    })


# ============================================================
# PDF GENERATION
# ============================================================

def build_pdf(case_id):

    if not REPORTLAB_AVAILABLE:

        raise RuntimeError(
            "ReportLab is not installed. "
            "Run: /usr/local/bin/python3.14 "
            "-m pip install reportlab"
        )

    row = get_case(
        case_id
    )

    if not row:

        raise FileNotFoundError(
            "Case not found."
        )

    report_data = create_report_data(
        case_id
    )

    pdf_path = (
        REPORT_DIR
        / f"NETRA_Case_{case_id}.pdf"
    )

    document = SimpleDocTemplate(

        str(pdf_path),

        pagesize=A4,

        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,

        title=f"NETRA Case {case_id}",

        author="NETRA"
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "NetraTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontSize=18,
        leading=22,
        spaceAfter=10
    )

    subtitle_style = ParagraphStyle(
        "NetraSubtitle",
        parent=styles["Normal"],
        alignment=TA_CENTER,
        fontSize=9,
        textColor=colors.grey,
        spaceAfter=18
    )

    heading_style = ParagraphStyle(
        "NetraHeading",
        parent=styles["Heading2"],
        fontSize=12,
        leading=15,
        spaceBefore=10,
        spaceAfter=7
    )

    body_style = ParagraphStyle(
        "NetraBody",
        parent=styles["BodyText"],
        fontSize=9,
        leading=13,
        spaceAfter=6
    )

    small_style = ParagraphStyle(
        "NetraSmall",
        parent=styles["BodyText"],
        fontSize=7.5,
        leading=10,
        textColor=colors.grey
    )

    story = []

    story.append(
        Paragraph(
            "NETRA — Explainable Retinal AI",
            title_style
        )
    )

    story.append(
        Paragraph(
            "Retinal Screening & Rural Telemedicine Report",
            subtitle_style
        )
    )

    patient = report_data["patient"]
    screening = report_data["screening"]
    review = report_data["clinical_review"]

    # --------------------------------------------------------
    # PATIENT INFORMATION
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "Patient Information",
            heading_style
        )
    )

    patient_table = Table(
        [
            ["Case ID", str(report_data["case_id"])],
            ["Patient", patient["name"]],
            ["Age", str(patient["age"])],
            ["Sex", patient["sex"]],
            ["Location", patient["location"]],
            [
                "Screened",
                str(
                    report_data["timestamps"]["created_at"]
                    or ""
                )
            ]
        ],
        colWidths=[120, 360]
    )

    patient_table.setStyle(
        TableStyle([
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.lightgrey
            ),

            (
                "BACKGROUND",
                (0, 0),
                (0, -1),
                colors.whitesmoke
            ),

            (
                "FONTNAME",
                (0, 0),
                (0, -1),
                "Helvetica-Bold"
            ),

            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                8.5
            ),

            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "TOP"
            ),

            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                6
            ),

            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                6
            )
        ])
    )

    story.append(
        patient_table
    )

    story.append(
        Spacer(1, 10)
    )

    # --------------------------------------------------------
    # SCREENING SUMMARY
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "Screening Summary",
            heading_style
        )
    )

    screening_table = Table(
        [
            [
                "Screening Result",
                screening["severity"]
            ],

            [
                "Clinical Scale Level",
                f"Level {screening['level']}"
            ],

            [
                "Displayed Confidence",
                f"{screening['confidence'] * 100:.1f}%"
            ],

            [
                "Image Quality",
                screening["image_quality"]
            ],

            [
                "Referral Flag",
                screening["referral"]
            ],

            [
                "Review Status",
                review["status"]
            ]
        ],
        colWidths=[180, 300]
    )

    screening_table.setStyle(
        TableStyle([
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.lightgrey
            ),

            (
                "BACKGROUND",
                (0, 0),
                (0, -1),
                colors.whitesmoke
            ),

            (
                "FONTNAME",
                (0, 0),
                (0, -1),
                "Helvetica-Bold"
            ),

            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                8.5
            ),

            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                6
            ),

            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                6
            )
        ])
    )

    story.append(
        screening_table
    )

    # --------------------------------------------------------
    # EXPLAINABILITY
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "Explainability Evidence",
            heading_style
        )
    )

    for evidence in report_data[
        "explainability"
    ]["evidence"]:

        story.append(
            Paragraph(
                f"• {evidence}",
                body_style
            )
        )

    story.append(
        Paragraph(
            report_data[
                "explainability"
            ]["explanation"],
            body_style
        )
    )

    # --------------------------------------------------------
    # ORIGINAL IMAGE
    # --------------------------------------------------------

    if row["image_path"]:

        original_path = Path(
            row["image_path"]
        )

        if original_path.exists():

            try:

                story.append(
                    Paragraph(
                        "Retinal Image",
                        heading_style
                    )
                )

                image = RLImage(
                    str(original_path),
                    width=420,
                    height=300,
                    kind="proportional"
                )

                story.append(
                    image
                )

            except Exception:
                pass

    # --------------------------------------------------------
    # XAI
    # --------------------------------------------------------

    if row["xai_path"]:

        xai_path = Path(
            row["xai_path"]
        )

        if xai_path.exists():

            try:

                story.append(
                    Paragraph(
                        "Explainability Visualization",
                        heading_style
                    )
                )

                xai_image = RLImage(
                    str(xai_path),
                    width=420,
                    height=300,
                    kind="proportional"
                )

                story.append(
                    xai_image
                )

            except Exception:
                pass

    # --------------------------------------------------------
    # TELEMEDICINE
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "Rural Telemedicine Recommendation",
            heading_style
        )
    )

    telemedicine = report_data[
        "telemedicine"
    ]

    telemedicine_table = Table(
        [
            [
                "Remote Review Recommended",
                "Yes"
                if telemedicine["recommended"]
                else "No"
            ],

            [
                "Priority",
                telemedicine["priority"]
            ],

            [
                "Destination",
                telemedicine["destination"]
            ]
        ],
        colWidths=[210, 270]
    )

    telemedicine_table.setStyle(
        TableStyle([
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.lightgrey
            ),

            (
                "BACKGROUND",
                (0, 0),
                (0, -1),
                colors.whitesmoke
            ),

            (
                "FONTNAME",
                (0, 0),
                (0, -1),
                "Helvetica-Bold"
            ),

            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                8.5
            ),

            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                6
            ),

            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                6
            )
        ])
    )

    story.append(
        telemedicine_table
    )

    # --------------------------------------------------------
    # CLINICAL REVIEW
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "Clinical Review",
            heading_style
        )
    )

    reviewer = (
        review["reviewer"]
        or "Not assigned"
    )

    reviewer_notes = (
        review["notes"]
        or "No reviewer notes yet."
    )

    story.append(
        Paragraph(
            f"Reviewer: {reviewer}",
            body_style
        )
    )

    story.append(
        Paragraph(
            f"Notes: {reviewer_notes}",
            body_style
        )
    )

    # --------------------------------------------------------
    # DISCLAIMER
    # --------------------------------------------------------

    story.append(
        Spacer(1, 15)
    )

    story.append(
        Paragraph(
            report_data["notice"],
            small_style
        )
    )

    story.append(
        Spacer(1, 6)
    )

    story.append(
        Paragraph(
            "NETRA prototype • Explainable retinal screening • "
            "Hackathon demonstration",
            small_style
        )
    )

    document.build(
        story
    )

    return pdf_path


@app.route(
    "/api/reports/<int:case_id>/download"
)
def download_report(case_id):

    try:

        pdf_path = build_pdf(
            case_id
        )

    except FileNotFoundError:

        return jsonify({
            "error":
                "Case not found."
        }), 404

    except RuntimeError as error:

        return jsonify({
            "error":
                str(error)
        }), 500

    except Exception as error:

        return jsonify({

            "error":
                "Could not generate PDF report.",

            "details":
                str(error)
        }), 500

    return send_file(

        pdf_path,

        as_attachment=True,

        download_name=
            pdf_path.name,

        mimetype=
            "application/pdf"
    )


# ============================================================
# CSV EXPORT
# ============================================================

@app.route(
    "/api/export/cases.csv"
)
def export_cases():

    connection = get_db()

    rows = connection.execute(
        """
        SELECT

            id,
            patient_name,
            age,
            sex,
            location,
            severity,
            level,
            confidence,
            image_quality,
            referral,
            review_status,
            reviewer,
            reviewer_notes,
            created_at,
            updated_at

        FROM cases

        ORDER BY id DESC
        """
    ).fetchall()

    connection.close()

    output = io.StringIO()

    writer = csv.writer(
        output
    )

    writer.writerow([
        "Case ID",
        "Patient",
        "Age",
        "Sex",
        "Location",
        "Severity",
        "Level",
        "Confidence",
        "Image Quality",
        "Referral",
        "Review Status",
        "Reviewer",
        "Reviewer Notes",
        "Created At",
        "Updated At"
    ])

    for row in rows:

        writer.writerow([
            row["id"],
            row["patient_name"] or "",
            row["age"] or "",
            row["sex"] or "",
            row["location"] or "",
            row["severity"] or "",
            row["level"],
            row["confidence"],
            row["image_quality"] or "",
            row["referral"] or "",
            row["review_status"] or "",
            row["reviewer"] or "",
            row["reviewer_notes"] or "",
            row["created_at"] or "",
            row["updated_at"] or ""
        ])

    data = output.getvalue().encode(
        "utf-8"
    )

    return send_file(

        io.BytesIO(data),

        mimetype="text/csv",

        as_attachment=True,

        download_name=
            "NETRA_cases.csv"
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.route(
    "/api/dashboard"
)
def dashboard():

    connection = get_db()

    total = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM cases
        """
    ).fetchone()["count"]

    referable = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM cases
        WHERE level >= 2
        """
    ).fetchone()["count"]

    pending = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM cases
        WHERE review_status IN (
            'Pending',
            'Under Review'
        )
        """
    ).fetchone()["count"]

    connection.close()

    return jsonify({

        "success":
            True,

        "dashboard":
            {

                "total_screenings":
                    total,

                "referable_cases":
                    referable,

                "pending_reviews":
                    pending,

                "network_nodes":
                    len(
                        TELEMEDICINE_NETWORK
                    ),

                "telemedicine_enabled":
                    True,

                "reports_enabled":
                    REPORTLAB_AVAILABLE,

                "prototype_mode":
                    True
            }
    })


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(413)
def file_too_large(error):

    return jsonify({
        "error":
            "Uploaded file is too large."
    }), 413


@app.errorhandler(404)
def page_not_found(error):

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({
            "error":
                "API endpoint not found."
        }), 404

    return error


# ============================================================
# START
# ============================================================

initialize_database()


if __name__ == "__main__":

    print("=" * 60)

    print(
        "NETRA — Explainable Retinal AI"
    )

    print(
        "STEP 4 — REAL MODEL + GRAD-CAM BACKEND"
    )

    print("=" * 60)

    print(
        f"Project:  {BASE_DIR}"
    )

    print(
        f"Database: {DATABASE_PATH}"
    )

    print(
        f"Uploads:  {UPLOAD_DIR}"
    )

    print(
        f"Reports:  {REPORT_DIR}"
    )

    print(
        "PDF:      "
        + (
            "READY"
            if REPORTLAB_AVAILABLE
            else "NOT INSTALLED"
        )
    )

    print(
        "Real model: "
        + ("READY" if REAL_AI_AVAILABLE else "NOT FOUND")
    )

    print(
        "Grad-CAM: "
        + ("READY" if REAL_AI_AVAILABLE else "NOT AVAILABLE")
    )

    print(
        "Clinical validation: OFF"
    )

    print(
        "URL: http://127.0.0.1:5000/"
    )

    print("=" * 60)

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )