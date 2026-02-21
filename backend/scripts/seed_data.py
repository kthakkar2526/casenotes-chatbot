"""
seed_data.py — Generate and insert dummy child-welfare case data into Neon.

WHAT THIS SCRIPT DOES:
  1. Connects to Postgres using a synchronous psycopg2 connection (simpler
     for a one-off script than the async engine used by the server).
  2. Creates the four tables (cases, case_notes, chat_sessions,
     chat_messages) and the pgvector extension if they don't exist yet.
  3. Inserts 10 cases, each with 50–55 notes spread over ~18 months.
  4. Note text ranges from ~100 to ~8 000 characters and covers realistic
     caseworker observations: home visits, school check-ins, court hearings,
     medical appointments, safety assessments, family interactions, service
     referrals, and crisis incidents.

HOW TO RUN:
  cd backend
  source .venv/bin/activate
  python scripts/seed_data.py

NOTES:
  - The script is idempotent: if a case_number already exists it skips
    that case.  To fully re-seed, truncate the tables first.
  - Embeddings are NOT generated here; run embed_notes.py afterwards.
  - The DATABASE_URL is read from backend/.env via python-dotenv.
"""

import os
import random
import textwrap
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
from dotenv import load_dotenv

# ------------------------------------------------------------------ #
# Load environment
# ------------------------------------------------------------------ #
# Walk up from scripts/ to find the .env file in backend/
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

# psycopg2 needs a plain "postgresql://" URL (not asyncpg)
_raw_url = os.environ["DATABASE_URL"]
SYNC_DATABASE_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://")


# ------------------------------------------------------------------ #
# Reference data for realistic note generation
# ------------------------------------------------------------------ #
CASEWORKERS = [
    "Maria Santos", "James Okonkwo", "Linda Petersen", "David Kim",
    "Angela Torres", "Robert Hayes", "Priya Mehta", "Chris Nguyen",
]

NOTE_TYPES = ["in-person", "virtual", "phone", "written"]

FIRST_NAMES = [
    "Aaliyah", "Marcus", "Sofia", "Elijah", "Destiny", "Noah",
    "Jasmine", "Caleb", "Brianna", "Isaiah",
]
LAST_NAMES = [
    "Johnson", "Williams", "Martinez", "Brown", "Davis", "Wilson",
    "Anderson", "Thomas", "Garcia", "Jackson",
]

# ------------------------------------------------------------------ #
# Note templates
# ------------------------------------------------------------------ #
# Each template is a (note_type, min_chars_category, text_template) tuple.
# {cw} = caseworker name, {child} = child's first name,
# {family} = family last name, {date_str} = formatted date string.
# Templates are expanded with random details in generate_note().

SHORT_NOTES = [
    ("phone",
     "Received a brief phone call from {cw} who followed up with the {family} family. "
     "{child} was reported to be at school and doing well. No new concerns identified at this time. "
     "Next visit scheduled for two weeks."),

    ("written",
     "Email received from {child}'s school counselor. {child} attended class today and "
     "completed all assignments. Teacher noted improved attention. No behavioral incidents reported."),

    ("phone",
     "Brief check-in call with Ms. {family}. She confirmed that {child} had a medical "
     "appointment yesterday and that everything went well. Prescription renewed. "
     "Will follow up next week."),

    ("virtual",
     "15-minute video check-in with {child}. Child appeared calm and well-groomed. "
     "Stated they were 'doing okay' at school. No visible marks or bruising. "
     "Home background appeared tidy."),
]

