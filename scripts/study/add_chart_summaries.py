#!/usr/bin/env python3
"""Give every case a synthetic chart, so a complete letter is possible at all.

Without one, both arms write letters made of [placeholders] and the grader
marks them unfinished -- which measures the study's missing inputs, not either
system. Six of the first eleven appeal-fatal letters were that artifact.

The chart is deliberately plain: the facts a surgeon's office would put in a
prior-auth packet, in the order a reviewer reads them, with dates relative to
the denial. It is written to be sufficient but not decisive -- every case
carries a documented conservative-care trial, imaging, and a functional
deficit, so a letter that maps criteria to records CAN be written, while
whether the letter actually does so stays the thing being measured.

Attached as `chart_summary` and used only when drafting the letter. Phase 1 is
policy retrieval from payer, code and state; the chart does not enter it, so
adding this does not invalidate retrieval runs already paid for. case_ids are
untouched.

  python3 scripts/study/add_chart_summaries.py
"""
from __future__ import annotations

import datetime
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study"
SEED = 20260905

# Conservative care that is actually plausible for the joint in question.
PT = {
    "knee": ("supervised physical therapy focused on quadriceps strengthening and "
             "range of motion"),
    "hip": "supervised physical therapy focused on hip abductor strengthening and gait",
    "shoulder": ("supervised physical therapy focused on rotator cuff strengthening "
                 "and scapular mechanics"),
    "spine": ("supervised physical therapy including core stabilization and lumbar "
              "flexibility"),
    "cervical": "supervised physical therapy including cervical traction and postural training",
    "ankle": "supervised physical therapy focused on ankle strengthening and balance",
    "foot": "activity modification, wide toe-box footwear and a custom orthotic",
}
IMAGING = {
    "knee": ("MRI of the knee: full-thickness cartilage loss in the medial compartment "
             "with bone-on-bone apposition; Kellgren-Lawrence grade 4 medially"),
    "hip": ("Weight-bearing AP pelvis radiograph: joint space narrowed to 1 mm "
            "superolaterally with subchondral sclerosis and osteophytes"),
    "shoulder": ("MRI of the shoulder: full-thickness supraspinatus tear measuring "
                 "1.8 cm with grade 2 fatty atrophy"),
    "spine": ("MRI lumbar spine: L4-L5 disc extrusion with severe right lateral "
              "recess stenosis and compression of the traversing L5 nerve root"),
    "cervical": ("MRI cervical spine: C5-C6 disc herniation with severe right "
                 "foraminal narrowing and C6 nerve root compression"),
    "ankle": ("Weight-bearing ankle radiographs: tibiotalar joint space obliteration "
              "with subchondral cysts"),
    "foot": ("Weight-bearing foot radiographs: hallux valgus angle 38 degrees, "
             "intermetatarsal angle 17 degrees"),
}
JOINT = {
    "27447": "knee", "27446": "knee", "29881": "knee", "29888": "knee",
    "27130": "hip", "29914": "hip",
    "23472": "shoulder", "29827": "shoulder", "29806": "shoulder",
    "22551": "cervical", "22612": "spine", "63030": "spine",
    "27702": "ankle", "28296": "foot",
}
FUNCTION = {
    "knee": "cannot climb stairs without assistance and wakes 3-4 times nightly with pain",
    "hip": "ambulates with a cane, limited to one block, and cannot put on shoes unassisted",
    "shoulder": "cannot lift the arm above shoulder height or sleep on the affected side",
    "spine": "cannot stand more than 10 minutes; radicular pain into the right calf",
    "cervical": "radicular pain and numbness into the right thumb and index finger with weakness",
    "ankle": "ambulates with an antalgic gait, limited to two blocks",
    "foot": "cannot tolerate closed shoes; ulceration risk over the prominence",
}


def chart(case, rng) -> str:
    j = JOINT.get(case["cpt"], "knee")
    dd = datetime.date.fromisoformat(case["denial_date"])
    weeks = rng.choice([8, 10, 12, 14, 16])
    pt_end = dd - datetime.timedelta(days=rng.randint(20, 60))
    pt_start = pt_end - datetime.timedelta(weeks=weeks)
    inj = pt_end - datetime.timedelta(days=rng.randint(30, 90))
    img = dd - datetime.timedelta(days=rng.randint(25, 75))
    months = rng.choice([9, 12, 14, 18, 24])
    return "\n".join([
        "CLINICAL SUMMARY (from the prior authorization packet)",
        f"- Symptom duration: {months} months of progressive pain in the "
        f"{'lower back' if j == 'spine' else 'neck' if j == 'cervical' else j}, "
        "unrelieved by rest.",
        f"- Conservative care: {PT[j]}, {weeks} weeks, "
        f"{pt_start.isoformat()} to {pt_end.isoformat()}, {rng.choice([16,18,20,24])} "
        "visits completed. Documented in the physical therapy discharge note.",
        f"- Medication: NSAIDs for {rng.choice([4,6,8])} months with inadequate relief; "
        f"corticosteroid injection {inj.isoformat()} giving {rng.choice([2,3,4])} weeks "
        "of partial relief.",
        f"- Imaging {img.isoformat()}: {IMAGING[j]}.",
        f"- Function: patient {FUNCTION[j]}.",
        f"- Exam: positive provocative testing on the affected side; "
        f"{'neurologic deficit corresponding to the imaged level' if j in ('spine','cervical') else 'range of motion limited by pain'}.",
        "- No active infection, no untreated substance use, BMI 29, non-smoker.",
        f"- Surgeon: {rng.choice(['Reyes','Okafor','Lindqvist','Marchetti','Duval'])}, MD, "
        "orthopedic surgery.",
    ])


def main() -> int:
    p = STUDY / "poc_cases.json"
    doc = json.loads(p.read_text())
    rng = random.Random(SEED)
    for c in sorted(doc["cases"], key=lambda x: x["case_id"]):   # deterministic
        c["chart_summary"] = chart(c, rng)
    doc["chart_summaries"] = "added 2026-09-05; used when drafting letters, not in retrieval"
    p.write_text(json.dumps(doc, indent=1))
    print(f"chart summary attached to {len(doc['cases'])} cases")
    print("\nexample:\n" + doc["cases"][0]["chart_summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
