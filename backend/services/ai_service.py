from __future__ import annotations

import logging
from random import Random
import re
from typing import Any, Dict, List

from backend.ai_client import (
    PROVIDER_RUNTIME_METADATA_KEY,
    AIProvider,
    AIProviderError,
    GeminiProvider,
    GroqProvider,
    MistralProvider,
    OpenAIProvider,
    ProviderRouter,
)
from backend.config import AI_TESTING_ONLY_PROVIDER_NAMES, Settings, get_settings
from backend.services.knowledge_service import clean_bullets, extract_keywords, extract_section


logger = logging.getLogger(__name__)


class AIServiceUnavailableError(RuntimeError):
    """Raised when strict live-only AI generation cannot produce a response."""

    status_code = 503
    public_detail = "AI generation is temporarily unavailable. Please try again."

    def __init__(self, *, attempted_provider_chain: list[str] | None = None) -> None:
        super().__init__(self.public_detail)
        self.attempted_provider_chain = tuple(
            provider
            for provider in (str(item or "").strip() for item in (attempted_provider_chain or []))
            if provider and provider != "mock"
        )


ABSURD_OPTION_FRAGMENTS = (
    "no connection with the constitution",
    "relevant only for geography questions",
    "only for geography questions",
    "can never appear in prelims or mains",
    "never appear in prelims or mains",
    "no role in upsc",
)

WEAK_DISTRACTOR_FRAGMENTS = (
    "is mainly associated with",
    "primarily framed through",
    "usually explained almost entirely through",
    "without its usual link",
    "instead of its usual link",
    "in exam terms",
    "is more closely linked with",
    "treated chiefly as a question of",
)

TERM_SWAP_PAIRS = (
    ("Governor", "President"),
    ("President", "Governor"),
    ("Chief Minister", "Prime Minister"),
    ("Prime Minister", "Chief Minister"),
    ("Legislative Assembly", "Parliament"),
    ("legislative assembly", "Parliament"),
    ("state government", "Union government"),
    ("Union government", "state government"),
    ("state Council of Ministers", "Union Council of Ministers"),
    ("Part III", "Part IV"),
    ("Part IV", "Part III"),
    ("Fundamental Rights", "Directive Principles"),
    ("Directive Principles", "Fundamental Rights"),
    ("all persons", "only citizens"),
    ("only citizens", "all persons"),
    ("real executive", "nominal executive"),
    ("nominal executive", "real executive"),
    ("strong Centre", "complete parity between Centre and states"),
    ("unitary tilt", "complete absence of any central tilt"),
    ("reasonable restrictions", "absolute freedom without restriction"),
    ("non-justiciable", "directly enforceable by courts"),
    ("residuary powers", "only State List powers"),
    ("Union, State, and Concurrent Lists", "only the Union and State Lists"),
    ("single citizenship rather than dual citizenship at the Union and state levels", "dual citizenship at the Union and state levels rather than single citizenship"),
    ("Articles 5 to 11", "the Directive Principles alone"),
    ("Parliament can regulate citizenship further through ordinary law", "citizenship cannot be shaped further by ordinary law"),
    ("Himalayan rivers", "Peninsular rivers"),
    ("Peninsular rivers", "Himalayan rivers"),
    ("perennial", "mostly seasonal"),
    ("rain-fed", "glacier-fed"),
    ("older geological surfaces", "young fold mountains"),
        ("The Congress began with moderate constitutional demands", "The Congress began with immediate mass civil disobedience"),
    ("moderate constitutional demands", "armed anti-colonial insurrection from the outset"),
    ("moderate petitioning body", "permanent revolutionary secret society"),
    ("mass anti-colonial struggle", "narrow colonial support politics"),
    ("all-India national movement", "isolated provincial lobbying"),
    ("1885", "1905"),
    ("colonial government", "post-independence planning commission"),
)

QUALIFIER_SWAP_PAIRS = (
    ("usually", "uniformly"),
    ("guided by", "completely independent of"),
    ("support cooperative federalism", "eliminate the federal balance"),
    ("limit arbitrary state action", "remove limits on state action"),
    ("generally", "in every case"),
    ("mostly", "entirely"),
    ("over time", "without any major change over time"),
    ("central role", "minor and incidental role"),
    ("important", "largely irrelevant"),
    ("often", "rarely"),
)

NEGATION_SWAP_PAIRS = (
    (" can ", " cannot "),
    (" cannot ", " can "),
    (" are generally ", " are never "),
    (" are mostly ", " are entirely "),
    (" is often ", " is rarely "),
    (" played a central role in ", " played only a limited role in "),
    (" became important ", " remained peripheral "),
    (" links ", " isolates "),
    (" link ", " isolate "),
    (" evolved from ", " remained only "),
    (" is important for ", " is mostly detached from "),
    (" are important for ", " are mostly detached from "),
    (" reflect ", " ignore "),
    (" support ", " have little connection to "),
    (" begins with ", " does not begin with "),
    (" showing ", " denying "),
    (" describes ", " misdescribes "),
    (" highlights ", " downplays "),
    (" helps interpret ", " cannot guide the interpretation of "),
    (" is the introductory statement of ", " is an enforceable chapter of "),
    (" defines the formal legal membership of ", " does not determine the legal membership of "),
)


MOCK_QUIZ_BANK: Dict[str, List[Dict[str, Any]]] = {
    "fundamental rights": [
        {
            "concept": "Scope",
            "question": "What do Fundamental Rights primarily protect?",
            "options": [
                "Core freedoms and safeguards against arbitrary state action",
                "Only economic planning targets for the state",
                "Only customs followed by village councils",
                "Only emergency powers of Parliament",
            ],
            "correct_answer": "Core freedoms and safeguards against arbitrary state action",
            "explanation": "Fundamental Rights in Part III protect liberties, equality, and remedies against unconstitutional action.",
        },
        {
            "concept": "Article 32",
            "question": "Why is Article 32 often called the heart and soul of the Constitution?",
            "options": [
                "It gives the right to move the Supreme Court for enforcement of Fundamental Rights",
                "It allows the Rajya Sabha to amend any law alone",
                "It sets the salary of the President",
                "It abolishes all preventive detention laws",
            ],
            "correct_answer": "It gives the right to move the Supreme Court for enforcement of Fundamental Rights",
            "explanation": "Dr. B.R. Ambedkar described Article 32 this way because it guarantees remedies when rights are violated.",
        },
        {
            "concept": "Reasonable restrictions",
            "question": "Which statement about Fundamental Rights is correct?",
            "options": [
                "They are subject to reasonable restrictions in the public interest",
                "They are always absolute and can never be regulated",
                "They apply only during a national emergency",
                "They can be suspended permanently by any district authority",
            ],
            "correct_answer": "They are subject to reasonable restrictions in the public interest",
            "explanation": "Rights such as freedom of speech can be reasonably restricted for public order, security, and similar grounds.",
        },
        {
            "concept": "Citizens vs persons",
            "question": "Which of the following is true about the beneficiaries of Fundamental Rights?",
            "options": [
                "Some rights are available only to citizens, while others are available to all persons",
                "All rights are available only to elected representatives",
                "All rights are available only to citizens",
                "No right is available to non-citizens under any circumstance",
            ],
            "correct_answer": "Some rights are available only to citizens, while others are available to all persons",
            "explanation": "For example, Article 19 is only for citizens, while Articles 14 and 21 extend to persons more broadly.",
        },
        {
            "concept": "Writs",
            "question": "Writ remedies are most directly linked with which feature of Fundamental Rights?",
            "options": [
                "Judicial enforcement",
                "Directive policy guidance",
                "Budget approval",
                "Election scheduling",
            ],
            "correct_answer": "Judicial enforcement",
            "explanation": "Writs like habeas corpus and mandamus help courts enforce rights when violations occur.",
        },
        {
            "concept": "Equality",
            "question": "The Right to Equality mainly aims to prevent:",
            "options": [
                "Arbitrary discrimination",
                "Constitutional amendments",
                "State finance commissions",
                "Parliamentary debates",
            ],
            "correct_answer": "Arbitrary discrimination",
            "explanation": "Articles 14 to 18 focus on equality before law, equal protection, and ending practices like untouchability and titles.",
        },
    ],
    "directive principles": [
        {
            "concept": "Nature",
            "question": "Directive Principles of State Policy are best described as:",
            "options": [
                "Non-justiciable principles guiding the state toward welfare goals",
                "Enforceable criminal prohibitions",
                "Temporary ordinances issued by governors",
                "Rules only for local bodies",
            ],
            "correct_answer": "Non-justiciable principles guiding the state toward welfare goals",
            "explanation": "Directive Principles are not directly enforceable in courts, but they guide governance and policymaking.",
        },
        {
            "concept": "Part IV",
            "question": "Directive Principles are contained in which part of the Constitution?",
            "options": ["Part IV", "Part III", "Part V", "Part IX"],
            "correct_answer": "Part IV",
            "explanation": "Part IV deals with Directive Principles of State Policy.",
        },
        {
            "concept": "Welfare state",
            "question": "The central goal of Directive Principles is to promote:",
            "options": ["A welfare state", "Judicial supremacy only", "Military governance", "Emergency administration"],
            "correct_answer": "A welfare state",
            "explanation": "They aim to secure social and economic justice and reduce inequalities.",
        },
        {
            "concept": "Enforceability",
            "question": "Which statement is correct regarding enforceability of Directive Principles?",
            "options": [
                "Courts cannot directly enforce them, but governments should apply them in lawmaking",
                "Every Directive Principle can be enforced through Article 32",
                "They override all Fundamental Rights in every situation",
                "They apply only to Parliament and never to states",
            ],
            "correct_answer": "Courts cannot directly enforce them, but governments should apply them in lawmaking",
            "explanation": "They are fundamental in governance even though not justiciable.",
        },
        {
            "concept": "Examples",
            "question": "Which of the following is an example of a Directive Principle?",
            "options": [
                "Promotion of equal justice and free legal aid",
                "The right against exploitation",
                "The right to constitutional remedies",
                "The anti-defection schedule",
            ],
            "correct_answer": "Promotion of equal justice and free legal aid",
            "explanation": "Free legal aid and social justice measures are classic Directive Principle goals.",
        },
        {
            "concept": "Balance with rights",
            "question": "UPSC often tests Directive Principles together with:",
            "options": ["Fundamental Rights", "Municipal bonds", "Delimitation tables", "Election symbols"],
            "correct_answer": "Fundamental Rights",
            "explanation": "A common exam theme is the balance and harmony between rights and Directive Principles.",
        },
    ],
    "parliament": [
        {
            "concept": "Composition",
            "question": "Which of the following correctly describes the Indian Parliament?",
            "options": [
                "President, Lok Sabha, and Rajya Sabha",
                "Prime Minister, Supreme Court, and Lok Sabha",
                "President and only Lok Sabha",
                "Lok Sabha and state legislatures only",
            ],
            "correct_answer": "President, Lok Sabha, and Rajya Sabha",
            "explanation": "The Constitution treats the President as an integral part of Parliament along with the two Houses.",
        },
        {
            "concept": "Money Bill",
            "question": "A Money Bill can be introduced only in:",
            "options": ["Lok Sabha", "Rajya Sabha", "Either House", "Any state legislature"],
            "correct_answer": "Lok Sabha",
            "explanation": "Money Bills originate only in the Lok Sabha, while the Rajya Sabha has limited powers over them.",
        },
        {
            "concept": "Rajya Sabha",
            "question": "Which statement about the Rajya Sabha is correct?",
            "options": [
                "It is a permanent House that is not subject to dissolution",
                "It is dissolved every five years",
                "It can pass a no-confidence motion against the Council of Ministers",
                "It can introduce all Money Bills",
            ],
            "correct_answer": "It is a permanent House that is not subject to dissolution",
            "explanation": "One-third of its members retire periodically, but the House itself continues permanently.",
        },
        {
            "concept": "Collective responsibility",
            "question": "The Council of Ministers is collectively responsible to:",
            "options": ["Lok Sabha", "Rajya Sabha", "President alone", "Election Commission"],
            "correct_answer": "Lok Sabha",
            "explanation": "This is why a no-confidence motion matters in the Lok Sabha, not the Rajya Sabha.",
        },
        {
            "concept": "Legislative function",
            "question": "What is one of Parliament's core functions?",
            "options": [
                "Making laws and holding the executive accountable",
                "Conducting judicial review of all cases",
                "Appointing every district collector",
                "Administering panchayat elections directly",
            ],
            "correct_answer": "Making laws and holding the executive accountable",
            "explanation": "Parliament legislates, debates, approves finances, and scrutinizes the executive.",
        },
        {
            "concept": "Sessions",
            "question": "Why are parliamentary sessions important in exam preparation?",
            "options": [
                "They show how legislative business, questions, and accountability operate in practice",
                "They permanently amend the Constitution each time",
                "They replace judicial proceedings",
                "They are relevant only to local government",
            ],
            "correct_answer": "They show how legislative business, questions, and accountability operate in practice",
            "explanation": "UPSC frequently links institutions with their functioning, including sessions, questions, and legislative procedures.",
        },
    ],
    "chief minister": [
        {
            "concept": "Real executive",
            "question": "Which statement best explains why the Chief Minister is called the real executive at the state level?",
            "options": [
                "The Chief Minister leads the Council of Ministers and directs the working of the elected state government",
                "The Chief Minister is only a ceremonial head with no role in day-to-day governance",
                "The Chief Minister performs the same constitutional role as the Governor",
                "The Chief Minister functions mainly as a judicial authority in the state",
            ],
            "correct_answer": "The Chief Minister leads the Council of Ministers and directs the working of the elected state government",
            "explanation": "The Chief Minister is the real executive because the elected ministry functions under this office in a parliamentary system.",
        },
        {
            "concept": "Appointment",
            "question": "Which statement correctly captures the appointment of the Chief Minister?",
            "options": [
                "The Governor appoints the Chief Minister, but the choice is shaped by majority support in the legislative assembly",
                "The President directly appoints the Chief Minister of every state",
                "The Chief Minister is elected separately by all voters of the state",
                "The Chief Minister is nominated by the Speaker of the legislative assembly",
            ],
            "correct_answer": "The Governor appoints the Chief Minister, but the choice is shaped by majority support in the legislative assembly",
            "explanation": "Formally the appointment is by the Governor, but in practice it follows the logic of legislative majority in a parliamentary system.",
        },
        {
            "concept": "Council of Ministers",
            "question": "What is the Chief Minister's constitutional position in relation to the state Council of Ministers?",
            "options": [
                "The Chief Minister heads the state Council of Ministers",
                "The Chief Minister is outside the Council of Ministers and only advises it informally",
                "The Chief Minister is subordinate to the state legislature in ministerial appointments",
                "The Chief Minister can function without a Council of Ministers in normal constitutional practice",
            ],
            "correct_answer": "The Chief Minister heads the state Council of Ministers",
            "explanation": "The office of Chief Minister is central to the working of the state ministry and coordinates its functioning.",
        },
        {
            "concept": "Governor link",
            "question": "Which statement correctly reflects the Chief Minister's role in relation to the Governor?",
            "options": [
                "The Chief Minister communicates decisions of the Council of Ministers to the Governor",
                "The Chief Minister exercises all powers of the Governor directly",
                "The Chief Minister is constitutionally insulated from all communication with the Governor",
                "The Chief Minister can remove the Governor through a vote in the assembly",
            ],
            "correct_answer": "The Chief Minister communicates decisions of the Council of Ministers to the Governor",
            "explanation": "The Chief Minister is the main constitutional link between the elected ministry and the Governor.",
        },
        {
            "concept": "Parliamentary basis",
            "question": "Which political condition most strongly supports the office of the Chief Minister in normal state politics?",
            "options": [
                "Commanding majority support in the legislative assembly",
                "Holding simultaneous membership in both Houses of Parliament",
                "Being nominated by the Election Commission",
                "Receiving judicial approval from the High Court",
            ],
            "correct_answer": "Commanding majority support in the legislative assembly",
            "explanation": "In a parliamentary system, majority support in the elected House is what gives stability and legitimacy to the office.",
        },
    ],
    "federalism": [
        {
            "concept": "Division of powers",
            "question": "Which constitutional mechanism most directly reflects the federal division of legislative powers in India?",
            "options": [
                "The Union, State, and Concurrent Lists",
                "Only the Fundamental Duties chapter",
                "The annual budget speech alone",
                "The schedules for parliamentary salaries",
            ],
            "correct_answer": "The Union, State, and Concurrent Lists",
            "explanation": "The Seventh Schedule distributes legislative subjects across the Union, State, and Concurrent Lists.",
        },
        {
            "concept": "Strong Centre",
            "question": "Which statement best captures the federal design of the Indian Constitution?",
            "options": [
                "It is federal in structure but gives the Centre a stronger constitutional position",
                "It creates a confederation with complete state sovereignty",
                "It gives equal residuary powers to the Union and the states in all matters",
                "It removes all central influence from Centre-state relations",
            ],
            "correct_answer": "It is federal in structure but gives the Centre a stronger constitutional position",
            "explanation": "Indian federalism is often described as federal with a strong unitary or central bias.",
        },
        {
            "concept": "Residuary powers",
            "question": "In India's constitutional design, residuary powers are generally associated with:",
            "options": [
                "The Union or Parliament",
                "The states alone",
                "Local self-government institutions only",
                "The judiciary through advisory opinions",
            ],
            "correct_answer": "The Union or Parliament",
            "explanation": "The residuary field strengthens the Centre and is one reason India is seen as having a unitary tilt.",
        },
        {
            "concept": "Emergency provisions",
            "question": "Why are emergency provisions important in discussions of Indian federalism?",
            "options": [
                "They show how the Constitution can shift power toward the Centre in exceptional situations",
                "They permanently abolish the federal structure once invoked",
                "They transfer all judicial power to local governments",
                "They operate only in matters unrelated to Centre-state relations",
            ],
            "correct_answer": "They show how the Constitution can shift power toward the Centre in exceptional situations",
            "explanation": "Emergency provisions are one of the clearest examples of the unitary tilt within Indian federalism.",
        },
        {
            "concept": "Cooperative federalism",
            "question": "Which institution is commonly linked with cooperative federalism in India?",
            "options": [
                "The Inter-State Council",
                "The Supreme Court as a House of Parliament",
                "The Election Commission as a financial tribunal",
                "The Rajya Sabha acting as a state cabinet",
            ],
            "correct_answer": "The Inter-State Council",
            "explanation": "Institutions like the Inter-State Council help consultation and coordination between the Union and the states.",
        },
    ],
    "parliament sessions": [
        {
            "concept": "Conventional calendar",
            "question": "Parliament in India usually meets through which session pattern by convention?",
            "options": [
                "Budget, Monsoon, and Winter sessions",
                "Spring, Summer, and Autumn sessions fixed by the Constitution",
                "One continuous annual session with no break",
                "Only emergency and financial sessions",
            ],
            "correct_answer": "Budget, Monsoon, and Winter sessions",
            "explanation": "These three sessions are followed by convention, even though the Constitution does not name them in this form.",
        },
        {
            "concept": "Summoning authority",
            "question": "Who formally summons a session of Parliament?",
            "options": [
                "The President acting on the advice of the government",
                "The Lok Sabha Speaker acting independently",
                "The Rajya Sabha Chairperson after consulting party whips",
                "The Election Commission before each legislative agenda",
            ],
            "correct_answer": "The President acting on the advice of the government",
            "explanation": "Sessions are formally summoned by the President, but the advice comes from the elected government in a parliamentary system.",
        },
        {
            "concept": "Constitutional gap",
            "question": "What constitutional limit applies between two sessions of Parliament?",
            "options": [
                "Not more than six months should pass between two sessions",
                "Exactly ninety days must separate every session",
                "Parliament must meet at least once every calendar month",
                "A session can be delayed indefinitely during ordinary times",
            ],
            "correct_answer": "Not more than six months should pass between two sessions",
            "explanation": "The Constitution requires that the gap between two sessions must not exceed six months.",
        },
        {
            "concept": "Accountability tools",
            "question": "Why are Question Hour, debates, and motions important during parliamentary sessions?",
            "options": [
                "They make sessions central to executive accountability",
                "They permanently replace judicial review during the session",
                "They allow the Rajya Sabha to convert every bill into a Money Bill",
                "They suspend all committee scrutiny until the session ends",
            ],
            "correct_answer": "They make sessions central to executive accountability",
            "explanation": "These tools allow members to question ministers, debate policy, and scrutinize government actions in practice.",
        },
        {
            "concept": "Exam value",
            "question": "Why are parliamentary sessions important for UPSC-style Polity preparation?",
            "options": [
                "They connect static institutions with real legislative functioning and oversight",
                "They matter only for ceremonial presidential powers",
                "They are relevant only to state legislative councils",
                "They are mainly about judicial appointments rather than lawmaking",
            ],
            "correct_answer": "They connect static institutions with real legislative functioning and oversight",
            "explanation": "This topic helps link formal institutions with procedures like legislative business, accountability, and the parliamentary calendar.",
        },
    ],
    "revolt of 1857": [
        {
            "concept": "Trigger and causes",
            "question": "Which statement best captures the causes of the Revolt of 1857?",
            "options": [
                "Immediate military grievances acted as the trigger, but deeper political and economic causes already existed",
                "It arose only from one military grievance and had no wider political background",
                "It was purely a peasant tax revolt with no sepoy involvement",
                "It began as a constitutional reform conference led entirely by loyal princely elites",
            ],
            "correct_answer": "Immediate military grievances acted as the trigger, but deeper political and economic causes already existed",
            "explanation": "UPSC often distinguishes between the immediate trigger and the broader structural causes behind the uprising.",
        },
        {
            "concept": "Social base",
            "question": "Who participated in the Revolt of 1857 across different regions?",
            "options": [
                "Sepoys, dispossessed rulers, zamindars, peasants, and townspeople",
                "Only European officers dismissed by the Company",
                "Only tribal communities from southern India",
                "Only merchants from the presidency towns acting without military support",
            ],
            "correct_answer": "Sepoys, dispossessed rulers, zamindars, peasants, and townspeople",
            "explanation": "Participation varied regionally, but the revolt drew support from more than just sepoys.",
        },
        {
            "concept": "Symbolic centre",
            "question": "Why did Delhi become a symbolic centre of the Revolt of 1857?",
            "options": [
                "Bahadur Shah II was declared the leader of the revolt there",
                "It was the first region where the British Crown had already taken direct control",
                "It housed the permanent headquarters of the Indian National Congress",
                "It became the centre because the revolt was led entirely by the Bengal zamindars from there",
            ],
            "correct_answer": "Bahadur Shah II was declared the leader of the revolt there",
            "explanation": "Delhi gave the uprising a symbolic Mughal centre, even though its spread and leadership remained regionally varied.",
        },
        {
            "concept": "Regional limits",
            "question": "Which statement best describes the regional spread of the Revolt of 1857?",
            "options": [
                "It was strong in north and central India but weak or absent in many southern and eastern areas",
                "It spread with equal intensity across every province of British India",
                "It remained confined only to the Bombay Presidency",
                "It was strongest in the deep south and barely touched north India",
            ],
            "correct_answer": "It was strong in north and central India but weak or absent in many southern and eastern areas",
            "explanation": "Its uneven geography is a recurring exam theme when discussing the limits of the uprising.",
        },
        {
            "concept": "Aftermath",
            "question": "What major administrative change followed the suppression of the Revolt of 1857?",
            "options": [
                "The British Crown took direct control from the East India Company in 1858",
                "The East India Company was restored with wider territorial powers in 1859",
                "Provincial self-government replaced British rule immediately after the revolt",
                "The revolt ended with the Mughal Empire regaining full sovereignty over India",
            ],
            "correct_answer": "The British Crown took direct control from the East India Company in 1858",
            "explanation": "One of the most important consequences of the revolt was the transfer of authority from the Company to the Crown.",
        },
    ],
    "plate tectonics": [
        {
            "concept": "Basic idea",
            "question": "What is the central claim of plate tectonics?",
            "options": [
                "The Earth's lithosphere is divided into moving plates that interact at their boundaries",
                "The Earth's crust is fixed permanently in one rigid shell",
                "Only oceans move while continents remain completely stationary",
                "Volcanoes form independently of plate movement or boundaries",
            ],
            "correct_answer": "The Earth's lithosphere is divided into moving plates that interact at their boundaries",
            "explanation": "Plate tectonics explains Earth processes through the motion and interaction of lithospheric plates.",
        },
        {
            "concept": "Asthenosphere",
            "question": "Lithospheric plates move over which layer?",
            "options": [
                "The semi-fluid asthenosphere",
                "The inner core directly",
                "The atmosphere above the crust",
                "A fixed granite shell with no internal movement",
            ],
            "correct_answer": "The semi-fluid asthenosphere",
            "explanation": "The theory explains plate motion through lithospheric movement over the weaker asthenosphere.",
        },
        {
            "concept": "Boundary types",
            "question": "Which set correctly lists the main plate boundary types?",
            "options": [
                "Convergent, divergent, and transform boundaries",
                "Continental, tropical, and equatorial boundaries",
                "Volcanic, sedimentary, and igneous boundaries",
                "Mountain, plateau, and plain boundaries",
            ],
            "correct_answer": "Convergent, divergent, and transform boundaries",
            "explanation": "These three boundary types explain different tectonic processes, landforms, and hazards.",
        },
        {
            "concept": "Landforms",
            "question": "Plate interactions help explain the formation of which features?",
            "options": [
                "Fold mountains, ocean trenches, and mid-ocean ridges",
                "Only river meanders and floodplains",
                "Only monsoon winds and pressure belts",
                "Desert dunes formed without any internal Earth process",
            ],
            "correct_answer": "Fold mountains, ocean trenches, and mid-ocean ridges",
            "explanation": "Different plate boundaries generate distinct tectonic landforms and geophysical activity.",
        },
        {
            "concept": "Importance for India",
            "question": "Why is plate tectonics important for understanding India?",
            "options": [
                "It helps explain the Himalayas, earthquakes, and India's tectonic setting",
                "It is relevant only to ocean floors outside South Asia",
                "It explains climate zones without reference to Earth structure",
                "It replaces the need to study earthquakes and volcano belts separately",
            ],
            "correct_answer": "It helps explain the Himalayas, earthquakes, and India's tectonic setting",
            "explanation": "UPSC often links plate tectonics to mountain building, seismicity, and the Indian plate's interaction with Eurasia.",
        },
    ],
}


