"""The proposed drug-class vocabulary, and the one rule that matches it to a product name.

Phase 6 step 3c, decision B (ADR 0014). `drug_class` is in the plan's `dim_drug` (§8.1) and
`mart_drug_class_failures` needs it (§8.2), but **nothing in the CDSCO archive classifies a
medicine**: there is no ATC code, no therapeutic group, no BNF chapter - only the product name a
manufacturer printed on the pack. So the class cannot be read from the data. It has to come from
outside it, and that means it is a *claim someone made*, not a fact the archive reports.

This module holds that claim in the only form that can be defended: a vocabulary of ingredient
names with a proposed class and a written reason each, which a person accepts or rejects one
batch at a time (`drug_class_review.py`). Only accepted entries reach `dbt/seeds/`. Everything the
vocabulary does not match stays **Unclassified**, and Unclassified is reported as a number on the
dashboard rather than hidden.

Three design choices, each made against the real product names:

1. **Phrases, not words.** A single-word vocabulary gets "Atorvastatin Calcium Tablets IP" filed
   under mineral supplements, because `calcium` here is the salt the statin is formulated as, not
   an ingredient. So mineral and salt names only ever appear as full phrases - `calcium carbonate`,
   `ferrous sulphate`, `sodium chloride` - and a bare `calcium`, `sodium` or `sulphate` is never in
   the vocabulary. Checked against "Diclofenac Sodium", "Thyroxine Sodium" and "Rabeprazole Sodium":
   each matches only its active ingredient.
2. **A list per product, not one class.** Combination products are the norm here, not the exception
   ("Ambroxol Hydrochloride, Terbutaline Sulphate and Guaiphenesin Syrup"), and picking one class
   from three needs a priority rule that cannot be justified. Same shape as `failure_categories`
   (ADR 0009): an array, counted under each class, with the double-counting stated wherever it is
   charted.
3. **Not everything in this archive is a medicine.** Absorbent cotton wool, absorbent gauze,
   bandages, hypodermic syringes, hand sanitiser, soap, hair colour and propylene glycol are all in
   it. Forcing them into a therapeutic class would be a straightforward falsehood, so they get
   classes that say what they are: `Surgical consumable or device`, `Antiseptic / disinfectant`,
   `Cosmetic or toiletry`, `Pharmaceutical raw material`.

**Where the classes come from.** The class of a named ingredient (paracetamol is an analgesic) is
ordinary published pharmacology, not anything derived from CDSCO rows, which is why the accepted
vocabulary is committed to git while the manufacturer-review decisions are not (ADR 0003: those
hold real CDSCO manufacturer names). No count from the archive is stored in the seed either.
"""

import re

# CLEAR: the class is the ingredient's textbook use, single and uncontested, so these are offered
# in one batch per class. JUDGEMENT: a choice had to be made - two defensible classes, an
# ingredient that is not a drug, or a role that depends on what it is combined with. Those are
# asked one at a time with the reason shown, never accepted in a batch.
CLEAR, JUDGEMENT = "clear", "judgement"

UNCLASSIFIED = "Unclassified"  # the residue; never a seed row, always a reported number

