import io
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torchvision import models, transforms


# ============================================================
# NETRA — REAL GRAD-CAM
# EfficientNet-B0
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

MODEL_PATH = (
    BASE_DIR
    / "models"
    / "netra_dr_efficientnet_b0.pth"
)

CLASS_NAMES = [
    "No DR",
    "Mild NPDR",
    "Moderate NPDR",
    "Severe NPDR",
    "Proliferative DR",
]

IMAGE_SIZE = 224


# ============================================================
# DEVICE
# ============================================================

if torch.backends.mps.is_available():
    DEVICE = torch.device("mps")
elif torch.cuda.is_available():
    DEVICE = torch.device("cuda")
else:
    DEVICE = torch.device("cpu")


# ============================================================
# MODEL
# ============================================================

def build_model():
    """
    Build the same EfficientNet-B0 architecture used
    during NETRA training.
    """

    model = models.efficientnet_b0(
        weights=None
    )

    input_features = (
        model.classifier[1].in_features
    )

    model.classifier[1] = torch.nn.Linear(
        input_features,
        5
    )

    checkpoint = torch.load(
        MODEL_PATH,
        map_location=DEVICE
    )

    # Support either a plain state_dict or a
    # checkpoint dictionary.
    if isinstance(checkpoint, dict):

        if "model_state_dict" in checkpoint:
            state_dict = checkpoint["model_state_dict"]

        elif "state_dict" in checkpoint:
            state_dict = checkpoint["state_dict"]

        else:
            state_dict = checkpoint

    else:
        state_dict = checkpoint

    # Remove DataParallel prefix if present.
    cleaned_state_dict = {}

    for key, value in state_dict.items():

        if key.startswith("module."):
            key = key[7:]

        cleaned_state_dict[key] = value

    model.load_state_dict(
        cleaned_state_dict,
        strict=True
    )

    model.to(DEVICE)
    model.eval()

    return model


# ============================================================
# IMAGE TRANSFORM
# ============================================================

transform = transforms.Compose([
    transforms.Resize(
        (IMAGE_SIZE, IMAGE_SIZE)
    ),

    transforms.ToTensor(),

    transforms.Normalize(
        mean=[
            0.485,
            0.456,
            0.406
        ],
        std=[
            0.229,
            0.224,
            0.225
        ]
    )
])


# ============================================================
# GRAD-CAM ENGINE
# ============================================================

class GradCAM:

    def __init__(self, model):

        self.model = model

        self.activations = None
        self.gradients = None

        # EfficientNet-B0 final convolutional
        # feature layer.
        self.target_layer = (
            self.model.features[-1]
        )

        self.forward_hook = (
            self.target_layer.register_forward_hook(
                self._save_activation
            )
        )

        self.backward_hook = (
            self.target_layer.register_full_backward_hook(
                self._save_gradient
            )
        )


    def _save_activation(
        self,
        module,
        input_data,
        output
    ):

        self.activations = output


    def _save_gradient(
        self,
        module,
        grad_input,
        grad_output
    ):

        self.gradients = grad_output[0]


    def generate(
        self,
        image
    ):

        """
        Generate Grad-CAM for a PIL image.

        Returns:

            heatmap
            predicted_class
            confidence
            probabilities
        """

        if not isinstance(
            image,
            Image.Image
        ):
            raise TypeError(
                "image must be a PIL.Image.Image"
            )

        image = image.convert("RGB")

        tensor = transform(
            image
        ).unsqueeze(0).to(
            DEVICE
        )

        self.model.zero_grad(
            set_to_none=True
        )

        output = self.model(
            tensor
        )

        probabilities = F.softmax(
            output,
            dim=1
        )

        predicted_class = int(
            torch.argmax(
                probabilities,
                dim=1
            ).item()
        )

        confidence = float(
            probabilities[
                0,
                predicted_class
            ].item()
        )

        target_score = output[
            0,
            predicted_class
        ]

        target_score.backward()

        if self.activations is None:
            raise RuntimeError(
                "Grad-CAM activation was not captured."
            )

        if self.gradients is None:
            raise RuntimeError(
                "Grad-CAM gradients were not captured."
            )

        activations = (
            self.activations.detach()
        )

        gradients = (
            self.gradients.detach()
        )

        # Global average pooling over spatial
        # dimensions.
        weights = gradients.mean(
            dim=(2, 3),
            keepdim=True
        )

        cam = (
            weights * activations
        ).sum(
            dim=1,
            keepdim=True
        )

        cam = F.relu(
            cam
        )

        cam = F.interpolate(
            cam,
            size=(
                image.height,
                image.width
            ),
            mode="bilinear",
            align_corners=False
        )

        cam = cam[
            0,
            0
        ]

        cam_min = cam.min()
        cam_max = cam.max()

        cam = (
            cam - cam_min
        ) / (
            cam_max - cam_min + 1e-8
        )

        heatmap = (
            cam.cpu()
            .numpy()
            .astype(np.float32)
        )

        probabilities = (
            probabilities[
                0
            ]
            .detach()
            .cpu()
            .numpy()
        )

        return (
            heatmap,
            predicted_class,
            confidence,
            probabilities
        )


    def close(self):

        try:
            self.forward_hook.remove()
        except Exception:
            pass

        try:
            self.backward_hook.remove()
        except Exception:
            pass