EXPLANATION_SYSTEM_PROMPT = """
You are Adhyantra, an exam-aware tutor for the selected exam and study subject.
Return valid JSON only.
Use the provided local knowledge-base context when it exists.
If no context is available, still explain the topic from general subject knowledge.
Teach like a strong exam tutor, not like a summary tool.
If local notes are present, rely on them strongly and organize them like a lesson.
The explanation should feel like guided teaching:
1. begin with a beginner-friendly meaning
2. go deeper into its structure, working, and significance
3. show how the exam frames the topic in prelims and mains
4. highlight traps, comparisons, and quick recall aids
The JSON must contain:
- topic: string
- simple_explanation: string (2 to 3 sentences)
- detailed_explanation: string (at least 3 short teaching paragraphs, clearly more detailed than the simple explanation)
- key_points: array of 4 to 7 short strings
- examples: array of 3 to 5 exam-oriented examples or ways the concept appears in questions
- exam_relevance: string
- common_traps: array of 3 to 5 short strings
- memory_hooks: array of 3 to 5 short strings
- practice_questions: array of 5 to 10 guided short questions, moving from basic recall to application and comparison
""".strip()


DOUBT_SYSTEM_PROMPT = """
You are Adhyantra, an exam-aware tutor for the selected exam and study subject.
Return valid JSON only.
Answer the student's exact doubt like a patient, exam-smart tutor.
Treat the typed student doubt as the primary query.
Use the selected topic, optional grounding context, and local knowledge-base context only when they help answer that doubt.
If the selected topic or optional grounding does not match the doubt, say that briefly in the correction field and answer the doubt anyway.
Do not sound like a retrieval system and do not simply restate the topic summary.
Start with a short direct answer in 1 to 2 sentences that addresses the exact doubt.
Then explain why that answer is correct in 2 to 4 sentences.
Add one related concept that helps the student connect the idea, one correction or misconception fix, one practical exam tip, one short follow-up check question, and one short what-to-remember anchor.
If a misconception signal is provided, use it to make the correction and common confusion more helpful, but stay tentative.
Do not claim certainty about the student's misconception. Phrases like "a possible confusion here" or "a likely confusion here" are safer than pretending you know exactly what the student believes.
Use local knowledge-base context strongly when it exists, but synthesize it instead of copying it.
If context is missing, still answer from general subject knowledge.
Keep the tone clear, conversational, exam-oriented, and concise.
Mention the most relevant article, institution, principle, event, or exam distinction when useful.
If the doubt seems outside the usual syllabus, say that clearly and give the closest useful framing.
The JSON must contain:
- direct_answer: string
- explanation: string
- related_concept: string
- correction: string
- common_confusion: string
- what_to_remember: string
- exam_tip: string
- follow_up_prompt: string
""".strip()


QUIZ_SYSTEM_PROMPT = """
You are Adhyantra, an exam-aware tutor for the selected exam and study subject.
Return valid JSON only.
Create objective MCQ revision questions for the given topic and difficulty.
Use local knowledge-base context strongly when available.
Every question must feel like a realistic exam-style revision MCQ.
All four options must stay inside the same topic and the same conceptual area.
Wrong options must be plausible distractors based on common exam confusions, such as:
- wrong article, timeline, principle, formula, region, or classification
- wrong institution or appointing authority
- reversed relationship between closely linked ideas
- incorrect scope, limitation, enforceability, cause, or sequence
- confusion between closely related syllabus concepts
Never use absurd, jokey, dismissive, or obviously irrelevant distractors.
Never write options such as:
- no connection with the Constitution
- relevant only for geography questions
- can never appear in prelims or mains
Each question must have exactly one correct answer and three plausible topic-related distractors.
The JSON must contain:
- topic: string
- difficulty: string
- questions: array
Each question must contain:
- concept: string
- question: string
- options: array of 4 strings
- correct_answer: string
- explanation: string
""".strip()


def _normalize_explanation_depth(explanation_depth: str | None) -> str:
    normalized = str(explanation_depth or "standard").strip().lower()
    if normalized not in {"foundational", "standard", "advanced"}:
        return "standard"
    return normalized


def _normalize_teaching_mode(teaching_mode: str | None) -> str:
    normalized = str(teaching_mode or "concept_overview").strip().lower()
    if normalized not in {"concept_overview", "step_by_step", "example_driven", "exam_focused"}:
        return "concept_overview"
    return normalized


def _normalize_teaching_support(teaching_support: str | None) -> str:
    normalized = str(teaching_support or "balanced").strip().lower()
    if normalized not in {"supportive", "balanced", "stretch"}:
        return "balanced"
    return normalized


def _normalize_teaching_pacing(teaching_pacing: str | None) -> str:
    normalized = str(teaching_pacing or "balanced").strip().lower()
    if normalized not in {"gentle", "balanced", "accelerated"}:
        return "balanced"
    return normalized


def _normalize_conceptual_density(conceptual_density: str | None) -> str:
    normalized = str(conceptual_density or "medium").strip().lower()
    if normalized not in {"low", "medium", "high"}:
        return "medium"
    return normalized


def _normalize_lesson_mode(lesson_mode: str | None) -> str:
    normalized = str(lesson_mode or "lecture_outline").strip().lower()
    if normalized not in {
        "lecture_outline",
        "mini_lesson",
        "revision_lesson",
        "crash_course",
        "video_lecture",
        "revision_video",
        "crash_course_video",
    }:
        return "lecture_outline"
    return normalized