MEDIUM_NOTES = [
    ("in-person",
     """Home visit conducted by {cw} on {date_str}. Arrived at the residence at approximately
2:00 PM. Ms. {family} answered the door and welcomed caseworker inside. The home was clean and
adequately furnished. The kitchen had food visible in the refrigerator, and {child}'s room contained
age-appropriate toys and a made bed.

{child} was present and appeared healthy. The child made eye contact, smiled, and engaged in brief
conversation. When asked about school, {child} said they liked their teacher and had a best friend
named Tyler. No signs of physical abuse or neglect were observed.

Ms. {family} discussed her progress in the parenting skills class offered by the Family Resource
Center. She has attended 4 of 6 sessions so far. She expressed some frustration about transportation
barriers but stated a neighbor has been helping. Caseworker provided information about the county
bus voucher program.

No new safety concerns identified. Case remains open for monitoring. Next visit in 30 days."""),

    ("in-person",
     """Unannounced home visit at 10:15 AM. {cw} conducting. No one answered the door initially.
After knocking twice, Mr. {family} opened the door. He appeared drowsy and smelled of alcohol.
Caseworker noted the odor and asked if he had been drinking. He stated he had "a couple beers last
night" but denied drinking that morning.

{child} was home from school (reported sick with a cold). The child appeared pale but alert and
said their stomach hurt. The living room had several empty beer bottles on the coffee table.
Caseworker expressed concern about the bottles being accessible to the child. Mr. {family}
agreed to dispose of them and moved them to a cabinet.

Caseworker reviewed safety plan with the household. Mr. {family} acknowledged the plan and
agreed that alcohol should not be consumed in the home when {child} is present. He became
somewhat defensive but ultimately cooperative.

Concerns documented. Supervisor notified. Follow-up visit scheduled for 48 hours."""),

    ("virtual",
     """Virtual meeting held via Zoom with Ms. {family} and {child}. {cw} facilitated.
Connection quality was good. Both individuals appeared comfortable on camera.

{child} showed the caseworker a drawing they made in art class — a colorful house with a
rainbow. Child seemed proud and engaged. When asked about home, {child} said "Mommy makes
good spaghetti" and laughed. No indicators of stress or fear were observed in the child's
demeanor.

Ms. {family} updated the caseworker on her job search. She has applied to three positions at
local retail stores and received one callback for an interview next Tuesday. Caseworker
encouraged her and offered to help with resume review if needed.

Utilities are current. Rent is paid through the end of the month. No new concerns noted.
Case status: active monitoring."""),
]

