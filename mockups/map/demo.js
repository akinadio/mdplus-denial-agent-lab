/*
 * OrthoAppeals — stage-proof DEMO mode.
 *
 * When `window.__ORTHO_DEMO__` is true (set by ?demo=1, or hard-wired in the
 * self-contained demo build), this file installs a fetch() shim so the ENTIRE
 * real patient flow runs unchanged — the "searching for your policy" progress
 * beats, the result screen, the two-voice appeal letter — but never touches a
 * network. Every response below is canned, deterministic, and offline.
 *
 * Two paths:
 *   1. The scripted walkthrough (patient clicks "See how it works with an
 *      example"): the fictional "Maria Torres" case — an Aetna knee replacement
 *      (CPT 27447) denied for "missing documentation" even though she completed
 *      conservative care. It cites the REAL Aetna Clinical Policy Bulletin 0660.
 *      Harbor Rehabilitation / Suncoast Imaging are fictional providers that
 *      belong to that example patient — they are illustrative, not real data.
 *   2. Free play (patient fills in their own procedure / insurer / state): a
 *      GENERIC result that reflects THEIR choices, with no fabricated policy
 *      number, URL, provider name, or hard deadline. It says plainly that the
 *      demo is not fetching a live policy.
 *
 * Nothing here runs unless the demo flag is set, so shipping it in the repo is
 * inert for the live product.
 */