def _normalize_quiz_mode(quiz_mode: str | None) -> str:
    normalized = str(quiz_mode or "test").strip().lower()
    if normalized not in {"practice", "test", "revision", "weak_area_drill"}:
        return "test"
    return normalized


class AIService:
    def __init__(self, settings: Settings | None = None, provider: AIProvider | None = None) -> None:
        self.settings = settings or get_settings()
        self._provider_unavailable_reasons: list[str] = []
        self.provider = provider or self._build_provider()
        self.mock_fallback_allowed = self.settings.mock_ai_runtime_allowed
        self.mock_mode = self.provider is None and self.mock_fallback_allowed
        self.provider_chain = list(self.settings.effective_ai_provider_chain)
        self._random = Random(7)

    def explain_topic(
        self,
        topic: str,
        context: str,
        explanation_depth: str = "standard",
        teaching_mode: str = "concept_overview",
        teaching_support: str = "balanced",
        teaching_pacing: str = "balanced",
        conceptual_density: str = "medium",
        teaching_profile_note: str | None = None,
        lesson_mode: str | None = None,
    ) -> dict:
        normalized_explanation_depth = _normalize_explanation_depth(explanation_depth)
        normalized_teaching_mode = _normalize_teaching_mode(teaching_mode)
        normalized_teaching_support = _normalize_teaching_support(teaching_support)
        normalized_teaching_pacing = _normalize_teaching_pacing(teaching_pacing)
        normalized_conceptual_density = _normalize_conceptual_density(conceptual_density)
        normalized_lesson_mode = _normalize_lesson_mode(lesson_mode)
        fallback = (
            self.default_explanation_response(
                topic=topic,
                context=context,
                explanation_depth=normalized_explanation_depth,
                teaching_mode=normalized_teaching_mode,
                teaching_support=normalized_teaching_support,
                teaching_pacing=normalized_teaching_pacing,
                conceptual_density=normalized_conceptual_density,
                teaching_profile_note=teaching_profile_note,
            )
            if self.mock_fallback_allowed
            else None
        )
        if self.provider is None:
            if fallback is not None:
                return fallback
            raise self._service_unavailable_error()

        depth_instruction = self._explanation_depth_instruction(normalized_explanation_depth)
        teaching_mode_instruction = self._teaching_mode_instruction(normalized_teaching_mode)
        teaching_shape_instruction = self._teaching_shape_instruction(
            normalized_teaching_support,
            normalized_teaching_pacing,
            normalized_conceptual_density,
        )
        lesson_mode_instruction = self._lesson_mode_instruction(normalized_lesson_mode)
        profile_summary = (teaching_profile_note or "").strip() or "Use the default exam teaching profile."
        user_prompt = (
            f"Topic: {topic}\n"
            f"Lesson mode: {normalized_lesson_mode}\n"
            f"Requested explanation depth: {normalized_explanation_depth}\n"
            f"Teaching mode: {normalized_teaching_mode}\n"
            f"Teaching support: {normalized_teaching_support}\n"
            f"Teaching pacing: {normalized_teaching_pacing}\n"
            f"Conceptual density: {normalized_conceptual_density}\n"
            f"Exam teaching profile: {profile_summary}\n"
            f"Local syllabus context:\n{context.strip() or 'No local knowledge-base context was found.'}\n\n"
            f"{depth_instruction} {teaching_mode_instruction} {teaching_shape_instruction} {lesson_mode_instruction}"
        )
        response = self._call_with_fallback(
            system_prompt=EXPLANATION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            fallback=fallback,
            validator=lambda payload: self._validate_explanation_payload(payload, topic=topic),
        )
        response.update(self._explanation_metadata(generation_mode=response.get("generation_mode"), context=context))
        return response

    def solve_doubt(
        self,
        topic: str | None,
        question: str,
        context: str,
        subject: str | None = None,
        selected_topic: str | None = None,
        grounding_context: str | None = None,
        misconception_signal: str = "none",
        misconception_reason: str | None = None,
        what_to_remember: str | None = None,
        explanation_depth: str = "standard",
        teaching_mode: str = "concept_overview",
        teaching_support: str = "balanced",
        teaching_pacing: str = "balanced",
        conceptual_density: str = "medium",
    ) -> dict:
        resolved_topic = topic or "General subject topic"
        normalized_selected_topic = str(selected_topic or "").strip() or None
        normalized_grounding_context = str(grounding_context or "").strip() or None
        normalized_misconception_signal = str(misconception_signal or "none").strip() or "none"
        normalized_misconception_reason = str(misconception_reason or "").strip() or None
        normalized_what_to_remember = str(what_to_remember or "").strip() or None
        normalized_explanation_depth = _normalize_explanation_depth(explanation_depth)
        normalized_teaching_mode = _normalize_teaching_mode(teaching_mode)
        normalized_teaching_support = _normalize_teaching_support(teaching_support)
        normalized_teaching_pacing = _normalize_teaching_pacing(teaching_pacing)
        normalized_conceptual_density = _normalize_conceptual_density(conceptual_density)
        subject_label = str(subject or "general subject").replace("_", " ").title()
        fallback = (
            self.default_doubt_response(
                topic=resolved_topic,
                question=question,
                context=context,
                subject=subject,
                selected_topic=normalized_selected_topic,
                grounding_context=normalized_grounding_context,
                misconception_signal=normalized_misconception_signal,
                misconception_reason=normalized_misconception_reason,
                what_to_remember=normalized_what_to_remember,
                explanation_depth=normalized_explanation_depth,
                teaching_mode=normalized_teaching_mode,
                teaching_support=normalized_teaching_support,
                teaching_pacing=normalized_teaching_pacing,
                conceptual_density=normalized_conceptual_density,
            )
            if self.mock_fallback_allowed
            else None
        )
        if self.provider is None:
            if fallback is not None:
                return fallback
            raise self._service_unavailable_error()

        depth_instruction = self._explanation_depth_instruction(normalized_explanation_depth)
        teaching_mode_instruction = self._teaching_mode_instruction(normalized_teaching_mode)
        teaching_shape_instruction = self._teaching_shape_instruction(
            normalized_teaching_support,
            normalized_teaching_pacing,
            normalized_conceptual_density,
        )
        doubt_mode_instruction = self._doubt_mode_instruction(
            question=question,
            misconception_signal=normalized_misconception_signal,
            teaching_mode=normalized_teaching_mode,
            explanation_depth=normalized_explanation_depth,
        )
        user_prompt = (
            f"Subject: {subject_label}\n"
            f"Selected topic in the UI: {normalized_selected_topic or 'None'}\n"
            f"Resolved topic grounding: {resolved_topic}\n"
            f"Student doubt: {question}\n"
            f"Optional student grounding: {normalized_grounding_context or 'None'}\n"
            f"Misconception signal: {normalized_misconception_signal}\n"
            f"Misconception note: {normalized_misconception_reason or 'None'}\n"
            f"What to remember anchor: {normalized_what_to_remember or 'None'}\n"
            f"Requested explanation depth: {normalized_explanation_depth}\n"
            f"Teaching mode: {normalized_teaching_mode}\n"
            f"Teaching support: {normalized_teaching_support}\n"
            f"Teaching pacing: {normalized_teaching_pacing}\n"
            f"Conceptual density: {normalized_conceptual_density}\n"
            f"Local syllabus context:\n{context.strip() or 'No local knowledge-base context was found.'}\n\n"
            f"{depth_instruction} {teaching_mode_instruction} {teaching_shape_instruction} "
            f"{doubt_mode_instruction} "
            "Primary rule: answer the student's typed doubt first. Use the selected topic and optional grounding only when they help. "
            "If they conflict with the doubt, correct the mismatch briefly and still answer the doubt. Keep the response tutor-like, not retrieval-like."
        )
        response = self._call_with_fallback(
            system_prompt=DOUBT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            fallback=fallback,
            validator=self._validate_doubt_payload,
        )
        response = self._shape_doubt_response(
            response,
            topic=resolved_topic,
            explanation_depth=normalized_explanation_depth,
            teaching_mode=normalized_teaching_mode,
            teaching_support=normalized_teaching_support,
            teaching_pacing=normalized_teaching_pacing,
            conceptual_density=normalized_conceptual_density,
        )
        response.update(self._doubt_metadata(generation_mode=response.get("generation_mode"), context=context))
        return response

    def generate_quiz(
        self,
        topic: str,
        difficulty: str,
        question_count: int,
        context: str,
        quiz_mode: str = "test",
        focus_concepts: List[str] | None = None,
        quiz_profile_note: str | None = None,
    ) -> dict:
        fallback = (
            self.default_quiz_response(
                topic=topic,
                difficulty=difficulty,
                question_count=question_count,
                context=context,
                quiz_mode=quiz_mode,
                focus_concepts=focus_concepts,
                quiz_profile_note=quiz_profile_note,
            )
            if self.mock_fallback_allowed
            else None
        )
        if self.provider is None:
            if fallback is not None:
                return fallback
            raise self._service_unavailable_error()

        focus_summary = ", ".join(focus_concepts or []) or "None specified"
        normalized_quiz_mode = _normalize_quiz_mode(quiz_mode)
        quiz_mode_instruction = self._quiz_mode_instruction(
            quiz_mode=normalized_quiz_mode,
            difficulty=difficulty,
            focus_concepts=focus_concepts,
        )
        profile_summary = (quiz_profile_note or "").strip() or "Use the default exam quiz profile."
        user_prompt = (
            f"Topic: {topic}\n"
            f"Difficulty: {difficulty}\n"
            f"Question count: {question_count}\n"
            f"Quiz mode: {normalized_quiz_mode}\n"
            f"Focus concepts: {focus_summary}\n"
            f"Exam quiz profile: {profile_summary}\n"
            f"Local syllabus context:\n{context.strip() or 'No local knowledge-base context was found.'}\n\n"
            "Generate subject-grounded MCQs for the selected study subject. Treat the subject, chapter, and topic in the local context as authoritative, and do not mix in concepts, institutions, articles, or examples from a different subject unless the local context explicitly does so. "
            f"{quiz_mode_instruction} Keep wrong options in the same topic domain, make them plausible but distinct, and avoid reusing the same distractor framing across nearby questions. Never expose answer keys outside correct_answer in the private provider JSON contract."
        )
        response = self._call_with_fallback(
            system_prompt=QUIZ_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            fallback=fallback,
            validator=lambda payload: self._validate_quiz_payload(
                payload,
                topic=topic,
                difficulty=difficulty,
                question_count=question_count,
            ),
        )
        return response

    def _build_provider(self) -> AIProvider | None:
        providers: list[AIProvider] = []
        configured_live_chain: list[str] = []
        unavailable_reasons: list[str] = []
        for provider_name in self.settings.effective_ai_provider_chain:
            if provider_name == "mock":
                continue
            configured_live_chain.append(provider_name)
            if provider_name in AI_TESTING_ONLY_PROVIDER_NAMES and self.settings.deployed_mode:
                logger.warning(
                    "AI provider '%s' is testing-only and disabled in deployed environments. Skipping provider.",
                    provider_name,
                )
                unavailable_reasons.append(f"{provider_name}: testing-only provider disabled in deployed environment")
                continue
            provider = self._build_single_provider(provider_name)
            if provider is not None:
                providers.append(provider)
            else:
                unavailable_reasons.append(f"{provider_name}: {self._provider_unavailable_reason(provider_name)}")

        self._provider_unavailable_reasons = unavailable_reasons

        if not providers:
            if self.settings.mock_ai_runtime_allowed:
                logger.info("No configured live AI provider is available. Falling back to explicit mock mode.")
            else:
                logger.warning("No configured live AI provider is available and production mock fallback is disabled.")
            return None

        return ProviderRouter(
            providers=providers,
            configured_provider_chain=configured_live_chain,
            unavailable_provider_reasons=unavailable_reasons,
        )

    def _build_single_provider(self, provider_name: str) -> AIProvider | None:
        api_key = self.settings.ai_provider_api_key(provider_name).strip()
        model = self.settings.ai_provider_model(provider_name).strip()
        base_url = self.settings.ai_provider_base_url(provider_name).strip()
        timeout_seconds = float(self.settings.effective_ai_timeout_seconds)
        if not api_key or not model:
            logger.info("AI provider '%s' is missing API key or model. Skipping provider.", provider_name)
            return None
        if provider_name == "gemini":
            return GeminiProvider(api_key=api_key, model=model, base_url=base_url, timeout_seconds=timeout_seconds)
        if provider_name == "groq":
            return GroqProvider(api_key=api_key, model=model, base_url=base_url, timeout_seconds=timeout_seconds)
        if provider_name == "mistral":
            return MistralProvider(api_key=api_key, model=model, base_url=base_url, timeout_seconds=timeout_seconds)
        if provider_name == "openai":
            return OpenAIProvider(api_key=api_key, model=model, base_url=base_url, timeout_seconds=timeout_seconds)
        logger.warning("Unsupported AI provider '%s'. Skipping provider.", provider_name)
        return None

    def _provider_unavailable_reason(self, provider_name: str) -> str:
        if provider_name in AI_TESTING_ONLY_PROVIDER_NAMES and self.settings.deployed_mode:
            return "testing-only provider disabled in deployed environment"
        api_key = self.settings.ai_provider_api_key(provider_name).strip()
        model = self.settings.ai_provider_model(provider_name).strip()
        if not api_key and not model:
            return "missing API key and model"
        if not api_key:
            return "missing API key"
        if not model:
            return "missing model"
        return "unsupported or unavailable provider configuration"

    def _startup_provider_fallback_reason(self) -> str | None:
        return self._safe_provider_fallback_reason("; ".join(self._provider_unavailable_reasons)) if self._provider_unavailable_reasons else None

    def _safe_provider_fallback_reason(self, reason: object | None) -> str | None:
        text = str(reason or "").strip()
        if not text:
            return None
        secret_patterns = (
            r"(?i)(key=)[^\s;&]+",
            r"(?i)(api[_-]?key\s*[:=]\s*)[^\s;&,]+",
            r"(?i)(token\s*[:=]\s*)[^\s;&,]+",
            r"(?i)(password\s*[:=]\s*)[^\s;&,]+",
            r"(?i)(secret\s*[:=]\s*)[^\s;&,]+",
            r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+",
        )
        for pattern in secret_patterns:
            text = re.sub(pattern, r"\1[redacted]", text)
        text = re.sub(r"\s+", " ", text)
        return text[:700] + "..." if len(text) > 700 else text

    def _metadata_provider_chain(self, provider_chain: list[str] | None, *, include_mock_fallback: bool = False) -> list[str]:
        raw_chain = provider_chain or list(self.settings.effective_ai_provider_chain)
        cleaned_chain: list[str] = []
        for provider_name in raw_chain:
            normalized_provider = str(provider_name or "").strip()
            if normalized_provider and normalized_provider not in cleaned_chain:
                cleaned_chain.append(normalized_provider)
        if include_mock_fallback and "mock" not in cleaned_chain:
            cleaned_chain.append("mock")
        return cleaned_chain or ["mock"]

    def _normalize_runtime_metadata(self, metadata: dict[str, object] | None = None) -> dict[str, object]:
        metadata = metadata or {}
        provider = self.provider
        provider_name = str(
            metadata.get("provider_name")
            or getattr(provider, "last_provider_name", "")
            or getattr(provider, "provider_name", "")
            or ""
        ).strip()
        if provider_name == "router":
            provider_name = ""
        if not provider_name:
            provider_name = str(getattr(provider, "provider_name", "") or "live_ai").strip()
        model_name = str(
            metadata.get("model_name")
            or getattr(provider, "last_model_name", "")
            or getattr(provider, "model_name", "")
            or ""
        ).strip()
        attempted = metadata.get("attempted_provider_chain")
        if not isinstance(attempted, list):
            attempted = getattr(provider, "last_attempted_provider_names", None)
        attempted_chain = [str(item) for item in attempted] if isinstance(attempted, list) else list(self.settings.live_ai_provider_chain)
        if "provider_fallback_reason" in metadata:
            fallback_reason = metadata.get("provider_fallback_reason")
        else:
            fallback_reason = getattr(provider, "last_fallback_reason", None)
        return {
            "provider_name": provider_name,
            "model_name": model_name,
            "attempted_provider_chain": self._metadata_provider_chain(attempted_chain),
            "provider_fallback_used": bool(metadata.get("provider_fallback_used", getattr(provider, "last_fallback_used", False))),
            "provider_fallback_reason": self._safe_provider_fallback_reason(fallback_reason),
        }

    def _provider_runtime_metadata(self) -> dict[str, object]:
        return self._normalize_runtime_metadata()

    def _extract_payload_provider_metadata(self, payload: dict) -> dict[str, object] | None:
        metadata = payload.pop(PROVIDER_RUNTIME_METADATA_KEY, None)
        if not isinstance(metadata, dict):
            return None
        return self._normalize_runtime_metadata(metadata)

    def _exception_provider_metadata(self, exc: AIProviderError) -> dict[str, object] | None:
        metadata = getattr(exc, "provider_metadata", None)
        if not isinstance(metadata, dict):
            return None
        return self._normalize_runtime_metadata(metadata)

    def _service_unavailable_error(self, metadata: dict[str, object] | None = None) -> AIServiceUnavailableError:
        attempted = (metadata or {}).get("attempted_provider_chain")
        attempted_chain = [str(item) for item in attempted] if isinstance(attempted, list) else list(self.settings.live_ai_provider_chain)
        return AIServiceUnavailableError(attempted_provider_chain=attempted_chain)

    def _live_generation_metadata(
        self,
        *,
        provider_name: str | None = None,
        model_name: str | None = None,
        attempted_provider_chain: list[str] | None = None,
        provider_fallback_used: bool = False,
        provider_fallback_reason: str | None = None,
    ) -> dict[str, object]:
        resolved_provider = str(provider_name or "live_ai").strip() or "live_ai"
        provider_label = resolved_provider.replace("_", " ").title()
        resolved_model = str(model_name or "").strip() or None
        safe_fallback_reason = self._safe_provider_fallback_reason(provider_fallback_reason)
        model_note = f" using model {resolved_model}" if resolved_model else ""
        note = f"Live AI used: {provider_label}{model_note}."
        if provider_fallback_used:
            note = f"{note} Provider fallback occurred before this response succeeded."
        return {
            "generation_mode": resolved_provider,
            "generation_note": note,
            "generation_provider": resolved_provider,
            "generation_model": resolved_model,
            "provider_chain": self._metadata_provider_chain(attempted_provider_chain),
            "provider_fallback_used": provider_fallback_used,
            "provider_fallback_reason": safe_fallback_reason,
        }

    def _mock_generation_metadata(
        self,
        *,
        provider_fallback_reason: str | None = None,
        attempted_provider_chain: list[str] | None = None,
    ) -> dict[str, object]:
        safe_fallback_reason = self._safe_provider_fallback_reason(provider_fallback_reason)
        fallback_used = bool(safe_fallback_reason)
        note = "Generated by Adhyantra's local mock fallback, not a live AI call."
        if fallback_used:
            note = "Generated by Adhyantra's local mock fallback after live AI was unavailable or failed; not a live AI call."
        return {
            "generation_mode": "mock",
            "generation_note": note,
            "generation_provider": "mock",
            "generation_model": None,
            "provider_chain": self._metadata_provider_chain(attempted_provider_chain, include_mock_fallback=True),
            "provider_fallback_used": fallback_used,
            "provider_fallback_reason": safe_fallback_reason,
        }

    def _normalized_generation_mode(self, generation_mode: str | None) -> str:
        return "mock" if generation_mode == "mock" else "live"

    def _context_status(self, context: str) -> str:
        return "knowledge_base_context" if context.strip() else "no_knowledge_base_context"

    def _response_provenance(self, *, generation_mode: str | None, context: str) -> str:
        normalized_generation_mode = self._normalized_generation_mode(generation_mode)
        context_status = self._context_status(context)
        if normalized_generation_mode == "live":
            return "live_ai_grounded" if context_status == "knowledge_base_context" else "live_ai_general"
        return "mock_context_summary" if context_status == "knowledge_base_context" else "mock_general_fallback"

    def _explanation_metadata(self, *, generation_mode: str | None, context: str) -> dict[str, str]:
        return {
            "context_status": self._context_status(context),
            "response_provenance": self._response_provenance(generation_mode=generation_mode, context=context),
        }

    def _doubt_metadata(self, *, generation_mode: str | None, context: str) -> dict[str, str]:
        context_status = self._context_status(context)
        response_provenance = self._response_provenance(generation_mode=generation_mode, context=context)
        return {
            "context_status": context_status,
            "response_provenance": response_provenance,
            "answer_mode": context_status,
            "answer_source": response_provenance,
        }

    def default_explanation_response(
        self,
        topic: str,
        context: str,
        explanation_depth: str = "standard",
        teaching_mode: str = "concept_overview",
        teaching_support: str = "balanced",
        teaching_pacing: str = "balanced",
        conceptual_density: str = "medium",
        teaching_profile_note: str | None = None,
    ) -> dict:
        normalized_explanation_depth = _normalize_explanation_depth(explanation_depth)
        normalized_teaching_mode = _normalize_teaching_mode(teaching_mode)
        normalized_teaching_support = _normalize_teaching_support(teaching_support)
        normalized_teaching_pacing = _normalize_teaching_pacing(teaching_pacing)
        normalized_conceptual_density = _normalize_conceptual_density(conceptual_density)
        response = self._validate_explanation_payload(
            self._mock_explanation(
                topic=topic,
                context=context,
                explanation_depth=normalized_explanation_depth,
                teaching_mode=normalized_teaching_mode,
                teaching_support=normalized_teaching_support,
                teaching_pacing=normalized_teaching_pacing,
                conceptual_density=normalized_conceptual_density,
                teaching_profile_note=teaching_profile_note,
            ),
            topic=topic,
        )
        response.update(self._mock_generation_metadata(provider_fallback_reason=self._startup_provider_fallback_reason()))
        response.update(self._explanation_metadata(generation_mode=response.get("generation_mode"), context=context))
        return response

    def default_doubt_response(
        self,
        topic: str,
        question: str,
        context: str,
        subject: str | None = None,
        selected_topic: str | None = None,
        grounding_context: str | None = None,
        misconception_signal: str = "none",
        misconception_reason: str | None = None,
        what_to_remember: str | None = None,
        explanation_depth: str = "standard",
        teaching_mode: str = "concept_overview",
        teaching_support: str = "balanced",
        teaching_pacing: str = "balanced",
        conceptual_density: str = "medium",
    ) -> dict:
        response = self._validate_doubt_payload(
            self._mock_doubt(
                topic=topic,
                question=question,
                context=context,
                subject=subject,
                selected_topic=selected_topic,
                grounding_context=grounding_context,
                misconception_signal=misconception_signal,
                misconception_reason=misconception_reason,
                what_to_remember=what_to_remember,
            )
        )
        response = self._shape_doubt_response(
            response,
            topic=topic,
            explanation_depth=explanation_depth,
            teaching_mode=teaching_mode,
            teaching_support=teaching_support,
            teaching_pacing=teaching_pacing,
            conceptual_density=conceptual_density,
        )
        response.update(self._mock_generation_metadata(provider_fallback_reason=self._startup_provider_fallback_reason()))
        response.update(self._doubt_metadata(generation_mode=response.get("generation_mode"), context=context))
        return response

    def default_quiz_response(
        self,
        topic: str,
        difficulty: str,
        question_count: int,
        context: str,
        quiz_mode: str = "test",
        focus_concepts: List[str] | None = None,
        quiz_profile_note: str | None = None,
    ) -> dict:
        response = self._validate_quiz_payload(
            self._mock_quiz(
                topic=topic,
                difficulty=difficulty,
                question_count=question_count,
                context=context,
                quiz_mode=quiz_mode,
                focus_concepts=focus_concepts,
                quiz_profile_note=quiz_profile_note,
            ),
            topic=topic,
            difficulty=difficulty,
            question_count=question_count,
        )
        response.update(self._mock_generation_metadata(provider_fallback_reason=self._startup_provider_fallback_reason()))
        return response

    def _call_with_fallback(self, *, system_prompt: str, user_prompt: str, fallback: dict | None, validator) -> dict:
        runtime_metadata: dict[str, object] | None = None
        try:
            payload = self.provider.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
            runtime_metadata = self._extract_payload_provider_metadata(payload)
            response = validator(payload)
            metadata = runtime_metadata or self._provider_runtime_metadata()
            response.update(
                self._live_generation_metadata(
                    provider_name=str(metadata["provider_name"]),
                    model_name=str(metadata["model_name"] or ""),
                    attempted_provider_chain=list(metadata["attempted_provider_chain"]),
                    provider_fallback_used=bool(metadata["provider_fallback_used"]),
                    provider_fallback_reason=metadata["provider_fallback_reason"],
                )
            )
            return response
        except AIProviderError as exc:
            metadata = self._exception_provider_metadata(exc) or runtime_metadata or self._provider_runtime_metadata()
            if not self.mock_fallback_allowed or fallback is None:
                logger.warning(
                    "Configured live AI providers failed; returning service unavailable. error_type=%s",
                    type(exc).__name__,
                )
                raise self._service_unavailable_error(metadata) from exc
            logger.warning("AI provider call failed, using mock fallback: %s", self._safe_provider_fallback_reason(exc))
            fallback_response = dict(fallback)
            fallback_reason = str(metadata.get("provider_fallback_reason") or exc)
            fallback_response.update(
                self._mock_generation_metadata(
                    provider_fallback_reason=fallback_reason,
                    attempted_provider_chain=list(metadata["attempted_provider_chain"]),
                )
            )
            return fallback_response
        except (TypeError, ValueError) as exc:
            metadata = runtime_metadata or self._provider_runtime_metadata()
            if not self.mock_fallback_allowed or fallback is None:
                logger.warning(
                    "Configured live AI provider returned an invalid response; returning service unavailable. error_type=%s",
                    type(exc).__name__,
                )
                raise self._service_unavailable_error(metadata) from exc
            logger.warning("AI provider returned invalid JSON shape, using mock fallback: %s", self._safe_provider_fallback_reason(exc))
            fallback_response = dict(fallback)
            fallback_response.update(
                self._mock_generation_metadata(
                    provider_fallback_reason=f"{metadata['provider_name']} returned invalid JSON shape: {exc}",
                    attempted_provider_chain=list(metadata["attempted_provider_chain"]),
                )
            )
            return fallback_response

    def _validate_explanation_payload(self, payload: dict, topic: str) -> dict:
        response = {
            "topic": self._coerce_text(payload.get("topic")) or topic,
            "simple_explanation": self._coerce_text(payload.get("simple_explanation")),
            "detailed_explanation": self._coerce_text(payload.get("detailed_explanation")),
            "key_points": self._coerce_string_list(payload.get("key_points"), limit=7),
            "examples": self._coerce_string_list(payload.get("examples"), limit=5),
            "exam_relevance": self._coerce_text(payload.get("exam_relevance")),
            "common_traps": self._coerce_string_list(payload.get("common_traps"), limit=5),
            "memory_hooks": self._coerce_string_list(payload.get("memory_hooks"), limit=5),
            "practice_questions": self._coerce_string_list(payload.get("practice_questions"), limit=10),
        }
        if (
            not response["simple_explanation"]
            or not response["detailed_explanation"]
            or not response["exam_relevance"]
        ):
            raise ValueError("Explanation response is missing core text fields.")
        if (
            len(response["key_points"]) < 3
            or len(response["examples"]) < 3
            or len(response["common_traps"]) < 3
            or len(response["memory_hooks"]) < 3
            or len(response["practice_questions"]) < 5
        ):
            raise ValueError("Explanation response is missing required teaching lists.")
        if len(response["detailed_explanation"]) <= len(response["simple_explanation"]):
            raise ValueError("Detailed explanation should be richer than the simple explanation.")
        return response

    def _shape_doubt_response(
        self,
        payload: dict,
        *,
        topic: str,
        explanation_depth: str = "standard",
        teaching_mode: str = "concept_overview",
        teaching_support: str = "balanced",
        teaching_pacing: str = "balanced",
        conceptual_density: str = "medium",
    ) -> dict:
        response = dict(payload)
        normalized_explanation_depth = _normalize_explanation_depth(explanation_depth)
        normalized_teaching_mode = _normalize_teaching_mode(teaching_mode)
        normalized_teaching_support = _normalize_teaching_support(teaching_support)
        normalized_teaching_pacing = _normalize_teaching_pacing(teaching_pacing)
        normalized_conceptual_density = _normalize_conceptual_density(conceptual_density)
        topic_label = str(topic or "this topic").strip() or "this topic"

        if normalized_teaching_support == "supportive" or normalized_explanation_depth == "foundational":
            response["direct_answer"] = f"Start with this anchor: {response['direct_answer']}"
            response["explanation"] = f"Take it step by step. {response['explanation']}"
            response["exam_tip"] = f"First secure the main anchor before adding extra detail. {response['exam_tip']}"
            if normalized_teaching_mode == "example_driven":
                response["follow_up_prompt"] = f"Can you give one simple example that makes {topic_label} clearer now?"
            else:
                response["follow_up_prompt"] = (
                    f"Can you restate the main idea behind {topic_label} in one simple line before we add more detail?"
                )
            return response

        if normalized_teaching_support == "stretch" or normalized_explanation_depth == "advanced":
            response["explanation"] = (
                f"{response['explanation']} After that, push yourself to name the sharper distinction, limitation, or trap inside {topic_label}."
            )
            if normalized_teaching_mode == "exam_focused" or normalized_conceptual_density == "high":
                response["exam_tip"] = f"{response['exam_tip']} Push one step further by naming the sharpest distinction or trap."
                response["follow_up_prompt"] = (
                    f"Can you now state the sharpest exam distinction or trap inside {topic_label} in one line?"
                )
            elif normalized_teaching_mode == "example_driven":
                response["follow_up_prompt"] = (
                    f"Can you now give one example or comparison that proves you understand {topic_label}?"
                )
            return response

        if normalized_teaching_mode == "example_driven":
            response["follow_up_prompt"] = f"Can you give one example that makes {topic_label} easier to remember?"
        elif normalized_teaching_mode == "exam_focused":
            response["follow_up_prompt"] = f"Can you now restate {topic_label} in one exam-safe line and add one trap?"
        elif normalized_teaching_pacing == "gentle":
            response["follow_up_prompt"] = f"Can you restate the first anchor behind {topic_label} in one clean line?"
        return response

    def _validate_doubt_payload(self, payload: dict) -> dict:
        response = {
            "direct_answer": self._coerce_text(payload.get("direct_answer")),
            "explanation": self._coerce_text(payload.get("explanation")),
            "related_concept": self._coerce_text(payload.get("related_concept")),
            "correction": self._coerce_text(payload.get("correction")),
            "common_confusion": self._coerce_text(payload.get("common_confusion")),
            "what_to_remember": self._coerce_text(payload.get("what_to_remember")),
            "exam_tip": self._coerce_text(payload.get("exam_tip")),
            "follow_up_prompt": self._coerce_text(payload.get("follow_up_prompt")),
        }
        if not all(response.values()):
            raise ValueError("Doubt response is missing one or more required fields.")
        return response

    def _validate_quiz_payload(self, payload: dict, topic: str, difficulty: str, question_count: int) -> dict:
        raw_questions = payload.get("questions")
        if not isinstance(raw_questions, list):
            raise ValueError("Quiz response is missing questions.")

        questions: List[dict[str, Any]] = []
        for raw_question in raw_questions:
            if not isinstance(raw_question, dict):
                continue
            options = self._coerce_string_list(raw_question.get("options"), limit=4)
            question_text = self._coerce_text(raw_question.get("question"))
            correct_answer = self._coerce_text(raw_question.get("correct_answer"))
            explanation = self._coerce_text(raw_question.get("explanation"))
            concept = self._coerce_text(raw_question.get("concept"))
            if len(options) < 4 or not question_text or not correct_answer or not explanation:
                continue
            options = self._normalize_question_options(
                question_text=question_text,
                options=options,
                correct_answer=correct_answer,
            )
            if len(options) < 4 or correct_answer not in options:
                continue
            if any(self._looks_absurd_option(option) for option in options):
                continue
            question_payload: dict[str, Any] = {
                "question": question_text,
                "options": options,
                "correct_answer": correct_answer,
                "explanation": explanation,
            }
            if concept:
                question_payload["concept"] = concept
            questions.append(question_payload)

        if len(questions) < question_count:
            raise ValueError("Quiz response did not contain enough valid questions.")

        return {
            "topic": self._coerce_text(payload.get("topic")) or topic,
            "difficulty": self._coerce_text(payload.get("difficulty")) or difficulty,
            "questions": questions[:question_count],
        }

    def _coerce_text(self, value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        return text

    def _coerce_string_list(self, value: Any, limit: int) -> List[str]:
        if not isinstance(value, list):
            return []
        items = [self._coerce_text(item) for item in value]
        return [item for item in items if item][:limit]

    def _normalize_question_options(self, question_text: str, options: List[str], correct_answer: str) -> List[str]:
        normalized_options: List[str] = []
        seen: set[str] = set()
        for option in options:
            cleaned_option = self._coerce_text(option)
            if not cleaned_option or cleaned_option in seen:
                continue
            seen.add(cleaned_option)
            normalized_options.append(cleaned_option)

        if correct_answer not in seen:
            if len(normalized_options) >= 4:
                normalized_options[-1] = correct_answer
            else:
                normalized_options.append(correct_answer)

        if len(normalized_options) < 4:
            return normalized_options

        shuffled_options = normalized_options[:4]
        Random(f"{question_text}|{correct_answer}").shuffle(shuffled_options)
        return shuffled_options

    def _pad_list(self, items: List[str], fallback_items: List[str], minimum: int, limit: int) -> List[str]:
        combined = list(items[:limit])
        for fallback_item in fallback_items:
            if len(combined) >= limit:
                break
            if fallback_item and fallback_item not in combined:
                combined.append(fallback_item)
        return combined[: max(minimum, min(limit, len(combined)))]

    def _best_context_line(self, question: str, context: str, topic: str) -> str:
        question_keywords = set(extract_keywords(question, limit=10))
        candidate_lines = (
            clean_bullets(extract_section(context, "Key Points"))
            + extract_section(context, "Simple Explanation")
            + extract_section(context, "Exam Relevance")
        )
        if not candidate_lines:
            context_lines = [line.strip() for line in context.splitlines() if line.strip()]
            candidate_lines = context_lines[2:] if len(context_lines) > 2 else context_lines

        best_line = ""
        best_score = -1
        for line in candidate_lines:
            line_keywords = set(extract_keywords(line, limit=10))
            overlap_score = len(question_keywords & line_keywords)
            length_bonus = 1 if len(line) <= 220 else 0
            score = overlap_score * 10 + length_bonus
            if score > best_score:
                best_score = score
                best_line = line

        return best_line or f"{topic} is important in this subject."

    def _best_context_lines(self, question: str, context: str, topic: str, limit: int = 3) -> List[str]:
        question_keywords = set(extract_keywords(question, limit=10))
        candidate_lines = (
            clean_bullets(extract_section(context, "Key Points"))
            + extract_section(context, "Simple Explanation")
            + extract_section(context, "Exam Relevance")
        )
        if not candidate_lines:
            context_lines = [line.strip() for line in context.splitlines() if line.strip()]
            candidate_lines = context_lines[2:] if len(context_lines) > 2 else context_lines

        scored_lines: List[tuple[int, str]] = []
        seen: set[str] = set()
        for line in candidate_lines:
            normalized_line = line.strip()
            if not normalized_line or normalized_line in seen:
                continue
            seen.add(normalized_line)
            line_keywords = set(extract_keywords(normalized_line, limit=10))
            overlap_score = len(question_keywords & line_keywords)
            length_bonus = 1 if len(normalized_line) <= 220 else 0
            score = overlap_score * 10 + length_bonus
            scored_lines.append((score, normalized_line))

        ranked = [line for score, line in sorted(scored_lines, key=lambda item: (-item[0], item[1])) if score > 0]
        if ranked:
            return ranked[:limit]

        return [self._best_context_line(question=question, context=context, topic=topic)]

    def _question_style(self, question: str) -> str:
        normalized = question.strip().lower()
        if normalized.startswith("why "):
            return "why"
        if normalized.startswith("how "):
            return "how"
        if "difference" in normalized or normalized.startswith("compare ") or normalized.startswith("distinguish "):
            return "compare"
        if normalized.startswith("what "):
            return "what"
        if normalized.startswith("can ") or normalized.startswith("is ") or normalized.startswith("does "):
            return "check"
        return "general"

    def _first_reference(self, question: str, topic: str, context: str) -> str:
        question_refs = self._extract_constitutional_refs(question)
        if question_refs:
            return question_refs[0]
        context_refs = self._extract_constitutional_refs(context)
        if context_refs:
            return context_refs[0]
        return topic

    def _compose_grounded_direct_answer(self, question: str, topic: str, context: str) -> str:
        lines = self._best_context_lines(question=question, context=context, topic=topic, limit=3)
        primary = lines[0] if lines else f"{topic} is important in this subject."
        secondary = lines[1] if len(lines) > 1 else ""
        style = self._question_style(question)
        reference = self._first_reference(question=question, topic=topic, context=context)

        if style == "why":
            if reference.lower().startswith("article "):
                return (
                    f"{reference} matters because it gives a concrete constitutional remedy or protection, not just a symbolic promise. "
                    f"In simple terms, {primary[:1].lower() + primary[1:] if primary else primary}"
                )
            return (
                f"It matters because {primary[:1].lower() + primary[1:] if primary else primary} "
                f"{secondary if secondary else 'That is why the topic has practical constitutional importance.'}"
            ).strip()

        if style == "how":
            return (
                f"It works by linking the core idea to its constitutional mechanism. "
                f"In this case, {primary[:1].lower() + primary[1:] if primary else primary}"
            )

        if style == "compare":
            comparison_hint = secondary or "the real difference usually turns on power, scope, or remedy."
            return (
                f"The key distinction is not just in definition, but in function and constitutional scope. "
                f"For this doubt, {primary[:1].lower() + primary[1:] if primary else primary} {comparison_hint}"
            ).strip()

        if style == "what":
            return f"In simple terms, {primary[:1].lower() + primary[1:] if primary else primary}"

        return (
            f"The short answer is that {primary[:1].lower() + primary[1:] if primary else primary} "
            f"{secondary if secondary else ''}"
        ).strip()

    def _compose_grounded_explanation(self, question: str, topic: str, context: str) -> str:
        lines = self._best_context_lines(question=question, context=context, topic=topic, limit=3)
        primary = lines[0] if lines else f"{topic} is important in this subject."
        secondary = lines[1] if len(lines) > 1 else ""
        tertiary = lines[2] if len(lines) > 2 else ""
        style = self._question_style(question)

        if style == "why":
            return (
                f"The real point is not only what the provision or institution says on paper, but why it matters in constitutional practice. "
                f"{primary} {secondary} {tertiary} That is why UPSC often frames such doubts through significance, enforceability, or comparison."
            ).strip()

        if style == "how":
            return (
                f"To explain a 'how' question well, show the mechanism instead of only the result. "
                f"{primary} {secondary} {tertiary} That makes the answer feel constitutional rather than descriptive."
            ).strip()

        if style == "compare":
            return (
                f"In comparison-based doubts, the safest method is to identify the axis of difference first: scope, authority, remedy, or accountability. "
                f"{primary} {secondary} {tertiary} That gives you a sharper exam answer than listing facts separately."
            ).strip()

        return (
            f"After the direct answer, connect the concept to its constitutional role and exam framing. "
            f"{primary} {secondary} {tertiary} That is usually how a tutor would turn a one-line fact into an exam-ready explanation."
        ).strip()

    def _compose_grounded_common_confusion(self, question: str, topic: str, context: str) -> str:
        style = self._question_style(question)
        reference = self._first_reference(question=question, topic=topic, context=context)
        if style == "why":
            return (
                f"Students often remember {reference} as a fact, but miss why it matters in practice, which is usually the real exam point."
            )
        if style == "compare":
            return "Students often define both sides correctly but fail to state the real basis of distinction."
        if style == "how":
            return "A common mistake is to state the outcome without explaining the constitutional mechanism behind it."
        return (
            f"A common mistake is to answer {topic} only at the definition level and skip the article, remedy, limitation, or comparison that makes it exam-relevant."
        )

    def _compose_grounded_related_concept(self, question: str, topic: str, context: str) -> str:
        reference = self._first_reference(question=question, topic=topic, context=context)
        style = self._question_style(question)
        if reference and reference.lower() != topic.strip().lower():
            return f"Connect this doubt to {reference}, because that is the cleanest syllabus anchor behind the answer."
        if style == "compare":
            return f"The related concept to keep beside {topic} is the comparison axis itself: scope, remedy, authority, or accountability."
        if style == "how":
            return f"The related concept to keep in mind is the mechanism behind {topic}, not just its outcome."
        return f"The related concept to keep in view is the main constitutional anchor, limitation, or comparison point inside {topic}."

    def _compose_grounded_correction(self, question: str, topic: str, context: str, selected_topic: str | None = None) -> str:
        normalized_selected_topic = str(selected_topic or "").strip()
        if normalized_selected_topic and normalized_selected_topic.lower() != topic.strip().lower():
            return (
                f"Correction: do not let the selected topic {normalized_selected_topic} override the actual doubt. "
                f"This question is better answered through {topic}."
            )
        style = self._question_style(question)
        if style == "compare":
            return "Correction: do not list both sides separately without naming the basis of distinction first."
        if style == "how":
            return "Correction: do not jump from the result to the conclusion without showing the mechanism."
        if style == "why":
            return "Correction: do not stop at the article or institution name; explain why it matters in practice."
        return f"Correction: do not stop at the definition of {topic}. Add the anchor, limit, or comparison that actually resolves the doubt."

    def _compose_grounded_exam_tip(self, question: str, topic: str, context: str) -> str:
        reference = self._first_reference(question=question, topic=topic, context=context)
        if reference == "Article 32":
            return "In UPSC, pair Article 32 with the idea of enforceability and be ready to compare it with Article 226."
        if self._question_style(question) == "compare":
            return "In comparison questions, write the basis of distinction first and then add one constitutional consequence."
        return (
            f"If this appears in UPSC, anchor the answer to {reference} and then add one distinction, limitation, or institutional consequence."
        )

    def _compose_grounded_follow_up(self, question: str, topic: str, context: str) -> str:
        reference = self._first_reference(question=question, topic=topic, context=context)
        if reference == "Article 32":
            return "Can you now explain, in one line, how Article 32 differs from Article 226?"
        if self._question_style(question) == "compare":
            return f"Can you state the distinction in one line and then give one example related to {topic}?"
        return f"Can you now explain {topic} in one line and add one syllabus anchor or comparison point?"

    def _extract_constitutional_refs(self, context: str, limit: int = 4) -> List[str]:
        pattern = re.compile(r"\b(?:Article\s+\d+[A-Z]?|Part\s+[IVXLC]+|Lok Sabha|Rajya Sabha|Supreme Court|High Court)\b")
        refs: List[str] = []
        seen: set[str] = set()
        for match in pattern.findall(context):
            if match in seen:
                continue
            seen.add(match)
            refs.append(match)
            if len(refs) >= limit:
                break
        return refs

    def _build_detailed_explanation(
        self,
        topic: str,
        simple_explanation: str,
        key_points: List[str],
        exam_relevance: str,
        context: str,
        explanation_depth: str = "standard",
        teaching_support: str = "balanced",
        teaching_pacing: str = "balanced",
        conceptual_density: str = "medium",
    ) -> str:
        refs = self._extract_constitutional_refs(context)
        anchor_text = ", ".join(refs[:2]) if refs else "the relevant constitutional article, institution, or doctrine"
        working_point = key_points[0] if key_points else f"Start with the constitutional meaning of {topic}."
        distinction_point = key_points[1] if len(key_points) > 1 else f"Then connect {topic} to how it works in practice."
        application_point = key_points[2] if len(key_points) > 2 else f"Finally, study how UPSC converts {topic} into statement, comparison, and concept questions."

        normalized_explanation_depth = _normalize_explanation_depth(explanation_depth)
        normalized_teaching_support = _normalize_teaching_support(teaching_support)
        normalized_teaching_pacing = _normalize_teaching_pacing(teaching_pacing)
        normalized_conceptual_density = _normalize_conceptual_density(conceptual_density)

        support_sentence = (
            f"Keep the explanation reassuring and explicit so {topic} feels safer to rebuild."
            if normalized_teaching_support == "supportive"
            else f"Treat {topic} as ready for a little more stretch, so sharper distinctions can come earlier."
            if normalized_teaching_support == "stretch"
            else f"Keep the explanation steady so {topic} stays connected without feeling overworked."
        )
        pacing_sentence = (
            "Move one layer at a time instead of stacking too many ideas into the same step."
            if normalized_teaching_pacing == "gentle"
            else "Move a little faster and spend less time repeating the headline definition."
            if normalized_teaching_pacing == "accelerated"
            else "Move at a balanced pace so the concept grows without dragging."
        )
        density_sentence = (
            "Unpack only one major idea at a time and keep technical density low."
            if normalized_conceptual_density == "low"
            else "Bring in tighter distinctions, comparisons, and exam-useful detail once the base idea is set."
            if normalized_conceptual_density == "high"
            else "Keep a moderate conceptual load so the explanation stays teachable and exam-usable."
        )

        if normalized_explanation_depth == "foundational":
            paragraphs = [
                (
                    f"{simple_explanation} {support_sentence} {pacing_sentence} Start with the base meaning of {topic} before moving into exceptions, comparisons, or edge cases. "
                    f"The safest first step is to connect the topic to {anchor_text} in plain language."
                ),
                (
                    f"{working_point} {distinction_point} {density_sentence} Build the topic one layer at a time, and keep returning to the core definition whenever the wording becomes abstract. "
                    f"That stops {topic} from feeling bigger or more technical than it really is."
                ),
                (
                    f"For exam preparation, first lock the basic concept, then the main syllabus anchor, and then one standard trap. "
                    f"{exam_relevance} That slower sequence makes revision safer when the topic is still developing."
                ),
            ]
        elif normalized_explanation_depth == "advanced":
            paragraphs = [
                (
                    f"{simple_explanation} {support_sentence} Treat {topic} as more than a definition: place it against {anchor_text} and ask what distinction, limitation, or institutional tension UPSC is most likely to test next."
                ),
                (
                    f"{working_point} {distinction_point} {application_point} {density_sentence} At this depth, the goal is to move from recall into comparison, exception handling, and exam-trap elimination."
                ),
                (
                    f"For advanced revision, study {topic} through three lenses: constitutional anchor, operational distinction, and likely trap. "
                    f"{exam_relevance} {pacing_sentence} That makes the topic easier to deploy in both nuanced prelims elimination and mains analysis."
                ),
            ]
        else:
            paragraphs = [
                (
                    f"{simple_explanation} {support_sentence} As a tutor, the next step is to move beyond the headline meaning and ask where {topic} sits in the constitutional design. "
                    f"That means linking the topic to {anchor_text} instead of memorizing it as an isolated definition."
                ),
                (
                    f"{working_point} {distinction_point} {application_point} {density_sentence} "
                    f"When you study {topic} this way, you understand not just what it is, but why it matters in constitutional practice."
                ),
                (
                    f"For exam preparation, {topic} should always be revised through three lenses: the basic concept, the syllabus anchor, and the usual exam trap. "
                    f"{exam_relevance} {pacing_sentence} That layered approach makes the topic useful for both prelims elimination and mains explanation."
                ),
            ]
        return "\n\n".join(paragraphs)

    def _explanation_depth_instruction(self, explanation_depth: str) -> str:
        normalized_explanation_depth = _normalize_explanation_depth(explanation_depth)
        if normalized_explanation_depth == "foundational":
            return (
                "Teach at a foundational depth. Assume the student may still be building the basics. "
                "Use plain language, define terms explicitly, and avoid jumping straight to advanced distinctions."
            )
        if normalized_explanation_depth == "advanced":
            return (
                "Teach at an advanced depth. Assume the student already knows the basic definition. "
                "Emphasize sharper distinctions, comparisons, limits, edge cases, and exam traps."
            )
        return (
            "Teach at a standard depth. Assume the student knows the broad idea but still needs a connected, exam-usable explanation."
        )


    def _teaching_mode_instruction(self, teaching_mode: str) -> str:
        normalized_teaching_mode = _normalize_teaching_mode(teaching_mode)
        if normalized_teaching_mode == "step_by_step":
            return (
                "Teach sequentially. Break the topic into clear learning steps, and make each step build on the previous one."
            )
        if normalized_teaching_mode == "example_driven":
            return (
                "Teach through examples and illustrations. Use concrete examples to reveal the rule, then generalize the concept."
            )
        if normalized_teaching_mode == "exam_focused":
            return (
                "Teach with exam use in mind. Emphasize answer framing, prelims traps, mains angle, and quick recall anchors."
            )
        return (
            "Teach through a concise concept overview. Focus on the definition, structure, and where the topic fits in the wider syllabus."
        )

    def _teaching_shape_instruction(self, teaching_support: str, teaching_pacing: str, conceptual_density: str) -> str:
        normalized_teaching_support = _normalize_teaching_support(teaching_support)
        normalized_teaching_pacing = _normalize_teaching_pacing(teaching_pacing)
        normalized_conceptual_density = _normalize_conceptual_density(conceptual_density)
        support_instruction = (
            "Keep the tone supportive and reassuring. Rebuild the concept patiently and do not assume too much prior confidence."
            if normalized_teaching_support == "supportive"
            else "Keep the tone stretch-oriented. Assume the student can handle tighter comparisons and sharper distinctions."
            if normalized_teaching_support == "stretch"
            else "Keep the tone balanced. Connect the concept clearly without overexplaining or overshooting."
        )
        pacing_instruction = (
            "Move gently. Take smaller conceptual steps and avoid stacking too many ideas at once."
            if normalized_teaching_pacing == "gentle"
            else "Move a little faster. Compress the basics and climb into distinctions sooner."
            if normalized_teaching_pacing == "accelerated"
            else "Move at a balanced pace so the explanation stays connected and usable."
        )
        density_instruction = (
            "Keep conceptual density low. Unpack one main idea at a time in plain language."
            if normalized_conceptual_density == "low"
            else "Keep conceptual density high. Bring in sharper comparisons, exam angles, and fine distinctions."
            if normalized_conceptual_density == "high"
            else "Keep conceptual density moderate. Connect the core idea with one or two supporting distinctions."
        )
        return f"{support_instruction} {pacing_instruction} {density_instruction}"

    def _lesson_mode_instruction(self, lesson_mode: str) -> str:
        normalized_lesson_mode = _normalize_lesson_mode(lesson_mode)
        if normalized_lesson_mode == "mini_lesson":
            return (
                "Lesson-mode contract: shape the explanation as a compact mini-lesson. "
                "Make simple_explanation direct and teachable, keep key_points as the few ideas the student must learn now, "
                "use one especially clear anchor in examples, and make memory_hooks feel like short remember-this cues."
            )
        if normalized_lesson_mode == "revision_lesson":
            return (
                "Lesson-mode contract: shape the explanation as revision reinforcement. "
                "Lead with the weak or due idea, use key_points as repair anchors, make common_traps likely confusion points, "
                "and make practice_questions recall-oriented rather than broad overview prompts."
            )
        if normalized_lesson_mode == "crash_course":
            return (
                "Lesson-mode contract: shape the explanation as a concise exam crash-course script. "
                "Compress the basics, prioritize high-yield exam points, include likely asked angles in examples, "
                "make common_traps sharp elimination traps, and make memory_hooks short must-remember items."
            )
        if normalized_lesson_mode == "video_lecture":
            return (
                "Lesson-mode contract: shape the explanation as a video lecture seed. "
                "Make detailed_explanation easy to segment into an intro, concept build, visual example, and recap. "
                "Keep it broader and teachable rather than compressed: key_points should support the instructional body, "
                "examples should be visualizable, and practice_questions should work as on-screen learner prompts."
            )
        if normalized_lesson_mode == "revision_video":
            return (
                "Lesson-mode contract: shape the explanation as a compact revision video seed. "
                "Do not turn it into a broad overview. Lead with quick recall, make common_traps explicit key-correction scenes, "
                "keep examples short, make memory_hooks strong enough for a final remember-this recap, "
                "and make practice_questions feel like recall checks after the correction."
            )
        if normalized_lesson_mode == "crash_course_video":
            return (
                "Lesson-mode contract: shape the explanation as a compressed exam crash-course video seed. "
                "Do not reteach broadly. Prioritize high-yield points, must-remember items, likely asked angles, and trap elimination. "
                "Keep the wording concise enough for fast narration and checklist-style slides; if context shows weak recovery, stay supportive but still compressed."
            )
        return (
            "Lesson-mode contract: shape the explanation as a lecture outline seed. "
            "Make detailed_explanation sectionable, key_points usable as outline headings, examples usable as teaching anchors, "
            "and practice_questions progress from recall to application."
        )

    def _doubt_mode_instruction(
        self,
        *,
        question: str,
        misconception_signal: str,
        teaching_mode: str,
        explanation_depth: str,
    ) -> str:
        style = self._question_style(question)
        normalized_misconception_signal = str(misconception_signal or "none").strip().lower()
        normalized_teaching_mode = _normalize_teaching_mode(teaching_mode)
        normalized_explanation_depth = _normalize_explanation_depth(explanation_depth)

        if style == "compare":
            intent_instruction = (
                "Doubt-mode contract: this is a comparison doubt. Start with the basis of distinction, then explain each side only as much as needed."
            )
        elif style == "how":
            intent_instruction = (
                "Doubt-mode contract: this is a mechanism doubt. Explain the process or causal chain instead of giving only a definition."
            )
        elif style == "why":
            intent_instruction = (
                "Doubt-mode contract: this is a significance doubt. Answer why it matters, then connect that significance to the exam framing."
            )
        elif style == "what":
            intent_instruction = (
                "Doubt-mode contract: this is a definition doubt. Give the clean meaning first, then add one anchor, one limit, and one exam cue."
            )
        else:
            intent_instruction = (
                "Doubt-mode contract: answer the exact doubt first, then add only the supporting concept needed to remove confusion."
            )

        repair_instruction = (
            " Because the signal suggests a possible misconception, make correction and common_confusion specific but tentative."
            if normalized_misconception_signal in {"possible", "likely"}
            else ""
        )
        mode_instruction = (
            " Keep the answer exam-compressed and avoid a long lecture."
            if normalized_teaching_mode == "exam_focused"
            else " Use one concrete example before generalizing."
            if normalized_teaching_mode == "example_driven"
            else " Move in small sequential steps."
            if normalized_teaching_mode == "step_by_step"
            else " Keep the answer concept-centered."
        )
        depth_instruction = (
            " Stay foundational and reassuring."
            if normalized_explanation_depth == "foundational"
            else " Add a sharper distinction or limitation after the direct answer."
            if normalized_explanation_depth == "advanced"
            else " Keep depth balanced."
        )
        return f"{intent_instruction}{repair_instruction}{mode_instruction}{depth_instruction}"

    def _quiz_mode_instruction(self, *, quiz_mode: str, difficulty: str, focus_concepts: List[str] | None = None) -> str:
        normalized_quiz_mode = _normalize_quiz_mode(quiz_mode)
        normalized_difficulty = str(difficulty or "medium").strip().lower()
        focus_count = len([concept for concept in (focus_concepts or []) if str(concept or "").strip()])

        if normalized_quiz_mode == "practice":
            mode_instruction = (
                "Quiz-mode contract: practice questions should teach through assessment. "
                "Use clear stems, reinforce the concept, and make explanations repair learning without revealing answers in public payloads."
            )
        elif normalized_quiz_mode == "revision":
            mode_instruction = (
                "Quiz-mode contract: revision questions should test recall and reinforcement of due or recently weak material. "
                "Prefer compact recall stems, repeated-confusion distractors, and explanations that rebuild the missed anchor."
            )
        elif normalized_quiz_mode == "weak_area_drill":
            mode_instruction = (
                "Quiz-mode contract: weak-area drill questions must stay tightly centered on the listed focus concepts and recent mistakes. "
                "Use easy-to-medium repair questions before adding any stretch."
            )
        else:
            mode_instruction = (
                "Quiz-mode contract: test questions should feel like balanced assessment. "
                "Mix recall, application, and elimination without drifting outside the selected topic."
            )

        difficulty_instruction = (
            " Difficulty contract: easy means clear recall with plausible but not tricky distractors."
            if normalized_difficulty == "easy"
            else " Difficulty contract: hard means sharper statements, closer distractors, and stronger application while remaining fair."
            if normalized_difficulty == "hard"
            else " Difficulty contract: medium means one conceptual step beyond direct recall with fair distractors."
        )
        focus_instruction = (
            f" Focus contract: at least some questions must directly exercise the {focus_count} listed focus concept(s)."
            if focus_count
            else " Focus contract: keep every question anchored to the target topic and local notes."
        )
        return f"{mode_instruction} {difficulty_instruction} {focus_instruction}"

    def _adapt_simple_explanation(
        self,
        simple_explanation: str,
        topic: str,
        explanation_depth: str,
        teaching_support: str = "balanced",
        teaching_pacing: str = "balanced",
        conceptual_density: str = "medium",
    ) -> str:
        normalized_explanation_depth = _normalize_explanation_depth(explanation_depth)
        normalized_teaching_support = _normalize_teaching_support(teaching_support)
        normalized_conceptual_density = _normalize_conceptual_density(conceptual_density)
        cleaned = simple_explanation.strip()
        if normalized_explanation_depth == "foundational" or normalized_teaching_support == "supportive":
            return f"Start gently with the core idea of {topic}: {cleaned}"
        if normalized_explanation_depth == "advanced" or normalized_teaching_support == "stretch" or normalized_conceptual_density == "high":
            return f"Assume the basic definition is already familiar. Use this sharper frame for {topic}: {cleaned}"
        return cleaned

    def _build_examples(self, topic: str, key_points: List[str], context: str, teaching_mode: str = "concept_overview") -> List[str]:
        refs = self._extract_constitutional_refs(context)
        ref_text = refs[0] if refs else f"the main syllabus anchor of {topic}"
        normalized_teaching_mode = _normalize_teaching_mode(teaching_mode)
        if normalized_teaching_mode == "step_by_step":
            candidates = [
                f"Base example: Start with one plain-language example that shows what {topic} actually means before adding exceptions.",
                f"Anchor example: Link that example to {ref_text} so the concept stays tied to the syllabus.",
                f"Application example: Show how the same example changes once {topic} is tested in a real institutional or governance setting.",
                f"Comparison example: Place {topic} next to a nearby topic and explain the first major difference.",
            ]
        elif normalized_teaching_mode == "example_driven":
            candidates = [
                f"Worked example: Explain {topic} through one concrete illustration before giving the general rule.",
                f"Comparison example: Use a second illustration to show how {topic} differs from a nearby idea that UPSC may mix up.",
                f"Application example: Convert the illustration into a governance, constitutional, historical, or geographical application of {topic}.",
                f"Revision example: Use one short example to rebuild the rule behind {topic} during revision.",
            ]
        elif normalized_teaching_mode == "exam_focused":
            candidates = [
                f"Prelims angle: UPSC may ask which statement correctly captures the role, limit, or constitutional position of {topic}.",
                f"Mains angle: A strong answer on {topic} should connect the definition with {ref_text}.",
                f"Elimination angle: Use one example to show how a wrong statement about {topic} can be ruled out quickly.",
                f"Comparison angle: If {topic} appears alongside a related topic, focus on who holds power, who is accountable, and what the limitation is.",
            ]
        else:
            candidates = [
                f"Concept angle: Use one example to show the core meaning of {topic} before memorizing isolated facts.",
                f"Syllabus anchor: Connect that example to {ref_text} so the topic stays grounded in the wider subject.",
                f"Application angle: Use {topic} to explain how the broader system works in practice rather than only in theory.",
                f"Comparison angle: Put {topic} next to a nearby concept and note the cleanest distinction.",
            ]
        return self._pad_list([], candidates + [f"Revision angle: {point}" for point in key_points[:2]], minimum=3, limit=5)

    def _build_common_traps(self, topic: str, context: str) -> List[str]:
        refs = self._extract_constitutional_refs(context)
        ref_text = refs[0] if refs else "the syllabus anchor"
        return self._pad_list(
            [],
            [
                f"Do not confuse the basic meaning of {topic} with its exception, remedy, or related institution.",
                f"UPSC often tests {topic} through comparison, so memorizing only the definition without the distinction is risky.",
                f"Watch for questions that mix the formal constitutional position of {topic} with how it works in practice.",
                f"If a question refers to {ref_text}, make sure you connect it back to the core concept of {topic} rather than treating it as a separate fact.",
            ],
            minimum=3,
            limit=5,
        )

    def _build_memory_hooks(self, topic: str, context: str) -> List[str]:
        refs = self._extract_constitutional_refs(context)
        ref_text = refs[0] if refs else "one syllabus anchor"
        return self._pad_list(
            [],
            [
                f"Remember {topic} through four anchors: meaning, constitutional location, role, and limitation.",
                f"For revision, reduce {topic} to {ref_text}, one core function, and one common trap.",
                f"If you forget details, rebuild {topic} by asking: who holds the power, on what basis, and with what checks?",
                f"A quick recall formula is: definition first, syllabus anchor second, exam distinction third.",
            ],
            minimum=3,
            limit=5,
        )

    def _build_guided_practice_questions(
        self,
        topic: str,
        practice_lines: List[str],
        key_points: List[str],
        context: str,
        teaching_mode: str = "concept_overview",
    ) -> List[str]:
        refs = self._extract_constitutional_refs(context)
        ref_text = refs[0] if refs else f"the main syllabus anchor behind {topic}"
        normalized_teaching_mode = _normalize_teaching_mode(teaching_mode)
        if normalized_teaching_mode == "step_by_step":
            fallback_questions = [
                f"What is the first core idea you should learn inside {topic}?",
                f"After the definition, what is the next layer you would add to explain {topic}?",
                f"Which example would you use to make {topic} easier to understand?",
                f"Why does {topic} matter beyond a one-line definition in the exam?",
                f"What is one confusion point that usually appears inside {topic}?",
                f"If a question mentions {ref_text}, how would you connect it back to the basic idea of {topic}?",
            ]
        elif normalized_teaching_mode == "example_driven":
            fallback_questions = [
                f"Which example helps you understand {topic} fastest?",
                f"What general rule does that example reveal about {topic}?",
                f"Which nearby topic should be compared with {topic} to sharpen the concept?",
                f"How would you turn an example of {topic} into a prelims or mains answer point?",
                f"What misconception disappears once you study {topic} through examples?",
                f"If a question mentions {ref_text}, which example would you use to anchor your answer?",
            ]
        elif normalized_teaching_mode == "exam_focused":
            fallback_questions = [
                f"How would you define {topic} in one exam-safe line?",
                f"Which distinction or constitutional anchor makes {topic} a strong answer point?",
                f"What is the biggest prelims trap inside {topic}?",
                f"How would you structure a short mains answer on {topic}?",
                f"Which comparison would help you eliminate a wrong statement on {topic}?",
                f"If a question mentions {ref_text}, how would you use it in an exam answer on {topic}?",
            ]
        else:
            fallback_questions = [
                f"In your own words, what is the central idea behind {topic}?",
                f"Where does {topic} sit in the wider syllabus structure?",
                f"Why does {topic} matter in the exam beyond a one-line definition?",
                f"What is one common exam trap or misconception related to {topic}?",
                f"How would you compare {topic} with a closely related topic from the same syllabus?",
                f"If a question mentions {ref_text}, how would you connect it back to {topic}?",
            ]
        practice_seed = practice_lines + [f"Guided recall: {point}" for point in key_points[:2]]
        return self._pad_list(practice_seed, fallback_questions, minimum=5, limit=10)

    def _refine_explanation_for_teaching_mode(
        self,
        detailed_explanation: str,
        topic: str,
        teaching_mode: str,
        teaching_support: str = "balanced",
        teaching_pacing: str = "balanced",
        conceptual_density: str = "medium",
    ) -> str:
        normalized_teaching_mode = _normalize_teaching_mode(teaching_mode)
        normalized_teaching_support = _normalize_teaching_support(teaching_support)
        normalized_teaching_pacing = _normalize_teaching_pacing(teaching_pacing)
        normalized_conceptual_density = _normalize_conceptual_density(conceptual_density)
        if normalized_teaching_mode == "step_by_step":
            suffix = f"Study {topic} in sequence: definition first, structure second, application third, and confusion check last."
        elif normalized_teaching_mode == "example_driven":
            suffix = f"Use one concrete example for {topic}, then generalize the rule, then compare it with one nearby idea before revising it."
        elif normalized_teaching_mode == "exam_focused":
            suffix = f"For exam preparation, revise {topic} through one-line definition, one anchor or distinction, and one trap that can eliminate a wrong option quickly."
        else:
            suffix = f"Keep {topic} as a connected concept map first: core idea, syllabus anchor, key distinction, and why the exam cares."

        if normalized_teaching_support == "supportive":
            shape_suffix = "Keep this pass supportive: restate the core idea clearly, move slowly, and do not stack too many distinctions at once."
        elif normalized_teaching_support == "stretch":
            shape_suffix = "Keep this pass stretch-oriented: move faster, compress the basics, and pressure-test sharper distinctions or exam traps."
        else:
            shape_suffix = "Keep this pass balanced: move steadily and connect the core idea with one or two exam-usable distinctions."

        if normalized_teaching_pacing == "gentle":
            shape_suffix += " Stay gentle in pacing by letting each step settle before the next jump."
        elif normalized_teaching_pacing == "accelerated":
            shape_suffix += " Stay brisk in pacing by spending less time on the headline definition."

        if normalized_conceptual_density == "low":
            shape_suffix += " Keep conceptual density low by unpacking one main idea at a time."
        elif normalized_conceptual_density == "high":
            shape_suffix += " Keep conceptual density high by bringing in tighter comparisons, limitations, and edge cases."

        cleaned = detailed_explanation.strip()
        full_suffix = f"{suffix} {shape_suffix}".strip()
        if not cleaned:
            return full_suffix
        if full_suffix.lower() in cleaned.lower():
            return cleaned
        return f"{cleaned}\n\n{full_suffix}"

    def _mock_explanation(
        self,
        topic: str,
        context: str,
        explanation_depth: str = "standard",
        teaching_mode: str = "concept_overview",
        teaching_support: str = "balanced",
        teaching_pacing: str = "balanced",
        conceptual_density: str = "medium",
        teaching_profile_note: str | None = None,
    ) -> Dict[str, Any]:
        normalized_explanation_depth = _normalize_explanation_depth(explanation_depth)
        normalized_teaching_mode = _normalize_teaching_mode(teaching_mode)
        normalized_teaching_support = _normalize_teaching_support(teaching_support)
        normalized_teaching_pacing = _normalize_teaching_pacing(teaching_pacing)
        normalized_conceptual_density = _normalize_conceptual_density(conceptual_density)
        profile_note = str(teaching_profile_note or "").strip()
        if not context.strip():
            exam_relevance = (
                f"{topic} can still be studied even without local notes because the exam often tests definitions, powers, limits, causes, and comparative understanding."
            )
            if profile_note and profile_note.lower() not in exam_relevance.lower():
                exam_relevance = f"{exam_relevance} {profile_note}"
            key_points = [
                f"Begin with a simple syllabus-level definition of {topic}.",
                "Identify where it appears in the standard exam syllabus, if applicable.",
                "Connect the concept to the wider system, process, institution, event, or principle around it.",
                "Compare it with nearby topics that the exam commonly mixes up.",
                "Revise both prelims facts and mains-style analytical relevance.",
            ]
            simple_explanation = self._adapt_simple_explanation(
                (
                    f"{topic} is an exam topic that should be understood through definition, core role, and exam-oriented comparisons. "
                    f"A good explanation starts with what {topic} means, then shows how it functions inside the wider syllabus."
                ),
                topic=topic,
                explanation_depth=normalized_explanation_depth,
                teaching_support=normalized_teaching_support,
                teaching_pacing=normalized_teaching_pacing,
                conceptual_density=normalized_conceptual_density,
            )
            detailed_explanation = self._build_detailed_explanation(
                topic=topic,
                simple_explanation=simple_explanation,
                key_points=key_points,
                exam_relevance=exam_relevance,
                context=context,
                explanation_depth=normalized_explanation_depth,
                teaching_support=normalized_teaching_support,
                teaching_pacing=normalized_teaching_pacing,
                conceptual_density=normalized_conceptual_density,
            )
            detailed_explanation = self._refine_explanation_for_teaching_mode(
                detailed_explanation,
                topic=topic,
                teaching_mode=normalized_teaching_mode,
                teaching_support=normalized_teaching_support,
                teaching_pacing=normalized_teaching_pacing,
                conceptual_density=normalized_conceptual_density,
            )
            return {
                "topic": topic,
                "simple_explanation": simple_explanation,
                "detailed_explanation": detailed_explanation,
                "key_points": key_points,
                "examples": self._build_examples(topic=topic, key_points=key_points, context=context, teaching_mode=normalized_teaching_mode),
                "exam_relevance": exam_relevance,
                "common_traps": self._build_common_traps(topic=topic, context=context),
                "memory_hooks": self._build_memory_hooks(topic=topic, context=context),
                "practice_questions": self._build_guided_practice_questions(
                    topic=topic,
                    practice_lines=[],
                    key_points=key_points,
                    context=context,
                    teaching_mode=normalized_teaching_mode,
                ),
            }

        simple_lines = extract_section(context, "Simple Explanation")
        key_point_lines = clean_bullets(extract_section(context, "Key Points"))
        exam_relevance_lines = extract_section(context, "Exam Relevance")
        practice_lines = clean_bullets(extract_section(context, "Practice Questions"))

        context_lines = [line.strip() for line in context.splitlines() if line.strip()]
        fallback_context_line = (
            context_lines[2]
            if len(context_lines) >= 3
            else context_lines[-1]
            if context_lines
            else f"{topic} is important in this subject."
        )
        simple_explanation = self._adapt_simple_explanation(
            " ".join(simple_lines) if simple_lines else fallback_context_line,
            topic=topic,
            explanation_depth=normalized_explanation_depth,
        )
        exam_relevance = " ".join(exam_relevance_lines) if exam_relevance_lines else f"{topic} is important for exam questions, revision, and linked current-affairs framing."
        if profile_note and profile_note.lower() not in exam_relevance.lower():
            exam_relevance = f"{exam_relevance} {profile_note}".strip()
        key_points = self._pad_list(
            key_point_lines,
            [
                f"Start with the basic exam meaning of {topic}.",
                f"Link {topic} to its role, powers, causes, features, or limitations.",
                f"Revise how the exam frames factual and analytical questions around {topic}.",
            ],
            minimum=3,
            limit=7,
        )
        detailed_explanation = self._build_detailed_explanation(
            topic=topic,
            simple_explanation=simple_explanation,
            key_points=key_points,
            exam_relevance=exam_relevance,
            context=context,
            explanation_depth=normalized_explanation_depth,
        )
        detailed_explanation = self._refine_explanation_for_teaching_mode(
            detailed_explanation,
            topic=topic,
            teaching_mode=normalized_teaching_mode,
        )
        practice_questions = self._build_guided_practice_questions(
            topic=topic,
            practice_lines=practice_lines,
            key_points=key_points,
            context=context,
            teaching_mode=normalized_teaching_mode,
        )
        examples = self._build_examples(topic=topic, key_points=key_points, context=context, teaching_mode=normalized_teaching_mode)
        common_traps = self._build_common_traps(topic=topic, context=context)
        memory_hooks = self._build_memory_hooks(topic=topic, context=context)

        return {
            "topic": topic,
            "simple_explanation": simple_explanation,
            "detailed_explanation": detailed_explanation,
            "key_points": key_points,
            "examples": examples,
            "exam_relevance": exam_relevance,
            "common_traps": common_traps,
            "memory_hooks": memory_hooks,
            "practice_questions": practice_questions,
        }

    def _mock_doubt(
        self,
        topic: str,
        question: str,
        context: str,
        subject: str | None = None,
        selected_topic: str | None = None,
        grounding_context: str | None = None,
        misconception_signal: str = "none",
        misconception_reason: str | None = None,
        what_to_remember: str | None = None,
    ) -> Dict[str, str]:
        normalized_selected_topic = str(selected_topic or "").strip()
        normalized_grounding_context = str(grounding_context or "").strip()
        normalized_misconception_signal = str(misconception_signal or "none").strip().lower()
        if normalized_misconception_signal not in {"none", "possible", "likely"}:
            normalized_misconception_signal = "none"
        normalized_misconception_reason = str(misconception_reason or "").strip()
        normalized_what_to_remember = str(what_to_remember or "").strip() or (
            f"Remember: keep {topic} tied to one definition, one anchor, and one clear comparison point."
        )
        misconception_suffix = ""
        if normalized_misconception_signal == "likely":
            misconception_suffix = " Treat this as a likely conceptual mix-up and rebuild the answer from the main anchor first."
        elif normalized_misconception_signal == "possible":
            misconception_suffix = " Treat this as a possible conceptual mix-up and rebuild the answer from the main anchor first."
        subject_label = str(subject or "general subject").replace("_", " ").title()
        mismatch_note = (
            f" Do not let the selected topic {normalized_selected_topic} override the real doubt."
            if normalized_selected_topic and normalized_selected_topic.lower() != topic.strip().lower()
            else ""
        )

        if not context.strip():
            if topic in {"General subject topic", "General UPSC Polity", f"General {subject_label}"}:
                return {
                    "direct_answer": "By that exact name, this is not a standard syllabus term I would rely on in an exam answer. The safe move is to identify the nearest real principle or topic before using it.",
                    "explanation": (
                        "When a term looks unfamiliar, do not try to sound confident by inventing a definition. "
                        "Instead, ask whether it is really pointing to a known article, institution, process, event, doctrine, or principle from the syllabus. "
                        "Once you identify that anchor, answer from the recognized concept rather than the unfamiliar label."
                    ),
                    "related_concept": "The related concept to look for is the nearest real syllabus anchor, such as an article, institution, doctrine, or event that the phrase is probably pointing toward.",
                    "correction": (
                        "Correction: do not define the unfamiliar phrase itself as if it were a confirmed syllabus term. Map it to the closest recognized concept first."
                        f"{mismatch_note}{misconception_suffix}"
                    ).strip(),
                    "common_confusion": normalized_misconception_reason or "Students often waste time trying to define the unfamiliar phrase itself instead of translating it into a known syllabus idea.",
                    "what_to_remember": normalized_what_to_remember,
                    "exam_tip": "If a term looks unfamiliar in the exam, write the nearest recognized syllabus concept and show why you mapped it that way.",
                    "follow_up_prompt": "Do you want me to map this phrase to the closest syllabus topic and turn it into an exam-safe answer?",
                }

            style = self._question_style(question)
            return {
                "direct_answer": (
                    f"The safest tutor-style answer is to define {topic} clearly and then connect it to its real role, limit, or practical significance."
                    if style != "why"
                    else f"{topic} matters because its real value becomes clearer once you connect the concept to its function and limits."
                ),
                "explanation": (
                    f"For this doubt, begin with the core meaning of {topic}, then mention the most relevant anchor from the syllabus if you know it, "
                    f"and finish with one distinction, limitation, or comparison. That makes the answer feel like a tutor explanation rather than a vague summary."
                ),
                "related_concept": (
                    f"The related concept to pair with {topic} is its closest syllabus anchor, limitation, or comparison point."
                    if not normalized_grounding_context
                    else f"Use your extra grounding context as a supporting anchor, but keep the main explanation centered on {topic}."
                ),
                "correction": (
                    f"Correction: do not stop at the definition of {topic}. Add one anchor point and one comparison point."
                    f"{mismatch_note}{misconception_suffix}"
                ).strip(),
                "common_confusion": normalized_misconception_reason or "When notes are missing, students often stop at the definition and fail to add the syllabus anchor or comparison that the exam expects.",
                "what_to_remember": normalized_what_to_remember,
                "exam_tip": f"If the exam asks about {topic}, do not stop at definition. Add one anchor point and one comparison point.",
                "follow_up_prompt": f"Would you like me to turn this into a one-line comparison or a quick exam-style check question on {topic}?",
            }

        base_correction = self._compose_grounded_correction(
            question=question,
            topic=topic,
            context=context,
            selected_topic=normalized_selected_topic or None,
        )
        return {
            "direct_answer": self._compose_grounded_direct_answer(question=question, topic=topic, context=context),
            "explanation": self._compose_grounded_explanation(question=question, topic=topic, context=context),
            "related_concept": self._compose_grounded_related_concept(question=question, topic=topic, context=context),
            "correction": f"{base_correction}{misconception_suffix}".strip(),
            "common_confusion": normalized_misconception_reason or self._compose_grounded_common_confusion(question=question, topic=topic, context=context),
            "what_to_remember": normalized_what_to_remember,
            "exam_tip": self._compose_grounded_exam_tip(question=question, topic=topic, context=context),
            "follow_up_prompt": self._compose_grounded_follow_up(question=question, topic=topic, context=context),
        }

    def _looks_absurd_option(self, option: str) -> bool:
        normalized_option = option.strip().lower()
        return any(fragment in normalized_option for fragment in ABSURD_OPTION_FRAGMENTS)

    def _clean_statement(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text.strip()).rstrip(".")
        if cleaned and cleaned[0].isalpha():
            cleaned = cleaned[0].upper() + cleaned[1:]
        return cleaned

    def _replace_phrase_once(self, text: str, old: str, new: str) -> str:
        if old in text:
            return text.replace(old, new, 1)
        pattern = re.compile(re.escape(old), re.IGNORECASE)
        return pattern.sub(new, text, count=1) if pattern.search(text) else text

    def _distractor_signature(self, text: str) -> str:
        keywords = extract_keywords(text, limit=6)
        if not keywords:
            return text.strip().lower()
        return "|".join(sorted(set(keyword.strip().lower() for keyword in keywords[:4] if keyword.strip())))

    def _keyword_overlap_count(self, text: str, keywords: set[str]) -> int:
        if not keywords:
            return 0
        return sum(1 for keyword in extract_keywords(text, limit=12) if keyword in keywords)

    def _has_repeated_option_phrase(self, text: str) -> bool:
        normalized = text.strip().lower()
        return bool(re.search(r"\b([a-z][a-z\s-]{4,})\b\s+and\s+(?:the\s+)?\1\b", normalized))

    def _mutate_statement_candidates(self, statement: str, context: str) -> List[str]:
        refs = self._extract_constitutional_refs(context, limit=8)
        candidates: List[str] = []
        for old, new in TERM_SWAP_PAIRS:
            mutated = self._replace_phrase_once(statement, old, new)
            if mutated != statement:
                candidates.append(self._clean_statement(mutated))
        for old, new in QUALIFIER_SWAP_PAIRS:
            mutated = self._replace_phrase_once(statement, old, new)
            if mutated != statement:
                candidates.append(self._clean_statement(mutated))
        for old, new in NEGATION_SWAP_PAIRS:
            mutated = self._replace_phrase_once(statement, old, new)
            if mutated != statement:
                candidates.append(self._clean_statement(mutated))
        statement_refs = self._extract_constitutional_refs(statement, limit=2)
        if statement_refs:
            source_ref = statement_refs[0]
            for ref in refs:
                if ref != source_ref and ref not in statement:
                    candidates.append(self._clean_statement(statement.replace(source_ref, ref, 1)))
                    break
        return candidates

    def _collect_fallback_source_statements(self, topic: str, context: str) -> List[str]:
        candidate_lines = (
            clean_bullets(extract_section(context, "Key Points"))
            + extract_section(context, "Simple Explanation")
            + extract_section(context, "Exam Relevance")
        )
        primary_statements: List[str] = []
        secondary_statements: List[str] = []
        seen: set[str] = set()
        for line in candidate_lines:
            if not line:
                continue
            for fragment in re.split(r"(?<=[.!?])\s+", line):
                cleaned_fragment = self._clean_statement(fragment)
                if len(cleaned_fragment) < 24:
                    continue
                lowered = cleaned_fragment.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                if any(token in lowered for token in ("upsc", "prelims", "mains", "exam")):
                    secondary_statements.append(cleaned_fragment)
                else:
                    primary_statements.append(cleaned_fragment)
        statements = primary_statements if len(primary_statements) >= 3 else primary_statements + secondary_statements
        if not statements:
            statements.append(f"{topic} should be studied through its main definition, core features, and exam relevance")
        return statements[:8]

    def _extract_topic_anchor_terms(self, topic: str, context: str, source_statements: List[str]) -> List[str]:
        seed_text = " ".join([topic, *source_statements, *extract_section(context, "Exam Relevance")])
        blocked_terms = {
            "topic",
            "topics",
            "subject",
            "subjects",
            "study",
            "studied",
            "important",
            "current",
            "developments",
            "question",
            "questions",
            "exam",
            "exams",
            "upsc",
            "style",
            "area",
            "areas",
            "basis",
            "role",
            "core",
            "main",
            "often",
            "through",
            "across",
            "together",
            "because",
        }
        anchors: List[str] = []
        seen: set[str] = set()
        for keyword in extract_keywords(seed_text, limit=24):
            normalized_keyword = keyword.strip().lower()
            if len(normalized_keyword) < 4 or normalized_keyword in blocked_terms:
                continue
            if normalized_keyword in topic.lower():
                continue
            if normalized_keyword in seen:
                continue
            seen.add(normalized_keyword)
            anchors.append(normalized_keyword)
            if len(anchors) >= 10:
                break
        return anchors

    def _anchor_swap_candidates(self, statement: str, anchors: List[str]) -> List[str]:
        candidates: List[str] = []
        statement_keywords = extract_keywords(statement, limit=8)
        lowered_statement = statement.lower()
        for keyword in statement_keywords:
            normalized_keyword = keyword.strip().lower()
            if len(normalized_keyword) < 4:
                continue
            pattern = re.compile(rf"\b{re.escape(normalized_keyword)}\b", re.IGNORECASE)
            if not pattern.search(statement):
                continue
            for anchor in anchors:
                if anchor == normalized_keyword or anchor in lowered_statement:
                    continue
                swapped = pattern.sub(anchor, statement, count=1)
                if swapped != statement:
                    candidates.append(self._clean_statement(swapped))
                    break
        return candidates

    def _anchored_summary_distractors(self, topic: str, anchors: List[str], source_statements: List[str]) -> List[str]:
        if not anchors:
            return []
        templates: List[str] = []
        if len(anchors) >= 2:
            templates.extend(
                [
                    self._clean_statement(f"{topic} is more closely linked with {anchors[0]} than with {anchors[1]}"),
                    self._clean_statement(f"{topic} is treated chiefly as a question of {anchors[1]} rather than {anchors[0]}"),
                    self._clean_statement(f"{topic} is treated chiefly as a question of {anchors[0]} alone"),
                ]
            )
        else:
            templates.append(self._clean_statement(f"{topic} is treated chiefly as a question of {anchors[0]} alone"))
        return templates

    def _last_resort_topic_distractors(self, topic: str, anchors: List[str]) -> List[str]:
        primary = anchors[0] if anchors else "one narrow factor"
        secondary = anchors[1] if len(anchors) >= 2 else "the wider topic context"
        tertiary = anchors[2] if len(anchors) >= 3 else "broader structural drivers"
        return [
            self._clean_statement(f"{topic} is explained mainly through {primary} alone, with little role for {secondary}."),
            self._clean_statement(f"{topic} remained a narrow and isolated issue rather than shaping wider patterns in the subject."),
            self._clean_statement(f"{topic} is best understood as a uniform process with minimal variation across cases or regions."),
            self._clean_statement(f"{topic} is usually treated as separate from {secondary} and {tertiary}, rather than connected to them."),
        ]

    def _collect_domain_keywords(self, topic: str, anchors: List[str], source_statements: List[str]) -> set[str]:
        keywords = {
            keyword.strip().lower()
            for keyword in extract_keywords(" ".join([topic, *anchors, *source_statements]), limit=24)
            if keyword.strip()
        }
        keywords.update(keyword.strip().lower() for keyword in extract_keywords(topic, limit=8) if keyword.strip())
        keywords.update(anchor.strip().lower() for anchor in anchors if anchor.strip())
        return keywords

    def _build_plausible_distractors(
        self,
        correct_statement: str,
        topic: str,
        context: str,
        source_statements: List[str],
        used_distractor_signatures: set[str] | None = None,
    ) -> List[str]:
        anchors = self._extract_topic_anchor_terms(topic=topic, context=context, source_statements=source_statements)
        domain_keywords = self._collect_domain_keywords(topic=topic, anchors=anchors, source_statements=source_statements)
        candidate_pool: List[str] = []
        candidate_pool.extend(self._mutate_statement_candidates(correct_statement, context))
        for statement in source_statements:
            point_statement = self._clean_statement(statement)
            if not point_statement or point_statement == correct_statement:
                continue
            candidate_pool.extend(self._mutate_statement_candidates(point_statement, context))

        if len(candidate_pool) < 3:
            candidate_pool.extend(
                self._anchored_summary_distractors(
                    topic=topic,
                    anchors=anchors,
                    source_statements=source_statements,
                )
            )

        used_signatures = set(used_distractor_signatures or set())
        correct_signature = self._distractor_signature(correct_statement)
        seen_text: set[str] = {correct_statement.lower()}
        scored_candidates: List[tuple[int, int, int, bool, str, str]] = []
        for candidate in candidate_pool:
            cleaned_candidate = self._clean_statement(candidate)
            if not cleaned_candidate or len(cleaned_candidate) < 20:
                continue
            lowered = cleaned_candidate.lower()
            if lowered in seen_text or self._looks_absurd_option(cleaned_candidate) or self._has_repeated_option_phrase(cleaned_candidate):
                continue
            keyword_count = len(set(extract_keywords(cleaned_candidate, limit=8)))
            if keyword_count < 2:
                continue
            overlap = self._keyword_overlap_count(cleaned_candidate, domain_keywords)
            if topic.lower() not in lowered and overlap < 2:
                continue
            signature = self._distractor_signature(cleaned_candidate)
            if not signature or signature == correct_signature:
                continue
            weak_fragment = any(fragment in lowered for fragment in WEAK_DISTRACTOR_FRAGMENTS)
            anchor_hits = sum(1 for anchor in anchors[:6] if anchor in lowered)
            score = overlap + min(keyword_count, 4) + min(anchor_hits, 2)
            if topic.lower() in lowered:
                score += 2
            if signature in used_signatures:
                score -= 5
            if weak_fragment:
                score -= 4
            seen_text.add(lowered)
            scored_candidates.append((score, overlap, anchor_hits, weak_fragment, cleaned_candidate, signature))

        scored_candidates.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3], item[4].lower()))

        distractors: List[str] = []
        selected_signatures: set[str] = set()
        for allow_reuse, allow_weak in ((False, False), (True, False), (True, True)):
            for _, _, _, weak_fragment, candidate, signature in scored_candidates:
                if not allow_reuse and signature in used_signatures:
                    continue
                if not allow_weak and weak_fragment:
                    continue
                if signature in selected_signatures:
                    continue
                distractors.append(candidate)
                selected_signatures.add(signature)
                if len(distractors) >= 3:
                    return distractors

        for candidate in self._last_resort_topic_distractors(topic=topic, anchors=anchors):
            cleaned_candidate = self._clean_statement(candidate)
            lowered = cleaned_candidate.lower()
            if not cleaned_candidate or lowered in seen_text or self._looks_absurd_option(cleaned_candidate):
                continue
            signature = self._distractor_signature(cleaned_candidate)
            if not signature or signature == correct_signature or signature in selected_signatures:
                continue
            distractors.append(cleaned_candidate)
            selected_signatures.add(signature)
            if len(distractors) >= 3:
                break
        return distractors

    def _collect_used_distractor_signatures(self, questions: List[Dict[str, Any]]) -> set[str]:
        signatures: set[str] = set()
        for question in questions:
            correct_answer = self._coerce_text(question.get("correct_answer"))
            options = question.get("options")
            if not isinstance(options, list):
                continue
            for option in options:
                cleaned_option = self._coerce_text(option)
                if not cleaned_option or cleaned_option == correct_answer:
                    continue
                signatures.add(self._distractor_signature(cleaned_option))
        return signatures

    def _build_revision_question_text(self, topic: str, source: str) -> str:
        normalized_source = source.lower()
        if "appointed by" in normalized_source:
            return f"Which statement correctly captures the appointment logic related to {topic}?"
        if "part iii" in normalized_source or "part iv" in normalized_source or "article " in normalized_source:
            return f"Which statement correctly identifies the syllabus anchor of {topic}?"
        if "real executive" in normalized_source or "nominal executive" in normalized_source:
            return f"Which statement best captures the executive position of {topic}?"
        if "majority" in normalized_source:
            return f"Which statement correctly reflects the political basis of {topic}?"
        if "federal" in normalized_source or "unitary" in normalized_source or "concurrent" in normalized_source:
            return f"Which statement best explains the constitutional design of {topic}?"
        if "founded" in normalized_source or "mass movement" in normalized_source or "national movement" in normalized_source:
            return f"Which statement most accurately reflects the historical development of {topic}?"
        if "river" in normalized_source or "drainage" in normalized_source or "delta" in normalized_source:
            return f"Which statement best matches the geography of {topic}?"
        return f"Which statement about {topic} is most accurate?"

    def _build_focus_revision_question_text(self, topic: str, focus_concept: str, quiz_mode: str) -> str:
        if quiz_mode == "weak_area_drill":
            return f"Which option best corrects the common confusion around {focus_concept} in {topic}?"
        return f"Which option best reinforces {focus_concept} within {topic}?"

    def _prioritize_bank_by_focus_concepts(
        self,
        bank: List[Dict[str, Any]],
        focus_concepts: List[str] | None,
    ) -> List[Dict[str, Any]]:
        normalized_focus = [concept.strip().lower() for concept in (focus_concepts or []) if concept and concept.strip()]
        if not normalized_focus:
            return bank

        prioritized: List[Dict[str, Any]] = []
        secondary: List[Dict[str, Any]] = []
        for question in bank:
            concept_text = str(question.get("concept") or "").strip().lower()
            question_text = str(question.get("question") or "").strip().lower()
            if any(focus in concept_text or focus in question_text for focus in normalized_focus):
                prioritized.append(question)
            else:
                secondary.append(question)
        return prioritized + secondary

    def _select_balanced_questions(
        self,
        bank: List[Dict[str, Any]],
        question_count: int,
        seed_text: str,
    ) -> List[Dict[str, Any]]:
        if len(bank) <= question_count:
            return bank

        grouped: dict[str, List[Dict[str, Any]]] = {}
        for question in bank:
            concept_key = self._coerce_text(question.get("concept")).strip().lower()
            if not concept_key:
                concept_key = self._coerce_text(question.get("question")).strip().lower()
            grouped.setdefault(concept_key or f"question-{len(grouped)}", []).append(question)

        ordered_keys = list(grouped.keys())
        Random(seed_text).shuffle(ordered_keys)
        balanced: List[Dict[str, Any]] = []
        index = 0
        while len(balanced) < len(bank):
            added = False
            for key in ordered_keys:
                items = grouped[key]
                if index < len(items):
                    balanced.append(items[index])
                    added = True
            if not added:
                break
            index += 1
        return balanced[:question_count]

    def _mock_quiz(
        self,
        topic: str,
        difficulty: str,
        question_count: int,
        context: str,
        quiz_mode: str = "test",
        focus_concepts: List[str] | None = None,
        quiz_profile_note: str | None = None,
    ) -> Dict[str, Any]:
        topic_key = topic.lower().strip()
        bank = list(MOCK_QUIZ_BANK.get(topic_key, []))
        if quiz_mode in {"practice", "revision", "weak_area_drill"} and focus_concepts:
            bank = self._prioritize_bank_by_focus_concepts(bank, focus_concepts)
        used_distractor_signatures = self._collect_used_distractor_signatures(bank)
        if len(bank) < question_count:
            missing_count = question_count - len(bank)
            safety_buffer = max(2, min(4, question_count))
            bank.extend(
                self._build_revision_questions(
                    topic=topic,
                    context=context,
                    count=missing_count + safety_buffer,
                    focus_concepts=focus_concepts,
                    quiz_mode=quiz_mode,
                    used_distractor_signatures=used_distractor_signatures,
                )
            )
        if quiz_mode == "test":
            profile_seed = (quiz_profile_note or "").strip().lower()
            bank = self._select_balanced_questions(bank, question_count, f"{topic}|{difficulty}|{question_count}|{profile_seed}")
        return {
            "topic": topic,
            "difficulty": difficulty,
            "questions": bank[:question_count],
        }

    def _build_revision_questions(
        self,
        topic: str,
        context: str,
        count: int,
        focus_concepts: List[str] | None = None,
        quiz_mode: str = "test",
        used_distractor_signatures: set[str] | None = None,
    ) -> List[Dict[str, Any]]:
        source_statements = self._collect_fallback_source_statements(topic=topic, context=context)
        normalized_focus = [concept.strip() for concept in (focus_concepts or []) if concept and concept.strip()]
        used_signatures = set(used_distractor_signatures or set())
        generated: List[Dict[str, Any]] = []
        for index in range(count):
            source = self._clean_statement(source_statements[index % len(source_statements)])
            distractors = self._build_plausible_distractors(
                correct_statement=source,
                topic=topic,
                context=context,
                source_statements=source_statements,
                used_distractor_signatures=used_signatures,
            )
            focus_concept = normalized_focus[index % len(normalized_focus)] if normalized_focus else ""
            options = self._normalize_question_options(
                question_text=f"{topic}|{quiz_mode}|{focus_concept or index}",
                options=[source] + distractors,
                correct_answer=source,
            )
            question_text = (
                self._build_focus_revision_question_text(topic=topic, focus_concept=focus_concept, quiz_mode=quiz_mode)
                if focus_concept
                else self._build_revision_question_text(topic=topic, source=source)
            )
            explanation = f"The correct option matches the local notes on {topic}: {source}."
            if focus_concept:
                explanation = f"This {quiz_mode.replace('_', ' ')} item is centered on {focus_concept}. {explanation}"
            generated.append(
                {
                    "concept": focus_concept or f"Revision {index + 1}",
                    "question": question_text,
                    "options": options,
                    "correct_answer": source,
                    "explanation": explanation,
                }
            )
            for distractor in distractors:
                signature = self._distractor_signature(distractor)
                if signature:
                    used_signatures.add(signature)
        return generated