LONG_NOTES = [
    ("in-person",
     """COMPREHENSIVE HOME VISIT AND SAFETY ASSESSMENT — {date_str}

Caseworker: {cw}
Family: {family} household
Child: {child} (present during visit)
Visit duration: approximately 2 hours 45 minutes

BACKGROUND:
This visit was prompted by a referral received on {date_str} alleging physical discipline
leaving marks on the child. The referral was rated as Priority 1 and assigned to {cw}
for same-day response.

ARRIVAL AND INITIAL CONTACT:
Caseworker arrived at 3:45 PM. The home is a two-bedroom apartment on the third floor of a
six-unit building. Ms. {family} answered the door with {child} standing behind her. {child}
was dressed in school clothes and appeared alert. Ms. {family} was initially guarded but
allowed caseworker entry after showing identification and explaining the purpose of the visit.

HOME CONDITIONS:
The apartment was in generally acceptable condition. The living room contained a couch, television,
and small bookshelf with children's books. The kitchen had a full refrigerator and evidence of a
recent meal (dishes in the drying rack). {child}'s bedroom had a twin bed, dresser, and several
stuffed animals. No hazardous conditions were observed (outlet covers present, cleaning supplies
stored in upper cabinet).

CHILD INTERVIEW (conducted privately in {child}'s bedroom):
Caseworker asked {child} open-ended questions using the CornerHouse protocol. {child} was
cooperative and articulate for their age. When asked "how things are at home," {child} said
"it's okay mostly." When caseworker asked about the specific mark on the back of {child}'s
thigh (reported by the school), {child} initially hesitated, then said "Mommy hit me with
the wooden spoon because I broke her plate." {child} did not appear distressed describing
this and said "she only does it when I do something really bad."

PHYSICAL OBSERVATION:
With {child}'s consent and in the presence of a same-gender colleague (Officer Rodriguez,
DHS liaison), a limited physical check was conducted. A 3-inch elongated bruise was observed
on the back of the left thigh, yellowish-green in color (consistent with bruising 5–7 days
old). No other marks observed.

PARENT INTERVIEW:
Caseworker met with Ms. {family} in the living room while the DHS liaison remained with
{child} in the bedroom. Ms. {family} was asked about discipline methods. After initially
denying the incident, she became tearful and acknowledged striking {child} with a wooden
spoon. She stated she was "at the end of her rope" that day — she had just learned her hours
at work were cut and {child} had broken a serving dish that belonged to her late mother.

Ms. {family} expressed immediate remorse. She said she knew it was wrong and had not done
it since. She asked what would happen to her. Caseworker explained the process and emphasized
that the goal was to keep the family together safely.

ASSESSMENT:
The physical mark, the child's disclosure, and the parent's admission constitute confirmed
physical abuse. However, the incident appears isolated, there is no pattern in the record,
the parent is remorseful, and the home is otherwise safe and nurturing.

SAFETY DECISION:
Child is safe to remain in the home under an in-home safety plan.

SAFETY PLAN ESTABLISHED:
  1. Ms. {family} agrees to use only verbal redirection and time-out as discipline methods.
  2. All physical implements (wooden spoon identified) removed from potential use.
  3. Emergency contact: Aunt Rosa {family} (maternal), phone on file.
  4. {cw} will visit twice per week for the next 30 days.
  5. Ms. {family} will enroll in the "Positive Parenting" evidence-based program at
     the Family Resource Center within 5 business days.

Ms. {family} signed the safety plan. Copy provided to family.

NEXT STEPS:
- Substantiated finding of physical abuse will be reported per state mandate.
- Referral to Positive Parenting program to be submitted today.
- Follow-up visit in 48 hours.
- Supervisor review required before case plan is finalized.

CASEWORKER SIGNATURE: {cw}
"""),

    ("in-person",
     """MULTI-DISCIPLINARY TEAM (MDT) MEETING NOTES — {date_str}

Case: {family} / {child}
Location: Child Advocacy Center, Conference Room B
Attendees:
  - {cw}, Lead Caseworker, Child Protective Services
  - Dr. Amanda Reyes, Forensic Interviewer, Child Advocacy Center
  - Det. Marcus Webb, Crimes Against Children Unit, Metro PD
  - Susan Park, LCSW, Trauma Therapist assigned to {child}
  - Principal Janet Oliver, {child}'s school
  - Guardian ad litem: Attorney Tomas Varela

SUMMARY OF FORENSIC INTERVIEW:
Dr. Reyes conducted a forensic interview with {child} earlier the same morning. The interview
lasted 47 minutes. {child} was cooperative throughout and demonstrated developmentally appropriate
language. {child} disclosed a total of three incidents of physical discipline by the primary
caregiver within the past 90 days, including the bruising incident documented in the prior visit.
{child} described the household emotional climate as "mostly happy" and expressed love for the
caregiver.

SCHOOL REPORT (Principal Oliver):
{child} has maintained regular attendance (3 absences in 90 days, all excused). Academic
performance is at grade level in reading and slightly below in math. Teacher has noted increased
withdrawn behavior over the past 6 weeks. {child} was referred to the school counselor twice,
both times declining to disclose anything specific but saying they were "worried about Mom."
No peer conflict or bullying reported.

THERAPY UPDATE (Susan Park, LCSW):
{child} began trauma-focused CBT four weeks ago, attending weekly sessions. {child} has
engaged well with the trauma narrative component. Early indicators suggest the child has
a secure attachment to the caregiver despite the abuse incidents. Prognosis for recovery
is good with continued treatment and a stable home environment. Ms. Park recommended
12 additional sessions minimum.

LAW ENFORCEMENT UPDATE (Det. Webb):
Detective Webb reported that the criminal investigation is ongoing. At this time, no arrest
has been made. The District Attorney's office has reviewed the evidence and indicated that
charges are possible but that diversion to a parenting program may be recommended given
the circumstances. Detective Webb will update MDT at the next meeting.

CASE PLAN DISCUSSION:
The team agreed on the following case plan elements:
  1. {child} to continue weekly TF-CBT with Susan Park.
  2. Ms. {family} to attend Positive Parenting — she has completed 2 of 8 sessions.
  3. Caseworker ({cw}) to conduct twice-weekly visits for next 60 days, then reassess.
  4. Safety plan to remain in effect; no new safety concerns identified since implementation.
  5. School counselor to continue weekly check-ins with {child} and report any changes.
  6. Court date set for 45 days out for dispositional hearing.

GUARDIAN AD LITEM NOTES (Atty. Varela):
Attorney Varela indicated {child}'s expressed wishes are to remain at home with the caregiver.
He will submit his report to the court in advance of the hearing. He noted no concerns about
the current safety plan.

NEXT MDT MEETING: 60 days from today.

Documented by: {cw}
"""),

    ("in-person",
     """COURT PREPARATION AND PRE-HEARING STAFFING NOTES — {date_str}

Case: {family} family — {child}
Caseworker: {cw}
Supervisor: Denise Holloway

BACKGROUND:
A dependency petition was filed 30 days ago following substantiation of neglect (inadequate
supervision, lack of consistent medical care). The child, {child}, had been found alone in
the apartment on two occasions by neighbors. Medical records indicated that two well-child
visits and a recommended dental appointment had been missed in the preceding year.

CURRENT CASE STATUS:
  - {child} remains in the home under a safety plan with maternal grandmother, Evelyn {family},
    as an in-home safety monitor.
  - Ms. {family} (mother) has been engaged with services with some inconsistency (details below).
  - No new safety incidents since the petition was filed.

SERVICE COMPLIANCE REVIEW:

Parenting Education (Family Resource Center):
  Ms. {family} has attended 5 of 8 required sessions. She missed two sessions without notice
  and one with 2 hours advance notice (she was ill). Program coordinator says her engagement
  when present is good — she participates, takes notes, and has applied techniques observed
  during home visits. Recommendation: extend completion date by 3 weeks.

Substance Abuse Assessment:
  Completed. Results: No substance use disorder diagnosis. Assessor noted occasional social
  drinking (self-reported). No treatment recommended. Full report in case file.

Individual Counseling:
  Ms. {family} has attended 4 of 6 scheduled sessions with counselor Dr. Kim Osei. Dr. Osei
  reports that the client is working through trauma related to domestic violence by a former
  partner (not {child}'s father). Ms. {family} has made progress in recognizing how that
  trauma affected her capacity to be present for {child}. Continuing.

Employment and Financial Stability:
  Ms. {family} obtained part-time employment at a local grocery chain 3 weeks ago (18 hrs/wk,
  $14/hr). She has applied for SNAP benefits and is on the waitlist for a childcare subsidy
  through the county. Caseworker assisted with the SNAP application in a prior visit.

  Evelyn {family} (maternal grandmother / safety monitor) has been consistent and reliable.
  She accompanies {child} to the school bus stop each morning, is present in the evenings,
  and has maintained clear communication with the caseworker.

CHILD'S WELL-BEING:
  {child} had a medical check-up 10 days ago — all immunizations current, growth on track,
  no health concerns. A dental appointment is scheduled for next week.
  School reports that {child}'s attendance has been perfect for 30 consecutive days.
  The child seems happier, according to the teacher; is more talkative and initiating play
  with peers.

RECOMMENDED COURT POSITION:
  The agency will recommend to the court:
  1. Case remain open with continued in-home services for 90 additional days.
  2. Safety monitor arrangement (grandmother) to continue.
  3. Service plan compliance to be updated at next court date.
  4. If full compliance is achieved at the 90-day mark, a motion to dismiss will be filed.

RISKS TO HIGHLIGHT FOR COURT:
  - Pattern of missed appointments warrants continued oversight.
  - Financial instability remains a stressor; subsidies still pending.
  - Mother's trauma history is being addressed but is a long-term factor.

STRENGTHS TO HIGHLIGHT FOR COURT:
  - No new safety incidents.
  - Child's health and school engagement have improved measurably.
  - Mother is employed and actively engaged in services when present.
  - Strong extended family support via grandmother.

Documents prepared for court:
  [x] Court report (18 pages) — filed with clerk 48 hrs prior
  [x] Service provider reports attached as exhibits
  [x] Updated case plan signed by Ms. {family}
  [ ] Guardian ad litem report (attorney filing separately)

Caseworker: {cw}
Supervisor review completed: Denise Holloway
"""),
]