(function () {
  if (!window.__ORTHO_DEMO__) return;

  // Read the live intake state (the main script's top-level `A`). Resolved at
  // call time, by which point `A` is initialised.
  function getA() {
    try { if (typeof A !== 'undefined' && A) return A; } catch (e) {}
    return window.A || {};
  }

  // A fresh episode id per page load, so the on-screen checklist (which the app
  // saves per episode id) always starts unchecked in a new demo session instead
  // of showing ticks left over from a previous run.
  const RUN_ID = 'demo-' + Math.floor(Math.random() * 1e9);

  // ---- 1) the scripted Maria / Aetna / knee result -------------------------
  const MARIA_RESULT = {
    episode_id: 'demo-maria',
    case_identification: {
      procedure: 'Total knee replacement (right)',
      cpt: '27447',
      payer: 'Aetna Open Choice PPO',
      unresolved_fields: []
    },
    policy_analysis: {
      apparent_reason:
        'Aetna did not say your surgery is unnecessary. It said the packet it received did not yet show two things its own policy requires: a completed trial of non-surgical treatment, and an X-ray report showing the arthritis in your knee. Both of those are true for you — they simply were not in the file Aetna reviewed.',
      unmet_criteria: [
        'Proof of a completed and failed course of non-surgical treatment (physical therapy, anti-inflammatory medicine, activity change, or an injection).',
        'A written X-ray or imaging report documenting advanced arthritis in the knee.'
      ],
      denial_category: 'insufficient_documentation',
      criteria_at_issue: [
        'A trial of non-surgical treatment that did not relieve the pain.',
        'Imaging (X-ray) showing advanced joint disease.',
        'Knee pain that limits your daily activities.'
      ],
      documentation_gaps: [
        'The physical therapy records from Harbor Rehabilitation — the dates you attended and the therapist’s notes.',
        'The written X-ray report from Suncoast Imaging — the radiologist’s typed report, not the images.',
        'A short note listing the medicines you tried (ibuprofen) and the cortisone injection, with rough dates.'
      ],
      uncertainty: []
    },
    next_steps: {
      primary_action:
        'Gather the three records that prove you already meet Aetna’s rules, then send them with a short appeal. You are not missing any treatment — only the paperwork that documents it.',
      ordered_actions: [
        {
          order: 1, party: 'you',
          action: 'Call Harbor Rehabilitation and ask them to send your physical therapy attendance and progress notes to your surgeon’s office.',
          records_needed: ['Your date of birth', 'The rough dates you went to physical therapy']
        },
        {
          order: 2, party: 'you',
          action: 'Call Suncoast Imaging and request the written radiology report for your knee X-ray (the typed report, not the images).',
          records_needed: ['The approximate date of the X-ray']
        },
        {
          order: 3, party: 'provider',
          action: 'Have your surgeon’s office write a brief letter of medical necessity that lists your completed conservative treatment and attaches the PT notes and the X-ray report, citing Aetna CPB 0660.',
          records_needed: ['PT records', 'Radiology report', 'Medication and injection history']
        },
        {
          order: 4, party: 'provider',
          action: 'Submit the appeal to Aetna before the deadline, referencing the original denial and your member ID.',
          records_needed: ['The denial letter', 'Member ID']
        }
      ],
      deadline: {
        value:
          'Most plans give you about 180 days from the date of the denial to appeal, but yours may be shorter. Check the exact deadline on your denial letter, put it on your calendar, and start now — appeal windows are easy to miss.',
        source: null,
        verification_needed: true
      },
      safety_caveat:
        'This plan is based on how denials like this usually work and the answers you gave. Confirm the exact requirements and the appeal deadline printed on your own denial letter before you rely on them.'
    },
    patient_interaction: {
      questions: [
        { question_id: 'pt_dates', text: 'Roughly when did you start and finish physical therapy at Harbor Rehabilitation?', rationale: 'Aetna wants to see that the non-surgical trial lasted long enough. Even approximate months help your surgeon’s office request the right records.', answer_type: 'text' },
        { question_id: 'xray_date', text: 'About when did you have the knee X-ray at Suncoast Imaging?', rationale: 'This helps the office pull the exact radiology report Aetna is asking for.', answer_type: 'text' },
        { question_id: 'other_tx', text: 'Besides ibuprofen and the cortisone injection, did you try anything else for the pain — a brace, a cane, other medicine?', rationale: 'Every piece of conservative treatment you can list makes the case that you meet the policy.', answer_type: 'text' }
      ],
      question_stop_reason: 'These are the only gaps between your file and what Aetna’s policy asks for. Everything else in your case already lines up.',
      provider_records_needed: [
        'Physical therapy attendance and progress notes (Harbor Rehabilitation)',
        'Written radiology report for the knee X-ray (Suncoast Imaging)',
        'Documentation of the anti-inflammatory medicine and the cortisone injection, with dates',
        'A short letter of medical necessity referencing Aetna CPB 0660 (Knee Arthroplasty)'
      ]
    },
    retrieval: {
      selected_source: {
        title: 'Aetna — Knee Arthroplasty (Clinical Policy Bulletin 0660)',
        effective_date: 'revised February 26, 2026',
        url: 'https://www.aetna.com/cpb/medical/data/600_699/0660.html'
      },
      citations: [
        { claim: 'Aetna’s policy requires a documented trial of conservative treatment before it will approve a total knee replacement.', excerpt: 'documentation of a failed course of conservative therapy', reference: 'Aetna CPB 0660, Knee Arthroplasty' },
        { claim: 'The policy also asks for imaging that shows advanced joint disease.', excerpt: 'radiographic evidence of osteoarthritis', reference: 'Aetna CPB 0660, Knee Arthroplasty' }
      ],
      candidates: [
        { title: 'Aetna — Knee Arthroplasty (CPB 0660)', url: 'https://www.aetna.com/cpb/medical/data/600_699/0660.html', decision_summary: 'Selected — this is the bulletin that governs CPT 27447 for your plan.', selected: true },
        { title: 'CMS National Coverage Determination — Lower Limb Arthroplasty', url: 'https://www.cms.gov', decision_summary: 'Not used — this applies to Medicare, not your Aetna commercial plan.', selected: false }
      ]
    },
    confidence: {
      overall: 'high',
      rationale: 'We found the exact Aetna bulletin that covers your procedure and matched every reason in your denial letter to a documentation requirement you already satisfy.'
    },
    blockers: []
  };

  const MARIA_APPEAL = { assessment: { recommended: true, kind: 'appeal', reason: '' }, letters_available: [] };

  const MARIA_LETTERS = {
    provider: {
      markdown:
        '[Date]\n\n' +
        'Aetna — Appeals Department\n' +
        'Re: Appeal of denial for [Member name], Member ID [ID]\n' +
        'Procedure: Total knee arthroplasty, right (CPT 27447)\n' +
        'Denial dated June 9, 2026\n\n' +
        'To the Aetna Medical Review team,\n\n' +
        'We are writing to appeal the denial of the total knee arthroplasty requested for [Member name]. The denial states that the submission did not demonstrate a completed and failed course of conservative treatment or sufficient radiographic documentation. In fact both requirements in Aetna Clinical Policy Bulletin 0660 (Knee Arthroplasty) are met; the supporting records were not included in the original submission and are attached now.\n\n' +
        '**Conservative treatment (CPB 0660).** The patient completed a supervised course of physical therapy at Harbor Rehabilitation, a trial of anti-inflammatory medication, activity modification, and an intra-articular corticosteroid injection, without durable relief. Attendance and progress notes are enclosed.\n\n' +
        '**Radiographic evidence (CPB 0660).** The enclosed radiology report documents advanced degenerative joint disease of the right knee.\n\n' +
        'Because the member meets the criteria set out in Aetna’s own bulletin, we respectfully request that the denial be overturned and the procedure authorized.\n\n' +
        'Sincerely,\n[Surgeon name]\n[Practice name and contact]\n\n' +
        'Enclosures: physical therapy records; radiology report; medication and injection history'
    },
    patient: {
      markdown:
        '[Date]\n\n' +
        'Aetna Appeals Department\n' +
        'Re: [Your name], Member ID [ID]\n' +
        'Knee replacement denied on June 9, 2026\n\n' +
        'To whom it may concern,\n\n' +
        'I am asking you to look again at the denial of my knee replacement. Your letter said the request did not show that I had tried other treatments first, or include my X-ray report. I want you to know that I did do those things.\n\n' +
        'Before surgery was recommended, I went to physical therapy at Harbor Rehabilitation, I took ibuprofen for the pain, I changed how I move to protect my knee, and I had a cortisone injection that only helped for a couple of weeks. I also had an X-ray at Suncoast Imaging. My surgeon’s office is sending you the records that show all of this.\n\n' +
        'I believe my request meets the rules in your own policy for knee replacement (CPB 0660). Please approve the surgery so I can get out of pain and back on my feet.\n\n' +
        'Thank you for reconsidering,\n[Your name]\n[Phone number]'
    }
  };

  // ---- 2) a generic result that reflects the patient's real choices --------
  function genericResult() {
    const a = getA();
    const procedure = (a.surgery && String(a.surgery).trim()) || 'your procedure';
    const procLower = procedure.charAt(0).toLowerCase() + procedure.slice(1);
    const insurer = (a.insurer && String(a.insurer).trim()) || 'your plan';
    const cpt = (a.cpt && String(a.cpt).trim()) || '';
    return {
      episode_id: 'demo-generic',
      case_identification: { procedure: procedure, cpt: cpt, payer: insurer, unresolved_fields: [] },
      policy_analysis: {
        apparent_reason:
          insurer + ' did not necessarily say your ' + procLower + ' is unnecessary. Denials like this usually rest on paperwork the plan wanted but did not receive — most often proof that you tried non-surgical treatment first, and imaging showing the problem. The plan checks your file against its own published coverage policy for ' + procLower + '.',
        unmet_criteria: [
          'Documentation of the non-surgical treatment you already tried (physical therapy, anti-inflammatory medicine, activity change, or an injection).',
          'Imaging (such as an X-ray or MRI) showing the condition that led to surgery.'
        ],
        denial_category: 'insufficient_documentation',
        criteria_at_issue: [
          'A trial of non-surgical treatment.',
          'Imaging showing the underlying problem.',
          'Symptoms that limit your daily activities.'
        ],
        documentation_gaps: [
          'Your physical therapy records — the dates you attended and the therapist’s notes.',
          'Your written imaging report (the radiologist’s typed report, not the images).',
          'A short note listing the medicines and any injections you tried, with rough dates.'
        ],
        uncertainty: []
      },
      next_steps: {
        primary_action:
          'Gather the records that document the treatment you already tried, then send them with a short appeal to ' + insurer + '. In most denials like this, the care was done — only the paperwork was missing from the file.',
        ordered_actions: [
          { order: 1, party: 'you', action: 'Call the clinics where you had physical therapy and imaging, and ask them to send your records to your surgeon’s office.', records_needed: ['Your date of birth', 'The rough dates of your visits'] },
          { order: 2, party: 'you', action: 'Write down the non-surgical treatments you tried for ' + procLower + ' (medicine, activity changes, injections) with approximate dates.', records_needed: [] },
          { order: 3, party: 'provider', action: 'Have your surgeon’s office write a brief letter of medical necessity citing ' + insurer + '’s coverage policy for ' + procLower + ', with your records attached.', records_needed: ['Physical therapy records', 'Imaging report', 'Medication and injection history'] },
          { order: 4, party: 'provider', action: 'Submit the appeal to ' + insurer + ' before the deadline on your denial letter, referencing the denial and your member ID.', records_needed: ['The denial letter', 'Member ID'] }
        ],
        deadline: {
          value:
            'Most plans give you about 180 days from the date of the denial to appeal, but yours may be shorter. Check the exact deadline on your denial letter, put it on your calendar, and start now — appeal windows are easy to miss.',
          source: null,
          verification_needed: true
        },
        safety_caveat:
          'This is general guidance for how denials like this usually work — not a statement about your specific plan. Confirm the exact requirements and deadline on your own denial letter and with ' + insurer + '.'
      },
      patient_interaction: {
        questions: [
          { question_id: 'tx', text: 'What non-surgical treatments did you try for ' + procLower + ', and roughly when?', rationale: 'Your plan wants to see you tried other options first. Even approximate dates help your surgeon’s office pull the right records.', answer_type: 'text' },
          { question_id: 'imaging', text: 'Have you had an X-ray, MRI, or other scan of the area, and about when?', rationale: 'This helps the office get the exact imaging report your plan is asking for.', answer_type: 'text' }
        ],
        question_stop_reason: 'These cover the usual gaps between a file and what a plan asks for. Your denial letter may list others — add anything it names.',
        provider_records_needed: [
          'Physical therapy attendance and progress notes',
          'The written report for any X-ray or MRI of the area',
          'Documentation of medications and any injections you tried, with dates',
          'A short letter of medical necessity referencing ' + insurer + '’s coverage policy for ' + procLower
        ]
      },
      retrieval: {
        selected_source: { title: insurer + ' — its published coverage policy for ' + procLower + ' (this demo does not fetch it live)', effective_date: null, url: null },
        citations: [],
        candidates: []
      },
      confidence: {
        overall: 'medium',
        rationale: 'This is a demonstration using general appeal guidance. The live product looks up ' + insurer + '’s actual published policy for ' + procLower + ' and matches each reason in your denial letter to it.'
      },
      blockers: []
    };
  }

  function genericLetters() {
    const a = getA();
    const procedure = (a.surgery && String(a.surgery).trim()) || 'the procedure';
    const procLower = procedure.charAt(0).toLowerCase() + procedure.slice(1);
    const insurer = (a.insurer && String(a.insurer).trim()) || '[Insurer]';
    const cptLine = a.cpt ? ' (CPT ' + a.cpt + ')' : '';
    return {
      provider: {
        markdown:
          '[Date]\n\n' +
          insurer + ' — Appeals Department\n' +
          'Re: Appeal of denial for [Member name], Member ID [ID]\n' +
          'Procedure: ' + procedure + cptLine + '\n' +
          'Denial dated [date on your letter]\n\n' +
          'To the Medical Review team,\n\n' +
          'We are writing to appeal the denial of the ' + procLower + ' requested for [Member name]. The denial indicates the submission did not fully document the medical-necessity criteria in ' + insurer + '’s coverage policy. The clinical record supports those criteria; the supporting records were not included in the original submission and are attached now.\n\n' +
          '**Conservative treatment.** The patient completed non-surgical treatment (physical therapy, anti-inflammatory medication, activity modification, and/or an injection) without lasting relief. Records are enclosed.\n\n' +
          '**Imaging.** The enclosed report documents the condition underlying the surgical recommendation.\n\n' +
          'Because the member meets the criteria in the plan’s own policy, we respectfully request that the denial be overturned and the procedure authorized.\n\n' +
          'Sincerely,\n[Surgeon name]\n[Practice name and contact]\n\n' +
          'Enclosures: physical therapy records; imaging report; medication and injection history'
      },
      patient: {
        markdown:
          '[Date]\n\n' +
          insurer + ' Appeals Department\n' +
          'Re: [Your name], Member ID [ID]\n' +
          procedure + ' denied on [date on your letter]\n\n' +
          'To whom it may concern,\n\n' +
          'I am asking you to look again at the denial of my ' + procLower + '. Your letter said the request did not show that I had tried other treatments first, or did not include my imaging. I did do those things, and my surgeon’s office is sending you the records that show it.\n\n' +
          'I believe my request meets the rules in your own coverage policy. Please approve it so I can move forward with the care my doctor recommended.\n\n' +
          'Thank you for reconsidering,\n[Your name]\n[Phone number]'
      }
    };
  }

  const isExample = () => !!getA().__demoExample;
  const resultFor = () => (isExample() ? MARIA_RESULT : genericResult());
  const appealFor = () => MARIA_APPEAL; // an appeal is recommended either way
  function _stampDate(letters) {
    const today = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
    const out = {};
    for (const k of Object.keys(letters)) {
      out[k] = { markdown: (letters[k].markdown || '').replace(/\[Date\]/g, today) };
    }
    return out;
  }
  const lettersFor = () => _stampDate(isExample() ? MARIA_LETTERS : genericLetters());

  // Canned response for /api/intake/read so the offline demo can show the whole
  // read + plan-pin + confirm flow. Reflects whatever the player typed; invents
  // nothing beyond a plausible plan name. Add ?confirm=1 to the URL to preview
  // the "confirm what we couldn't read" screen.
  function demoRead() {
    const A = getA();
    const insurer = A.insurer || 'Your insurer';
    const surgery = (A.surgery || 'the surgery');
    const cell = (v, c) => ({ value: v, confidence: c || 'high' });
    const showConfirm = /[?&]confirm=1\b/.test(location.search);
    const letterText =
      'Denial notice from ' + insurer + '.\n' +
      'Requested service: ' + surgery + (A.cpt ? ' (CPT ' + A.cpt + ')' : '') + ' — DENIED.\n' +
      'Reason: not medically necessary under the plan criteria.\n' +
      'You have 180 days from the date of this notice to appeal.';
    const letter = {
      kind: 'denial_letter', outcome: 'read', document_type: 'denial_letter',
      text: letterText,
      fields: {}, denied_procedures: A.cpt ? [{ code: A.cpt, description: surgery, decision: 'DENIED', confidence: 'high' }] : [],
      needs_confirmation: []
    };
    const identity = {
      name: cell('', 'unreadable'),
      insurer_name: cell(insurer),
      insurer_key: null,
      plan_name: showConfirm ? cell('', 'unreadable') : cell(insurer + ' Choice PPO'),
      plan_type: showConfirm ? cell('', 'unreadable') : cell('PPO'),
      member_id: showConfirm ? cell('', 'unreadable') : cell('W123456789'),
      coverage_line: 'commercial'
    };
    const needs = showConfirm ? [
      { key: 'member_id', label: 'Member ID', value: '', confidence: 'unreadable', reason: 'missing', source: 'insurance card' },
      { key: 'plan', label: 'Your exact plan', value: '', confidence: 'unreadable', reason: 'We have your insurer but not the exact plan name — most insurers have many plans.', source: 'plan' }
    ] : [];
    return {
      outcome: 'read', letter: letter, card: null,
      plan: { identity: identity, pinned: !showConfirm, reasons: [] },
      needs_confirmation: needs
    };
  }

  // ---- the fetch shim ------------------------------------------------------
  const realFetch = typeof window.fetch === 'function' ? window.fetch.bind(window) : null;
  const reply = (obj, ok) =>
    Promise.resolve({ ok: ok !== false, status: ok === false ? 500 : 200, json: () => Promise.resolve(obj) });
  const state = { polls: 0 };

  window.fetch = function (url, opts) {
    const u = String(url);
    const method = ((opts && opts.method) || 'GET').toUpperCase();
    if (u.indexOf('/api/') === -1 && !/\/api$/.test(u)) {
      return realFetch ? realFetch(url, opts) : reply({}, false);
    }
    if (/\/api\/health$/.test(u)) return reply({ ok: true, demo: true });
    if (/\/api\/intake\/read$/.test(u) && method === 'POST') {
      return reply(demoRead());
    }
    if (/\/api\/episodes$/.test(u) && method === 'POST') {
      state.polls = 0;
      return reply({ manifest: { episode_id: RUN_ID } });
    }
    if (/\/appeal-letter$/.test(u) && method === 'POST') {
      return reply({ letters: lettersFor() });
    }
    const mv = u.match(/\/appeal-letter\/web_only\?version=(\w+)/);
    if (mv) {
      const v = mv[1];
      return reply({ version: v, markdown: (lettersFor()[v] || {}).markdown || '' });
    }
    if (/\/api\/episodes\/[^/]+$/.test(u)) {
      state.polls += 1;
      const done = state.polls >= 1; // completes on the first poll (~5s of "searching")
      let armResult = null;
      if (done) { armResult = resultFor(); armResult.episode_id = RUN_ID; }
      const arm = done
        ? { runtime: { status: 'completed' }, result: armResult, appeal: appealFor() }
        : { runtime: { status: 'running' } };
      return reply({
        manifest: { episode_id: RUN_ID },
        arms: { web_only: arm },
        events: done ? [] : [{ arm: 'web_only', summary: 'searching' }]
      });
    }
    return reply({}, false);
  };

  // A small badge so it is obvious (to you, not the audience) this is the
  // offline demo build. Hidden when printing.
  document.addEventListener('DOMContentLoaded', function () {
    const b = document.createElement('div');
    b.textContent = 'DEMO';
    b.setAttribute('aria-hidden', 'true');
    b.style.cssText =
      'position:fixed;bottom:10px;right:10px;z-index:9999;background:#1f7d70;color:#fff;' +
      'font:600 11px/1 system-ui,sans-serif;letter-spacing:.08em;padding:5px 8px;border-radius:6px;' +
      'opacity:.75;pointer-events:none;';
    const style = document.createElement('style');
    style.textContent = '@media print{[aria-hidden="true"]{display:none!important}}';
    document.head.appendChild(style);
    document.body.appendChild(b);
  });
})();