# (ingredient phrase, proposed class, kind, reason shown during review)
# The reason is mandatory even for CLEAR rows: "accepted without being told why" is not review.
PROPOSALS: tuple[tuple[str, str, str, str], ...] = (
    # ---------------------------------------------------------------- Antibiotic
    ("amoxycillin", "Antibiotic", CLEAR, "Penicillin-group antibiotic (IP spelling)."),
    ("amoxicillin", "Antibiotic", CLEAR, "The same antibiotic, spelled the INN way."),
    ("ampicillin", "Antibiotic", CLEAR, "Penicillin-group antibiotic."),
    ("cloxacillin", "Antibiotic", CLEAR, "Penicillin-group antibiotic."),
    ("cefixime", "Antibiotic", CLEAR, "Third-generation cephalosporin."),
    ("cefpodoxime", "Antibiotic", CLEAR, "Third-generation cephalosporin."),
    ("cefuroxime", "Antibiotic", CLEAR, "Second-generation cephalosporin."),
    ("ceftriaxone", "Antibiotic", CLEAR, "Third-generation cephalosporin."),
    ("cefoperazone", "Antibiotic", CLEAR, "Cephalosporin (printed for cefoperazone/sulbactam)."),
    ("ciprofloxacin", "Antibiotic", CLEAR, "Fluoroquinolone antibiotic."),
    ("ofloxacin", "Antibiotic", CLEAR, "Fluoroquinolone antibiotic."),
    ("norfloxacin", "Antibiotic", CLEAR, "Fluoroquinolone antibiotic."),
    ("azithromycin", "Antibiotic", CLEAR, "Macrolide-group antibiotic."),
    ("erythromycin", "Antibiotic", CLEAR, "Macrolide-group antibiotic."),
    ("gentamicin", "Antibiotic", CLEAR, "Aminoglycoside antibiotic."),
    ("amikacin", "Antibiotic", CLEAR, "Aminoglycoside antibiotic."),
    ("tobramycin", "Antibiotic", CLEAR, "Aminoglycoside antibiotic (eye drops here)."),
    ("neomycin", "Antibiotic", CLEAR, "Aminoglycoside antibiotic (topical here)."),
    ("doxycycline", "Antibiotic", CLEAR, "Tetracycline antibiotic."),
    ("meropenem", "Antibiotic", CLEAR, "Carbapenem-group antibiotic."),
    ("piperacillin", "Antibiotic", CLEAR, "Penicillin-group antibiotic."),
    ("vancomycin", "Antibiotic", CLEAR, "Glycopeptide antibiotic."),
    ("co-trimoxazole", "Antibiotic", CLEAR, "Sulfamethoxazole + trimethoprim."),
    (
        "clavulanate",
        "Antibiotic",
        JUDGEMENT,
        "Not an antibiotic itself - it blocks the enzyme that destroys amoxycillin. In this"
        " archive it only ever appears alongside amoxycillin, so classing it as Antibiotic adds no"
        " class the product does not already have. Reject it and nothing is lost.",
    ),
    (
        "sulbactam",
        "Antibiotic",
        JUDGEMENT,
        "Same as clavulanate - an enzyme inhibitor paired with a cephalosporin. One product,"
        " 'Sulbactam Sodium Sterile I.P./USP.', is the bulk ingredient on its own.",
    ),
    (
        "tazobactam",
        "Antibiotic",
        JUDGEMENT,
        "Same as clavulanate - an enzyme inhibitor, not an antibiotic. Always printed with"
        " piperacillin here, so accepting it adds no class the product does not already carry.",
    ),
    (
        "metronidazole",
        "Antibiotic",
        JUDGEMENT,
        "Treats both bacteria and protozoa (amoebiasis, giardiasis). Antibiotic is the commoner"
        " reading; Antiparasitic is equally defensible.",
    ),
    (
        "ornidazole",
        "Antibiotic",
        JUDGEMENT,
        "Same ambiguity as metronidazole. Printed with ofloxacin here, which is an antibiotic.",
    ),
    (
        "tinidazole",
        "Antibiotic",
        JUDGEMENT,
        "Same ambiguity as metronidazole: it treats bacteria and protozoa, so Antiparasitic is"
        " equally defensible. Printed on its own here, so nothing else settles it.",
    ),
    # ---------------------------------------------------------------- Antifungal
    ("itraconazole", "Antifungal", CLEAR, "Triazole-group antifungal."),
    ("fluconazole", "Antifungal", CLEAR, "Triazole-group antifungal."),
    ("ketoconazole", "Antifungal", CLEAR, "Imidazole-group antifungal."),
    ("miconazole", "Antifungal", CLEAR, "Imidazole antifungal (topical here)."),
    ("clotrimazole", "Antifungal", CLEAR, "Imidazole antifungal (topical here)."),
    # ---------------------------------------------------------------- Antiparasitic
    ("albendazole", "Antiparasitic", CLEAR, "Anthelmintic - treats worm infestations."),
    ("mebendazole", "Antiparasitic", CLEAR, "Treats worm infestations."),
    ("oxfendazole", "Antiparasitic", CLEAR, "Anthelmintic (veterinary products here)."),
    ("ivermectin", "Antiparasitic", CLEAR, "Antiparasitic (veterinary products here)."),
    ("primaquine", "Antiparasitic", CLEAR, "Treats malaria."),
    # ---------------------------------------------------------------- Analgesic
    (
        "paracetamol",
        "Analgesic / anti-inflammatory",
        CLEAR,
        "Painkiller and fever reducer; the single commonest ingredient in the archive.",
    ),
    ("acetaminophen", "Analgesic / anti-inflammatory", CLEAR, "The US name for paracetamol."),
    ("ibuprofen", "Analgesic / anti-inflammatory", CLEAR, "Anti-inflammatory painkiller."),
    ("diclofenac", "Analgesic / anti-inflammatory", CLEAR, "Anti-inflammatory painkiller."),
    ("aceclofenac", "Analgesic / anti-inflammatory", CLEAR, "Anti-inflammatory painkiller."),
    ("nimesulide", "Analgesic / anti-inflammatory", CLEAR, "Anti-inflammatory painkiller."),
    (
        "mefenamic acid",
        "Analgesic / anti-inflammatory",
        CLEAR,
        "Anti-inflammatory painkiller, also for period pain.",
    ),
    (
        "tramadol",
        "Analgesic / anti-inflammatory",
        JUDGEMENT,
        "An opioid painkiller, not an NSAID. Same purpose, a controlled substance; a separate"
        " 'Opioid' class would be more precise but would hold two ingredients.",
    ),
    (
        "buprenorphine",
        "Analgesic / anti-inflammatory",
        JUDGEMENT,
        "An opioid used both for pain and, with naloxone, to treat opioid dependence - and both"
        " forms are in this archive. Neither reading is wrong.",
    ),
    (
        "methyl salicylate",
        "Analgesic / anti-inflammatory",
        JUDGEMENT,
        "Wintergreen oil in pain-relief gels: it works by warming the skin, not by the NSAID"
        " mechanism. Only ever printed alongside diclofenac here.",
    ),
    # ---------------------------------------------------------------- Muscle relaxant
    ("chlorzoxazone", "Muscle relaxant", CLEAR, "Centrally acting muscle relaxant."),
    ("thiocolchicoside", "Muscle relaxant", CLEAR, "Relaxes muscle spasm."),
    # ---------------------------------------------------------------- Anaesthetic
    ("bupivacaine", "Anaesthetic", CLEAR, "Local anaesthetic; numbs one area."),
    ("lignocaine", "Anaesthetic", CLEAR, "Local anaesthetic (IP spelling)."),
    ("lidocaine", "Anaesthetic", CLEAR, "The same anaesthetic, spelled the INN way."),
    ("propofol", "Anaesthetic", CLEAR, "General anaesthetic given intravenously."),
    (
        "oxetacaine",
        "Anaesthetic",
        JUDGEMENT,
        "A local anaesthetic, but here it is always in an antacid suspension to numb the stomach"
        " lining - so Gastrointestinal describes the product better than the molecule does.",
    ),
    # ---------------------------------------------------------------- Gastrointestinal
    ("pantoprazole", "Gastrointestinal", CLEAR, "Proton-pump inhibitor; reduces stomach acid."),
    ("rabeprazole", "Gastrointestinal", CLEAR, "Proton-pump inhibitor."),
    ("omeprazole", "Gastrointestinal", CLEAR, "Proton-pump inhibitor."),
    ("esomeprazole", "Gastrointestinal", CLEAR, "Proton-pump inhibitor."),
    ("ranitidine", "Gastrointestinal", CLEAR, "H2 blocker; reduces stomach acid."),
    ("domperidone", "Gastrointestinal", CLEAR, "Anti-nausea, speeds stomach emptying."),
    ("ondansetron", "Gastrointestinal", CLEAR, "Anti-nausea / anti-vomiting."),
    ("sucralfate", "Gastrointestinal", CLEAR, "Coats stomach ulcers."),
    ("simethicone", "Gastrointestinal", CLEAR, "Relieves trapped wind."),
    ("dicyclomine", "Gastrointestinal", CLEAR, "Antispasmodic for abdominal cramps."),
    ("drotaverine", "Gastrointestinal", CLEAR, "Antispasmodic for abdominal cramps."),
    ("loperamide", "Gastrointestinal", CLEAR, "Anti-diarrhoeal."),
    ("bisacodyl", "Gastrointestinal", CLEAR, "Stimulant laxative."),
    ("lactulose", "Gastrointestinal", CLEAR, "Osmotic laxative."),
    ("sodium picosulfate", "Gastrointestinal", CLEAR, "Stimulant laxative."),
    ("pancreatin", "Gastrointestinal", CLEAR, "Digestive enzyme replacement."),
    ("aluminium hydroxide", "Gastrointestinal", CLEAR, "Antacid; neutralises stomach acid."),
    ("magnesium hydroxide", "Gastrointestinal", CLEAR, "Antacid; neutralises stomach acid."),
    ("alumina", "Gastrointestinal", CLEAR, "Antacid (aluminium hydroxide, as IP writes it)."),
    ("magnesia", "Gastrointestinal", CLEAR, "Antacid (magnesium hydroxide, written this way)."),
    (
        "sodium bicarbonate",
        "Gastrointestinal",
        JUDGEMENT,
        "An antacid in tablets, but also given intravenously to correct blood acidity, which is"
        " electrolyte therapy. The archive's rows are 1000 mg tablets, i.e. the antacid use.",
    ),
    # ---------------------------------------------------------------- Respiratory
    ("guaiphenesin", "Respiratory / cough and cold", CLEAR, "Expectorant; loosens mucus."),
    ("ambroxol", "Respiratory / cough and cold", CLEAR, "Mucolytic; thins mucus."),
    ("bromhexine", "Respiratory / cough and cold", CLEAR, "Mucolytic; thins mucus."),
    ("terbutaline", "Respiratory / cough and cold", CLEAR, "Bronchodilator; opens the airways."),
    ("salbutamol", "Respiratory / cough and cold", CLEAR, "Bronchodilator."),
    ("levosalbutamol", "Respiratory / cough and cold", CLEAR, "Bronchodilator."),
    ("salmeterol", "Respiratory / cough and cold", CLEAR, "Long-acting bronchodilator."),
    ("dextromethorphan", "Respiratory / cough and cold", CLEAR, "Cough suppressant."),
    ("montelukast", "Respiratory / cough and cold", CLEAR, "Prevents asthma and allergic attacks."),
    (
        "phenylephrine",
        "Respiratory / cough and cold",
        CLEAR,
        "Decongestant; shrinks swollen nasal lining.",
    ),
    (
        "menthol",
        "Respiratory / cough and cold",
        JUDGEMENT,
        "In cough syrups here (a decongestant sensation), but also in the pain-relief gels"
        " alongside diclofenac, where it is a skin coolant. One class cannot cover both.",
    ),
    (
        "caffeine",
        "Respiratory / cough and cold",
        JUDGEMENT,
        "A stimulant on its own. In this archive it appears only inside paracetamol cold-and-flu"
        " combinations, where it is there to counter the drowsiness of the antihistamine.",
    ),
    (
        "fluticasone",
        "Respiratory / cough and cold",
        JUDGEMENT,
        "A corticosteroid by molecule, but inhaled for asthma here, with salmeterol. Could equally"
        " be Corticosteroid; the array means it can carry both if you accept it in both batches.",
    ),
    # ---------------------------------------------------------------- Antihistamine
    ("levocetirizine", "Antihistamine / antiallergic", CLEAR, "Non-drowsy antihistamine."),
    (
        "levocetrizine",
        "Antihistamine / antiallergic",
        CLEAR,
        "The same ingredient, misspelled on the pack - and printed that way on 11 findings, so the"
        " vocabulary has to carry the misspelling to match them.",
    ),
    ("cetirizine", "Antihistamine / antiallergic", CLEAR, "Antihistamine; treats allergy."),
    ("chlorpheniramine", "Antihistamine / antiallergic", CLEAR, "Older, drowsy antihistamine."),
    ("pheniramine", "Antihistamine / antiallergic", CLEAR, "Antihistamine, injected here."),
    ("fexofenadine", "Antihistamine / antiallergic", CLEAR, "Non-drowsy antihistamine."),
    ("diphenhydramine", "Antihistamine / antiallergic", CLEAR, "Older, drowsy antihistamine."),
    ("promethazine", "Antihistamine / antiallergic", CLEAR, "Antihistamine, also anti-nausea."),
    (
        "cyproheptadine",
        "Antihistamine / antiallergic",
        JUDGEMENT,
        "An antihistamine sold mainly as an appetite stimulant - which is why it is paired with"
        " tricholine citrate here, a combination for poor appetite rather than for allergy.",
    ),
    # ---------------------------------------------------------------- Corticosteroid
    ("dexamethasone", "Corticosteroid", CLEAR, "Steroid; suppresses inflammation."),
    ("betamethasone", "Corticosteroid", CLEAR, "Steroid, topical here."),
    ("prednisolone", "Corticosteroid", CLEAR, "Steroid; suppresses inflammation."),
    ("methylprednisolone", "Corticosteroid", CLEAR, "Steroid; suppresses inflammation."),
    ("clobetasol", "Corticosteroid", CLEAR, "Potent topical steroid."),
    ("hydrocortisone", "Corticosteroid", CLEAR, "Steroid; suppresses inflammation."),
    # ---------------------------------------------------------------- Antidiabetic
    ("metformin", "Antidiabetic", CLEAR, "First-line type-2 diabetes medicine."),
    ("glimepiride", "Antidiabetic", CLEAR, "Sulfonylurea; raises insulin release."),
    ("pioglitazone", "Antidiabetic", CLEAR, "Improves insulin sensitivity."),
    ("teneligliptin", "Antidiabetic", CLEAR, "Lowers blood sugar (DPP-4 inhibitor)."),
    # ---------------------------------------------------------------- Cardiovascular
    ("telmisartan", "Antihypertensive / cardiovascular", CLEAR, "Lowers blood pressure (ARB)."),
    ("losartan", "Antihypertensive / cardiovascular", CLEAR, "Lowers blood pressure (ARB)."),
    ("olmesartan", "Antihypertensive / cardiovascular", CLEAR, "Lowers blood pressure (ARB)."),
    ("ramipril", "Antihypertensive / cardiovascular", CLEAR, "Lowers blood pressure (ACE)."),
    ("enalapril", "Antihypertensive / cardiovascular", CLEAR, "Lowers blood pressure (ACE)."),
    (
        "amlodipine",
        "Antihypertensive / cardiovascular",
        CLEAR,
        "Lowers blood pressure (calcium-channel blocker).",
    ),
    (
        "nifedipine",
        "Antihypertensive / cardiovascular",
        CLEAR,
        "Lowers blood pressure (calcium-channel blocker).",
    ),
    ("atenolol", "Antihypertensive / cardiovascular", CLEAR, "Beta blocker; slows the heart."),
    ("metoprolol", "Antihypertensive / cardiovascular", CLEAR, "Beta blocker; slows the heart."),
    (
        "hydrochlorothiazide",
        "Antihypertensive / cardiovascular",
        JUDGEMENT,
        "A diuretic - it lowers blood pressure by making you pass water. Printed only with"
        " telmisartan here, so the product is a blood-pressure tablet either way.",
    ),
    (
        "frusemide",
        "Antihypertensive / cardiovascular",
        JUDGEMENT,
        "A loop diuretic, given mainly for the fluid overload of heart and kidney failure rather"
        " than for blood pressure. A separate 'Diuretic' class would hold two ingredients.",
    ),
    (
        "adrenaline",
        "Antihypertensive / cardiovascular",
        JUDGEMENT,
        "The opposite of an antihypertensive: it is injected in anaphylaxis and cardiac arrest to"
        " *raise* blood pressure. It belongs under a cardiovascular heading, not that label.",
    ),
    (
        "noradrenaline",
        "Antihypertensive / cardiovascular",
        JUDGEMENT,
        "Same as adrenaline - an intensive-care vasopressor, filed under cardiovascular.",
    ),
    # ---------------------------------------------------------------- Lipid-lowering
    ("atorvastatin", "Lipid-lowering", CLEAR, "Statin; lowers cholesterol."),
    ("rosuvastatin", "Lipid-lowering", CLEAR, "Statin; lowers cholesterol."),
    ("fenofibrate", "Lipid-lowering", CLEAR, "Lowers blood triglycerides."),
    # ---------------------------------------------------------------- Blood and clotting
    ("clopidogrel", "Blood and clotting", CLEAR, "Antiplatelet; prevents clots."),
    ("heparin", "Blood and clotting", CLEAR, "Anticoagulant; thins the blood."),
    (
        "aspirin",
        "Blood and clotting",
        JUDGEMENT,
        "An NSAID painkiller at full dose, but at the low dose used here - and printed with"
        " clopidogrel - it is an antiplatelet. The archive's rows are the clot-prevention use.",
    ),
    (
        "tranexamic acid",
        "Blood and clotting",
        JUDGEMENT,
        "It does the *opposite* of the other two: it stops bleeding. Grouping them under one"
        " heading is honest only because the heading is the body system, not the effect.",
    ),
    # ---------------------------------------------------------------- Neuro / psych
    ("pregabalin", "Neurological / psychiatric", CLEAR, "Nerve pain and epilepsy."),
    ("gabapentin", "Neurological / psychiatric", CLEAR, "Nerve pain and epilepsy."),
    ("levetiracetam", "Neurological / psychiatric", CLEAR, "Prevents epileptic seizures."),
    ("phenytoin", "Neurological / psychiatric", CLEAR, "Prevents epileptic seizures."),
    ("sodium valproate", "Neurological / psychiatric", CLEAR, "Prevents epileptic seizures."),
    ("valproic acid", "Neurological / psychiatric", CLEAR, "Prevents epileptic seizures."),
    ("divalproex", "Neurological / psychiatric", CLEAR, "Prevents epileptic seizures."),
    ("amitriptyline", "Neurological / psychiatric", CLEAR, "Antidepressant, also for nerve pain."),
    ("nortriptyline", "Neurological / psychiatric", CLEAR, "Antidepressant, also for nerve pain."),
    ("alprazolam", "Neurological / psychiatric", CLEAR, "Benzodiazepine for anxiety."),
    ("lorazepam", "Neurological / psychiatric", CLEAR, "Benzodiazepine sedative."),
    ("clonazepam", "Neurological / psychiatric", CLEAR, "Benzodiazepine; seizures and anxiety."),
    # ---------------------------------------------------------------- Vitamin / mineral
    ("folic acid", "Vitamin / mineral supplement", CLEAR, "Vitamin B9; given in pregnancy."),
    ("ascorbic acid", "Vitamin / mineral supplement", CLEAR, "Vitamin C, by its chemical name."),
    ("vitamin a", "Vitamin / mineral supplement", CLEAR, "Retinol; eyes and skin."),
    ("vitamin b12", "Vitamin / mineral supplement", CLEAR, "Cobalamin; nerves and blood."),
    ("vitamin c", "Vitamin / mineral supplement", CLEAR, "Ascorbic acid, named the short way."),
    ("vitamin d3", "Vitamin / mineral supplement", CLEAR, "Cholecalciferol; bone health."),
    ("vitamin e", "Vitamin / mineral supplement", CLEAR, "Tocopherol; an antioxidant."),
    ("multivitamin", "Vitamin / mineral supplement", CLEAR, "A mixture of vitamins."),
    ("cholecalciferol", "Vitamin / mineral supplement", CLEAR, "Vitamin D3, by its chemical name."),
    ("calcitriol", "Vitamin / mineral supplement", CLEAR, "The active form of vitamin D."),
    ("methylcobalamin", "Vitamin / mineral supplement", CLEAR, "A form of vitamin B12."),
    ("mecobalamin", "Vitamin / mineral supplement", CLEAR, "The same thing, spelled differently."),
    ("niacinamide", "Vitamin / mineral supplement", CLEAR, "Vitamin B3; skin and nerves."),
    ("nicotinamide", "Vitamin / mineral supplement", CLEAR, "Vitamin B3, the other spelling."),
    ("pyridoxine", "Vitamin / mineral supplement", CLEAR, "Vitamin B6; nerve function."),
    ("thiamine", "Vitamin / mineral supplement", CLEAR, "Vitamin B1; nerve function."),
    ("biotin", "Vitamin / mineral supplement", CLEAR, "Vitamin B7; hair and skin."),
    ("benfotiamine", "Vitamin / mineral supplement", CLEAR, "A form of vitamin B1."),
    ("calcium carbonate", "Vitamin / mineral supplement", CLEAR, "Calcium for bone health."),
    ("calcium phosphate", "Vitamin / mineral supplement", CLEAR, "Calcium for bone health."),
    ("calcium gluconate", "Vitamin / mineral supplement", CLEAR, "Injected calcium."),
    ("calcium citrate", "Vitamin / mineral supplement", CLEAR, "Calcium for bone health."),
    (
        "zinc sulphate",
        "Vitamin / mineral supplement",
        CLEAR,
        "Zinc; given for childhood diarrhoea.",
    ),
    ("zinc acetate", "Vitamin / mineral supplement", CLEAR, "Zinc; given for childhood diarrhoea."),
    (
        "zinc gluconate",
        "Vitamin / mineral supplement",
        CLEAR,
        "Zinc; given for childhood diarrhoea.",
    ),
    ("ferrous sulphate", "Vitamin / mineral supplement", CLEAR, "Iron supplement."),
    ("ferrous ascorbate", "Vitamin / mineral supplement", CLEAR, "Iron supplement."),
    ("iron sucrose", "Vitamin / mineral supplement", CLEAR, "Injected iron supplement."),
    ("alpha lipoic acid", "Vitamin / mineral supplement", CLEAR, "Antioxidant supplement."),
    ("chromium picolinate", "Vitamin / mineral supplement", CLEAR, "Chromium; a trace element."),
    (
        "l-methylfolate",
        "Vitamin / mineral supplement",
        CLEAR,
        "The active form of folic acid.",
    ),
    # ---------------------------------------------------------------- Fluids
    (
        "sodium chloride",
        "Fluid / electrolyte replacement",
        CLEAR,
        "Saline drip - 0.9% w/v is the normal-saline strength in the archive.",
    ),
    ("dextrose", "Fluid / electrolyte replacement", CLEAR, "Glucose given by drip."),
    ("compound sodium lactate", "Fluid / electrolyte replacement", CLEAR, "Ringer's lactate drip."),
    ("ringer", "Fluid / electrolyte replacement", CLEAR, "Ringer's lactate drip."),
    (
        "oral rehydration salts",
        "Fluid / electrolyte replacement",
        CLEAR,
        "ORS - the WHO salt-and-sugar mixture for dehydration.",
    ),
    (
        "water for injection",
        "Fluid / electrolyte replacement",
        CLEAR,
        "Sterile water used to dilute an injection.",
    ),
    (
        "magnesium sulphate",
        "Fluid / electrolyte replacement",
        JUDGEMENT,
        "Injected, its main use is to stop seizures in pregnancy (eclampsia), so Hormone /"
        " obstetric or Neurological would both be arguable. It is also a laxative by mouth.",
    ),
    # ---------------------------------------------------------------- Enzymes
    ("serratiopeptidase", "Enzyme preparation", CLEAR, "Enzyme given to reduce swelling."),
    ("trypsin", "Enzyme preparation", CLEAR, "Enzyme given to reduce swelling."),
    ("chymotrypsin", "Enzyme preparation", CLEAR, "Enzyme given to reduce swelling."),
    ("bromelain", "Enzyme preparation", CLEAR, "Enzyme given to reduce swelling."),
    # ---------------------------------------------------------------- Probiotic
    ("lactic acid bacillus", "Probiotic", CLEAR, "Gut bacteria, added to antibiotic tablets."),
    ("bacillus clausii", "Probiotic", CLEAR, "Gut bacteria given as a supplement."),
    ("probiotic", "Probiotic", CLEAR, "The products that say only this on the pack."),
    # ---------------------------------------------------------------- Hormone / obstetric
    ("thyroxine", "Hormone", CLEAR, "Thyroid hormone replacement."),
    ("oxytocin", "Hormone", CLEAR, "Induces labour and controls bleeding after birth."),
    (
        "misoprostol",
        "Hormone",
        JUDGEMENT,
        "A prostaglandin, not a hormone in the strict sense. Used in obstetrics and to protect the"
        " stomach from NSAIDs, so Gastrointestinal is also defensible.",
    ),
    # ---------------------------------------------------------------- Urological
    ("tamsulosin", "Urological", CLEAR, "Eases urine flow in prostate enlargement."),
    ("dutasteride", "Urological", CLEAR, "Shrinks an enlarged prostate."),
    # ---------------------------------------------------------------- Antiseptic
    ("povidone-iodine", "Antiseptic / disinfectant", CLEAR, "Wound and skin antiseptic."),
    ("chlorhexidine", "Antiseptic / disinfectant", CLEAR, "Skin and wound antiseptic."),
    ("cetrimide", "Antiseptic / disinfectant", CLEAR, "Skin and wound antiseptic."),
    ("isopropyl alcohol", "Antiseptic / disinfectant", CLEAR, "The alcohol in hand sanitiser."),
    (
        "hand sanitizer",
        "Antiseptic / disinfectant",
        CLEAR,
        "Not a medicine, but a disinfectant - and CDSCO tested a lot of it in 2020-21.",
    ),
    ("handrub", "Antiseptic / disinfectant", CLEAR, "The same product, named the other way."),
    ("disinfectant", "Antiseptic / disinfectant", CLEAR, "Surface disinfectant fluid."),
    # ---------------------------------------------------------------- Not a medicine
    (
        "absorbent cotton wool",
        "Surgical consumable or device",
        CLEAR,
        "Cotton wool. CDSCO tests it to IP standard, but it is not a drug and must not be charted"
        " as one.",
    ),
    ("absorbent gauze", "Surgical consumable or device", CLEAR, "Gauze dressing; not a drug."),
    ("bandage", "Surgical consumable or device", CLEAR, "Rolled cloth dressing; not a drug."),
    ("surgical dressing", "Surgical consumable or device", CLEAR, "Wound dressing; not a drug."),
    ("hypodermic syringe", "Surgical consumable or device", CLEAR, "A sterile device, not a drug."),
    ("infusion set", "Surgical consumable or device", CLEAR, "Drip tubing; a device, not a drug."),
    (
        "soap",
        "Cosmetic or toiletry",
        JUDGEMENT,
        "Plain and 'medicated' soaps are both in the archive. A medicated one arguably belongs"
        " under Antiseptic; a beauty soap is a cosmetic. The pack name rarely settles it.",
    ),
    (
        "hair colour",
        "Cosmetic or toiletry",
        JUDGEMENT,
        "A cosmetic, regulated separately from medicines - included only so it is not left looking"
        " like an unclassified drug.",
    ),
    (
        "beauty cream",
        "Cosmetic or toiletry",
        JUDGEMENT,
        "Fairness and beauty creams. Some were tested because they contained steroids they should"
        " not have, which is exactly why they must not be charted as a therapeutic class.",
    ),
    (
        "mehandi",
        "Cosmetic or toiletry",
        JUDGEMENT,
        "Henna cones. Regulated as a cosmetic, not a medicine - included so they do not sit in"
        " Unclassified looking like a drug nobody could identify.",
    ),
    (
        "teeth whitening",
        "Cosmetic or toiletry",
        JUDGEMENT,
        "A cosmetic preparation, not a medicine. Same reasoning as the other entries here: it is"
        " classed so that it is visibly not a drug, rather than left to look like an unknown one.",
    ),
    (
        "propylene glycol",
        "Pharmaceutical raw material",
        CLEAR,
        "A solvent sold as a bulk ingredient, not a finished medicine.",
    ),
    ("glycerin", "Pharmaceutical raw material", CLEAR, "A bulk ingredient, not a medicine."),
    (
        "liquid paraffin",
        "Pharmaceutical raw material",
        CLEAR,
        "A bulk ingredient; also a laxative.",
    ),
    ("sorbitol", "Pharmaceutical raw material", CLEAR, "A bulk sweetener and solvent."),
    ("linseed oil", "Pharmaceutical raw material", CLEAR, "Carrier oil in pain-relief gels."),
    # ---------------------------------------------------------------- Vaccine
    (
        "vaccine",
        "Vaccine",
        CLEAR,
        "Covishield, and one unlabelled vial purported to be a covid vaccine - which is a"
        " spurious finding, so the pack's claim is exactly what was disproved.",
    ),
)