CRISIS_NOTES = [
    ("phone",
     """EMERGENCY RESPONSE — {date_str}

At 11:47 PM, caseworker {cw} received a call from the on-call line. A neighbor at the
{family} residence had called 911 reporting loud arguing and the sound of breaking glass.
Metro Police were dispatched. The on-call supervisor was notified.

Caseworker {cw} arrived at the address at 12:31 AM to find two police officers on scene.
Ms. {family} was sitting on the front steps, visibly upset but uninjured. {child} was
inside with a female officer. The male partner (Mr. Leon {family}, not a case-involved
adult) had left the premises before police arrived.

{child} was found under their bed, covering their ears. The officer reported the child
was frightened but uninjured. Caseworker spoke with {child} for approximately 20 minutes.
{child} said "they were really loud and scary" and had hidden when the yelling started.
{child} did not disclose any physical harm to themselves.

Ms. {family} stated that Mr. Leon had come over intoxicated and became aggressive when she
asked him to leave. She said she had not invited him and did not want him there.
She did not sustain any injuries.

SAFETY DECISION AT SCENE:
{child} is safe to remain in the home with Ms. {family}. Mr. Leon has left.
Ms. {family} agreed to call 911 if he returned and to call the caseworker in the morning.

FOLLOW-UP REQUIRED:
- Safety plan to be reviewed and updated at morning visit.
- Domestic violence services to be discussed with Ms. {family}.
- Supervisor to be briefed at 8 AM.
- Incident documented in case file as domestic violence exposure.

Caseworker {cw} departed at 1:55 AM. Supervisor Denise Holloway notified by text.
"""),
]

