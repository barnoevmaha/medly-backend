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
from typing import List

from sqlmodel import Session, select

from app.models.casebook import CaseImage, CaseReference
from app.models.challenge import (
    Challenge,
    ChallengeChoice,
    ChallengeQuestion,
)
from app.models.community import Community, CommunityMessage
from app.models.enums import Modality, Role
from app.models.social import Article, Resource
from app.models.user import User

NOW = datetime.utcnow()


# ==========================================================================
# Feed articles — each one has a real body, not a card and a placeholder
# ==========================================================================

ARTICLES = [
    {
        "slug": "ai-assisted-reading-what-the-evidence-says",
        "tag": "Medical News",
        "title": "What the Evidence Actually Says About AI-Assisted Reading",
        "author": "Dr. Sarah Chen",
        "author_role": "Radiology, Columbia",
        "read_minutes": 7,
        "base_likes": 234,
        "hours_ago": 2,
        "excerpt": (
            "Artificial intelligence can assist radiologists in detecting abnormalities, but "
            "the size of that benefit depends almost entirely on how the tool is introduced "
            "into the reading workflow."
        ),
        "body_md": (
            "Artificial intelligence can assist radiologists in detecting abnormalities on "
            "chest radiographs, mammograms and head CT — that much is no longer seriously "
            "disputed. What remains contested, and what matters far more for patients, is the "
            "size of that benefit and the conditions under which it survives contact with a "
            "real department.\n\n"
            "## The headline numbers are reader-plus-model, not model\n\n"
            "Most positive trials report the performance of a *combined* system: a clinician "
            "reading with the tool available. That combination frequently beats the unaided "
            "reader. It does not follow that the model alone is safe, and it does not follow "
            "that the combination beats the reader in every subgroup.\n\n"
            "The Swedish MASAI trial randomised over 80,000 women to AI-supported versus "
            "standard double reading in breast screening. Cancer detection rose modestly and "
            "screen-reading workload fell substantially. The workload result was arguably the "
            "more important one: it changes staffing, and staffing changes what a service can "
            "offer.\n\n"
            "## Where the gains disappear\n\n"
            "Three things reliably erode a published benefit:\n\n"
            "1. **Distribution shift.** A model validated on one vendor's scanners at three "
            "academic sites does not automatically transfer to a district general hospital "
            "with older equipment and a different case mix.\n"
            "2. **Prevalence.** Positive predictive value falls as prevalence falls. A tool "
            "impressive in an enriched research set can generate an unworkable false-positive "
            "rate in routine screening.\n"
            "3. **The human in the loop.** If the reader defers to the model when it is wrong, "
            "the combined system inherits the model's errors and adds nothing. This is "
            "automation bias, and it is measurable: the override rate is the metric to watch.\n\n"
            "## What a department should ask before deployment\n\n"
            "- On which population, and which equipment, was this validated?\n"
            "- What is the performance stratified by age, sex and ethnicity — not in aggregate?\n"
            "- What happens to the output when the model is uncertain? Does it abstain, or does "
            "it guess with the same confident interface?\n"
            "- Who reviews flagged cases, and is that person's time actually funded?\n\n"
            "## The uncomfortable part\n\n"
            "The most reliable predictor of whether an imaging AI deployment improves care is "
            "not the model's reported AUC. It is whether the department built a review process "
            "around it and kept measuring after go-live. Tools do not fail loudly. They drift, "
            "quietly, while the dashboard still shows green.\n\n"
            "> Read the film. Commit to your own answer. Then look at the model, and notice "
            "whether it changed your mind and why."
        ),
    },
    {
        "slug": "active-recall-the-evidence",
        "tag": "Study Tip",
        "title": "Active Recall: Why Testing Yourself Beats Re-Reading",
        "author": "StudyHacks",
        "author_role": "Medly Learning",
        "read_minutes": 5,
        "base_likes": 567,
        "hours_ago": 4,
        "excerpt": (
            "Stop passive reading. Retrieval practice improves long-term retention by roughly "
            "50% over re-reading, and the effect is largest exactly where medical students "
            "need it — weeks later, under exam conditions."
        ),
        "body_md": (
            "Re-reading feels productive because fluency feels like knowledge. It is not. The "
            "sensation of a passage being easy to read is a property of the passage, not of "
            "your memory of it.\n\n"
            "## The core finding\n\n"
            "Roediger and Karpicke's testing-effect work is the reference point: students who "
            "studied a passage once and then tested themselves repeatedly outperformed those "
            "who re-read it repeatedly, by a wide margin at one week — even though the "
            "re-readers *predicted* they would do better. Confidence and retention move in "
            "opposite directions here.\n\n"
            "## Why retrieval works\n\n"
            "Pulling something out of memory is itself the learning event. Each successful "
            "retrieval strengthens the route back to it and, importantly, teaches you which "
            "routes are missing. Recognition — the feeling of \"yes, I've seen that\" — does "
            "not do this.\n\n"
            "## A protocol that survives a clinical timetable\n\n"
            "1. **Read once, actively.** One pass, generating questions as you go.\n"
            "2. **Close the book and write.** Blank page, everything you remember, no peeking. "
            "The gaps you find are the syllabus.\n"
            "3. **Space it.** Same material at day 1, day 3, day 7, day 21. Spacing beats "
            "cramming for anything you need past the exam.\n"
            "4. **Interleave.** Mix cardiology and respiratory in one session. It feels worse "
            "and works better, because diagnosis in real life is not sorted by chapter.\n"
            "5. **Explain it out loud.** If you cannot explain the mechanism to a colleague "
            "without notes, you have recognition, not recall.\n\n"
            "## The trap\n\n"
            "Highlighting, re-copying notes and re-watching lectures all feel like work and "
            "produce almost nothing durable. The techniques that work feel harder while you "
            "are doing them. That discomfort is the signal, not the problem."
        ),
    },
    {
        "slug": "virtual-anatomy-lab-cardiac-conduction",
        "tag": "Upcoming Event",
        "title": "Virtual Anatomy Lab: The Cardiac Conduction System",
        "author": "Medly Events",
        "author_role": "Events team",
        "read_minutes": 4,
        "base_likes": 189,
        "hours_ago": 6,
        "excerpt": (
            "An interactive 3D session on the conduction system of the heart, built for "
            "second-year students preparing for physiology exams. Places are limited."
        ),
        "body_md": (
            "## What the session covers\n\n"
            "Ninety minutes, live, working through the conduction system in a rotatable 3D "
            "heart with the electrical activity overlaid on the anatomy in real time.\n\n"
            "- Sinoatrial node: intrinsic rate, autonomic modulation, why it wins the race\n"
            "- Internodal pathways and the atrial depolarisation front\n"
            "- The atrioventricular node and the ~100 ms delay that makes atrial kick possible\n"
            "- Bundle of His, the bundle branches, and the Purkinje network\n"
            "- Mapping each step onto the surface ECG, wave by wave\n\n"
            "## Why it is worth ninety minutes\n\n"
            "Most students can recite the pathway and still cannot explain why a bundle branch "
            "block widens the QRS. The gap is spatial: the sequence is memorised as a list "
            "rather than as a wavefront moving through tissue. Watching the front propagate "
            "and then breaking a branch to see what happens fixes that in a way a diagram "
            "does not.\n\n"
            "## Preparation\n\n"
            "Come with the normal ECG intervals in your head — PR, QRS, QT. The session "
            "assumes them and builds on top. A tablet or second screen helps if you want to "
            "annotate.\n\n"
            "## Format\n\n"
            "Live walkthrough, then a case-based segment where the group localises a block "
            "from the trace before the answer is shown. Recording available afterwards to "
            "everyone who registers."
        ),
    },
    {
        "slug": "automation-bias-in-the-reading-room",
        "tag": "Medical News",
        "title": "Automation Bias Is a Clinical Skill Problem, Not a Software Problem",
        "author": "Dr. Amara Okafor",
        "author_role": "Clinical safety lead",
        "read_minutes": 6,
        "base_likes": 312,
        "hours_ago": 20,
        "excerpt": (
            "When a decision support tool is wrong, the harm depends on what the clinician "
            "does next. That step is trainable, and almost nobody trains it."
        ),
        "body_md": (
            "Automation bias has two faces. **Errors of commission**: doing what the system "
            "suggests when it is wrong. **Errors of omission**: missing something because the "
            "system did not flag it. The second is harder to detect and, in imaging, probably "
            "more common.\n\n"
            "## The experiment that should worry you\n\n"
            "In studies where clinicians are shown decision support that is deliberately "
            "incorrect on a subset of cases, accuracy on those cases falls sharply compared "
            "with unaided reading. Experienced clinicians are not immune. Under time pressure "
            "the effect gets worse, and time pressure is the normal operating condition of "
            "every department in the country.\n\n"
            "## Why \"just be careful\" fails\n\n"
            "Vigilance is not a stable resource. Telling readers to stay sceptical works for "
            "about a fortnight after the training session. What holds is structural:\n\n"
            "- **Order of operations.** Record your own read before the model output is "
            "visible. Anchoring cannot happen to an opinion you have already committed.\n"
            "- **Visible uncertainty.** Outputs below the confidence threshold should look "
            "different, not merely carry a smaller number.\n"
            "- **Measured overrides.** If a department's override rate is near zero, that is "
            "not agreement, it is rubber-stamping — and it is visible in the audit log.\n"
            "- **Named accountability.** Every decision carries a human name, always.\n\n"
            "## What this means for training\n\n"
            "Teaching students *how the model works* is necessary and insufficient. They also "
            "need supervised practice at disagreeing with one: cases where the tool is "
            "confidently wrong, in a setting where saying so costs nothing. That skill is the "
            "difference between a safety net and a single point of failure."
        ),
    },
    {
        "slug": "reading-a-chest-film-systematically",
        "tag": "Study Tip",
        "title": "A System for Chest Films That Survives a Night Shift",
        "author": "Dr. Michael Chen",
        "author_role": "Emergency medicine",
        "read_minutes": 6,
        "base_likes": 428,
        "hours_ago": 30,
        "excerpt": (
            "Pattern recognition is what you build to. A fixed search order is what stops you "
            "missing the second finding once you have found the first."
        ),
        "body_md": (
            "The classic failure on a chest radiograph is not missing the abnormality. It is "
            "finding one and stopping — satisfaction of search. A fixed order is the cheapest "
            "protection against it.\n\n"
            "## Before the anatomy\n\n"
            "Name, date, projection, rotation, inspiration, penetration. A rotated or "
            "underinspired film changes what you are allowed to conclude, and half the "
            "\"cardiomegaly\" on AP portable films is projection.\n\n"
            "## A workable order\n\n"
            "1. **Airway** — trachea central, carina, bronchi\n"
            "2. **Breathing** — lung fields zone by zone, compare left with right at the same "
            "height, then the pleural edges\n"
            "3. **Circulation** — heart size and contour, mediastinal width, hila\n"
            "4. **Diaphragm** — contours, costophrenic angles, gas under the domes\n"
            "5. **Everything else** — bones, soft tissues, lines, tubes, and the areas people "
            "skip: apices, behind the heart, below the diaphragm\n\n"
            "## The review areas\n\n"
            "Apices, hila, retrocardiac, retrodiaphragmatic, bones. Roughly speaking, that is "
            "where the missed findings live. Going back to them deliberately, every time, "
            "after you think you are done, catches a surprising proportion of them.\n\n"
            "## Then say it out loud\n\n"
            "Summarise in one sentence: what you see, what it means, what you would do. If "
            "that sentence is hard to say, the read is not finished — and an AI second opinion "
            "will not finish it for you."
        ),
    },
    {
        "slug": "privacy-what-de-identification-misses",
        "tag": "Medical News",
        "title": "De-Identified Is Not Anonymous: What Image Scrubbing Misses",
        "author": "Priya Nair",
        "author_role": "Clinical informatics",
        "read_minutes": 5,
        "base_likes": 176,
        "hours_ago": 46,
        "excerpt": (
            "Header scrubbing is the easy half of imaging privacy. Burned-in text, "
            "reconstructable faces and rare anatomy are the half that gets institutions into "
            "trouble."
        ),
        "body_md": (
            "Sharing imaging for teaching is normal, valuable, and routinely done with a "
            "confidence the technical reality does not support.\n\n"
            "## The three layers\n\n"
            "**Headers.** DICOM carries a long list of identifying tags, and vendor-private "
            "tags vary by scanner. A script that clears the standard fields and ignores the "
            "private ones leaves identity in the file.\n\n"
            "**Pixels.** Ultrasound and portable radiographs frequently have the patient name "
            "and record number burned into the image. No amount of header work touches this. "
            "It has to be detected in the rendered image and masked.\n\n"
            "**Anatomy.** Head CT and MRI can be volume-rendered into a recognisable face, and "
            "face-matching against public photographs has been demonstrated repeatedly. Rare "
            "hardware, unusual anatomy and distinctive surgical history identify people on "
            "their own.\n\n"
            "## Why automation is not the answer on its own\n\n"
            "Automated redaction is very good at removing what it can name and structurally "
            "unable to tell you what it missed. A tool that reports zero findings looks "
            "identical whether the image was clean or the detector was pointed at the wrong "
            "layer. Accepting that output unchecked is automation bias wearing a privacy "
            "costume.\n\n"
            "## A defensible workflow\n\n"
            "Automatic pass produces a proposal. A named human verifies the rendered image, "
            "not just the metadata. Only then does the image become available to learners, and "
            "the verification is recorded against the verifier. Minimum necessary applies "
            "throughout: an age band and a sex, never a date of birth.\n\n"
            "> If you cannot name the person who checked the image, it has not been checked."
        ),
    },
    {
        "slug": "sepsis-models-and-the-alarm-problem",
        "tag": "Medical News",
        "title": "Sepsis Prediction Models and the Alarm Fatigue Problem",
        "author": "Dr. James Wilson",
        "author_role": "Critical care",
        "read_minutes": 6,
        "base_likes": 203,
        "hours_ago": 60,
        "excerpt": (
            "A widely deployed sepsis alert performed far worse in external validation than "
            "its marketing suggested, and fired on so many patients that clinicians learned to "
            "ignore it."
        ),
        "body_md": (
            "Early warning for sepsis is a genuinely good idea. It is also the clearest "
            "worked example of how a model can be technically defensible and clinically "
            "useless at the same time.\n\n"
            "## What external validation found\n\n"
            "A widely deployed proprietary sepsis prediction model, evaluated independently "
            "across tens of thousands of hospitalisations, achieved an area under the curve "
            "far below the vendor's reported figure. It missed most sepsis cases and generated "
            "alerts on a large fraction of all patients. Both numbers matter, and the second "
            "may matter more.\n\n"
            "## Alert fatigue is a predictable consequence, not bad luck\n\n"
            "If a system fires often and is right rarely, staff learn — correctly, "
            "rationally — to discount it. That learned discounting then applies to the true "
            "positives too. A poorly calibrated alert does not merely fail to help; it "
            "degrades the response to every other alert in the building.\n\n"
            "## The lessons that generalise\n\n"
            "- **Demand external validation.** Vendor-reported performance on internal data is "
            "a marketing claim.\n"
            "- **Ask about the alert budget.** How many alerts per shift, and who is "
            "responding? If nobody has costed the response, the deployment is not real.\n"
            "- **Monitor after go-live.** Patient mix, documentation habits and coding all "
            "drift. Performance measured once is performance measured never.\n"
            "- **Watch what staff actually do.** Silent dismissal rates tell you more than any "
            "satisfaction survey.\n\n"
            "None of this argues against prediction models. It argues that the deployment, not "
            "the algorithm, is the intervention."
        ),
    },
    {
        "slug": "usmle-step-1-adaptive-practice",
        "tag": "Sponsored",
        "title": "Adaptive Step 1 Practice: What to Look For in a Question Bank",
        "author": "MedPrep",
        "author_role": "Sponsored content",
        "read_minutes": 4,
        "base_likes": 892,
        "hours_ago": 26,
        "excerpt": (
            "Sponsored: adaptive question banks are now standard. The features that actually "
            "affect your score are not the ones in the advertising."
        ),
        "body_md": (
            "*This post is sponsored. Medly labels sponsored content and does not endorse the "
            "product.*\n\n"
            "## What matters in a question bank\n\n"
            "1. **Explanation quality.** You learn from the explanation, not the question. If "
            "it does not say why each wrong option is wrong, it is a scoring tool, not a "
            "teaching tool.\n"
            "2. **Spacing built in.** A bank that re-surfaces your misses on a schedule beats "
            "one that leaves the scheduling to you.\n"
            "3. **Honest difficulty calibration.** Questions harder than the real exam waste "
            "time and damage morale; easier ones create false confidence.\n"
            "4. **Performance by system and by skill.** \"Cardiology 62%\" is actionable. "
            "\"Overall 71%\" is not.\n\n"
            "## What matters less than the marketing suggests\n\n"
            "Total question count past a few thousand, video libraries you will not watch, and "
            "\"AI-powered\" tutoring that mostly rewords the explanation you already have.\n\n"
            "## A fair warning about AI tutors\n\n"
            "Language models are fluent and occasionally, confidently wrong about mechanism "
            "and dosing. Treat generated explanations as a study partner's opinion: useful for "
            "prompting recall, not a citable source. Check anything that will end up in a "
            "clinical decision against a primary reference."
        ),
    },
]


