/* Shared mockup content.
 * DEFAULT STATE IS EMPTY / FROM ZERO. A brand-new visitor has provided nothing.
 * `requirements` is the GENERIC "what insurers usually ask for" list (no patient
 * specifics). `example` holds the optional Maria demo, whose wording is taken from
 * the real source e2e/tests/denial-case.spec.js. No invented medical numbers.
 * Nothing here makes a network call. */
window.APPEAL = {
  product: {
    name: "OrthoAppeals",
    tagline: "Your orthopedic procedure was denied? You can fix it, for free.",
    promise:
      "Insurance denials are often just missing paperwork, not a final no. We walk you through it in plain language and help you build a strong appeal, step by step.",
    reassure: "Most denials like this can be appealed. Let's do it together.",
  },

  // Common starting choices for a brand-new user (they pick or type their own).
  // Kept for backward-compat / the optional example; the live flows now use
  // procedureCategories (category → subtype drilldown) below.
  surgeries: [
    "Knee replacement",
    "Hip replacement",
    "Shoulder surgery",
    "Another surgery",
  ],

  // PROCEDURE PICKER: the patient first picks a body-area category, then a
  // specific procedure (or "My procedure isn't listed" free text). Grouped into
  // the 5 categories the clinical team specified. CPT codes are secondary/tiny
  // in the UI. Taxonomy source: procedure_taxonomy.csv.
  procedureCategories: [
    {
      id: "knee",
      label: "Knee",
      bodyPart: "knee",
      procedures: [
        { id: "tka", label: "Total knee replacement", cpt: "27447", bodyPart: "knee" },
        { id: "pka", label: "Partial knee replacement", cpt: "27446", bodyPart: "knee" },
        { id: "acl", label: "ACL reconstruction", cpt: "29888", bodyPart: "knee" },
        { id: "knee-scope", label: "Knee arthroscopy / meniscus surgery", cpt: "29881", bodyPart: "knee" },
      ],
    },
    {
      id: "hip",
      label: "Hip",
      bodyPart: "hip",
      procedures: [
        { id: "tha", label: "Total hip replacement", cpt: "27130", bodyPart: "hip" },
        { id: "hip-scope", label: "Hip arthroscopy", cpt: "29914", bodyPart: "hip" },
      ],
    },
    {
      id: "shoulder",
      label: "Shoulder",
      bodyPart: "shoulder",
      procedures: [
        { id: "rcr", label: "Rotator cuff repair", cpt: "29827", bodyPart: "shoulder" },
        { id: "tsa", label: "Total shoulder replacement", cpt: "23472", bodyPart: "shoulder" },
        { id: "labral", label: "Shoulder labral / instability repair", cpt: "29806", bodyPart: "shoulder" },
      ],
    },
    {
      id: "footankle",
      label: "Foot & Ankle",
      bodyPart: "ankle",
      procedures: [
        { id: "tar", label: "Total ankle replacement", cpt: "27702", bodyPart: "ankle" },
        { id: "bunion", label: "Bunion surgery (hallux valgus)", cpt: "28296", bodyPart: "ankle" },
      ],
    },
    {
      id: "spine",
      label: "Spine",
      bodyPart: "spine",
      procedures: [
        { id: "lumbar-fusion", label: "Lower back (lumbar) fusion", cpt: "22612", bodyPart: "spine" },
        { id: "acdf", label: "Neck (cervical) fusion (ACDF)", cpt: "22551", bodyPart: "spine" },
        { id: "microdisc", label: "Lower back disc surgery / decompression", cpt: "63030", bodyPart: "spine" },
      ],
    },
  ],

  // IMAGING questions are DERIVED from the chosen bodyPart, not hardcoded in the
  // flat requirements list. Surgeon's rule: knee → ask about X-ray only; every
  // other body part → ask about X-ray AND advanced imaging (MRI). Copy frames it
  // as pulling the imaging status "from the doctor's notes".
  imaging: {
    xray: {
      id: "xray",
      q: "Have you had any X-rays of the joint?",
      title: "X-ray report",
      plain: "The written report from your X-rays, not just the images.",
      why: "Your doctor's notes usually point to an X-ray, and insurers want the written report that describes the wear or damage in the joint, so this is a key piece.",
      how: "First, log in to your insurance or hospital patient portal and download the written radiology report, then send it to your insurance. If it isn't there, call the X-ray facility where it was done and ask them to send the report to your insurance.",
    },
    mri: {
      id: "mri",
      q: "Have you had an MRI or other advanced scan of the joint?",
      title: "MRI / advanced imaging report",
      plain: "The written report from an MRI or similar scan, not just the images.",
      why: "For this body part, insurers often expect a more detailed scan on top of an X-ray. Your doctor's notes usually mention it, and the written report really strengthens your case.",
      how: "First, log in to your insurance or hospital patient portal and download the written MRI report, then send it to your insurance. If it isn't there, call the MRI facility where it was done and ask them to send the report to your insurance.",
    },
  },

  // Which imaging questions apply to each bodyPart. Knee = X-ray only;
  // everything else = X-ray + MRI (per the surgeon's rule above).
  imagingByBodyPart: {
    knee: ["xray"],
    hip: ["xray", "mri"],
    shoulder: ["xray", "mri"],
    ankle: ["xray", "mri"],
    spine: ["xray", "mri"],
    _default: ["xray", "mri"],
  },

  // US states, asked BEFORE the insurer so we can filter the insurer list.
  states: [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "District of Columbia", "Florida", "Georgia",
    "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
    "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire",
    "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota",
    "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
    "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont",
    "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
  ],

  // STATE → INSURER map. Researched per-state directory of the major medical
  // insurers actually operating in each state (national carriers, the state's
  // Blue Cross/Blue Shield licensee(s), leading regional plans, and top Medicaid
  // managed-care plans), ordered by market presence. Sources: KFF market-share
  // data, state Departments of Insurance, and state Medicaid rosters — captured
  // with per-state citations in data/policy_platform/insurers_by_state.json.
  // Kaiser Permanente is intentionally excluded per product scope. Not exhaustive
  // of every small carrier; patients whose plan isn't listed can type it in.
  // Rebuild with scripts/build_insurer_directory.py.
  insurersByState: {
    "Alabama": ["Blue Cross and Blue Shield of Alabama", "UnitedHealthcare", "Humana", "Aetna", "Cigna", "Viva Health", "Ambetter"],
    "Alaska": ["Premera Blue Cross Blue Shield of Alaska", "Moda Health", "Aetna", "Cigna", "UnitedHealthcare"],
    "Arizona": ["Blue Cross Blue Shield of Arizona", "UnitedHealthcare", "Cigna", "Aetna", "Banner Health", "Ambetter (Arizona Complete Health)", "Molina Healthcare", "Humana"],
    "Arkansas": ["Arkansas Blue Cross and Blue Shield", "UnitedHealthcare", "Ambetter", "QualChoice / Health Advantage", "Cigna", "Humana"],
    "California": ["Blue Shield of California", "Anthem Blue Cross", "Health Net", "Molina Healthcare", "L.A. Care Health Plan", "UnitedHealthcare", "Aetna", "Cigna"],
    "Colorado": ["Anthem Blue Cross Blue Shield", "UnitedHealthcare", "Cigna", "Aetna", "Rocky Mountain Health Plans", "Denver Health Medical Plan", "Colorado Access"],
    "Connecticut": ["Anthem Blue Cross and Blue Shield", "ConnectiCare", "Cigna", "Aetna", "UnitedHealthcare / Oxford", "Harvard Pilgrim Health Care"],
    "Delaware": ["Highmark Blue Cross Blue Shield Delaware", "Aetna", "AmeriHealth Caritas Delaware", "Highmark Health Options", "UnitedHealthcare", "Cigna"],
    "District of Columbia": ["CareFirst BlueCross BlueShield", "UnitedHealthcare", "Aetna", "AmeriHealth Caritas DC", "MedStar Family Choice DC", "Cigna"],
    "Florida": ["Florida Blue", "UnitedHealthcare", "Humana", "Aetna", "Cigna", "Ambetter (Sunshine Health)", "Molina Healthcare", "Simply Healthcare"],
    "Georgia": ["Anthem Blue Cross and Blue Shield", "UnitedHealthcare", "Aetna", "CareSource", "Peach State Health Plan", "Cigna", "Humana", "Wellpoint"],
    "Hawaii": ["HMSA (Hawaii Medical Service Association)", "UHA (University Health Alliance)", "HMAA", "AlohaCare", "'Ohana Health Plan", "UnitedHealthcare Community Plan"],
    "Idaho": ["Blue Cross of Idaho", "Regence BlueShield of Idaho", "SelectHealth", "PacificSource Health Plans", "Molina Healthcare", "Mountain Health CO-OP", "UnitedHealthcare", "Cigna"],
    "Illinois": ["Blue Cross Blue Shield of Illinois", "UnitedHealthcare", "Aetna", "Cigna", "Humana", "Meridian", "Molina Healthcare", "CountyCare", "Ambetter"],
    "Indiana": ["Anthem Blue Cross Blue Shield", "UnitedHealthcare", "CareSource", "Managed Health Services (MHS)", "MDwise", "Aetna", "Cigna", "Humana"],
    "Iowa": ["Wellmark Blue Cross Blue Shield", "UnitedHealthcare", "Wellpoint Iowa", "Iowa Total Care", "Molina Healthcare", "Aetna", "Cigna"],
    "Kansas": ["Blue Cross and Blue Shield of Kansas", "Blue Cross and Blue Shield of Kansas City", "Sunflower Health Plan", "UnitedHealthcare", "Healthy Blue", "Aetna", "Cigna", "Ambetter"],
    "Kentucky": ["Anthem Blue Cross Blue Shield", "Humana", "Passport Health Plan by Molina", "WellCare of Kentucky", "UnitedHealthcare", "Aetna", "CareSource", "Ambetter"],
    "Louisiana": ["Blue Cross and Blue Shield of Louisiana", "UnitedHealthcare", "Humana", "Aetna", "Cigna", "Louisiana Healthcare Connections", "Healthy Blue Louisiana", "AmeriHealth Caritas Louisiana", "Vantage Health Plan"],
    "Maine": ["Anthem Blue Cross and Blue Shield", "Harvard Pilgrim Health Care", "Community Health Options", "Aetna", "UnitedHealthcare", "Cigna", "Martin's Point Health Care"],
    "Maryland": ["CareFirst BlueCross BlueShield", "UnitedHealthcare", "Aetna", "Cigna", "Priority Partners", "Maryland Physicians Care", "Wellpoint Maryland", "MedStar Family Choice"],
    "Massachusetts": ["Blue Cross Blue Shield of Massachusetts", "Harvard Pilgrim Health Care", "Tufts Health Plan", "Mass General Brigham Health Plan", "WellSense Health Plan", "Fallon Health", "Health New England", "UnitedHealthcare", "Aetna"],
    "Michigan": ["Blue Cross Blue Shield of Michigan", "Priority Health", "Health Alliance Plan (HAP)", "UnitedHealthcare", "Meridian Health Plan", "Molina Healthcare", "McLaren Health Plan", "Aetna", "Humana"],
    "Minnesota": ["Blue Cross and Blue Shield of Minnesota", "HealthPartners", "UCare", "Medica", "UnitedHealthcare", "PreferredOne", "Humana"],
    "Mississippi": ["Blue Cross & Blue Shield of Mississippi", "UnitedHealthcare", "Cigna", "Aetna", "Humana", "Ambetter (Magnolia Health)", "Molina Healthcare", "TrueCare"],
    "Missouri": ["Anthem Blue Cross Blue Shield", "Blue Cross and Blue Shield of Kansas City", "UnitedHealthcare", "Cigna", "Aetna", "Ambetter (Home State Health)", "Healthy Blue", "Medica"],
    "Montana": ["Blue Cross Blue Shield of Montana", "PacificSource Health Plans", "Mountain Health CO-OP", "UnitedHealthcare", "Allegiance", "Humana", "Aetna"],
    "Nebraska": ["Blue Cross and Blue Shield of Nebraska", "UnitedHealthcare", "Medica", "Aetna", "Cigna", "Nebraska Total Care", "Healthy Blue", "Molina Healthcare"],
    "Nevada": ["Health Plan of Nevada", "Anthem Blue Cross Blue Shield", "UnitedHealthcare", "SilverSummit Healthplan (Ambetter)", "Molina Healthcare", "Hometown Health", "Aetna", "Cigna"],
    "New Hampshire": ["Anthem Blue Cross Blue Shield", "Harvard Pilgrim Health Care", "Cigna", "UnitedHealthcare", "Aetna", "NH Healthy Families (Ambetter)", "Well Sense Health Plan", "AmeriHealth Caritas New Hampshire"],
    "New Jersey": ["Horizon Blue Cross Blue Shield of New Jersey", "Aetna", "UnitedHealthcare / Oxford", "Cigna", "AmeriHealth New Jersey", "WellCare", "Clover Health", "Wellpoint"],
    "New Mexico": ["Presbyterian Health Plan", "Blue Cross Blue Shield of New Mexico", "Molina Healthcare", "UnitedHealthcare Community Plan", "Western Sky Community Care", "Cigna", "Humana"],
    "New York": ["Fidelis Care", "Healthfirst", "UnitedHealthcare / Oxford", "Excellus BlueCross BlueShield", "Anthem Blue Cross and Blue Shield (formerly Empire)", "MVP Health Care", "EmblemHealth", "CDPHP", "Aetna"],
    "North Carolina": ["Blue Cross and Blue Shield of North Carolina", "UnitedHealthcare", "Aetna", "Cigna", "Humana", "Ambetter (WellCare)", "AmeriHealth Caritas North Carolina", "Healthy Blue", "Carolina Complete Health"],
    "North Dakota": ["Blue Cross Blue Shield of North Dakota", "Sanford Health Plan", "Medica", "UnitedHealthcare", "Humana", "Aetna"],
    "Ohio": ["Anthem Blue Cross and Blue Shield", "Medical Mutual of Ohio", "CareSource", "UnitedHealthcare", "Aetna", "Molina Healthcare", "Buckeye Health Plan", "Humana", "Cigna"],
    "Oklahoma": ["Blue Cross Blue Shield of Oklahoma", "UnitedHealthcare", "Aetna", "Cigna", "Humana", "CommunityCare", "Oklahoma Complete Health (Ambetter)", "Medica"],
    "Oregon": ["Regence BlueCross BlueShield of Oregon", "Providence Health Plan", "Moda Health", "PacificSource Health Plans", "UnitedHealthcare", "Trillium Community Health Plan", "Health Net of Oregon"],
    "Pennsylvania": ["Highmark Blue Cross Blue Shield", "Independence Blue Cross", "UPMC Health Plan", "Geisinger Health Plan", "Capital Blue Cross", "Aetna", "Cigna", "UnitedHealthcare"],
    "Rhode Island": ["Blue Cross & Blue Shield of Rhode Island", "UnitedHealthcare", "Neighborhood Health Plan of Rhode Island", "Tufts Health Plan", "Aetna", "Cigna"],
    "South Carolina": ["BlueCross BlueShield of South Carolina", "BlueChoice HealthPlan", "UnitedHealthcare", "Aetna", "Cigna", "Absolute Total Care (Ambetter)", "Molina Healthcare", "Humana"],
    "South Dakota": ["Sanford Health Plan", "Avera Health Plans", "Wellmark Blue Cross Blue Shield of South Dakota", "DakotaCare", "Medica", "UnitedHealthcare"],
    "Tennessee": ["BlueCross BlueShield of Tennessee", "Cigna", "UnitedHealthcare", "Aetna", "Humana", "Wellpoint (Amerigroup)", "Oscar Health", "Ambetter"],
    "Texas": ["Blue Cross Blue Shield of Texas", "UnitedHealthcare", "Aetna", "Cigna", "Humana", "Superior HealthPlan (Ambetter)", "Molina Healthcare", "Oscar Health", "Community Health Choice"],
    "Utah": ["SelectHealth", "Regence BlueCross BlueShield of Utah", "UnitedHealthcare", "PEHP", "Molina Healthcare", "University of Utah Health Plans (Healthy U)", "Cigna", "Aetna"],
    "Vermont": ["Blue Cross Blue Shield of Vermont", "MVP Health Care", "UnitedHealthcare", "Cigna", "Aetna"],
    "Virginia": ["Anthem Blue Cross Blue Shield (HealthKeepers)", "Sentara Health Plans", "UnitedHealthcare", "Aetna", "Cigna", "CareFirst BlueCross BlueShield", "Humana"],
    "Washington": ["Premera Blue Cross", "Regence BlueShield", "Molina Healthcare", "UnitedHealthcare", "Coordinated Care (Ambetter)", "Community Health Plan of Washington", "Wellpoint"],
    "West Virginia": ["Highmark Blue Cross Blue Shield West Virginia", "The Health Plan", "UnitedHealthcare", "Aetna Better Health of West Virginia", "UniCare Health Plan of West Virginia", "Highmark Health Options West Virginia", "CareSource", "Humana"],
    "Wisconsin": ["UnitedHealthcare", "Anthem Blue Cross Blue Shield of Wisconsin", "Security Health Plan", "Quartz Health Plan", "Network Health", "Dean Health Plan", "Common Ground Healthcare Cooperative", "Molina Healthcare", "MHS Health Wisconsin"],
    "Wyoming": ["Blue Cross Blue Shield of Wyoming", "UnitedHealthcare", "Cigna", "Aetna", "Humana"],
  },

  // Generic set shown for any state we don't have curated per-state data for. A
  // free-text "My plan isn't listed" fallback is ALWAYS offered on top of these.
  // Ordered by national covered lives (largest first) so the most likely payer
  // is near the top; together these cover the great majority of insured
  // Americans. Source: the payer covered-lives table in the internal benchmark
  // workbook (UnitedHealthcare 49.3M, Elevance/Anthem 45.7M, Centene 28.6M,
  // Aetna 27.1M, Cigna 19.1M, HCSC 18M, Humana 16.3M, Molina). Kaiser is
  // intentionally omitted (its integrated-HMO denials are out of scope here).
  // NOTE: still a national fallback, not an authoritative per-state directory —
  // a real per-state payer-availability dataset is still needed for that.
  insurersGeneric: [
    "UnitedHealthcare",
    "Anthem Blue Cross Blue Shield",
    "Blue Cross Blue Shield (other)",
    "Aetna (CVS Health)",
    "Cigna",
    "Humana",
    "Centene / Ambetter",
    "Molina Healthcare",
    "Medicare",
    "Medicaid",
  ],

  // MEMBER ACCESS: how a patient finds/downloads their own plan documents online,
  // per carrier (researched from each carrier's official site). The app fuzzy-
  // matches the chosen insurer name to one of these and shows the steps; anything
  // unmatched uses insurerAccessGeneric. Always also point to "the number on your
  // card". Full source: data/policy_platform/insurer_access_instructions.json.
  insurerAccess: {
    unitedhealthcare: { portal: "member.uhc.com", phone: "1-866-414-1959, or the number on your card", steps: ["Go to member.uhc.com and Sign In (first time: Register with the member ID on your card).", "In the top menu click 'Coverage & Benefits'.", "Choose 'Coverage Documents' (or 'Plan Documents') and download your Summary of Benefits and Coverage (SBC)."] },
    aetna: { portal: "aetna.com", phone: "1-800-872-3862, or the number on your card", steps: ["Go to aetna.com, click 'Log in' and choose 'Members' (first time: Register with your member ID).", "Open 'Coverage & Benefits' / 'Plan Documents'.", "Download your benefits summary / SBC. (No login for just the SBC: aetna.com/sbcsearch/home.)"] },
    cigna: { portal: "my.cigna.com", phone: "1-800-244-6224, or the number on your card", steps: ["Go to my.cigna.com or open the myCigna app and log in.", "Open the 'Coverage' or 'Plan Documents' section.", "Download your Summary of Benefits and Coverage (SBC)."] },
    anthem: { portal: "anthem.com", phone: "The number on the back of your ID card (TTY 711)", steps: ["Go to anthem.com and Log In, or open the Sydney Health app.", "Open the 'Benefits' section.", "Find 'Plan Documents' or your SBC and download it."] },
    humana: { portal: "account.humana.com", phone: "800-457-4708 (Medicare), or the number on your card", steps: ["Go to account.humana.com or open the MyHumana app and sign in.", "Open 'Coverage & Benefits' / 'Plan Documents'.", "Or faster: plandocs.humana.com/medicare-plan-documents with your ID, date of birth, and ZIP."] },
    centene: { portal: "ambetterhealth.com", phone: "The number on the back of your ID card", steps: ["Ambetter: go to ambetterhealth.com, pick your state, and Member Login.", "Open 'Coverage' and scroll to 'Plan Documents'.", "Download your SBC or Evidence of Coverage. (WellCare/Medicare: member.wellcare.com.)"] },
    hcsc: { portal: "your state's BCBS site", phone: "The Member Services number on your ID card", steps: ["Go to your state's Blue site (bcbsil.com, bcbstx.com, bcbsnm.com, bcbsok.com, bcbsmt.com) and Log In.", "Open 'My Coverage' / 'Benefits'.", "Choose 'Plan Documents' or 'Benefit Booklet' and download your SBC."] },
    molina: { portal: "mymolina.com", phone: "The Member Services number on your ID card", steps: ["Go to mymolina.com and sign in (first time: Create an Account with your Member ID, date of birth, and ZIP).", "For full documents, go to molinahealthcare.com > Members > your state > 'Member Materials and Forms'.", "Download your Member Handbook / Evidence of Coverage / SBC."] },
    floridablue: { portal: "floridablue.com", phone: "1-800-352-2583 (TTY 1-800-955-8770)", steps: ["Go to floridablue.com and Log In (first time: Register with your member ID).", "Open 'My Plan' / 'Plan Documents'.", "No login for the SBC: floridablue.com/sbc/search/byplan."] },
    medicare: { portal: "medicare.gov", phone: "1-800-MEDICARE (1-800-633-4227), TTY 1-877-486-2048", steps: ["Go to medicare.gov and Log in / Create account (use the number on your red-white-and-blue card).", "See your Part A & B coverage, claims, and card.", "To check if a service is covered, use medicare.gov/coverage."] },
  },
  insurerAccessGeneric: {
    phone: "The number on the back of your insurance card",
    steps: [
      "Log in to your insurer's member website or app (the address is on the back of your card).",
      "Look for 'Plan Documents', 'Coverage & Benefits', or 'My Plan'.",
      "Open your 'Summary of Benefits and Coverage (SBC)' and download the PDF.",
      "Can't find it? Call the Member Services number on your card and ask them to send it.",
    ],
  },

  // BLUE CROSS / BLUE SHIELD is not one company — each state has its own Blue
  // licensee with its own website. When a patient picks a Blue plan we look up
  // their state here and send them to the RIGHT site by name, instead of a
  // generic "your state's Blue site". (Anthem-branded Blues are handled by the
  // 'anthem' rule; Florida Blue and the HCSC states have their own entries too.)
  // Not exhaustive — states missing here fall back to a "search your state's
  // Blue Cross Blue Shield" instruction. name = the licensee, site = its portal.
  blueByState: {
    "Alabama": { name: "Blue Cross Blue Shield of Alabama", site: "bcbsal.org" },
    "Arizona": { name: "Blue Cross Blue Shield of Arizona", site: "azblue.com" },
    "Arkansas": { name: "Arkansas Blue Cross Blue Shield", site: "arkansasbluecross.com" },
    "California": { name: "Blue Shield of California", site: "blueshieldca.com" },
    "Florida": { name: "Florida Blue", site: "floridablue.com" },
    "Hawaii": { name: "Hawaii Medical Service Association (BCBS)", site: "hmsa.com" },
    "Idaho": { name: "Blue Cross of Idaho", site: "bcidaho.com" },
    "Illinois": { name: "Blue Cross Blue Shield of Illinois", site: "bcbsil.com" },
    "Iowa": { name: "Wellmark Blue Cross Blue Shield", site: "wellmark.com" },
    "Kansas": { name: "Blue Cross Blue Shield of Kansas", site: "bcbsks.com" },
    "Louisiana": { name: "Blue Cross Blue Shield of Louisiana", site: "bcbsla.com" },
    "Maryland": { name: "CareFirst BlueCross BlueShield", site: "carefirst.com" },
    "Massachusetts": { name: "Blue Cross Blue Shield of Massachusetts", site: "bluecrossma.org" },
    "Michigan": { name: "Blue Cross Blue Shield of Michigan", site: "bcbsm.com" },
    "Minnesota": { name: "Blue Cross Blue Shield of Minnesota", site: "bluecrossmn.com" },
    "Mississippi": { name: "Blue Cross Blue Shield of Mississippi", site: "bcbsms.com" },
    "Montana": { name: "Blue Cross Blue Shield of Montana", site: "bcbsmt.com" },
    "Nebraska": { name: "Blue Cross Blue Shield of Nebraska", site: "nebraskablue.com" },
    "New Jersey": { name: "Horizon Blue Cross Blue Shield of New Jersey", site: "horizonblue.com" },
    "New Mexico": { name: "Blue Cross Blue Shield of New Mexico", site: "bcbsnm.com" },
    "North Carolina": { name: "Blue Cross Blue Shield of North Carolina", site: "bluecrossnc.com" },
    "Oklahoma": { name: "Blue Cross Blue Shield of Oklahoma", site: "bcbsok.com" },
    "Pennsylvania": { name: "Independence Blue Cross (eastern PA) or Highmark (western PA)", site: "ibx.com / highmark.com" },
    "Rhode Island": { name: "Blue Cross Blue Shield of Rhode Island", site: "bcbsri.com" },
    "South Carolina": { name: "BlueCross BlueShield of South Carolina", site: "southcarolinablues.com" },
    "Tennessee": { name: "BlueCross BlueShield of Tennessee", site: "bcbst.com" },
    "Texas": { name: "Blue Cross Blue Shield of Texas", site: "bcbstx.com" },
    "Vermont": { name: "Blue Cross Blue Shield of Vermont", site: "bluecrossvt.org" },
    "Virginia": { name: "Anthem / CareFirst (depending on your plan)", site: "carefirst.com / anthem.com" },
    "Washington": { name: "Premera Blue Cross or Regence BlueShield", site: "premera.com / regence.com" },
    "Wyoming": { name: "Blue Cross Blue Shield of Wyoming", site: "bcbswy.com" },
  },

  // CONSERVATIVE-CARE questions: the four things a patient may have tried
  // before surgery. Per the surgeon's clinical model, patients typically must
  // have tried at least 2 OF THESE 4: (1) activity modification, (2) anti-
  // inflammatories, (3) injections, (4) formal physical therapy.
  //
  // We ask by RECENCY ("in the last 6 months"), NOT by dates, session counts,
  // or months of therapy. Those are backend/insurer-threshold logic for later,
  // never asked here. No doctor or pharmacy record is required to say yes (an
  // over-the-counter Advil counts). Every answer is PREPOPULATED "yes"
  // (`default: "yes"`) because most patients have tried these, but the patient
  // can change any answer; nothing is locked. A "yes" means it goes into the
  // appeal as "tried it, and it didn't give lasting relief."
  //
  // `followup` (when present) is the light lasting-vs-not nuance captured only
  // when the answer is yes. `reassure` drives the gentle 2-of-4 guidance.
  // This is reassurance, NOT a hard gate; progress is never blocked on it.
  //
  // Copy is body-part-generic ("your joint" / "your pain"), so it reads
  // correctly for a knee, shoulder, or spine patient. NOTE: imaging (X-ray /
  // MRI) is NOT in this list. It is derived from bodyPart via `imaging` /
  // `imagingByBodyPart` above.
  requirementsIntro:
    "Most people have tried at least three of these four, and that's usually all that's needed. Answer honestly; you can change any answer.",
  requirements: [
    {
      id: "activity",
      q: "Have you changed your activities to avoid the pain, like cutting back on stairs, walking, or sports?",
      title: "Changing your activities",
      default: "yes",
      plain: "You eased off the things that hurt, such as stairs, walking, standing, sports, or work, to get by.",
      why: "Cutting back on the activities that hurt is one of the everyday things insurers count as trying to manage it without surgery. Almost everyone does this, so it usually helps your case.",
      how: "Nothing to request. Just tell us in your own words how you've had to change what you do. Your surgeon's notes often mention it too.",
    },
    {
      id: "meds",
      q: "In the last 6 months, have you taken an anti-inflammatory, like Advil or ibuprofen (even the over-the-counter kind)?",
      title: "Anti-inflammatory medicine",
      default: "yes",
      plain: "You took something like Advil, Motrin, ibuprofen, Aleve, or a prescription version to ease the pain.",
      why: "Anti-inflammatory medicine counts as one of the treatments insurers expect you to try first. Over-the-counter is fine. You don't need a prescription or a pharmacy record.",
      how: "Nothing to request. An over-the-counter pill counts. Just let us know what you took; your doctor's chart may note it too.",
    },
    {
      id: "pt",
      q: "In the last twelve months, have you done any formal or directed therapy for this joint?",
      title: "Physical therapy",
      plain: "You went to a physical therapist, or did the exercises they gave you.",
      why: "Insurers like to see you gave physical therapy a real try. You don't need to count the visits. Just letting us know you did it is enough here.",
      how: "Nothing to hunt down right now. Just tell us you went. Later, your PT clinic can send over their notes if the insurer asks.",
    },
    {
      id: "injection",
      q: "In the last 6 months, have you had a steroid or cortisone injection in the joint?",
      title: "Steroid / cortisone injection",
      plain: "You had a shot in the joint to calm the pain and swelling.",
      why: "An injection is another treatment insurers like to see you tried. What matters most is whether the relief lasted. A shot that wore off actually strengthens the case for surgery.",
      how: "Nothing to request right now. Just tell us if you had one and how it went. Your doctor's office can confirm it from your chart.",
    },
  ],

  // OPTIONAL demo only, loaded when the user clicks "See an example".
  example: {
    name: "Maria Torres",
    plan: "Aetna Open Choice PPO",
    surgery: "Knee replacement",
    deniedOn: "June 9, 2026",
    cpt: "27447",
    denialLetter:
      "We are unable to approve the requested right total knee arthroplasty at this time. The clinical information submitted does not demonstrate that the member has completed and failed the required course of nonsurgical treatment. The submission also does not include sufficient radiographic documentation of qualifying advanced joint disease. The records did not include physical therapy attendance or progress records, dates and outcomes of other conservative treatment, or the formal knee radiology report.",
    // Her plain-language answers, keyed to the requirement ids (from the source).
    answers: {
      activity: "Yes. I stopped taking the stairs and gave up my morning walks because of the pain.",
      meds: "Yes. I took ibuprofen for the pain, but it only helped a little and the relief didn't last.",
      injection: "Yes. I had one cortisone injection that helped for a couple of weeks, then the pain came back.",
      pt: "Yes. I did physical therapy at Harbor Rehabilitation for a while.",
      xray: "Yes. I had X-rays at Suncoast Imaging, but I don't have the written report at home.",
    },
  },
};