ALL_TEMPLATES = SHORT_NOTES * 8 + MEDIUM_NOTES * 5 + LONG_NOTES * 3 + CRISIS_NOTES * 2


# ------------------------------------------------------------------ #
# Note generation
# ------------------------------------------------------------------ #
def generate_note(template_tuple, child_first, family_last, caseworker, note_date):
    """
    Fill in a template tuple (note_type, template_str) with concrete values
    and return (note_type, filled_text).
    """
    note_type, template = template_tuple
    date_str = note_date.strftime("%B %d, %Y")

    text = textwrap.dedent(template).strip().format(
        cw=caseworker,
        child=child_first,
        family=family_last,
        date_str=date_str,
    )
    return note_type, text


# ------------------------------------------------------------------ #
# SQL helpers
# ------------------------------------------------------------------ #
CREATE_EXTENSION = "CREATE EXTENSION IF NOT EXISTS vector;"

CREATE_CASES = """
CREATE TABLE IF NOT EXISTS cases (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_number VARCHAR(50)  UNIQUE NOT NULL,
    client_name VARCHAR(255) NOT NULL,
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);"""

CREATE_CASE_NOTES = """
CREATE TABLE IF NOT EXISTS case_notes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id         UUID    NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    note_text       TEXT    NOT NULL,
    caseworker_name VARCHAR(255),
    note_type       VARCHAR(50),
    created_at      TIMESTAMPTZ NOT NULL
);"""

# note_chunks is the table that actually holds embeddings.
# Each CaseNote is split into overlapping chunks of ~1 200 characters by
# embed_notes.py, and each chunk gets its own 1024-dim vector.
#
# case_id, created_at, caseworker_name, note_type are denormalised from the
# parent case_notes row so the vector search query can filter without a JOIN.
CREATE_NOTE_CHUNKS = """
CREATE TABLE IF NOT EXISTS note_chunks (
    id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    note_id         UUID    NOT NULL REFERENCES case_notes(id) ON DELETE CASCADE,
    case_id         UUID    NOT NULL,
    chunk_index     INTEGER NOT NULL,
    chunk_text      TEXT    NOT NULL,
    embedding       VECTOR(1024),
    created_at      TIMESTAMPTZ NOT NULL,
    caseworker_name VARCHAR(255),
    note_type       VARCHAR(50)
);"""

# ivfflat approximate-NN index on the chunk embeddings.
# Must be created AFTER note_chunks has data (ideally ≥ 1 000 rows).
# We create it at the end of main() after all data is inserted.
CREATE_CHUNKS_INDEX = """
CREATE INDEX IF NOT EXISTS note_chunks_embedding_idx
    ON note_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
"""