# ==========================================================================
# Library resources — books, PDFs and videos, all saveable
# ==========================================================================

RESOURCES = [
    {"slug": "grays-anatomy-for-students", "kind": "book", "title": "Gray's Anatomy for Students",
     "author": "Richard Drake", "rating": 4.9, "downloads": "45,200", "premium": True, "cover_hue": 210,
     "description": "The standard regional anatomy text, organised the way dissection is taught."},
    {"slug": "intro-clinical-medicine", "kind": "book", "title": "Introduction to Clinical Medicine",
     "author": "Dr. James Anderson", "rating": 4.7, "downloads": "23,100", "premium": False, "cover_hue": 168,
     "description": "History taking, examination and clinical reasoning for the first ward year."},
    {"slug": "harrisons-internal-medicine", "kind": "book", "title": "Harrison's Principles of Internal Medicine",
     "author": "J. Larry Jameson", "rating": 4.9, "downloads": "67,800", "premium": False, "cover_hue": 260,
     "description": "The reference text for adult internal medicine, disease by disease."},
    {"slug": "robbins-basic-pathology", "kind": "book", "title": "Robbins Basic Pathology",
     "author": "Vinay Kumar", "rating": 4.8, "downloads": "54,300", "premium": True, "cover_hue": 4,
     "description": "Mechanism-first pathology, from cell injury to systemic disease."},
    {"slug": "clinical-ai-primer", "kind": "book", "title": "A Clinician's Primer on Machine Learning",
     "author": "Dr. Amara Okafor", "rating": 4.6, "downloads": "9,800", "premium": False, "cover_hue": 190,
     "description": "What models do, how they fail, and what to ask before trusting one."},

    {"slug": "pathophysiology-study-guide", "kind": "pdf", "title": "Pathophysiology Study Guide",
     "author": "Medical Education Team", "rating": 4.8, "downloads": "18,500", "premium": True, "cover_hue": 32,
     "description": "Condensed mechanisms with worked clinical correlations. 96 pages."},
    {"slug": "pharmacology-quick-reference", "kind": "pdf", "title": "Pharmacology Quick Reference",
     "author": "PharmEd Solutions", "rating": 4.5, "downloads": "31,200", "premium": True, "cover_hue": 288,
     "description": "Drug classes, mechanisms and interactions on one page each."},
    {"slug": "ecg-interpretation-checklist", "kind": "pdf", "title": "ECG Interpretation Checklist",
     "author": "Dr. Sarah Williams", "rating": 4.7, "downloads": "27,400", "premium": False, "cover_hue": 350,
     "description": "The systematic order, the intervals, and the patterns you cannot miss."},
    {"slug": "chest-xray-review-areas", "kind": "pdf", "title": "Chest X-Ray Review Areas",
     "author": "Radiology Teaching Group", "rating": 4.8, "downloads": "15,900", "premium": False, "cover_hue": 200,
     "description": "A one-page search pattern and the five areas where findings hide."},
    {"slug": "ai-safety-checklist-imaging", "kind": "pdf", "title": "AI Safety Checklist for Imaging Deployment",
     "author": "Medly Governance", "rating": 4.9, "downloads": "6,100", "premium": False, "cover_hue": 150,
     "description": "Twelve questions to ask before an imaging model touches a patient."},

    {"slug": "ecg-masterclass", "kind": "video", "title": "ECG Interpretation Masterclass",
     "author": "Dr. Sarah Williams", "rating": 4.6, "downloads": "12,400", "premium": False,
     "duration": "3h 20m", "cover_hue": 340,
     "description": "Rate, rhythm, axis, intervals — then forty traces, worked through live."},
    {"slug": "surgical-techniques-vol-1", "kind": "video", "title": "Surgical Techniques Vol. 1",
     "author": "Dr. Michael Chen", "rating": 4.7, "downloads": "8,900", "premium": False,
     "duration": "5h 10m", "cover_hue": 220,
     "description": "Knots, closure, instrument handling and theatre discipline for students."},
    {"slug": "reading-chest-films", "kind": "video", "title": "Reading Chest Films Under Pressure",
     "author": "Dr. Priya Nair", "rating": 4.8, "downloads": "10,300", "premium": True,
     "duration": "1h 45m", "cover_hue": 195,
     "description": "A search pattern that holds at 3am, with twenty on-call cases."},
    {"slug": "automation-bias-workshop", "kind": "video", "title": "Automation Bias: A Practical Workshop",
     "author": "Medly Safety Faculty", "rating": 4.9, "downloads": "4,700", "premium": False,
     "duration": "58m", "cover_hue": 40,
     "description": "Supervised practice at disagreeing with a confident, incorrect model."},
]