# Every class the vocabulary can produce, for the review tool and the dashboard note.
CLASSES: tuple[str, ...] = tuple(dict.fromkeys(drug_class for _, drug_class, _, _ in PROPOSALS))

# An ingredient phrase is matched as a whole word (or whole phrase) anywhere in the printed product
# name, case-insensitively. `\y` is Postgres's word boundary; Python's `\b` is the equivalent. The
# SQL side of this lives in the dbt macro `ingredient_match`, and a test checks the two agree on
# every seed row rather than trusting that they do.
SAFE_INGREDIENT = re.compile(r"^[a-z0-9][a-z0-9 '-]*$")


def ingredient_regex(ingredient: str) -> re.Pattern[str]:
    """The Python half of the match rule. Kept to characters that mean the same thing to both
    regex engines, so the vocabulary can never smuggle a pattern into either one."""
    if not SAFE_INGREDIENT.match(ingredient):
        raise ValueError(f"ingredient is not plain text: {ingredient!r}")
    return re.compile(rf"\b{re.escape(ingredient)}\b", re.IGNORECASE)


def classes_for(product_name: str, vocabulary: dict[str, str]) -> list[str]:
    """Every class whose ingredient appears in this product name, in CLASSES order.

    Returns [] - not [UNCLASSIFIED] - when nothing matches: the caller decides whether an empty
    list reads as "unclassified" or as "no answer", and the two are not the same thing.
    """
    found = {
        drug_class
        for ingredient, drug_class in vocabulary.items()
        if ingredient_regex(ingredient).search(product_name)
    }
    return [drug_class for drug_class in CLASSES if drug_class in found]
