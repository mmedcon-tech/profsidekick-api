# IVF knowledge base, written for patients in plain language from public sources fetched 2026-11-03.
# Each doc: key, title, src (numbers in urls.txt), progs, facts (substrings verified in source text), body.
H, RF, NHS, ESH, AC = "HFEA", "ASRM ReproductiveFacts", "NHS", "ESHRE", "ACOG"
IVF = ["ivf-care"]
DOCS = [
dict(key="what-is-ivf", title="What IVF is and the main steps", src=[1, 44, 46], progs=IVF,
 facts=["four main steps", "36 hours later", "two and six days"],
 body="""## What is IVF (in vitro fertilisation)?
IVF means eggs are collected from the ovaries and fertilised with sperm in a laboratory, and an embryo is then placed in the womb (uterus). IVF may be suggested for blocked fallopian tubes, ovulation problems, endometriosis, low sperm quality or unexplained infertility.

## The main steps of an IVF cycle
ESHRE describes four main steps: 1) stimulating the ovaries so several eggs mature, 2) egg retrieval (egg collection), 3) fertilising the eggs in the laboratory, 4) transferring an embryo into the uterus. Around these steps there are monitoring scans and blood tests, a trigger injection about 36 hours before egg collection, and a pregnancy test about two weeks after transfer.

## How long does one IVF cycle take?
Stimulation usually lasts about 1 to 2 weeks, embryos develop in the lab for between two and six days, and the pregnancy test comes roughly two weeks after transfer. Your clinic gives you your own calendar.

## Is IVF guaranteed to work?
No. IVF helps many people but it is not guaranteed, and some people need more than one cycle. Your fertility team can talk about what it may mean for you."""),
dict(key="before-ivf-tests", title="Tests before IVF: AMH, AFC, FSH, semen analysis and HSG", src=[41, 36, 18, 25, 46], progs=IVF,
 facts=["AMH", "antral follicle count", "semen analysis", "Hysterosalpingography", "chlamydia"],
 body="""## Why are tests done before IVF?
Tests help your team understand ovarian reserve, sperm, the womb and the fallopian tubes, and plan safe stimulation.

## AMH (anti-Müllerian hormone)
AMH is a blood test made by the follicles that relates to the number of eggs remaining (ovarian reserve). It can be taken at any time in the menstrual cycle. AMH helps estimate how the ovaries may respond to stimulation; it does not on its own predict whether someone can get pregnant. Normal ranges differ between laboratories.

## AFC (antral follicle count)
The antral follicle count is a transvaginal ultrasound that counts small follicles in the ovaries. With AMH it helps predict a low or high response to stimulation.

## FSH and estradiol (day 3 tests)
FSH (follicle-stimulating hormone) and estradiol are blood tests usually done early in the cycle (around day 2 to 5). High day-3 FSH can suggest lower ovarian reserve, but a normal result does not rule it out.

## Semen analysis (sperm test)
A semen analysis checks the amount of sperm, how they move (motility) and their shape (morphology). Men may also have hormone blood tests.

## HSG (hysterosalpingogram) and other womb and tube checks
An HSG is an X-ray where fluid is placed into the uterus to show its shape and whether the fallopian tubes are open. Alternatives include a special ultrasound (HyCoSy or sonohysterography), hysteroscopy or laparoscopy.

## Infection screening
Clinics usually test for infections such as HIV, hepatitis B and C and chlamydia before treatment."""),
dict(key="ovarian-reserve-age", title="Ovarian reserve and age", src=[41, 42, 43, 36], progs=IVF,
 facts=["mid-30s", "less than 10 percent", "No single test"],
 body="""## What is ovarian reserve?
Ovarian reserve describes the number (and broadly the quality) of eggs remaining. People are born with all their eggs, and the number declines over time: gradually until the early 30s and faster after the mid-30s.

## How does age affect fertility?
ACOG notes that for healthy couples in their 20s or early 30s the chance of pregnancy is about 25 to 30 percent per cycle, declining from the early 30s and faster after 37; by 40 it is less than 10 percent per cycle. Miscarriage and chromosome differences become more common with age. Male fertility also declines with age, less predictably.

## Can a test tell me if I will get pregnant?
No single test measures ovarian reserve perfectly or predicts pregnancy. AMH, AFC and FSH help estimate response to stimulation. Your team interprets your results with you."""),
dict(key="protocols", title="IVF stimulation protocols (long, short, antagonist)", src=[46, 1], progs=IVF + ["ivf-medication-preparation"],
 facts=["pituitary suppression", "antagonist protocol", "long protocol"],
 body="""## What is an IVF protocol?
A protocol is the plan of medicines for ovarian stimulation. First the natural hormone signals are temporarily quietened (pituitary suppression) so the team controls when eggs mature, then FSH injections make several follicles grow.

## Long protocol, short protocol and antagonist protocol
In a long (agonist) protocol, suppression medicine starts before stimulation. In an antagonist protocol, an antagonist is added for a few days after stimulation injections have started to stop early ovulation. Short protocols are also used. ESHRE describes these as different ways of achieving the same aim.

## Which protocol is right for me?
Your fertility team chooses the protocol and doses based on your tests (such as AMH and AFC), age and history. Please ask them about your own plan."""),
dict(key="medications", title="IVF medications and common side effects", src=[3, 46, 22, 26], progs=IVF + ["ivf-medication-preparation"],
 facts=["Clomid", "Metformin", "FSH", "Progesterone"],
 body="""## Which medicines are used in IVF?
Common groups are: gonadotropins (FSH, sometimes with LH) injections to grow follicles; GnRH agonists or antagonists to prevent early ovulation; a trigger injection (hCG or a GnRH agonist) to finish egg maturation; and progesterone (injection, vaginal gel or pessary/tablet) for luteal support after egg collection. Clomid (clomifene) and metformin are used in some other fertility treatments, for example with PCOS.

## Common side effects of fertility injections
Bloating, breast tenderness, mood changes, headaches, tiredness and bruising or soreness at injection sites are common. Mild ovarian hyperstimulation symptoms (bloating, nausea) can occur.

## When should I contact my clinic about side effects?
Contact your clinic urgently for severe abdominal pain or swelling, vomiting, shortness of breath, reduced urine or sudden weight gain, which can be signs of OHSS.

## Doses
This guide does not give doses. Doses and timing are prescribed individually by your fertility team; always follow your clinic's written instructions."""),
dict(key="monitoring", title="Monitoring scans and blood tests during stimulation", src=[1, 46], progs=IVF,
 facts=["ultrasound scans", "20 mm"],
 body="""## Why are there so many monitoring appointments?
During stimulation the clinic checks progress with transvaginal ultrasound scans (to measure follicles) and blood tests (such as estradiol). Doses can be adjusted so eggs grow at the right speed and risks such as OHSS are reduced.

## How big do follicles need to be?
ESHRE explains that the trigger injection is usually given when the follicles are about 18–20 mm. Your team decides the exact day."""),
dict(key="trigger", title="The trigger injection", src=[44, 46, 22], progs=IVF + ["ivf-medication-preparation"],
 facts=["36 hours later", "trigger", "leuprolide"],
 body="""## What does the trigger injection do?
The trigger injection helps the eggs finish maturing so they can be collected. It is often given late in the evening, and egg collection is timed about 36 hours later, so the exact time matters.

## hCG trigger or agonist trigger
Triggers are hCG or a GnRH agonist (such as leuprolide). ASRM notes an agonist trigger can lower the risk of OHSS in people at higher risk. Your clinic chooses which one and tells you the exact time; contact them straight away if a trigger is missed or late."""),
dict(key="egg-retrieval", title="Egg retrieval (egg collection): what happens", src=[21, 13, 46], progs=IVF + ["egg-freezing"],
 facts=["transvaginal ultrasound aspiration", "pain medication", "needle"],
 body="""## What happens during egg retrieval?
Egg retrieval, also called egg collection or oocyte pick-up, is a short procedure. Under sedation or other pain relief, an ultrasound probe is placed in the vagina and a fine needle is guided through the vaginal wall into each follicle to draw out the fluid that contains the egg (transvaginal ultrasound aspiration). It usually takes about 15 to 30 minutes and you usually go home the same day.

## How should I prepare for egg collection?
Follow your clinic's fasting and arrival instructions, arrange for someone to take you home after sedation, and bring your medication list.

## Recovery after egg collection
Cramping, mild bleeding and bloating are common for a day or two. Contact your clinic for severe pain, heavy bleeding, fever, fainting or difficulty breathing.

## How many eggs will be collected?
Numbers vary a lot. Not every follicle contains an egg and not every egg is mature. Your team will tell you your own result on the day."""),
dict(key="ohss", title="OHSS (ovarian hyperstimulation syndrome): symptoms, warning signs and prevention", src=[22, 4], progs=IVF + ["egg-freezing"],
 facts=["One out of three", "mild, moderate, or severe", "cabergoline", "within two weeks"],
 body="""## What is OHSS?
Ovarian hyperstimulation syndrome is an excessive response to stimulation medicines. Many follicles and high estradiol can cause fluid to leak into the abdomen, causing bloating, nausea and swelling.

## How common is OHSS and how serious is it?
OHSS can be mild, moderate or severe. ASRM says about one out of three people have mild symptoms during stimulation for IVF. Severe OHSS is less common but can cause dehydration, blood clots and breathing problems and may need hospital care.

## OHSS warning signs: when to call
Contact your clinic urgently, or emergency services if severe, for severe abdominal pain or swelling, vomiting or being unable to keep fluids down, shortness of breath, passing little urine, or rapid weight gain.

## How is OHSS reduced and treated?
Strategies include lower stimulation doses, an agonist (leuprolide) trigger, cabergoline, and freezing all embryos instead of a fresh transfer. Symptoms usually settle within two weeks unless pregnancy occurs. Risk factors include high AMH and polycystic ovaries."""),
dict(key="ivf-vs-icsi", title="IVF compared with ICSI", src=[2, 21], progs=IVF,
 facts=["single sperm is injected", "ICSI"],
 body="""## What is ICSI?
ICSI (intracytoplasmic sperm injection) is a laboratory technique where a single sperm is injected directly into each mature egg. In standard IVF, eggs and many sperm are placed together and fertilisation happens on its own.

## When is ICSI used instead of IVF?
ICSI is mainly used for male factor infertility (low sperm count, poor movement or shape), when sperm is surgically retrieved, or after fertilisation failed in an earlier IVF cycle. The rest of the cycle (stimulation, egg collection, transfer) is the same.

## Does ICSI improve results for everyone?
HFEA notes ICSI is not needed for couples without sperm problems; your team will advise which method fits your situation."""),
dict(key="fertilisation-embryos", title="Fertilisation, embryo development and blastocysts", src=[21, 1, 45], progs=IVF,
 facts=["two pronuclei", "65% to 75%", "Blastocyst"],
 body="""## How do I know if my eggs fertilised?
The day after insemination or ICSI the embryologist checks for two pronuclei (one from the egg, one from the sperm), which confirms fertilisation. ASRM notes that usually about 65% to 75% of mature eggs fertilise, though this varies and sometimes fertilisation does not happen.

## How do embryos develop in the lab?
Embryos are watched for two to six days. By day 2 to 3 they have several cells (cleavage stage). By about day 5 or 6 some become blastocysts.

## What is a blastocyst?
A blastocyst is an embryo that has formed a fluid-filled cavity, with cells that will become the baby (inner cell mass) and the placenta (trophectoderm), usually about 5 days after egg retrieval. Not all embryos reach this stage, which is normal attrition."""),
dict(key="embryo-grading", title="Embryo grading and quality", src=[45, 21], progs=IVF,
 facts=["Embryos are graded", "Embryo quality"],
 body="""## What does embryo grading mean?
Embryologists grade embryos by how they look under the microscope: for day-3 embryos the number and evenness of cells and fragmentation; for blastocysts the expansion, inner cell mass and trophectoderm (often written like 4AA or 3BB).

## Does a lower grade mean the embryo will not work?
No. ESHRE notes embryo quality is an important factor, but grading is an estimate. Lower-graded embryos can lead to healthy pregnancies and top grades do not guarantee one. Your embryologist can explain your embryos' grades."""),
dict(key="pgt", title="Preimplantation genetic testing (PGT-A, PGT-M, PGT-SR)", src=[37, 38], progs=IVF,
 facts=["PGT-M", "Over 2,000 genetic conditions", "PGT-A", "rated red"],
 body="""## What is PGT?
Preimplantation genetic testing checks a few cells taken (biopsied) from embryos created through IVF. PGT-M tests for a specific inherited single-gene condition; PGT-SR for chromosome structural rearrangements; PGT-A screens for missing or extra chromosomes (aneuploidy).

## PGT-M and PGT-SR
HFEA explains PGT-M is used when there is a known risk of a serious genetic condition; over 2,000 conditions have been approved in the UK. IVF is needed even without fertility problems, and tested embryos are now usually frozen and transferred later.

## Does PGT-A improve my chance of a baby?
HFEA rates PGT-A red for increasing the chance of a baby for most fertility patients, because it often reduces the number of embryos available to transfer, and green for reducing the chance of miscarriage for most patients. For older women the evidence is rated grey (insufficient). Results can be inconclusive or mosaic. Discuss with your team whether it applies to you."""),
dict(key="fresh-vs-frozen", title="Fresh versus frozen embryo transfer and embryo freezing", src=[7, 21, 22], progs=IVF,
 facts=["vitrification", "most embryos do survive", "no evidence to suggest that embryos are affected by the length of time"],
 body="""## Fresh or frozen embryo transfer (FET)?
In a fresh transfer the embryo is transferred in the same cycle as egg collection. In a frozen embryo transfer (FET) embryos are frozen and transferred in a later cycle. Freezing all embryos may be advised to reduce OHSS risk, after PGT, or when the womb lining is not ideal.

## How are embryos frozen?
Embryos are frozen by vitrification (very fast freezing) and stored in liquid nitrogen. HFEA says most embryos survive the freeze-thaw process, although some may not, and there is no evidence that embryos are affected by how long they are frozen. ASRM notes frozen embryos do not appear to increase birth defect risk.

## How is a frozen transfer cycle prepared?
The womb lining is prepared either in a natural cycle or with estrogen and progesterone medicines, and the thawed embryo is transferred at the right time."""),
dict(key="transfer-day", title="Embryo transfer day and how many embryos", src=[13, 45, 7], progs=IVF,
 facts=["thin tube", "elective single embryo", "younger than 38"],
 body="""## What happens on embryo transfer day?
Embryo transfer is usually quick and similar to a smear test. A thin, soft tube (catheter) is passed through the cervix into the womb, often guided by abdominal ultrasound, and the embryo is placed inside. Anaesthetic is usually not needed. Many clinics ask for a comfortably full bladder.

## How many embryos are transferred?
Most clinics transfer one embryo (elective single embryo transfer, eSET) to avoid the risks of twins and triplets for parent and babies. ESHRE notes patients younger than 38 have similar or higher cumulative live birth rates with single embryo transfer.

## After the transfer
You can go home and return to normal light activities. Bed rest is not needed."""),
dict(key="two-week-wait", title="The two-week wait and the pregnancy test", src=[13, 1, 44], progs=IVF,
 facts=["16 days after the embryo transfer", "false result"],
 body="""## What is the two-week wait?
The two-week wait is the time between embryo transfer and the pregnancy test. NHS says the test is around 16 days after embryo transfer, depending on your clinic.

## Should I test early?
HFEA advises not testing early because you may get a false result: the trigger injection can cause a false positive, and early testing can give a false negative. Use the date your clinic gives you.

## Symptoms during the two-week wait
Cramping, spotting, breast tenderness or no symptoms at all are all common and do not reliably show whether treatment has worked. Keep taking prescribed medicines such as progesterone until your clinic tells you otherwise. Contact your clinic for heavy bleeding, severe pain or OHSS warning signs."""),
dict(key="luteal-support", title="Luteal phase support (progesterone)", src=[44, 26], progs=IVF + ["ivf-medication-preparation"],
 facts=["progesterone", "Progesterone (taken by intramuscular injection, vaginal gel, or tablet)"],
 body="""## What is luteal phase support?
After egg collection the body may not make enough progesterone to prepare the womb lining, so progesterone is usually given after IVF. ESHRE notes progesterone helps the womb get ready for pregnancy.

## How is progesterone given?
Progesterone may be an intramuscular injection, vaginal gel, pessary or tablet. If pregnancy is confirmed it is commonly continued for some weeks. Do not stop progesterone without your clinic's advice."""),
dict(key="unsuccessful-cycle", title="If an IVF cycle is unsuccessful", src=[44, 30, 1], progs=IVF,
 facts=["several rounds of IVF", "not successful"],
 body="""## My IVF cycle did not work. What now?
It is common for a cycle not to work; many people need more than one cycle, and ESHRE notes some try many rounds without success. A negative result is not your fault.

## The follow-up (review) appointment
Your team will usually offer a review to go through stimulation, eggs, embryos and transfer, and to discuss options such as another fresh cycle, using frozen embryos, changes to the protocol, further tests, donor eggs or sperm, or stopping treatment.

## Looking after yourself
Feelings of grief, anger and exhaustion are normal. Counselling and support groups can help; ask your clinic about counselling."""),
dict(key="egg-freezing", title="Egg freezing (oocyte cryopreservation)", src=[6, 28, 21], progs=IVF + ["egg-freezing"],
 facts=["7-14 eggs", "55 years", "vitrification"],
 body="""## What is egg freezing?
Egg freezing means stimulating the ovaries, collecting eggs and freezing them by vitrification to try to use later. It can be for medical reasons (for example before cancer treatment) or personal reasons.

## How many eggs are collected for egg freezing?
HFEA notes most people under 38 have around 7–14 eggs collected, though fewer with low ovarian reserve. Not every frozen egg will survive thawing, fertilise or become an embryo.

## Does age matter for egg freezing?
Yes: eggs frozen at a younger age have better chances later. Egg freezing does not guarantee a future pregnancy.

## How long can eggs be stored?
In the UK, since 1 July 2022 eggs can be stored up to a maximum of 55 years, with consent renewed every 10 years. Rules differ in other countries; your clinic will explain local rules."""),
dict(key="embryo-storage", title="Embryo storage, consent and what happens to unused embryos", src=[7, 48], progs=IVF,
 facts=["55 years", "consent", "donate"],
 body="""## How long can embryos be stored?
In the UK, since 1 July 2022 embryos can be stored for up to a maximum of 55 years, with consent renewed. Storage rules vary by country, and there are storage costs.

## What consent is needed?
Before freezing, you sign consent forms covering how long embryos are stored and what should happen to them in different situations.

## Options for embryos you do not use
Options include continued storage, donating them to someone else's treatment, donating to research or training, or allowing them to perish. HFEA notes embryo donors go through the same health checks as egg and sperm donors."""),
dict(key="donors", title="Donor eggs, donor sperm and donor embryos", src=[26, 48, 9], progs=IVF,
 facts=["anonymous", "quarantined", "18"],
 body="""## When are donor eggs, sperm or embryos used?
Donors may help people with low ovarian reserve or early menopause, severe sperm problems, a risk of passing on a genetic condition, single people and same-sex couples.

## How does donor egg IVF work?
The donor has stimulation and egg collection; the eggs are fertilised with partner or donor sperm and an embryo is transferred to the recipient, whose womb is prepared with estrogen and progesterone.

## Donor screening
Donors have medical, infectious disease and genetic carrier screening and counselling. Donor sperm is frozen and quarantined (ASRM: at least six months) and the donor retested before release.

## Can donors be anonymous?
It depends on the country. HFEA explains that in the UK donation through licensed clinics is not anonymous: at 18 a donor-conceived person can ask for the donor's identifying details. Implications counselling is recommended."""),
dict(key="male-factor", title="Male factor infertility", src=[36, 20, 2, 21], progs=IVF,
 facts=["semen analysis", "surgically", "MESA"],
 body="""## What is male factor infertility?
Male factor means a problem with sperm production, movement, shape, or delivery contributes to infertility. ACOG notes the most common cause of male infertility is a problem with sperm cells and how they function.

## How is it assessed?
A semen analysis, hormone blood tests and sometimes a scrotal ultrasound or genetic tests.

## Treatment options
Options include lifestyle changes, treating hormone problems, IUI, and IVF with ICSI. When there is no sperm in the ejaculate, sperm may be retrieved surgically from the testicle or epididymis (for example TESA, MESA or micro-TESE) and used with ICSI.

## Lifestyle and sperm
ACOG notes smoking, heavy drinking and marijuana can reduce sperm count and movement."""),
dict(key="success-rates", title="IVF success rates and age (general statistics)", src=[44, 36, 45], progs=IVF,
 facts=["30%", "under 3%"],
 body="""## What are IVF success rates?
Success rates depend mainly on the age of the person whose eggs are used. ESHRE's IVF leaflet, using UK data, says women under 35 have about a 30% chance of having a baby per embryo transferred, falling to under 3% for women over 44. These are population averages from published data, not a personal prediction.

## Other factors
Embryo quality, cause of infertility, previous pregnancies and lifestyle also matter. Many people need more than one cycle; cumulative chances over several cycles are higher than for one.

## What are my personal chances?
Only your fertility team can discuss your own chances, using your tests and history."""),
dict(key="costs", title="Costs and funding of IVF", src=[40, 21], progs=IVF,
 facts=["fully costed treatment plan", "free to set their own costs", "£115"],
 body="""## How much does IVF cost?
Costs vary a lot between clinics and countries. HFEA notes clinics are free to set their own costs, so the same treatment can cost two or three times more elsewhere.

## What should a quote include?
Ask for a fully costed treatment plan: consultations, tests, drugs (which can be very expensive), monitoring, egg collection, ICSI if needed, embryo freezing and storage, frozen transfers and any add-ons. HFEA notes there is no conclusive evidence that commonly offered add-ons increase the chance of pregnancy. In the UK, the HFEA charges clinics a regulator fee (£115 per IVF cycle) which some clinics list on bills.

## Insurance and public funding
Coverage depends on your country, insurer or health system. Ask your clinic's finance team about your coverage."""),
dict(key="add-ons", title="Treatment add-ons and the HFEA traffic-light ratings", src=[39, 38], progs=IVF,
 facts=["Green traffic light", "Red traffic light", "optional non-essential"],
 body="""## What are treatment add-ons?
Add-ons are optional non-essential extra treatments or tests offered on top of proven treatment such as IVF, for example endometrial scratching, embryo glue, time-lapse imaging, assisted hatching or PGT-A.

## The HFEA traffic-light ratings
HFEA rates add-ons: green (high-quality evidence shows benefit), yellow (conflicting evidence), grey (insufficient evidence), black (no effect) and red (possible safety concerns or may reduce effectiveness). For most patients, a routine cycle without add-ons is effective. Ask your clinic for the evidence and cost of any add-on."""),
dict(key="emotional-support", title="Emotional wellbeing and support during IVF", src=[30, 45], progs=IVF,
 facts=["reducing stress provides a better quality of life", "It is not clear how stress impacts fertility"],
 body="""## Does stress cause IVF to fail?
ASRM says it is not clear how stress affects fertility, and stress does not mean you caused a negative result. Reducing stress improves quality of life during treatment.

## Coping during treatment
Common helpful approaches include counselling, support groups, mind-body programmes, exercise, mindfulness and talking with your partner or friends. Telling someone to just relax can add pressure.

## Counselling
Fertility counselling is available at many clinics; ask your clinic. If you feel hopeless or think about harming yourself, contact emergency services or a crisis line now."""),
dict(key="lifestyle", title="Lifestyle before and during IVF: weight, smoking, alcohol, caffeine", src=[31, 36, 53], progs=IVF,
 facts=["BMI", "smoking", "alcohol"],
 body="""## Does weight affect IVF?
Being underweight or overweight can reduce fertility and treatment success. ASRM explains BMI (body mass index) categories; your team may discuss a healthy weight before treatment.

## Smoking, alcohol and drugs
ACOG notes smoking and moderate or heavy drinking may reduce fertility in women, and smoking, heavy drinking and marijuana can lower sperm count and movement. Stopping smoking is recommended for both partners.

## Folic acid, caffeine and exercise
Before pregnancy, ACOG advises a daily folic acid supplement, limiting caffeine, staying active and reviewing your medicines with your doctor. Ask your clinic before taking supplements or herbal remedies."""),
dict(key="myths", title="Common IVF myths and facts", src=[44, 30, 13, 7, 21], progs=IVF,
 facts=["not a guaranteed solution", "no evidence to suggest that embryos are affected by the length of time"],
 body="""## Myth: IVF always works the first time
Fact: IVF is not a guaranteed solution; many people need more than one cycle (ESHRE).

## Myth: Bed rest after embryo transfer helps the embryo implant
Fact: You can return to normal light activity after transfer.

## Myth: Stress caused my IVF to fail
Fact: It is not clear how stress affects fertility (ASRM); a failed cycle is not your fault.

## Myth: Frozen embryos are worse than fresh ones
Fact: Most embryos survive thawing, and HFEA says there is no evidence embryos are affected by how long they are frozen.

## Myth: IVF babies have many more health problems
Fact: The vast majority of babies born after IVF are healthy; your team can discuss any specific risks, such as those of multiple pregnancy."""),
dict(key="risks", title="Risks of IVF: multiple pregnancy, ectopic pregnancy and procedure risks", src=[4, 13], progs=IVF,
 facts=["multiple", "ectopic"],
 body="""## What are the main risks of IVF?
Risks include OHSS, multiple pregnancy (twins or more), ectopic pregnancy, miscarriage, and small risks from egg collection such as bleeding or infection.

## Why is multiple pregnancy a risk?
HFEA describes multiple births as the biggest health risk of fertility treatment, with higher risks of premature birth and complications for parent and babies. This is why single embryo transfer is recommended for most people.

## Ectopic pregnancy warning signs
An ectopic pregnancy grows outside the womb. Seek urgent care for one-sided abdominal pain, shoulder-tip pain, bleeding, dizziness or fainting."""),
dict(key="glossary", title="IVF glossary of common terms", src=[21, 36], progs=IVF,
 facts=["Assisted hatching", "Blastocyst", "Follicles"],
 body="""## IVF glossary A to F
AFC: antral follicle count, an ultrasound count of small follicles. AMH: anti-Müllerian hormone, a blood test of ovarian reserve. Assisted hatching: opening the embryo's outer shell (zona pellucida) to help implantation. Blastocyst: day 5 to 6 embryo with a fluid-filled cavity. Cleavage-stage embryo: day 2 to 3 embryo. eSET: elective single embryo transfer. Endometrium: womb lining. FET: frozen embryo transfer. Follicles: fluid sacs in the ovary where eggs develop. FSH: follicle-stimulating hormone.

## IVF glossary G to Z
Gonadotropins: injectable hormones that stimulate the ovaries. hCG: hormone used as a trigger and measured in pregnancy tests. HSG: X-ray of the womb and tubes. ICSI: injecting one sperm into an egg. Luteal phase: the time after ovulation or egg collection. OHSS: ovarian hyperstimulation syndrome. PGT: preimplantation genetic testing. Trigger: injection that finishes egg maturation. Vitrification: fast freezing of eggs or embryos."""),
dict(key="who-is-ivf-for", title="Who IVF is for and when to seek a fertility assessment", src=[36, 13, 46, 44], progs=IVF,
 facts=["1 year", "6 months", "older than 40"],
 body="""## When should I see a fertility specialist?
ACOG recommends an infertility evaluation after 1 year of trying without contraception, after 6 months if older than 35, and straight away to discuss evaluation if older than 40, or sooner with known problems such as irregular periods.

## Who might IVF help?
IVF/ICSI may be recommended for blocked tubes, irregular ovulation, very low sperm quality, endometriosis, unexplained infertility, fertility preservation, single people and same-sex couples using donors, and people needing genetic testing of embryos."""),
]