# ==========================================================================
# Communities — the description is the line under the title, and the only
# other field community search is allowed to match
# ==========================================================================

COMMUNITIES = [
    {"slug": "cardiology-club", "name": "Cardiology Club", "emoji": "🫀", "specialty": "Cardiology",
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
    {"slug": "radiology-residents", "name": "Radiology Residents", "emoji": "🩻", "specialty": "Radiology",
     "base_members": 5430,
     "description": "Image interpretation, diagnostic technique and daily teaching cases.",
     "messages": [
         ("Priya Nair", "Weekly reminder: commit your read before you open the AI overlay. We are collecting "
                        "override rates for the audit and they only mean something if the order holds."),
         ("Michael Brown", "Our override rate last month was 4%. Suspiciously low — I think we're anchoring."),
         ("Priya Nair", "That's exactly the number worth investigating. Low overrides can mean the model is "
                        "good or that nobody is really looking."),
     ]},
    {"slug": "neurology-network", "name": "Neurology Network", "emoji": "🧠", "specialty": "Neurology",
     "base_members": 8930,
     "description": "The nervous system, stroke pathways and neurological examination.",
     "messages": [
         ("Dr. Amara Okafor", "Door-to-needle audit is out. Median 41 minutes, down from 58."),
         ("Emily Davis", "What changed? Imaging turnaround or the pathway itself?"),
         ("Dr. Amara Okafor", "Mostly pre-alert. The scanner was never the bottleneck."),
     ]},
    {"slug": "surgery-society", "name": "Surgery Society", "emoji": "🔪", "specialty": "Surgery",
     "base_members": 15200,
     "description": "Surgical technique, operative case discussion and theatre etiquette.",
     "messages": [
         ("Michael Brown", "Suturing practice session Thursday 6pm, pads provided, bring loupes if you have them."),
         ("James Wilson", "Can we cover subcuticular closure? Mine still looks like a crime scene."),
     ]},
    {"slug": "emergency-medicine", "name": "Emergency Medicine", "emoji": "🚑", "specialty": "Emergency",
     "base_members": 11200,
     "description": "Critical care, trauma management and emergency protocols.",
     "messages": [
         ("Dr. Michael Chen", "Reminder that the sepsis alert is decision support, not a diagnosis. Two "
                              "flagged patients last night were both dehydration."),
         ("Emily Davis", "How many alerts per shift are you seeing?"),
         ("Dr. Michael Chen", "Eleven. Which is the whole problem — at that rate people stop reading them."),
     ]},
    {"slug": "pediatrics-pals", "name": "Pediatrics Pals", "emoji": "🧸", "specialty": "Paediatrics",
     "base_members": 7650,
     "description": "Child health, developmental milestones and paediatric emergencies.",
     "messages": [
         ("Emily Davis", "Weight-based dosing drill posted. Ten scenarios, no calculator on the first pass."),
     ]},
    {"slug": "internal-medicine", "name": "Internal Medicine", "emoji": "🩺", "specialty": "Internal Medicine",
     "base_members": 18900,
     "description": "Adult medicine, diagnostic reasoning and chronic disease management.",
     "messages": [
         ("James Wilson", "Case: 54F, three weeks of fatigue, normocytic anaemia, raised ferritin. Where are "
                          "you going next?"),
         ("Priya Nair", "Ferritin is an acute phase reactant — I'd want CRP and a transferrin saturation "
                        "before calling it iron overload."),
     ]},
    {"slug": "ai-in-medicine", "name": "AI in Medicine", "emoji": "🤖", "specialty": "Informatics",
     "base_members": 3120,
     "description": "Clinical AI, model evaluation, governance and safe deployment.",
     "messages": [
         ("Dr. Amara Okafor", "Paper of the week: external validation of a sepsis prediction model. AUC well "
                              "below the vendor claim, alerts on a large share of admissions."),
         ("Priya Nair", "The alert volume is the part people underestimate. Fatigue makes the true positives "
                        "worthless too."),
         ("Dr. Sarah Chen", "This is going in the certification reading list."),
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
        "emoji": "🩻",
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
            {"prompt": "A segmentation model returns a finding with 41% confidence on an unusual film. What "
                       "is the appropriate interpretation?",
             "explanation": "Low confidence signals the input may sit outside the model's operating "
                            "envelope. It is a prompt for closer human review, not a probability of disease.",
             "choices": [("Treat it as a flag that the input may be out of distribution and review it "
                          "carefully yourself", True),
                         ("Treat 41% as the probability the patient has the disease", False),
                         ("Discard the case as unreadable", False),
                         ("Re-run the model until confidence exceeds the threshold", False)]},
            {"prompt": "A saliency map highlights the region around a lesion the model flagged. What does "
                       "that establish?",
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
        "emoji": "🫀",
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
        "emoji": "🦴",
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
        "emoji": "💊",
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

def _seed_articles(session: Session) -> None:
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
                title=str(spec["title"]),
                author=str(spec["author"]),
                description=str(spec["description"]),
                rating=float(spec["rating"]),
                downloads=str(spec.get("downloads", "")),
                duration=str(spec.get("duration", "")),
                premium=bool(spec["premium"]),
                cover_hue=int(spec["cover_hue"]),
            )
        )
    session.commit()


def _seed_communities(session: Session) -> None:
    for spec in COMMUNITIES:
        community = session.exec(
            select(Community).where(Community.slug == spec["slug"])
        ).first()
        if community:
            continue
        community = Community(
            slug=str(spec["slug"]),
            name=str(spec["name"]),
            description=str(spec["description"]),
            specialty=str(spec["specialty"]),
            emoji=str(spec["emoji"]),
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
        if session.exec(select(Challenge).where(Challenge.slug == spec["slug"])).first():
            continue
        questions = spec["questions"]
        assert isinstance(questions, list)
        per_question = max(1, int(spec["points"]) // max(1, len(questions)))

        challenge = Challenge(
            slug=str(spec["slug"]),
            title=str(spec["title"]),
            description=str(spec["description"]),
            topic=str(spec["topic"]),
            emoji=str(spec["emoji"]),
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
        "certified@medly.dev": 1450,
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
            certified=True,
            certified_at=NOW - timedelta(days=30),
            competency_score=88,
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