CREATE_CHAT_SESSIONS = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id    UUID  NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    start_date DATE  NOT NULL,
    end_date   DATE  NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);"""

CREATE_CHAT_MESSAGES = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID    NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role       VARCHAR(10) NOT NULL,
    content    TEXT    NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);"""

INSERT_CASE = """
INSERT INTO cases (id, case_number, client_name)
VALUES (%s, %s, %s)
ON CONFLICT (case_number) DO NOTHING
RETURNING id;
"""

INSERT_NOTE = """
INSERT INTO case_notes (id, case_id, note_text, caseworker_name, note_type, created_at)
VALUES (%s, %s, %s, %s, %s, %s);
"""


# ------------------------------------------------------------------ #
# Main
# ------------------------------------------------------------------ #
def main():
    random.seed(42)  # reproducible data

    print(f"Connecting to database…")
    conn = psycopg2.connect(SYNC_DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    print("Creating tables and extensions…")
    for stmt in [
        CREATE_EXTENSION,
        CREATE_CASES,
        CREATE_CASE_NOTES,
        CREATE_NOTE_CHUNKS,   # must come after case_notes (FK dependency)
        CREATE_CHAT_SESSIONS,
        CREATE_CHAT_MESSAGES,
        # ivfflat index is created at the END of main() after data is inserted,
        # because pgvector needs existing rows to size the index properly.
    ]:
        cur.execute(stmt)
    conn.commit()

    # ---- Generate 10 cases ---------------------------------------- #
    total_notes = 0

    for i in range(10):
        first = FIRST_NAMES[i]
        last  = LAST_NAMES[i]
        case_number = f"CW-2023-{i + 1:03d}"
        client_name = f"{first} {last}"
        case_id = str(uuid.uuid4())

        print(f"\nInserting case {case_number} — {client_name}")

        cur.execute(INSERT_CASE, (case_id, case_number, client_name))
        row = cur.fetchone()
        if row is None:
            # ON CONFLICT DO NOTHING — case already exists; fetch its id
            cur.execute("SELECT id FROM cases WHERE case_number = %s", (case_number,))
            case_id = str(cur.fetchone()[0])
            print(f"  Case already exists (id={case_id}), skipping note insertion.")
            conn.commit()
            continue

        # ---- Generate 50–55 notes spread over 18 months ----------- #
        n_notes = random.randint(50, 55)

        # Start date: 18 months ago from "now" (we use a fixed anchor
        # so the data is consistent across re-runs)
        anchor = datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
        # Spread notes roughly evenly over 18 months (≈547 days)
        span_days = 547
        # Add slight jitter so notes don't land at perfectly even intervals
        interval_base = span_days / n_notes

        note_date = anchor
        for j in range(n_notes):
            template_tuple = random.choice(ALL_TEMPLATES)
            caseworker = random.choice(CASEWORKERS)
            note_type, note_text = generate_note(
                template_tuple, first, last, caseworker, note_date
            )

            # Jitter: ±30% of the base interval
            jitter = random.uniform(-0.3 * interval_base, 0.3 * interval_base)
            delta_days = max(1, int(interval_base + jitter))
            # Also randomise the time-of-day
            delta_hours = random.randint(0, 8)
            note_date = note_date + timedelta(days=delta_days, hours=delta_hours)

            note_id = str(uuid.uuid4())
            cur.execute(
                INSERT_NOTE,
                (note_id, case_id, note_text, caseworker, note_type, note_date),
            )
            total_notes += 1

        conn.commit()
        print(f"  Inserted {n_notes} notes.")

    # Create the ivfflat index NOW — after all data is inserted so pgvector
    # can size the index correctly.  Running it on an empty table would create
    # a useless index with lists=1.
    print("\nCreating ivfflat index on note_chunks.embedding…")
    cur.execute(CREATE_CHUNKS_INDEX)
    conn.commit()

    cur.close()
    conn.close()

    print(f"\nDone. Total notes inserted: {total_notes}")
    print("Next step: run  python scripts/embed_notes.py  to chunk and embed the notes.")


if __name__ == "__main__":
    main()