# ============================================================
# HEATMAP CREATION
# ============================================================

def create_heatmap_image(
    original_image,
    heatmap,
    alpha=0.45
):

    """
    Convert a Grad-CAM matrix into a visual
    heatmap overlay.

    The heatmap is generated from the model's
    actual gradients and activations.
    """

    original = (
        original_image
        .convert("RGB")
        .resize(
            (
                heatmap.shape[1],
                heatmap.shape[0]
            )
        )
    )

    heatmap_uint8 = (
        heatmap * 255
    ).clip(
        0,
        255
    ).astype(
        np.uint8
    )

    # Red/yellow style intensity map using
    # PIL's built-in color mapping approach.
    heatmap_rgb = np.zeros(
        (
            heatmap_uint8.shape[0],
            heatmap_uint8.shape[1],
            3
        ),
        dtype=np.uint8
    )

    # Blue -> cyan -> yellow -> red style.
    value = heatmap_uint8.astype(
        np.float32
    ) / 255.0

    heatmap_rgb[:, :, 0] = (
        np.clip(
            value * 2.0,
            0,
            1
        ) * 255
    ).astype(np.uint8)

    heatmap_rgb[:, :, 1] = (
        np.clip(
            2.0 - np.abs(
                2.0 * value - 1.0
            ) * 2.0,
            0,
            1
        ) * 255
    ).astype(np.uint8)

    heatmap_rgb[:, :, 2] = (
        np.clip(
            1.0 - value * 2.0,
            0,
            1
        ) * 255
    ).astype(np.uint8)

    heatmap_image = Image.fromarray(
        heatmap_rgb,
        mode="RGB"
    )

    blended = Image.blend(
        original,
        heatmap_image,
        alpha
    )

    return blended


# ============================================================
# SCREENING HELPER
# ============================================================

def analyze_image(
    image_bytes
):

    """
    Complete standalone NETRA Grad-CAM analysis.

    Returns a dictionary containing:

        level
        severity
        confidence
        probabilities
        heatmap
    """

    image = Image.open(
        io.BytesIO(image_bytes)
    ).convert("RGB")

    model = build_model()

    gradcam = GradCAM(
        model
    )

    try:

        (
            heatmap,
            predicted_class,
            confidence,
            probabilities
        ) = gradcam.generate(
            image
        )

        visualization = (
            create_heatmap_image(
                image,
                heatmap
            )
        )

        return {
            "level":
                predicted_class,

            "severity":
                CLASS_NAMES[
                    predicted_class
                ],

            "confidence":
                round(
                    confidence,
                    4
                ),

            "probabilities": {
                CLASS_NAMES[index]:
                    round(
                        float(
                            probability
                        ),
                        4
                    )
                for index, probability
                in enumerate(
                    probabilities
                )
            },

            "heatmap":
                visualization,

            "heatmap_array":
                heatmap
        }

    finally:

        gradcam.close()


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print("=" * 70)
    print("NETRA — REAL GRAD-CAM TEST")
    print("=" * 70)

    print()
    print(
        f"Model: {MODEL_PATH}"
    )

    print(
        f"Device: {DEVICE}"
    )

    print()

    if not MODEL_PATH.exists():

        print(
            "ERROR: trained model was not found."
        )

        print(
            f"Expected: {MODEL_PATH}"
        )

        raise SystemExit(1)

    print(
        "✓ Trained model found."
    )

    print()
    print(
        "Loading EfficientNet-B0..."
    )

    model = build_model()

    print(
        "✓ Model loaded."
    )

    print()

    print(
        "Grad-CAM target layer:"
    )

    print(
        f"  {model.features[-1]}"
    )

    print()

    print(
        "✓ Real Grad-CAM engine initialized."
    )

    print()
    print(
        "Step 3 component is ready."
    )

    print("=" * 70)