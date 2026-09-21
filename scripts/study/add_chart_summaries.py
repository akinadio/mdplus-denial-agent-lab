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
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study"
SEED = 20260905

# Conservative care that is actually plausible for the joint in question.
PT = {
    "knee": ("supervised physical therapy focused on quadriceps strengthening and "
             "range of motion"),
    "knee_scope": "supervised physical therapy focused on quadriceps strengthening and range of motion",
    "knee_acl": "supervised physical therapy for range of motion and quadriceps strengthening, with bracing",
    "hip_scope": "supervised physical therapy focused on core and hip stabilization with activity modification",
    "hip": "supervised physical therapy focused on hip abductor strengthening and gait",
    "shoulder": ("supervised physical therapy focused on rotator cuff strengthening "
                 "and scapular mechanics"),
    "spine": ("supervised physical therapy including core stabilization and lumbar "
              "flexibility"),
    "cervical": "supervised physical therapy including cervical traction and postural training",
    "ankle": "supervised physical therapy focused on ankle strengthening and balance",
    "foot": "activity modification, wide toe-box footwear and a custom orthotic",
    # 2026-09-21: the three profiles below replace charts that described the
    # WRONG disease for the operation (see JOINT).
    "shoulder_instability": ("supervised physical therapy focused on rotator cuff and "
                             "scapular stabilizer strengthening with activity modification"),
    "shoulder_oa": ("supervised physical therapy focused on range of motion and "
                    "periscapular strengthening"),
    "knee_tka": ("supervised physical therapy focused on quadriceps strengthening and "
                 "range of motion"),
    "spine_fusion": ("supervised physical therapy including core stabilization and lumbar "
                     "flexibility"),
}
IMAGING = {
    "knee": ("MRI of the knee: full-thickness cartilage loss in the medial compartment "
             "with bone-on-bone apposition; Kellgren-Lawrence grade 4 medially"),
    # Arthroscopy is EXCLUDED for end-stage arthritis. The first pilot gave every
    # knee case grade-4 OA and the grader rightly caught letters arguing for a
    # meniscectomy from a disqualifying chart.
    "knee_scope": ("MRI of the knee: displaced bucket-handle tear of the medial meniscus "
                   "with mechanical locking; articular cartilage preserved, Kellgren-Lawrence grade 1"),
    "knee_acl": ("MRI of the knee: complete mid-substance tear of the anterior cruciate "
                 "ligament with bone bruise pattern; menisci intact; no significant arthritis"),
    "hip_scope": ("MRI arthrogram of the hip: anterosuperior labral tear with cam-type "
                  "femoroacetabular impingement, alpha angle 68 degrees; joint space preserved, "
                  "Tonnis grade 0"),
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
    "shoulder_instability": ("MR arthrogram of the shoulder: anteroinferior labral tear "
                             "(Bankart lesion) with a small Hill-Sachs lesion; glenoid bone "
                             "loss under 10 percent; rotator cuff intact"),
    "shoulder_oa": ("Shoulder radiographs (true AP and axillary): complete loss of "
                    "glenohumeral joint space with osteophytes, subchondral sclerosis and "
                    "a flattened glenoid; CT confirms an intact rotator cuff"),
    "knee_tka": ("Weight-bearing knee radiographs: bone-on-bone apposition in the medial "
                 "and patellofemoral compartments with lateral joint-space narrowing; "
                 "Kellgren-Lawrence grade 4"),
    "spine_fusion": ("MRI lumbar spine and flexion-extension radiographs: grade I "
                     "degenerative spondylolisthesis at L4-L5 with 5 mm of translation "
                     "on flexion-extension and severe central stenosis compressing the "
                     "cauda equina"),
}
# Until 2026-09-21 four operations shared another operation's chart, and the
# smoke test's grader caught it: a labral REPAIR (29806) and a total shoulder
# REPLACEMENT (23472) both carried a rotator cuff tear -- for TSA an intact cuff
# is a requirement; a total knee (27447) carried isolated medial disease, which
# is the indication for a PARTIAL knee; and a lumbar fusion (22612) carried a
# plain disc extrusion, which is a decompression indication with nothing to
# fuse. Every arm wrote against the same wrong chart, so no arm was favoured,
# but a letter cannot be graded fairly against a chart that argues for a
# different operation.
JOINT = {
    "27447": "knee_tka", "27446": "knee", "29881": "knee_scope", "29888": "knee_acl",
    "27130": "hip", "29914": "hip_scope",
    "23472": "shoulder_oa", "29827": "shoulder", "29806": "shoulder_instability",
    "22551": "cervical", "22612": "spine_fusion", "63030": "spine",
    "27702": "ankle", "28296": "foot",
}
REGENERATED_2026_09_21 = {"27447", "23472", "29806", "22612"}
FUNCTION = {
    "knee": "cannot climb stairs without assistance and wakes 3-4 times nightly with pain",
    "knee_scope": "experiences locking and giving way; cannot squat or kneel; limited to level walking",
    "knee_acl": "experiences recurrent instability with pivoting; has given way twice on stairs",
    "hip_scope": "has sharp anterior groin pain with sitting and pivoting; cannot run or squat",
    "hip": "ambulates with a cane, limited to one block, and cannot put on shoes unassisted",
    "shoulder": "cannot lift the arm above shoulder height or sleep on the affected side",
    "spine": "cannot stand more than 10 minutes; radicular pain into the right calf",
    "cervical": "radicular pain and numbness into the right thumb and index finger with weakness",
    "ankle": "ambulates with an antalgic gait, limited to two blocks",
    "foot": "cannot tolerate closed shoes; ulceration risk over the prominence",
    "shoulder_instability": ("has had three anterior dislocations since symptoms began, the last "
                             "reduced in the emergency department; avoids overhead reaching "
                             "and cannot return to work lifting"),
    "shoulder_oa": "cannot reach overhead, dress without help, or sleep on the affected side",
    "knee_tka": "cannot climb stairs without assistance and wakes 3-4 times nightly with pain",
    "spine_fusion": ("cannot stand or walk more than 10 minutes before leg pain and "
                     "heaviness force a stop; relieved by sitting"),
}
# Only for the regenerated profiles; the other charts keep their original
# wording byte for byte so letters already drafted against them stay valid.
SYMPTOM = {
    "shoulder_instability": "recurrent episodes of shoulder instability with apprehension",
    "shoulder_oa": "progressive pain in the shoulder, unrelieved by rest",
    "knee_tka": "progressive pain in the knee, unrelieved by rest",
    "spine_fusion": "progressive pain in the lower back and legs, unrelieved by rest",
}
EXAM = {
    "shoulder_instability": ("positive apprehension and relocation tests; increased anterior "
                             "translation on load-and-shift; full strength"),
    "shoulder_oa": ("glenohumeral crepitus; active forward elevation limited to 90 degrees "
                    "and external rotation to 10 degrees; cuff strength intact"),
    "knee_tka": "varus alignment, crepitus and effusion; range of motion 5 to 100 degrees",
    "spine_fusion": ("neurogenic claudication; diminished sensation in both L5 dermatomes; "
                     "no bowel or bladder dysfunction"),
}
MEDS = {
    # an injection does nothing for a dislocating shoulder; it is not charted
    "shoulder_instability": "NSAIDs for {m} months during flares; no injection (not indicated for instability)",
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
    sym = SYMPTOM.get(j) or (
        "progressive pain in the "
        f"{'lower back' if j == 'spine' else 'neck' if j == 'cervical' else j.split('_')[0]}, "
        "unrelieved by rest")
    visits = rng.choice([16, 18, 20, 24])     # draw order kept: see test in main()
    med_m, inj_w = rng.choice([4, 6, 8]), rng.choice([2, 3, 4])
    meds = (MEDS[j].format(m=med_m) if j in MEDS else
            f"NSAIDs for {med_m} months with inadequate relief; "
            f"corticosteroid injection {inj.isoformat()} giving {inj_w} weeks "
            "of partial relief")
    exam = EXAM.get(j) or ("positive provocative testing on the affected side; "
                           f"{'neurologic deficit corresponding to the imaged level' if j in ('spine','cervical') else 'range of motion limited by pain'}")
    return "\n".join([
        "CLINICAL SUMMARY (from the prior authorization packet)",
        f"- Symptom duration: {months} months of {sym}.",
        f"- Conservative care: {PT[j]}, {weeks} weeks, "
        f"{pt_start.isoformat()} to {pt_end.isoformat()}, {visits} "
        "visits completed. Documented in the physical therapy discharge note.",
        f"- Medication: {meds}.",
        f"- Imaging {img.isoformat()}: {IMAGING[j]}.",
        f"- Function: patient {FUNCTION[j]}.",
        f"- Exam: {exam}.",
        "- No active infection, no untreated substance use, BMI 29, non-smoker.",
        f"- Surgeon: {rng.choice(['Reyes','Okafor','Lindqvist','Marchetti','Duval'])}, MD, "
        "orthopedic surgery.",
    ])


def main() -> int:
    p = STUDY / "cases.json"
    doc = json.loads(p.read_text())
    # PER CASE, not one shared stream. A single seeded RNG walked in case_id
    # order means adding one case reshuffles every chart after it -- which
    # would silently invalidate every letter already drafted against the old
    # charts. Seeding from the case_id makes each chart depend only on its own
    # case, so the set can grow without disturbing what is already paid for.
    regen = "--regenerate" in sys.argv
    fix_wrong = "--fix-wrong-disease" in sys.argv
    added = kept = 0
    for c in sorted(doc["cases"], key=lambda x: x["case_id"]):
        if fix_wrong and c["cpt"] in REGENERATED_2026_09_21 and not c.get("chart_regenerated"):
            c["chart_summary_before_2026_09_21"] = c.get("chart_summary", "")
            c["chart_regenerated"] = "2026-09-21: chart described another operation's disease"
            c["chart_summary"] = ""
        if c.get("chart_summary") and not regen:
            kept += 1
            continue
        seed = int(hashlib.sha256((str(SEED) + "|" + c["case_id"]).encode())
                   .hexdigest()[:12], 16)
        c["chart_summary"] = chart(c, random.Random(seed))
        added += 1
    print(f"chart summary written for {added} case(s); {kept} left untouched")
    doc["chart_summaries"] = "used when drafting letters, not during retrieval"
    p.write_text(json.dumps(doc, indent=1))
    print("\nexample:\n" + doc["cases"][0]["chart_summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
