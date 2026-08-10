"""Imaging inference, behind a swappable interface.

The engine that ships is simulated. It is deterministic per case reference, so
a demo behaves the same every run, and it deliberately produces a low-confidence
case so the safety path is visible rather than theoretical.

To use a real model later, implement `InferenceEngine` and register it in
`get_engine()`. Nothing else in the codebase changes.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import asdict, dataclass
from typing import Dict, List, Protocol

from app.config import settings
from app.models.enums import Modality


@dataclass
class Finding:
    label: str
    confidence: float
    # Normalised [x, y, w, h] in 0..1 so the frontend can overlay at any size.
    bbox: List[float]
    description: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class InferenceResult:
    findings: List[Finding]
    model_name: str
    model_version: str
    # What the model was trained on. Required by the standard: a user must be
    # able to see whether the model was ever validated on people like theirs.
    training_data: str
    known_limitations: List[str]


class InferenceEngine(Protocol):
    """Implement this to plug in a real model."""

    name: str
    version: str

    def analyze(self, case_ref: str, modality: Modality) -> InferenceResult: ...


# --------------------------------------------------------------------------

XRAY_LABELS = [
    ("Consolidation", "Airspace opacity, right lower zone"),
    ("Pleural effusion", "Blunting of the costophrenic angle"),
    ("Cardiomegaly", "Cardiothoracic ratio above 0.5"),
    ("Pneumothorax", "Visible pleural line with absent lung markings"),
    ("Pulmonary nodule", "Rounded opacity under 3 cm"),
    ("No acute finding", "No focal abnormality identified"),
]

CT_LABELS = [
    ("Ground-glass opacity", "Hazy increased attenuation, preserved margins"),
    ("Pulmonary embolism", "Filling defect in a segmental artery"),
    ("Hepatic lesion", "Hypodense focus in segment VI"),
    ("Lymphadenopathy", "Short-axis node above 10 mm"),
    ("No acute finding", "No acute intracranial or thoracic abnormality"),
]

LIMITATIONS = [
    "Trained on adult chest imaging only; not validated in paediatrics.",
    "Training data was predominantly from two North American centres, so "
    "performance on other populations and equipment is unmeasured.",
    "Performs poorly on rotated, under-penetrated or portable films.",
    "Cannot see prior imaging, so it cannot judge whether a finding is new.",
    "Never validated prospectively against clinical outcomes.",
]


class MockInferenceEngine:
    """Deterministic simulated engine. Same case reference, same result."""

    name = "medly-sim-cxr"
    version = "0.3.0-simulated"

    def analyze(self, case_ref: str, modality: Modality) -> InferenceResult:
        seed = int(hashlib.sha256(f"{case_ref}:{modality.value}".encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)

        labels = XRAY_LABELS if modality == Modality.XRAY else CT_LABELS
        count = rng.choice([1, 1, 2, 2, 3])
        chosen = rng.sample(labels, min(count, len(labels)))

        # One case in four is deliberately uncertain, so students meet the
        # low-confidence path during training rather than in a hospital.
        uncertain_case = seed % 4 == 0

        findings: List[Finding] = []
        for label, description in chosen:
            if uncertain_case:
                confidence = round(rng.uniform(0.42, 0.68), 3)
            else:
                confidence = round(rng.uniform(0.74, 0.96), 3)
            findings.append(
                Finding(
                    label=label,
                    confidence=confidence,
                    bbox=[
                        round(rng.uniform(0.08, 0.55), 3),
                        round(rng.uniform(0.08, 0.55), 3),
                        round(rng.uniform(0.15, 0.35), 3),
                        round(rng.uniform(0.15, 0.35), 3),
                    ],
                    description=description,
                )
            )

        findings.sort(key=lambda f: f.confidence, reverse=True)
        return InferenceResult(
            findings=findings,
            model_name=self.name,
            model_version=self.version,
            training_data="Simulated. No real patient data was used at any point.",
            known_limitations=LIMITATIONS,
        )


class OnnxInferenceEngine:
    """Placeholder for a real model. Raises until weights are supplied."""

    name = "onnx-runtime"
    version = "unconfigured"

    def analyze(self, case_ref: str, modality: Modality) -> InferenceResult:
        raise NotImplementedError(
            "Set MEDLY_ONNX_MODEL_PATH and implement OnnxInferenceEngine.analyze "
            "to run a real model. The interface is identical to MockInferenceEngine."
        )


_ENGINES = {"mock": MockInferenceEngine, "onnx": OnnxInferenceEngine}


def get_engine() -> InferenceEngine:
    engine_cls = _ENGINES.get(settings.inference_engine, MockInferenceEngine)
    return engine_cls()
