"""The student-facing AI assistant.

Providers sit behind one interface. The default needs no API key and no network,
so the demo always works; swap `MEDLY_ASSISTANT_PROVIDER` to use a real model.

Every provider's output goes through the same safety pipeline. A provider
cannot opt out of the disclaimer or the audit trail.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol

from app.config import settings

SYSTEM_PROMPT = """You are the study assistant inside Medly, a platform that teaches
medical students to use AI safely in radiology.

Your role is to teach. You explain concepts, reasoning and evidence.

You must never:
- diagnose a real patient, or interpret a real clinical image as if it were a diagnosis
- recommend a treatment, a drug or a dose for a real patient
- accept or repeat patient identifiers

When a student asks something that crosses those lines, say plainly that you are a
teaching tool and offer to explain the underlying reasoning instead.

Always name the limits of what you are saying. If you are unsure, say so. Being
uncertain out loud is the behaviour this platform exists to teach."""


@dataclass
class AssistantReply:
    content: str
    provider: str
    sources: Optional[List[str]] = None


class AssistantProvider(Protocol):
    name: str

    def reply(self, message: str, history: List[Dict[str, str]]) -> AssistantReply: ...


# --------------------------------------------------------------------------
# Offline provider. Curriculum-aware, keyed to the concepts the courses teach.
# --------------------------------------------------------------------------

KNOWLEDGE: List[Dict[str, object]] = [
    {
        "keys": ["automation bias", "over-reliance", "overreliance", "rubber stamp"],
        "answer": (
            "**Automation bias** is the tendency to accept a machine's suggestion even "
            "when your own judgement, or the evidence in front of you, says otherwise.\n\n"
            "It shows up in two directions:\n\n"
            "- **Commission** — you act on a wrong AI recommendation you would have caught yourself.\n"
            "- **Omission** — the AI stays silent, so you stop looking, and you miss the finding.\n\n"
            "The countermeasure this platform uses is sequencing: you record your own read "
            "*before* the model output is revealed. That way your interpretation is yours, and "
            "any disagreement becomes a learning moment instead of an invisible correction."
        ),
    },
    {
        "keys": ["sensitivity", "specificity", "ppv", "npv", "predictive value"],
        "answer": (
            "**Sensitivity** is the proportion of people *with* the condition the test "
            "correctly flags. **Specificity** is the proportion *without* it that it "
            "correctly clears.\n\n"
            "The trap with AI tools: vendors quote sensitivity and specificity, but what "
            "matters at the bedside is **positive predictive value**, and PPV depends on how "
            "common the condition is in *your* population.\n\n"
            "A model at 95% sensitivity and 95% specificity, applied where the condition "
            "affects 1 in 1,000, yields a PPV near 2%. Ninety-eight of every hundred alarms "
            "would be false. Same model, same numbers, completely different clinical meaning."
        ),
    },
    {
        "keys": ["dataset shift", "distribution shift", "generalis", "generaliz", "external validation"],
        "answer": (
            "**Dataset shift** is what happens when a model meets data that differs from "
            "what it was trained on — different scanner, different protocol, different "
            "population — and quietly gets worse.\n\n"
            "The well-known example: chest X-ray models that learned to read the portable "
            "scanner marker rather than the lungs. Sicker patients get portable films, so the "
            "shortcut scored well in training and collapsed elsewhere.\n\n"
            "What to ask before trusting any imaging model: where was it validated, on whose "
            "scanners, in what population, and was that validation external to the team that "
            "built it?"
        ),
    },
    {
        "keys": ["explainab", "saliency", "heatmap", "grad-cam", "gradcam", "interpretab"],
        "answer": (
            "**Saliency maps** show which pixels moved the model's output. They are useful "
            "and routinely over-read.\n\n"
            "A heatmap over the right lower lobe does not mean the model found consolidation "
            "there. It means those pixels influenced the score. Some published saliency methods "
            "produce similar-looking maps even when the model weights are randomised.\n\n"
            "Treat a heatmap as a prompt to look again at a region, never as an explanation "
            "of the model's reasoning."
        ),
    },
    {
        "keys": ["confidence", "calibrat", "probability", "uncertain"],
        "answer": (
            "A **calibrated** model is one where a stated 80% actually corresponds to being "
            "right about 80% of the time. Most deep networks are poorly calibrated out of the "
            "box and are systematically overconfident.\n\n"
            f"That is why this platform flags anything below "
            f"**{int(settings.low_confidence_threshold * 100)}%** as uncertain and routes it to "
            "a human rather than displaying it as a result.\n\n"
            "When you see a confidence number, ask what it was measured against. An uncalibrated "
            "0.94 tells you about the model's enthusiasm, not the patient."
        ),
    },
    {
        "keys": ["ethic", "consent", "gdpr", "hipaa", "privacy", "data protection"],
        "answer": (
            "Four questions worth asking of any clinical AI deployment:\n\n"
            "1. **Consent** — did the patients whose data trained this model agree to that use?\n"
            "2. **Accountability** — when the model is wrong, who is answerable? It is never the model.\n"
            "3. **Equity** — was performance measured separately across the groups it will be used on, "
            "or only in aggregate where a subgroup failure disappears?\n"
            "4. **Transparency** — does the patient know an AI was involved in their care?\n\n"
            "Identifiable data must not be sent to an external model without a lawful basis and a "
            "data processing agreement. This platform refuses identifiers outright rather than "
            "relying on you to remember."
        ),
    },
    {
        "keys": ["regulat", "ce mark", "fda", "clearance", "510k", "510(k)", "approval"],
        "answer": (
            "Most radiology AI reaches the market through pathways that compare it to an existing "
            "device rather than requiring a fresh clinical trial — FDA 510(k) in the US, CE marking "
            "under the MDR in Europe.\n\n"
            "Two consequences worth holding onto:\n\n"
            "- Clearance means *substantially equivalent to something already sold*. It does not "
            "mean a trial showed patients did better.\n"
            "- Clearance covers a stated intended use. Using the tool outside that scope — a "
            "different population, a different question — puts you outside the evidence and "
            "outside the approval."
        ),
    },
    {
        "keys": ["alara", "radiation", "dose", "shield"],
        "answer": (
            "**ALARA** — As Low As Reasonably Achievable. Every imaging request balances "
            "diagnostic benefit against radiation exposure.\n\n"
            "Rough comparison: a chest X-ray is around 0.1 mSv, a chest CT around 7 mSv, "
            "roughly seventy times more. Natural background is about 3 mSv a year.\n\n"
            "Where AI enters: models that reconstruct diagnostic images from lower-dose "
            "acquisitions genuinely reduce exposure, but they can also hallucinate plausible "
            "structure that was never in the raw data. Lower dose is not free."
        ),
    },
    {
        "keys": ["what is medly", "this platform", "how does this work", "what can you do"],
        "answer": (
            "Medly teaches medical students to work with AI safely rather than assuming they "
            "will pick it up on the job.\n\n"
            "- **Courses** cover how these models work, where they fail, and the ethics around them.\n"
            "- **Certification** must be passed before AI-assisted imaging features unlock.\n"
            "- **Every AI interaction is logged**, so instructors can see whether students are "
            "thinking or rubber-stamping.\n\n"
            "Ask me about automation bias, calibration, dataset shift, saliency maps, or the "
            "ethics of clinical AI and I will explain them."
        ),
    },
]

FALLBACK = (
    "I do not have a prepared explanation for that one.\n\n"
    "I am strongest on the topics this platform teaches: automation bias, sensitivity and "
    "specificity, calibration and confidence, dataset shift, saliency maps, the ethics and "
    "regulation of clinical AI, and radiation safety. Try me on one of those, or rephrase "
    "and I will have another go.\n\n"
    "For anything about a real patient, ask a supervising clinician. That is not what I am for."
)


class RuleBasedProvider:
    """Deterministic, offline, no API key. The default."""

    name = "rules"

    def reply(self, message: str, history: List[Dict[str, str]]) -> AssistantReply:
        text = message.lower()
        best: Optional[Dict[str, object]] = None
        best_score = 0

        for entry in KNOWLEDGE:
            keys = entry["keys"]
            assert isinstance(keys, list)
            score = sum(len(k) for k in keys if k in text)
            if score > best_score:
                best_score, best = score, entry

        if best is None:
            # Second pass: loose word overlap before giving up.
            words = set(re.findall(r"[a-z]{4,}", text))
            for entry in KNOWLEDGE:
                keys = entry["keys"]
                assert isinstance(keys, list)
                overlap = sum(1 for k in keys for w in words if w in k)
                if overlap > best_score:
                    best_score, best = overlap, entry

        content = str(best["answer"]) if best else FALLBACK
        return AssistantReply(content=content, provider=self.name)


class AnthropicProvider:
    """Real model. Requires ANTHROPIC_API_KEY and the `anthropic` package."""

    name = "anthropic"

    def reply(self, message: str, history: List[Dict[str, str]]) -> AssistantReply:
        try:
            import anthropic  # imported lazily so the default path needs no dependency
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pip install anthropic to use this provider") from exc

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        messages = [{"role": m["role"], "content": m["content"]} for m in history]
        messages.append({"role": "user", "content": message})
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        return AssistantReply(content=response.content[0].text, provider=self.name)


class OpenAIProvider:
    """Real model. Requires OPENAI_API_KEY and the `openai` package."""

    name = "openai"

    def reply(self, message: str, history: List[Dict[str, str]]) -> AssistantReply:
        try:
            from openai import OpenAI  # imported lazily
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pip install openai to use this provider") from exc

        client = OpenAI(api_key=settings.openai_api_key)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend({"role": m["role"], "content": m["content"]} for m in history)
        messages.append({"role": "user", "content": message})
        response = client.chat.completions.create(
            model="gpt-4o-mini", messages=messages, max_tokens=1024
        )
        return AssistantReply(content=response.choices[0].message.content or "", provider=self.name)


_PROVIDERS = {
    "rules": RuleBasedProvider,
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
}


def get_provider() -> AssistantProvider:
    provider_cls = _PROVIDERS.get(settings.assistant_provider, RuleBasedProvider)
    return provider_cls()


SUGGESTED_PROMPTS = [
    "What is automation bias?",
    "Why can a 95% accurate model still be wrong most of the time?",
    "What is dataset shift?",
    "Can I trust a saliency heatmap?",
    "What should I ask before using a clinical AI tool?",
]
