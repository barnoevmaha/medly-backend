"""Seed data for the feed, library, communities, challenges and casebook.

Kept out of seed.py so the curriculum and the product content can be read
separately. Every function here is idempotent: it looks for its rows by slug and
returns early if they exist, so `run()` can be called on every boot.

No real patient data appears anywhere in this file. The imaging cases are
synthetic by construction and carry `source="synthetic"`.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Dict, List

from sqlmodel import Session, select

from app.models.casebook import CaseImage, CaseReference
from app.models.challenge import (
    Challenge,
    ChallengeChoice,
    ChallengeQuestion,
)
from app.models.community import Community, CommunityMessage
from app.models.enums import Modality, Role
from app.models.social import (
    Article,
    ArticleComment,
    ArticleLike,
    Resource,
    SavedItem,
)
from app.models.user import User

NOW = datetime.utcnow()


# ==========================================================================
# Feed articles — each one has a real body, not a card and a placeholder
# ==========================================================================

ARTICLES = [
    {
        "slug": "post-concussion-syndrome-when-symptoms-persist",
        "tag": "Neurology",
        "title": "Post-Concussion Syndrome: When Symptoms Don't Go Away",
        "author": "Dr Neil Graham",
        "author_role": "Consultant neurologist \u2014 concussion, TBI and dementia, Central London",
        "read_minutes": 6,
        "base_likes": 0,
        "hours_ago": 2,
        "cover": "/covers/articles/post-concussion-syndrome-when-symptoms-persist.jpg",
        "cover_orientation": "landscape",
        "excerpt": (
            "A concussion usually settles within a few weeks. For a significant minority it "
            "does not \u2014 and the severity of the original injury turns out to be a poor "
            "guide to who those people will be."
        ),
        "body_md": '''A concussion \u2014 a *mild traumatic brain injury* (mTBI) \u2014 typically resolves within a few weeks. For a significant number of people, the physical, cognitive and psychological effects persist for months or even years.

When neurological symptoms fail to clear within the expected timeframe, they can severely disrupt someone's ability to work, study and maintain relationships. This article outlines how post-concussion syndrome develops, when to seek specialist advice, and the therapeutic pathways available.

## What are the symptoms after mild TBI?

Symptoms after mild TBI, sometimes termed *post-concussion syndrome*, are highly varied and typically span physical, cognitive and emotional categories. They can appear immediately after the head injury or emerge days later, and often fluctuate in intensity depending on physical exertion or mental focus.

- **Physical:** persistent headaches (frequently resembling migraine or tension headache), dizziness, nausea, light and sound sensitivity, and fatigue.
- **Cognitive:** difficulty concentrating, brain fog, short-term memory deficits, slowed information processing, reduced ability to multitask.
- **Emotional and behavioural:** irritability, anxiety, low mood, emotional sensitivity.
- **Sleep:** insomnia, fragmented sleep, or an excessive need for sleep during the day.

## Why do symptoms persist?

Studies suggest that as many as half of people may not be fully recovered six months after a so-called mild TBI. The underlying mechanisms are complex and multi-faceted, bringing together the direct physical effects of injury \u2014 disruption to brain tissue \u2014 and difficulties with brain function that do not directly reflect damage, such as psychological problems. The brain's ability to process information efficiently can become impaired, producing a wide array of symptoms that fluctuate with daily activity levels.

Research shows that the severity of the initial head injury does not necessarily predict who will develop chronic symptoms. A history of previous concussions, pre-existing migraine, or pre-injury psychiatric problems can each increase vulnerability to prolonged recovery.

## When should someone seek a specialist neurological assessment?

Follow the standard advice after a possible TBI first, so that no emergency problem is missed \u2014 see the [NHS guidance on head injury and concussion](https://www.nhs.uk/conditions/head-injury-and-concussion/).

Where problems are ongoing, a head-injury specialist neurologist can help. A specialist examination reviews the injury in detail and evaluates a range of neurological systems: cognition, psychiatric symptoms, sleep, and vestibular function (balance and spatial orientation). Because standard CT scans often appear completely normal following a mild head injury, it is the detailed clinical history and specialised symptom assessment that establish an accurate management plan.

## Management and rehabilitation pathways

Modern management of persistent post-concussive symptoms has shifted away from prolonged dark-room rest towards targeted, active rehabilitation, tailored to each patient's symptom profile.

- **Sub-symptom threshold exercise** \u2014 carefully controlled, gradual cardiovascular training that restores normal autonomic function and improves blood flow to the brain without triggering symptoms.
- **Vestibular and ocular therapy** \u2014 specialised physical therapy that retrains the integration of visual and balance signals, directly reducing dizziness and nausea.
- **Cognitive rehabilitation** \u2014 structured strategies and pacing techniques, guided by neuropsychologists, for memory deficits, attention difficulties and mental fatigue.
- **Pharmacological support** \u2014 targeted medication for post-traumatic headache, sleep disturbance or associated mood change.

## What is the long-term outlook?

The outlook is highly encouraging where care is structured and specialist-guided. The brain possesses a remarkable capacity for neuroplasticity \u2014 the ability to adapt, reorganise and forge new neural pathways over time. Working with a specialist neurologist, people can successfully manage their symptoms, regain control over daily life, and return to their personal and professional goals.

## References

- National Institute for Health and Care Excellence (NICE). *Head injury: assessment and early management* (NG232), 2024.
- *UK Concussion Guidelines for Non-Elite (Grassroots) Sport.*
- Leddy JJ, et al. Rest and exercise early after sport-related concussion: a systematic review and meta-analysis. *Br J Sports Med* 2023;57(12):762\u2013770. doi:10.1136/bjsports-2022-106676
- Woodrow RE, et al. Acute thalamic connectivity precedes chronic postconcussive symptoms in mild traumatic brain injury. *Brain*, 26 April 2023. doi:10.1093/brain/awad056

---

*Written in association with Dr Neil Graham, consultant neurologist specialising in concussion, traumatic brain injury (TBI) and dementia in Central London. Published 28/05/2026; edited by Karolyn Judge, 05/06/2026.*''',
    },
    {
        "slug": "autoimmune-encephalitis-and-the-brain-under-attack",
        "tag": "Neurology",
        "title": "Autoimmune Encephalitis: When the Immune System Attacks the Brain",
        "author": "Dr James Varley",
        "author_role": "Neurologist, Central London",
        "read_minutes": 4,
        "base_likes": 0,
        "hours_ago": 6,
        "cover": "/covers/articles/autoimmune-encephalitis-and-the-brain-under-attack.jpg",
        "cover_orientation": "landscape",
        "excerpt": (
            "Confusion, memory loss and a personality change that arrives over days. The "
            "presentation resembles psychiatric illness closely enough that the diagnosis is "
            "often reached late \u2014 and treatment works best when it is reached early."
        ),
        "body_md": '''Autoimmune encephalitis is a group of conditions in which the body's immune system mistakenly attacks healthy brain cells, causing inflammation of the brain. It can affect people of all ages, though certain types are more common in young adults and children. Because the brain governs behaviour, memory and bodily function, that inflammation produces a wide range of symptoms which often appear suddenly and progress rapidly.

## How it presents

Common early signs include confusion, memory loss, and changes in personality or behaviour. Individuals may become anxious or paranoid, or experience hallucinations.

As the condition advances, more severe neurological symptoms can develop: seizures, difficulty speaking, abnormal movements, or loss of consciousness. In some cases patients require intensive care because of complications affecting breathing or heart function.

## The antibodies involved

Autoimmune encephalitis is often associated with antibodies that target specific proteins in the brain. One well-known form involves antibodies against NMDA (N-methyl-D-aspartate) receptors, which disrupt normal brain signalling and produce the characteristic symptoms.

The condition can sometimes be linked to tumours \u2014 particularly ovarian teratomas \u2014 though many cases occur with no identifiable trigger.

## Why diagnosis is difficult

Diagnosis is challenging because the symptoms may resemble psychiatric disorders or viral infections. Clinicians typically rely on a combination of clinical evaluation, brain imaging, spinal fluid analysis and blood tests to detect specific antibodies.

Early diagnosis matters: prompt treatment significantly improves outcomes.

## Treatment

Treatment usually involves immunotherapy to reduce the immune system's attack on the brain. This may include corticosteroids, intravenous immunoglobulin (IVIG), or plasma exchange. Where a tumour is implicated, surgical removal is often necessary.

With timely treatment many patients recover well, though rehabilitation may be needed to address lingering cognitive or physical difficulties. Ongoing research continues to improve understanding and management of this complex condition.

---

*Written in association with Dr James Varley, neurologist in Central London. Published 18/06/2026; edited by Conor Lynch, 18/06/2026.*''',
    },
    {
        "slug": "oncology-must-confront-hidden-side-effects",
        "tag": "Oncology",
        "title": "Oncology Must Confront Hidden Side Effects",
        "author": "Nature Medicine",
        "author_role": "Editorial \u2014 Nature Medicine",
        "read_minutes": 5,
        "base_likes": 0,
        "hours_ago": 10,
        "cover": "/covers/articles/oncology-must-confront-hidden-side-effects.jpg",
        "cover_orientation": "landscape",
        "excerpt": (
            "Cancer therapy has become dramatically more targeted, and patients are living "
            "longer. The systems for recording what those therapies cost patients day to day "
            "have not kept pace."
        ),
        "body_md": '''> **About this piece.** This is a summary of the *Nature Medicine* editorial "Oncology must confront hidden side effects" (doi:[10.1038/s41591-026-04554-9](https://doi.org/10.1038/s41591-026-04554-9)), included here for teaching. Read the original for the full argument and its citations.

Recent breakthroughs in cancer therapy \u2014 immunotherapies, antibody\u2013drug conjugates and bispecific antibodies \u2014 have transformed oncology care. Treatment is more precisely targeted to a patient's tumour, and overall survival is lengthening. But people who survive cancer can face lifelong challenges from treatment-induced toxicities with both short- and long-term effects, and the editorial's argument is that the tooling for recording and managing those effects has not innovated at the same pace as the drugs.

## What current reporting misses

Trial reporting leans on CTCAE grading, which was not designed to capture functional and psychological disruption. Impaired daily functioning and emotional wellbeing therefore sit outside the framework \u2014 they are, in the editorial's word, *hidden* from prescribing clinicians in the first years after a therapy rolls out.

Full quality-of-life data, which would cover daily functioning and emotional wellbeing, frequently goes undisclosed because follow-up is short. The consequence is practical: patients may be less accepting of new agents when the expected toxicities cannot be described to them, because those toxicities are unknown, underappreciated, or their severity is underestimated.

## Why the gaps persist

Two structural problems compound the measurement gap.

1. **Exposure takes time.** Some toxicities \u2014 certain skin toxicities among them \u2014 only come to light once a broader patient population has been exposed to the drug. Early trial populations are too small and too selected to surface them.
2. **Disciplines are siloed.** Historical siloing limits knowledge transfer about how to detect, monitor and manage therapy-induced toxicity. Cytokine release syndrome in CAR T cell therapy and immune-related adverse events in checkpoint inhibition are the examples given \u2014 syndromes that demand expertise which may sit in a different department entirely.

As therapies are implemented across more cancer types, rare treatment-induced syndromes become more likely to appear, and coordinated research into their mechanisms is what would let clinicians mitigate the risk and develop better-targeted treatments.

## Why this matters for training

The editorial is a reminder that a treatment's record is incomplete until someone has asked the patient how they are actually functioning \u2014 and that a grading scale which does not ask cannot report the answer. For anyone learning to appraise oncology evidence, the useful habit is to check what a trial measured before accepting what it concluded about tolerability.

---

*Source: Editorial, "Oncology must confront hidden side effects", Nature Medicine. doi:10.1038/s41591-026-04554-9*''',
    },
]


# ==========================================================================
# Library resources — books, PDFs and videos, all saveable
# ==========================================================================

RESOURCES = [
    # Books ---------------------------------------------------------------
    {"slug": "grays-anatomy-for-students", "kind": "book", "title": "Gray's Anatomy for Students",
     "author": "Richard Drake", "rating": 4.9, "downloads": "45,200", "premium": True,
     "cover_hue": 210, "publisher": "Elsevier", "year": 2023, "pages": 1180,
     "level": "foundation", "topic": "Anatomy",
     "description": "Regional anatomy organised the way dissection is taught, with clinical correlations at the end of every section."},
    {"slug": "intro-clinical-medicine", "kind": "book", "title": "Introduction to Clinical Medicine",
     "author": "Dr. James Anderson", "rating": 4.7, "downloads": "23,100", "premium": False,
     "cover_hue": 168, "publisher": "Medly Press", "year": 2024, "pages": 640,
     "level": "clinical", "topic": "Clinical skills",
     "description": "History taking, examination and clinical reasoning for the first ward year."},
    {"slug": "harrisons-internal-medicine", "kind": "book", "title": "Harrison's Principles of Internal Medicine",
     "author": "J. Larry Jameson", "rating": 4.9, "downloads": "67,800", "premium": False,
     "cover_hue": 260, "publisher": "McGraw Hill", "year": 2022, "pages": 4048,
     "level": "advanced", "topic": "Internal medicine",
     "description": "The reference text for adult internal medicine, disease by disease."},
    {"slug": "robbins-basic-pathology", "kind": "book", "title": "Robbins Basic Pathology",
     "author": "Vinay Kumar", "rating": 4.8, "downloads": "54,300", "premium": True,
     "cover_hue": 4, "publisher": "Elsevier", "year": 2022, "pages": 952,
     "level": "foundation", "topic": "Pathology",
     "description": "Mechanism-first pathology, from cell injury through to systemic disease."},
    {"slug": "clinical-ai-primer", "kind": "book", "title": "A Clinician's Primer on Machine Learning",
     "author": "Dr. Amara Okafor", "rating": 4.6, "downloads": "9,800", "premium": False,
     "cover_hue": 190, "publisher": "Medly Press", "year": 2025, "pages": 288,
     "level": "foundation", "topic": "Clinical AI",
     "description": "What models do, how they fail, and what to ask before trusting one in a clinic."},

    # PDFs ----------------------------------------------------------------
    {"slug": "pathophysiology-study-guide", "kind": "pdf", "title": "Pathophysiology Study Guide",
     "author": "Medical Education Team", "rating": 4.8, "downloads": "18,500", "premium": True,
     "cover_hue": 32, "publisher": "Medly Press", "year": 2025, "pages": 96,
     "level": "foundation", "topic": "Pathology",
     "description": "Condensed mechanisms with worked clinical correlations."},
    {"slug": "pharmacology-quick-reference", "kind": "pdf", "title": "Pharmacology Quick Reference",
     "author": "PharmEd Solutions", "rating": 4.5, "downloads": "31,200", "premium": True,
     "cover_hue": 288, "publisher": "PharmEd", "year": 2024, "pages": 48,
     "level": "clinical", "topic": "Pharmacology",
     "description": "Drug classes, mechanisms and interactions, one page each."},
    {"slug": "ecg-interpretation-checklist", "kind": "pdf", "title": "ECG Interpretation Checklist",
     "author": "Dr. Sarah Williams", "rating": 4.7, "downloads": "27,400", "premium": False,
     "cover_hue": 350, "publisher": "Medly Press", "year": 2025, "pages": 12,
     "level": "clinical", "topic": "Cardiology",
     "description": "The systematic order, the intervals, and the patterns you cannot miss."},
    {"slug": "chest-xray-review-areas", "kind": "pdf", "title": "Chest X-Ray Review Areas",
     "author": "Radiology Teaching Group", "rating": 4.8, "downloads": "15,900", "premium": False,
     "cover_hue": 200, "publisher": "Medly Press", "year": 2025, "pages": 8,
     "level": "clinical", "topic": "Radiology",
     "description": "A one-page search pattern and the five areas where findings hide."},
    {"slug": "ai-safety-checklist-imaging", "kind": "pdf", "title": "AI Safety Checklist for Imaging Deployment",
     "author": "Medly Governance", "rating": 4.9, "downloads": "6,100", "premium": False,
     "cover_hue": 150, "publisher": "Medly Press", "year": 2026, "pages": 6,
     "level": "advanced", "topic": "Clinical AI",
     "description": "Twelve questions to ask before an imaging model touches a patient."},

    # Videos --------------------------------------------------------------
    {"slug": "ecg-masterclass", "kind": "video", "orientation": "landscape", "title": "ECG Interpretation Masterclass",
     "author": "Dr. Sarah Williams", "rating": 4.6, "downloads": "12,400", "premium": False,
     "duration": "3h 20m", "cover_hue": 340, "publisher": "Medly Studio", "year": 2025,
     "level": "clinical", "topic": "Cardiology",
     "description": "Rate, rhythm, axis, intervals — then forty traces worked through live."},
    {"slug": "surgical-techniques-vol-1", "kind": "video", "orientation": "landscape", "title": "Surgical Techniques Vol. 1",
     "author": "Dr. Michael Chen", "rating": 4.7, "downloads": "8,900", "premium": False,
     "duration": "5h 10m", "cover_hue": 220, "publisher": "Medly Studio", "year": 2024,
     "level": "clinical", "topic": "Surgery",
     "description": "Knots, closure, instrument handling and theatre discipline for students."},
    {"slug": "reading-chest-films", "kind": "video", "orientation": "landscape", "title": "Reading Chest Films Under Pressure",
     "author": "Dr. Priya Nair", "rating": 4.8, "downloads": "10,300", "premium": True,
     "duration": "1h 45m", "cover_hue": 195, "publisher": "Medly Studio", "year": 2026,
     "level": "clinical", "topic": "Radiology",
     "description": "A search pattern that holds at 3am, with twenty on-call cases."},
    {"slug": "automation-bias-workshop", "kind": "video", "orientation": "landscape", "title": "Automation Bias: A Practical Workshop",
     "author": "Medly Safety Faculty", "rating": 4.9, "downloads": "4,700", "premium": False,
     "duration": "58m", "cover_hue": 40, "publisher": "Medly Studio", "year": 2026,
     "level": "advanced", "topic": "Clinical AI",
     "description": "Supervised practice at disagreeing with a confident, incorrect model."},
]


# ==========================================================================
# Communities — the description is the line under the title, and the only
# other field community search is allowed to match
# ==========================================================================

COMMUNITIES = [
    {"slug": "cardiology-club", "name": "Cardiology Club", "icon": "heart-pulse", "specialty": "Cardiology",
     "base_members": 12450,
     "description": "Cardiovascular medicine, ECG interpretation and heart failure management.",
     "messages": [
         ("Dr. Sarah Chen", "Posting the trace from this morning's teaching round below — 68M, chest pain, "
                            "look at leads II, III and aVF before you scroll."),
         ("James Wilson", "Inferior ST elevation with reciprocal change in aVL. Right-sided leads next?"),
         ("Dr. Sarah Chen", "Exactly right, and yes — V4R to check for RV involvement changes fluid management."),
         ("Emily Davis", "This is the third inferior MI this month where aVL was the giveaway. Reciprocal "
                         "change is underrated."),
     ]},
    {"slug": "radiology-residents", "name": "Radiology Residents", "icon": "scan", "specialty": "Radiology",
     "base_members": 5430,
     "description": "Image interpretation, diagnostic technique and daily teaching cases.",
     "messages": [
         ("Priya Nair", "Weekly reminder: commit your read before you open the AI overlay. We are collecting "
                        "override rates for the audit and they only mean something if the order holds."),
         ("Michael Brown", "Our override rate last month was 4%. Suspiciously low — I think we're anchoring."),
         ("Priya Nair", "That's exactly the number worth investigating. Low overrides can mean the model is "
                        "good or that nobody is really looking."),
     ]},
    {"slug": "neurology-network", "name": "Neurology Network", "icon": "brain", "specialty": "Neurology",
     "base_members": 8930,
     "description": "The nervous system, stroke pathways and neurological examination.",
     "messages": [
         ("Dr. Amara Okafor", "Door-to-needle audit is out. Median 41 minutes, down from 58."),
         ("Emily Davis", "What changed? Imaging turnaround or the pathway itself?"),
         ("Dr. Amara Okafor", "Mostly pre-alert. The scanner was never the bottleneck."),
     ]},
    {"slug": "surgery-society", "name": "Surgery Society", "icon": "scissors", "specialty": "Surgery",
     "base_members": 15200,
     "description": "Surgical technique, operative case discussion and theatre etiquette.",
     "messages": [
         ("Michael Brown", "Suturing practice session Thursday 6pm, pads provided, bring loupes if you have them."),
         ("James Wilson", "Can we cover subcuticular closure? Mine still looks like a crime scene."),
     ]},
    {"slug": "emergency-medicine", "name": "Emergency Medicine", "icon": "siren", "specialty": "Emergency",
     "base_members": 11200,
     "description": "Critical care, trauma management and emergency protocols.",
     "messages": [
         ("Dr. Michael Chen", "Reminder that the sepsis alert is decision support, not a diagnosis. Two "
                              "flagged patients last night were both dehydration."),
         ("Emily Davis", "How many alerts per shift are you seeing?"),
         ("Dr. Michael Chen", "Eleven. Which is the whole problem — at that rate people stop reading them."),
     ]},
    {"slug": "pediatrics-pals", "name": "Pediatrics Pals", "icon": "baby", "specialty": "Paediatrics",
     "base_members": 7650,
     "description": "Child health, developmental milestones and paediatric emergencies.",
     "messages": [
         ("Emily Davis", "Weight-based dosing drill posted. Ten scenarios, no calculator on the first pass."),
     ]},
    {"slug": "internal-medicine", "name": "Internal Medicine", "icon": "stethoscope", "specialty": "Internal Medicine",
     "base_members": 18900,
     "description": "Adult medicine, diagnostic reasoning and chronic disease management.",
     "messages": [
         ("James Wilson", "Case: 54F, three weeks of fatigue, normocytic anaemia, raised ferritin. Where are "
                          "you going next?"),
         ("Priya Nair", "Ferritin is an acute phase reactant — I'd want CRP and a transferrin saturation "
                        "before calling it iron overload."),
     ]},
    {"slug": "ai-in-medicine", "name": "AI in Medicine", "icon": "cpu", "specialty": "Informatics",
     "base_members": 3120,
     "description": "Clinical AI, model evaluation, governance and safe deployment.",
     "messages": [
         ("Dr. Amara Okafor", "Paper of the week: external validation of a sepsis prediction model. AUC well "
                              "below the vendor claim, alerts on a large share of admissions."),
         ("Priya Nair", "The alert volume is the part people underestimate. Fatigue makes the true positives "
                        "worthless too."),
         ("Dr. Sarah Chen", "Adding this to the AI Safety reading list."),
     ]},
]


# ==========================================================================
# Challenges — questions follow the topic, and the topic is the title
# ==========================================================================

CHALLENGES = [
    {
        "slug": "ai-in-medical-imaging",
        "title": "AI in Medical Imaging",
        "topic": "AI in Medical Imaging",
        "icon": "scan",
        "difficulty": "hard",
        "points": 500,
        "base_participants": 1245,
        "days_left": 2,
        "order": 1,
        "description": (
            "Model behaviour, image analysis, radiology AI and the safety and ethics of "
            "putting either near a patient."
        ),
        "questions": [
            {"prompt": "A chest radiograph model reports 94% accuracy overall. Which follow-up question "
                       "most affects whether it is safe to deploy in your department?",
             "explanation": "Aggregate accuracy hides subgroup failure. Performance stratified by "
                            "population and equipment is what tells you whether the number applies to "
                            "your patients at all.",
             "choices": [("How does performance break down by patient subgroup, scanner and site?", True),
                         ("What is the model's total parameter count?", False),
                         ("Which deep learning framework was it trained in?", False),
                         ("How many images were in the training set in total?", False)]},
            {"prompt": "A student opens the AI overlay before recording their own reading. Why does this "
                       "order matter?",
             "explanation": "Seeing the model first anchors the reader to its answer. Committing your own "
                            "read first is the only reliable structural protection against automation bias.",
             "choices": [("Anchoring: once the model's answer is seen, the reader's independent judgement "
                          "is compromised", True),
                         ("The model runs faster when the reading field is empty", False),
                         ("Regulations require the overlay to load second", False),
                         ("It has no clinical effect, it is only a UI preference", False)]},
            {"prompt": "This chest radiograph is shown with a model overlay reporting 41% confidence "
                       "on a right lower zone opacity. What is the appropriate interpretation?",
             "image_seed": "CXR-CHALLENGE-41",
             "image_modality": "xray",
             "image_alt": "Synthetic chest radiograph. A dashed box sits over the right lower zone, "
                          "labelled with a 41% confidence score — below the platform's 70% threshold.",
             "explanation": "Low confidence signals the input may sit outside the model's operating "
                            "envelope. It is a prompt for closer human review, not a probability of disease.",
             "choices": [("Treat it as a flag that the input may be out of distribution and review it "
                          "carefully yourself", True),
                         ("Treat 41% as the probability the patient has the disease", False),
                         ("Discard the case as unreadable", False),
                         ("Re-run the model until confidence exceeds the threshold", False)]},
            {"prompt": "A saliency map highlights the region around the lesion the model flagged, as "
                       "shown. What does that establish?",
             "image_seed": "CXR-CHALLENGE-SALIENCY",
             "image_modality": "xray",
             "image_alt": "Synthetic chest radiograph with a warm heatmap patch over the left mid zone, "
                          "roughly overlapping a flagged lesion.",
             "explanation": "Saliency shows which pixels most change the output under perturbation. It is "
                            "an estimate about the model, carries its own error, and does not confirm the "
                            "prediction is correct.",
             "choices": [("Very little on its own — it indicates pixel influence, not that the prediction "
                          "is correct", True),
                         ("That the model reasoned about the lesion the way a radiologist would", False),
                         ("That the prediction has been independently verified", False),
                         ("That the model is compliant with regulatory requirements", False)]},
            {"prompt": "An imaging model cleared via the FDA 510(k) pathway is described as 'FDA approved "
                       "and proven to improve outcomes'. What is wrong with that statement?",
             "explanation": "510(k) establishes substantial equivalence to a predicate device. It is not "
                            "approval, and it does not require evidence that patient outcomes improve.",
             "choices": [("510(k) clearance shows substantial equivalence to an existing device, not "
                          "improved patient outcomes", True),
                         ("Nothing — clearance and outcome evidence are the same thing", False),
                         ("510(k) applies only to software, so imaging is out of scope", False),
                         ("It is correct as long as the vendor published an AUC", False)]},
        ],
    },
    {
        "slug": "cardiology-grand-challenge",
        "title": "Cardiology Grand Challenge",
        "topic": "Cardiac physiology and ECG",
        "icon": "heart-pulse",
        "difficulty": "hard",
        "points": 400,
        "base_participants": 982,
        "days_left": 3,
        "order": 2,
        "description": "Cardiac physiology, ECG interpretation and heart failure management.",
        "questions": [
            {"prompt": "ST elevation in leads II, III and aVF with reciprocal depression in aVL most "
                       "suggests infarction of which territory?",
             "explanation": "II, III and aVF face the inferior wall, usually supplied by the right "
                            "coronary artery. Reciprocal change in aVL supports the diagnosis.",
             "choices": [("Inferior wall", True), ("Anterior wall", False),
                         ("High lateral wall", False), ("Posterior wall only", False)]},
            {"prompt": "Which node normally sets heart rate, and why does it win?",
             "explanation": "The sinoatrial node has the fastest intrinsic rate of spontaneous "
                            "depolarisation, so it reaches threshold first and overdrive-suppresses "
                            "slower pacemakers.",
             "choices": [("The sinoatrial node, because its intrinsic rate is fastest", True),
                         ("The atrioventricular node, because it is centrally placed", False),
                         ("The bundle of His, because it conducts fastest", False),
                         ("Purkinje fibres, because they reach the most tissue", False)]},
            {"prompt": "What is the physiological purpose of the delay at the atrioventricular node?",
             "explanation": "Roughly 100 ms of delay lets atrial contraction finish and complete "
                            "ventricular filling before the ventricles contract.",
             "choices": [("It allows atrial contraction to complete ventricular filling", True),
                         ("It slows the heart rate to a safe level", False),
                         ("It prevents the atria from depolarising twice", False),
                         ("It generates the T wave", False)]},
            {"prompt": "In systolic heart failure with reduced ejection fraction, which drug class has the "
                       "clearest mortality benefit?",
             "explanation": "Beta blockers, ACE inhibitors/ARNI and mineralocorticoid antagonists reduce "
                            "mortality. Loop diuretics improve symptoms and congestion without a "
                            "demonstrated mortality benefit.",
             "choices": [("Beta blockers", True), ("Loop diuretics", False),
                         ("Calcium channel blockers", False), ("Short-acting nitrates", False)]},
            {"prompt": "A widened QRS with an RSR' pattern in V1 and a slurred S in V6 indicates what?",
             "explanation": "That combination is right bundle branch block: the right ventricle "
                            "depolarises late through myocardium rather than the conduction system.",
             "choices": [("Right bundle branch block", True), ("Left bundle branch block", False),
                         ("First degree AV block", False), ("Atrial flutter", False)]},
        ],
    },
    {
        "slug": "anatomy-speed-quiz",
        "title": "Anatomy Speed Quiz",
        "topic": "Human anatomy",
        "icon": "bone",
        "difficulty": "easy",
        "points": 150,
        "base_participants": 2341,
        "days_left": 1,
        "order": 3,
        "description": "Quick-fire recall across gross anatomy. Built for revision speed.",
        "questions": [
            {"prompt": "Which nerve is most at risk in a fracture of the surgical neck of the humerus?",
             "explanation": "The axillary nerve wraps the surgical neck; injury causes deltoid weakness "
                            "and numbness over the regimental badge area.",
             "choices": [("Axillary nerve", True), ("Radial nerve", False),
                         ("Median nerve", False), ("Ulnar nerve", False)]},
            {"prompt": "How many lobes does the right lung have?",
             "explanation": "Three — upper, middle and lower — separated by the oblique and horizontal "
                            "fissures. The left has two, making room for the heart.",
             "choices": [("Three", True), ("Two", False), ("Four", False), ("Five", False)]},
            {"prompt": "Which structure passes through the foramen magnum?",
             "explanation": "The medulla oblongata passes through, along with the vertebral arteries and "
                            "the spinal accessory nerve.",
             "choices": [("The medulla oblongata", True), ("The optic nerve", False),
                         ("The internal carotid artery", False), ("The oesophagus", False)]},
            {"prompt": "The femoral nerve, artery and vein sit in which order, lateral to medial?",
             "explanation": "NAVEL: nerve, artery, vein, empty space, lymphatics — lateral to medial.",
             "choices": [("Nerve, artery, vein", True), ("Vein, artery, nerve", False),
                         ("Artery, nerve, vein", False), ("Nerve, vein, artery", False)]},
            {"prompt": "Which muscle is the primary flexor of the elbow when the forearm is pronated?",
             "explanation": "Brachialis inserts on the ulna and is unaffected by forearm rotation, so it "
                            "does the work when biceps is at a mechanical disadvantage.",
             "choices": [("Brachialis", True), ("Biceps brachii", False),
                         ("Triceps brachii", False), ("Supinator", False)]},
        ],
    },
    {
        "slug": "pharmacology-master",
        "title": "Pharmacology Master",
        "topic": "Pharmacology",
        "icon": "pill",
        "difficulty": "medium",
        "points": 250,
        "base_participants": 756,
        "days_left": 4,
        "order": 4,
        "description": "Mechanisms, interactions and the clinical consequences of both.",
        "questions": [
            {"prompt": "A patient on warfarin is started on an antibiotic and the INR rises sharply. Which "
                       "mechanism most likely explains it?",
             "explanation": "Many antibiotics inhibit CYP2C9, reducing warfarin metabolism, and also "
                            "disrupt gut flora that produce vitamin K. Both push the INR up.",
             "choices": [("Inhibition of warfarin metabolism and disruption of vitamin K-producing gut flora", True),
                         ("Increased renal clearance of warfarin", False),
                         ("Displacement of warfarin from red blood cells", False),
                         ("Direct activation of clotting factor synthesis", False)]},
            {"prompt": "Why do ACE inhibitors cause a dry cough in some patients?",
             "explanation": "ACE also degrades bradykinin. Inhibiting it lets bradykinin accumulate in the "
                            "airway, provoking cough. ARBs avoid this because they act at the receptor.",
             "choices": [("Bradykinin accumulates because ACE normally degrades it", True),
                         ("Angiotensin II directly irritates the bronchi", False),
                         ("They cause reflex bronchoconstriction via beta blockade", False),
                         ("They dry airway secretions through antimuscarinic action", False)]},
            {"prompt": "Which electrolyte disturbance most increases the risk of digoxin toxicity?",
             "explanation": "Hypokalaemia. Digoxin and potassium compete at the Na+/K+ ATPase, so low "
                            "potassium increases digoxin binding at any given serum level.",
             "choices": [("Hypokalaemia", True), ("Hypernatraemia", False),
                         ("Hypocalcaemia", False), ("Hyperphosphataemia", False)]},
            {"prompt": "A drug with a narrow therapeutic index requires what in practice?",
             "explanation": "The gap between an effective and a toxic concentration is small, so dosing "
                            "needs monitoring and interaction checking — warfarin, digoxin, lithium, "
                            "phenytoin.",
             "choices": [("Close monitoring of levels and careful interaction checking", True),
                         ("Higher loading doses to reach effect faster", False),
                         ("Administration only by the intravenous route", False),
                         ("Avoidance in all patients over 65", False)]},
            {"prompt": "First-pass metabolism most directly affects which property of an oral drug?",
             "explanation": "Drug absorbed from the gut passes through the liver before systemic "
                            "circulation, so extensive first-pass metabolism lowers bioavailability.",
             "choices": [("Its bioavailability", True), ("Its receptor affinity", False),
                         ("Its volume of distribution", False), ("Its plasma protein binding", False)]},
        ],
    },
]


# ==========================================================================
# Imaging case references — synthetic, teacher-authored, fully verified
# ==========================================================================

CASES = [
    {
        "case_ref": "CXR-2041",
        "title": "Right lower zone consolidation in a febrile adult",
        "modality": Modality.XRAY,
        "body_region": "Chest",
        "patient_age_band": "60-69",
        "patient_sex": "F",
        "difficulty": "easy",
        "clinical_context": (
            "Four days of productive cough and fever. Reduced air entry at the right base with "
            "coarse crackles. CRP raised, oxygen saturation 94% on air."
        ),
        "teaching_points": (
            "Work through the search pattern before naming the obvious finding — satisfaction "
            "of search is the classic failure here. Check the costophrenic angles for an "
            "associated effusion and look behind the heart before you commit.\n\n"
            "Note what the imaging cannot tell you: consolidation is a pattern, not an "
            "organism, and the radiograph does not distinguish bacterial pneumonia from "
            "aspiration or infarction on its own."
        ),
        "findings_summary": (
            "Airspace opacification in the right lower zone with air bronchograms. No "
            "convincing effusion. Heart size normal for projection."
        ),
        "images": [
            {"caption": "PA chest radiograph on admission", "view": "PA",
             "metadata": {"PatientName": "REMOVED", "PatientID": "REMOVED",
                          "PatientBirthDate": "REMOVED", "PatientAge": "064Y",
                          "PatientSex": "F", "Modality": "CR", "BodyPartExamined": "CHEST",
                          "InstitutionName": "REMOVED", "StudyDate": "20260114"},
             "overlay_text": "PORTABLE AP  MRN 88213  14/01/2026"},
        ],
    },
    {
        "case_ref": "CXR-2087",
        "title": "Left apical pneumothorax after central line insertion",
        "modality": Modality.XRAY,
        "body_region": "Chest",
        "patient_age_band": "40-49",
        "patient_sex": "M",
        "difficulty": "medium",
        "clinical_context": (
            "Post-procedure film following left subclavian central line insertion. Increasing "
            "breathlessness in recovery."
        ),
        "teaching_points": (
            "Apices are a designated review area precisely because findings here are missed. "
            "Look for the visceral pleural line with absent lung markings beyond it — not for "
            "a black area, which is what people expect and often is not there.\n\n"
            "Also check line position: tip, course, and whether it crosses the midline. A "
            "post-procedure film answers two questions, and readers who find one finding "
            "frequently stop before the second."
        ),
        "findings_summary": (
            "Thin visceral pleural line at the left apex with absent peripheral lung markings. "
            "Central line tip projected over the superior vena cava."
        ),
        "images": [
            {"caption": "Erect AP film, post line insertion", "view": "AP",
             "metadata": {"PatientName": "REMOVED", "PatientID": "REMOVED",
                          "PatientBirthDate": "REMOVED", "PatientAge": "047Y",
                          "PatientSex": "M", "Modality": "CR", "BodyPartExamined": "CHEST",
                          "ReferringPhysicianName": "REMOVED", "StudyDate": "20260122"},
             "overlay_text": "AP ERECT  POST LINE"},
            {"caption": "Coned view of the left apex", "view": "AP detail",
             "metadata": {"PatientAge": "047Y", "PatientSex": "M", "Modality": "CR",
                          "BodyPartExamined": "CHEST", "StudyDate": "20260122"},
             "overlay_text": ""},
        ],
    },
    {
        "case_ref": "CT-3312",
        "title": "Acute ischaemic change on non-contrast head CT",
        "modality": Modality.CT,
        "body_region": "Head",
        "patient_age_band": "70-79",
        "patient_sex": "F",
        "difficulty": "hard",
        "clinical_context": (
            "Sudden right-sided weakness and expressive dysphasia, last seen well 90 minutes "
            "ago. Non-contrast CT as part of the acute stroke pathway."
        ),
        "teaching_points": (
            "Early ischaemic change is subtle: loss of grey-white differentiation, insular "
            "ribbon sign, effaced sulci. The purpose of the scan in the acute pathway is "
            "primarily to exclude haemorrhage, and a normal-looking CT does not exclude "
            "infarction.\n\n"
            "Privacy note specific to head CT: volumetric reconstructions of this dataset can "
            "produce a recognisable face. Defacing is required before any sharing, and header "
            "scrubbing alone does not achieve it."
        ),
        "findings_summary": (
            "Loss of grey-white differentiation in the left insular cortex with mild sulcal "
            "effacement. No haemorrhage. No established large territory infarct."
        ),
        "images": [
            {"caption": "Axial non-contrast CT at the level of the basal ganglia", "view": "Axial",
             "metadata": {"PatientName": "REMOVED", "PatientID": "REMOVED",
                          "PatientBirthDate": "REMOVED", "PatientAge": "076Y",
                          "PatientSex": "F", "Modality": "CT", "BodyPartExamined": "HEAD",
                          "InstitutionName": "REMOVED", "AccessionNumber": "REMOVED",
                          "StudyDate": "20260203"},
             "overlay_text": "HEAD CT NON CON"},
        ],
    },
]


# ==========================================================================
# Seeding
# ==========================================================================

# One-line description of each cover, used as the image alt text. Written per
# article rather than generated, because "cover image" is not alt text.
ARTICLE_COVER_ALT = {
    "post-concussion-syndrome-when-symptoms-persist":
        "A wall of MRI head scans on a lightbox, labelled \u2018what is mTBI\u2019",
    "autoimmune-encephalitis-and-the-brain-under-attack":
        "Axial CT of the head showing an area of low attenuation",
    "oncology-must-confront-hidden-side-effects":
        "Illustration of a researcher at a microscope beside a magnified field of cells",
}


# Articles that shipped with earlier versions of this seed and have since been
# replaced. They are removed on boot so a database seeded before the change ends
# up with the same feed as a fresh one. Their comments, likes and saved rows go
# with them \u2014 those reference the article by id or slug and would otherwise dangle.
RETIRED_ARTICLE_SLUGS = (
    "ai-assisted-reading-what-the-evidence-says",
    "active-recall-the-evidence",
    "virtual-anatomy-lab-cardiac-conduction",
    "automation-bias-in-the-reading-room",
    "reading-a-chest-film-systematically",
    "privacy-what-de-identification-misses",
    "sepsis-models-and-the-alarm-problem",
    "usmle-step-1-adaptive-practice",
)


def _retire_articles(session: Session) -> None:
    """Drop replaced articles and everything that pointed at them."""
    for slug in RETIRED_ARTICLE_SLUGS:
        article = session.exec(select(Article).where(Article.slug == slug)).first()
        if article is None:
            continue
        for comment in session.exec(
            select(ArticleComment).where(ArticleComment.article_id == article.id)
        ).all():
            session.delete(comment)
        for like in session.exec(
            select(ArticleLike).where(ArticleLike.article_id == article.id)
        ).all():
            session.delete(like)
        for saved in session.exec(
            select(SavedItem).where(
                SavedItem.item_type == "article", SavedItem.item_key == slug
            )
        ).all():
            session.delete(saved)
        session.delete(article)
    session.commit()


def _seed_articles(session: Session) -> None:
    _retire_articles(session)
    for spec in ARTICLES:
        if session.exec(select(Article).where(Article.slug == spec["slug"])).first():
            continue
        session.add(
            Article(
                slug=str(spec["slug"]),
                tag=str(spec["tag"]),
                title=str(spec["title"]),
                excerpt=str(spec["excerpt"]),
                body_md=str(spec["body_md"]),
                author=str(spec["author"]),
                author_role=str(spec["author_role"]),
                read_minutes=int(spec["read_minutes"]),
                cover=str(spec.get("cover", f"/covers/articles/{spec['slug']}.svg")),
                cover_alt=ARTICLE_COVER_ALT.get(str(spec["slug"]), ""),
                cover_orientation=str(spec.get("cover_orientation", "landscape")),
                base_likes=int(spec["base_likes"]),
                published_at=NOW - timedelta(hours=int(spec["hours_ago"])),
            )
        )
    session.commit()


def _seed_resources(session: Session) -> None:
    for spec in RESOURCES:
        if session.exec(select(Resource).where(Resource.slug == spec["slug"])).first():
            continue
        session.add(
            Resource(
                slug=str(spec["slug"]),
                kind=str(spec["kind"]),
                orientation=str(spec.get("orientation", "landscape")),
                title=str(spec["title"]),
                author=str(spec["author"]),
                description=str(spec["description"]),
                rating=float(spec["rating"]),
                downloads=str(spec.get("downloads", "")),
                duration=str(spec.get("duration", "")),
                premium=bool(spec["premium"]),
                cover_hue=int(spec["cover_hue"]),
                cover=f"/covers/resources/{spec['slug']}.svg",
                publisher=str(spec.get("publisher", "")),
                year=spec.get("year"),
                pages=spec.get("pages"),
                level=str(spec.get("level", "")),
                topic=str(spec.get("topic", "")),
            )
        )
    session.commit()


# Curated cover art, supplied for these items specifically and keyed by slug.
# A slug that is absent here falls back to the authored SVG of the same name.
#
# These are the authoritative images for their items. Nothing automatic may
# replace them: the stock-image service is not wired to communities or
# challenges at all, and if it ever is, it must treat a non-empty `cover` as a
# curated image and leave it alone.
COMMUNITY_COVERS: Dict[str, str] = {
    "cardiology-club": "/covers/communities/cardiology-club.jpg",
    "radiology-residents": "/covers/communities/radiology-residents.jpg",
    "surgery-society": "/covers/communities/surgery-society.jpg",
    "emergency-medicine": "/covers/communities/emergency-medicine.jpg",
    "pediatrics-pals": "/covers/communities/pediatrics-pals.jpg",
    "internal-medicine": "/covers/communities/internal-medicine.jpg",
    "ai-in-medicine": "/covers/communities/ai-in-medicine.jpg",
    "neurology-network": "/covers/communities/neurology-network.jpg",
}

CHALLENGE_COVERS: Dict[str, str] = {
    "ai-in-medical-imaging": "/covers/challenges/ai-in-medical-imaging.jpg",
    "cardiology-grand-challenge": "/covers/challenges/cardiology-grand-challenge.jpg",
    "anatomy-speed-quiz": "/covers/challenges/anatomy-speed-quiz.jpg",
    "pharmacology-master": "/covers/challenges/pharmacology-master.jpg",
}


def _cover_for(group: str, slug: str, curated: Dict[str, str]) -> str:
    return curated.get(slug, f"/covers/{group}/{slug}.svg")


def _seed_communities(session: Session) -> None:
    for spec in COMMUNITIES:
        community = session.exec(
            select(Community).where(Community.slug == spec["slug"])
        ).first()
        cover = _cover_for("communities", str(spec["slug"]), COMMUNITY_COVERS)
        if community:
            # Cover art is refreshed even on a row that already exists. It is
            # presentation rather than user data, and a database seeded before
            # the artwork landed would otherwise keep pointing at a file that
            # is no longer there — which is exactly how four of these ended up
            # requesting an SVG that was never drawn.
            if community.cover != cover:
                community.cover = cover
                session.add(community)
                session.commit()
            continue
        community = Community(
            slug=str(spec["slug"]),
            name=str(spec["name"]),
            description=str(spec["description"]),
            specialty=str(spec["specialty"]),
            icon=str(spec["icon"]),
            cover=cover,
            base_members=int(spec["base_members"]),
        )
        session.add(community)
        session.commit()
        session.refresh(community)

        messages = spec["messages"]
        assert isinstance(messages, list)
        for offset, (author, body) in enumerate(messages):
            session.add(
                CommunityMessage(
                    community_id=community.id or 0,
                    user_id=None,
                    author_name=author,
                    body=body,
                    created_at=NOW - timedelta(hours=len(messages) - offset, minutes=7 * offset),
                )
            )
        session.commit()


def _seed_challenges(session: Session) -> None:
    for spec in CHALLENGES:
        cover = _cover_for("challenges", str(spec["slug"]), CHALLENGE_COVERS)
        existing = session.exec(
            select(Challenge).where(Challenge.slug == spec["slug"])
        ).first()
        if existing:
            if existing.cover != cover:
                existing.cover = cover
                session.add(existing)
                session.commit()
            continue
        questions = spec["questions"]
        assert isinstance(questions, list)
        per_question = max(1, int(spec["points"]) // max(1, len(questions)))

        challenge = Challenge(
            slug=str(spec["slug"]),
            title=str(spec["title"]),
            description=str(spec["description"]),
            topic=str(spec["topic"]),
            icon=str(spec["icon"]),
            cover=cover,
            difficulty=str(spec["difficulty"]),
            points=per_question * len(questions),
            base_participants=int(spec["base_participants"]),
            ends_at=NOW + timedelta(days=int(spec["days_left"])),
            order=int(spec["order"]),
        )
        session.add(challenge)
        session.commit()
        session.refresh(challenge)

        for index, question_spec in enumerate(questions):
            question = ChallengeQuestion(
                challenge_id=challenge.id or 0,
                order=index,
                prompt=str(question_spec["prompt"]),
                explanation=str(question_spec["explanation"]),
                points=per_question,
                image_seed=question_spec.get("image_seed"),
                image_alt=str(question_spec.get("image_alt", "")),
                image_modality=str(question_spec.get("image_modality", "xray")),
            )
            session.add(question)
            session.commit()
            session.refresh(question)
            for choice_index, (text, correct) in enumerate(question_spec["choices"]):
                session.add(
                    ChallengeChoice(
                        question_id=question.id or 0,
                        order=choice_index,
                        text=text,
                        is_correct=bool(correct),
                    )
                )
        session.commit()


def _seed_cases(session: Session, teacher: User) -> None:
    """Publish the demo casebook, with every image verified by the teacher.

    The verification is recorded against a real instructor account, because the
    whole point of the workflow is that a named human signed it off.
    """
    from app.services.anonymize import anonymize

    for spec in CASES:
        if session.exec(
            select(CaseReference).where(CaseReference.case_ref == spec["case_ref"])
        ).first():
            continue

        case = CaseReference(
            case_ref=str(spec["case_ref"]),
            title=str(spec["title"]),
            modality=spec["modality"],
            body_region=str(spec["body_region"]),
            patient_age_band=str(spec["patient_age_band"]),
            patient_sex=str(spec["patient_sex"]),
            clinical_context=str(spec["clinical_context"]),
            teaching_points=str(spec["teaching_points"]),
            findings_summary=str(spec["findings_summary"]),
            difficulty=str(spec["difficulty"]),
            source="synthetic",
            created_by=teacher.id or 0,
            published=True,
        )
        session.add(case)
        session.commit()
        session.refresh(case)

        images = spec["images"]
        assert isinstance(images, list)
        for image_spec in images:
            result = anonymize(image_spec["metadata"], image_spec.get("overlay_text", ""))
            session.add(
                CaseImage(
                    case_id=case.id or 0,
                    caption=str(image_spec["caption"]),
                    view=str(image_spec["view"]),
                    render_seed=f"{case.case_ref}-{image_spec['view']}",
                    anonymization_status="verified",
                    redacted_fields_json=json.dumps(result["removed_fields"]),
                    review_notes=str(result["notes"]),
                    verified_by=teacher.id,
                    verified_at=NOW - timedelta(days=1),
                )
            )
        session.commit()


def _seed_peer_points(session: Session, users: List[User]) -> None:
    """Give the seeded peers a starting score so the leaderboard is not all zeros.

    Only ever applied to seeded demo accounts, and only when they are still on
    zero — a real user's score is never written here.
    """
    baseline = {
        "sarah.chen@medly.dev": 3120,
        "james.wilson@medly.dev": 2880,
        "emily.davis@medly.dev": 2640,
        "michael.brown@medly.dev": 2310,
        "premium@medly.dev": 1450,
        "student@medly.dev": 320,
        "instructor@medly.dev": 900,
    }
    for user in users:
        target = baseline.get(user.email)
        if target and not (user.points or 0):
            user.points = target
            session.add(user)
    session.commit()


PEERS = [
    ("sarah.chen@medly.dev", "Sarah Chen", "Harvard Medical School", 5),
    ("james.wilson@medly.dev", "James Wilson", "Johns Hopkins", 4),
    ("emily.davis@medly.dev", "Emily Davis", "Stanford Medicine", 3),
    ("michael.brown@medly.dev", "Michael Brown", "Yale School of Medicine", 4),
]


def _seed_peers(session: Session, password_hash: str) -> List[User]:
    """Other students, so ranking and chat have somebody in them."""
    created: List[User] = []
    for email, name, institution, year in PEERS:
        existing = session.exec(select(User).where(User.email == email)).first()
        if existing:
            created.append(existing)
            continue
        user = User(
            email=email,
            hashed_password=password_hash,
            full_name=name,
            role=Role.STUDENT,
            institution=institution,
            year_of_study=year,
        )
        session.add(user)
        created.append(user)
    session.commit()
    for user in created:
        session.refresh(user)
    return created


def run(session: Session, users: List[User], password_hash: str) -> None:
    peers = _seed_peers(session, password_hash)
    _seed_articles(session)
    _seed_resources(session)
    _seed_communities(session)
    _seed_challenges(session)

    teacher = next((u for u in users if u.role == Role.INSTRUCTOR), None)
    if teacher:
        _seed_cases(session, teacher)

    _seed_peer_points(session, list(users) + peers)
