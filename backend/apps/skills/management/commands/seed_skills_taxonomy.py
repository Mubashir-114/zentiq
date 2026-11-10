"""
Management command to seed the 8 core ZENTIQ skill domains, subdomains, and competencies.
Idempotent: uses get_or_create to safely run in any environment.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from apps.skills.models import Domain, Subdomain, Competency


TAXONOMY_DATA = [
    {
        'slug': 'numerical_intelligence',
        'name': 'Numerical Intelligence',
        'category': 'COGNITIVE',
        'description': 'Quantitative problem solving, numerical sequence recognition, probabilistic estimation, and mathematical reasoning.',
        'icon_key': 'Calculator',
        'display_order': 1,
        'subdomains': [
            {
                'slug': 'quantitative-arithmetic',
                'name': 'Quantitative Arithmetic',
                'description': 'Mental math, ratio operations, percentage scaling, and dimensional unit conversion.',
                'competencies': [
                    ('NUM-ARITH-01', 'Mental Arithmetic & Ratio Operations', 'Rapid calculation, proportional scaling, and ratio decomposition.', 'APPLY'),
                    ('NUM-ARITH-02', 'Percentage & Compounded Rate Dynamics', 'Financial and statistical compounding calculations.', 'APPLY'),
                    ('NUM-ARITH-03', 'Dimensional Analysis & Metric Conversion', 'Multi-unit conversion and dimensional consistency reasoning.', 'UNDERSTAND'),
                ],
            },
            {
                'slug': 'probability-statistics',
                'name': 'Probability & Statistics',
                'description': 'Bayesian likelihood, expected value, distributions, and risk estimation.',
                'competencies': [
                    ('NUM-PROB-01', 'Bayesian & Conditional Likelihood', 'Independent vs. dependent event probabilities and Bayesian updating.', 'ANALYZE'),
                    ('NUM-PROB-02', 'Expected Value & Risk Estimation', 'Decision tree expected payout and risk profile calculation.', 'EVALUATE'),
                    ('NUM-PROB-03', 'Variance & Normal Distributions', 'Standard deviation, dispersion, and percentile interpretation.', 'UNDERSTAND'),
                ],
            },
            {
                'slug': 'sequence-pattern-deduction',
                'name': 'Sequence & Pattern Deduction',
                'description': 'Polynomial, geometric, and recursive sequence interpolation.',
                'competencies': [
                    ('NUM-SEQ-01', 'Arithmetic & Geometric Progressions', 'Next-element prediction in multi-step sequences.', 'APPLY'),
                    ('NUM-SEQ-02', 'Recursive & Non-linear Series', 'Fibonacci, alternating, and modular progressions.', 'ANALYZE'),
                ],
            },
            {
                'slug': 'data-interpretation',
                'name': 'Data Interpretation',
                'description': 'Multi-source chart extraction, comparative rate-of-change, and tabular synthesis.',
                'competencies': [
                    ('NUM-DATA-01', 'Multi-Source Chart & Table Extraction', 'Synthesizing metrics across complex figures and tables.', 'ANALYZE'),
                    ('NUM-DATA-02', 'Comparative Rate-of-Change Analysis', 'Growth curve divergence and inflection deduction.', 'EVALUATE'),
                ],
            },
        ],
    },
    {
        'slug': 'logical_reasoning',
        'name': 'Logical Reasoning',
        'category': 'COGNITIVE',
        'description': 'Deductive and inductive logic, syllogistic inference, truth table analysis, and conditional relationship deduction.',
        'icon_key': 'Brain',
        'display_order': 2,
        'subdomains': [
            {
                'slug': 'deductive-syllogisms',
                'name': 'Deductive Syllogisms',
                'description': 'Categorical syllogisms, quantifier logic, and conditional validity.',
                'competencies': [
                    ('LOG-SYLL-01', 'Categorical Syllogisms & Quantifier Logic', 'Validating conclusions from categorical premises.', 'ANALYZE'),
                    ('LOG-SYLL-02', 'Modus Ponens & Modus Tollens Inferences', 'Validating conditional arguments and contrapositives.', 'ANALYZE'),
                ],
            },
            {
                'slug': 'propositional-boolean-logic',
                'name': 'Propositional & Boolean Logic',
                'description': 'Truth tables, De Morgan laws, and conditional necessity vs. sufficiency.',
                'competencies': [
                    ('LOG-BOOL-01', 'Truth Table & Compound Statement Evaluation', 'Evaluating compound Boolean logic circuits.', 'APPLY'),
                    ('LOG-BOOL-02', 'De Morgan Laws & Logic Simplification', 'Simplifying complex propositional expressions.', 'APPLY'),
                    ('LOG-BOOL-03', 'Necessary vs. Sufficient Condition Analysis', 'Isolating prerequisite conditional requirements.', 'EVALUATE'),
                ],
            },
            {
                'slug': 'relational-logic-puzzles',
                'name': 'Relational Logic & Puzzles',
                'description': 'Grid elimination, circular arrangements, and network constraint traversal.',
                'competencies': [
                    ('LOG-PUZ-01', 'Elimination Grid & Constraint Puzzles', 'Deducing unique attribute pairings under constraints.', 'ANALYZE'),
                    ('LOG-PUZ-02', 'Sequential & Ordinal Arrangements', 'Ordering elements under transitive relation constraints.', 'APPLY'),
                ],
            },
        ],
    },
    {
        'slug': 'verbal_intelligence',
        'name': 'Verbal Intelligence',
        'category': 'COGNITIVE',
        'description': 'Lexical precision, contextual comprehension, semantic relationship mapping, and nuanced linguistic analysis.',
        'icon_key': 'BookOpen',
        'display_order': 3,
        'subdomains': [
            {
                'slug': 'lexical-precision',
                'name': 'Lexical Precision',
                'description': 'Contextual word disambiguation, etymology, and morphological inference.',
                'competencies': [
                    ('VRB-LEX-01', 'Contextual Word Disambiguation', 'Disambiguating polysemous words within dense prose.', 'UNDERSTAND'),
                    ('VRB-LEX-02', 'Etymological & Morphological Inference', 'Deciphering unfamiliar vocabulary via morphological roots.', 'APPLY'),
                ],
            },
            {
                'slug': 'reading-comprehension',
                'name': 'Reading Comprehension & Synthesis',
                'description': 'Thesis extraction, implicit premises, and rhetorical tone analysis.',
                'competencies': [
                    ('VRB-COMP-01', 'Thesis & Primary Intent Extraction', 'Isolating central arguments in complex technical passages.', 'ANALYZE'),
                    ('VRB-COMP-02', 'Implicit Premise & Inference Extraction', 'Deducing unstated claims grounded in textual evidence.', 'ANALYZE'),
                    ('VRB-COMP-03', 'Rhetorical Tone & Authorial Stance', 'Classifying authorial bias and argumentative posture.', 'EVALUATE'),
                ],
            },
            {
                'slug': 'semantic-relationships',
                'name': 'Semantic Relationships',
                'description': 'High-order verbal analogies and semantic nuance calibration.',
                'competencies': [
                    ('VRB-SEM-01', 'High-Order Verbal Analogies', 'Identifying multi-attribute semantic analogies.', 'ANALYZE'),
                    ('VRB-SEM-02', 'Semantic Nuance & Antonym Calibration', 'Calibrating words across intensity spectra.', 'EVALUATE'),
                ],
            },
        ],
    },
    {
        'slug': 'analytical_thinking',
        'name': 'Analytical Thinking',
        'category': 'ANALYTICAL',
        'description': 'Deconstructing complex multifaceted systems, identifying root causes, and formulating structured resolution models.',
        'icon_key': 'LineChart',
        'display_order': 4,
        'subdomains': [
            {
                'slug': 'root-cause-analysis',
                'name': 'Root Cause Analysis',
                'description': '5-Whys causal chaining and failure mode deduction.',
                'competencies': [
                    ('ANA-ROOT-01', '5-Whys Causal Chain Construction', 'Distinguishing proximate symptoms from root triggers.', 'ANALYZE'),
                    ('ANA-ROOT-02', 'Fault Tree & Failure Mode Deduction', 'Identifying single points of failure in systems.', 'EVALUATE'),
                ],
            },
            {
                'slug': 'system-decomposition',
                'name': 'System Decomposition',
                'description': 'Subsystem boundary delineation and bottleneck identification.',
                'competencies': [
                    ('ANA-DECOMP-01', 'Boundary & Interface Delineation', 'Subsystem isolation and input/output contract definition.', 'UNDERSTAND'),
                    ('ANA-DECOMP-02', 'Feedback Loop & Bottleneck Identification', 'Detecting feedback cycles and flow constraints.', 'ANALYZE'),
                ],
            },
            {
                'slug': 'structured-problem-framing',
                'name': 'Structured Problem Framing',
                'description': 'MECE partitioning and multi-criteria trade-off scoring.',
                'competencies': [
                    ('ANA-FRAME-01', 'MECE Problem Partitioning', 'Partitioning problem domains without overlaps or gaps.', 'APPLY'),
                    ('ANA-FRAME-02', 'Multi-Criteria Trade-off Scoring', 'Scoring competing options against weighted operational criteria.', 'EVALUATE'),
                ],
            },
        ],
    },
    {
        'slug': 'spatial_intelligence',
        'name': 'Spatial Intelligence',
        'category': 'PERCEPTUAL',
        'description': 'Mental rotation, visual-spatial transformation, topological reasoning, and 3D geometric structure analysis.',
        'icon_key': 'Box',
        'display_order': 5,
        'subdomains': [
            {
                'slug': 'mental-rotation',
                'name': 'Mental Rotation & Projections',
                'description': '2D/3D orthographic and perspective transformation.',
                'competencies': [
                    ('SPA-ROT-01', '2D Isometric & Orthographic Projection', 'Matching 3D objects with planar projections.', 'APPLY'),
                    ('SPA-ROT-02', 'Multi-Axis 3D Rotation Invariance', 'Recognizing rotated volumetric shapes under perspective.', 'ANALYZE'),
                ],
            },
            {
                'slug': 'topological-reasoning',
                'name': 'Topological Reasoning',
                'description': 'Polyhedral net folding, cross-sections, and spatial symmetry.',
                'competencies': [
                    ('SPA-TOPO-01', 'Polyhedral Net Folding & Unfolding', 'Predicting 3D face adjacencies from 2D unfolded nets.', 'ANALYZE'),
                    ('SPA-TOPO-02', 'Spatial Symmetry & Cross-Sectional Slicing', 'Visualizing planar slices of geometric solids.', 'APPLY'),
                ],
            },
        ],
    },
    {
        'slug': 'programming_logic',
        'name': 'Programming Logic',
        'category': 'TECHNICAL',
        'description': 'Algorithmic execution flow, control state tracing, recursive problem decomposition, and data structure manipulation.',
        'icon_key': 'Code2',
        'display_order': 6,
        'subdomains': [
            {
                'slug': 'algorithmic-tracing',
                'name': 'Algorithmic Tracing',
                'description': 'Loop execution, call stack recursion, and boundary edge cases.',
                'competencies': [
                    ('PROG-TRACE-01', 'Iteration & Accumulator State Tracing', 'Evaluating variable states through loop cycles.', 'APPLY'),
                    ('PROG-TRACE-02', 'Recursion Stack & Base-Case Unwinding', 'Tracing call stack frames and unwinding states.', 'ANALYZE'),
                    ('PROG-TRACE-03', 'Off-By-One & Edge-Condition Detection', 'Identifying boundary and fencepost errors.', 'EVALUATE'),
                ],
            },
            {
                'slug': 'data-structure-operations',
                'name': 'Data Structure Operations',
                'description': 'Linear structures, hashing mechanics, and tree navigation.',
                'competencies': [
                    ('PROG-DS-01', 'Linear Structure Mechanics (Stack/Queue/List)', 'Predicting mutations in FIFO/LIFO sequences.', 'UNDERSTAND'),
                    ('PROG-DS-02', 'Associative Structures & Hash Key Mechanics', 'Analyzing key lookups, hash collisions, and sets.', 'APPLY'),
                ],
            },
            {
                'slug': 'control-flow-invariants',
                'name': 'Control Flow & Invariants',
                'description': 'Short-circuit evaluations, guard clauses, and loop invariants.',
                'competencies': [
                    ('PROG-CTRL-01', 'Short-Circuit Evaluation & Guard Conditions', 'Evaluating branching execution and early exits.', 'APPLY'),
                    ('PROG-CTRL-02', 'Loop Invariants & State Preconditions', 'Formulating invariant assertions across cycles.', 'ANALYZE'),
                ],
            },
            {
                'slug': 'computational-complexity',
                'name': 'Computational Complexity',
                'description': 'Big-O time complexity and auxiliary space classification.',
                'competencies': [
                    ('PROG-CPLX-01', 'Asymptotic Time Complexity Analysis', 'Deriving Big-O runtime from code structures.', 'ANALYZE'),
                    ('PROG-CPLX-02', 'Auxiliary Space Complexity Classification', 'Classifying extra memory allocations.', 'ANALYZE'),
                ],
            },
        ],
    },
    {
        'slug': 'critical_thinking',
        'name': 'Critical Thinking',
        'category': 'ANALYTICAL',
        'description': 'Evaluating argument validity, cognitive bias detection, empirical evidence critique, and logical fallacy analysis.',
        'icon_key': 'Compass',
        'display_order': 7,
        'subdomains': [
            {
                'slug': 'fallacy-identification',
                'name': 'Fallacy Identification',
                'description': 'Formal and informal logical fallacies in reasoning.',
                'competencies': [
                    ('CRT-FAL-01', 'Informal Fallacy Detection', 'Spotting straw man, ad hominem, and false equivalence.', 'ANALYZE'),
                    ('CRT-FAL-02', 'Formal Fallacy & Affirming Consequent', 'Detecting deductive structural fallacies.', 'ANALYZE'),
                ],
            },
            {
                'slug': 'cognitive-bias-recognition',
                'name': 'Cognitive Bias Recognition',
                'description': 'Confirmation bias, availability heuristic, and sunk cost fallacy.',
                'competencies': [
                    ('CRT-BIAS-01', 'Confirmation & Availability Bias Audit', 'Identifying selective evidence usage and salience bias.', 'EVALUATE'),
                    ('CRT-BIAS-02', 'Sunk Cost & Anchoring Effects', 'Identifying irrational commitment escalation in choices.', 'EVALUATE'),
                ],
            },
            {
                'slug': 'empirical-critique',
                'name': 'Empirical Critique & Hypotheses',
                'description': 'Correlation vs causation, sampling bias, and falsifiability.',
                'competencies': [
                    ('CRT-EMP-01', 'Correlation vs. Causation Disentanglement', 'Isolating confounding variables in statistical claims.', 'ANALYZE'),
                    ('CRT-EMP-02', 'Sample Bias & Generalizability Limits', 'Evaluating statistical study sample validity.', 'EVALUATE'),
                    ('CRT-HYP-01', 'Falsifiability & Counterexample Generation', 'Formulating the crucial test that refutes a hypothesis.', 'CREATE'),
                ],
            },
        ],
    },
    {
        'slug': 'career_readiness',
        'name': 'Career Readiness',
        'category': 'APPLIED',
        'description': 'Technical interview reasoning, practical systems architecture judgment, and professional communication acumen.',
        'icon_key': 'Briefcase',
        'display_order': 8,
        'subdomains': [
            {
                'slug': 'systems-judgment',
                'name': 'Systems Judgment & Architecture',
                'description': 'Latency vs throughput, CAP theorem, and caching strategies.',
                'competencies': [
                    ('CAR-SYS-01', 'Latency vs. Throughput Architecture Trade-offs', 'Evaluating architectural trade-offs in distributed systems.', 'EVALUATE'),
                    ('CAR-SYS-02', 'Consistency vs. Availability (CAP) Selection', 'Selecting appropriate data consistency models.', 'EVALUATE'),
                ],
            },
            {
                'slug': 'technical-communication',
                'name': 'Technical Communication',
                'description': 'Requirements disambiguation, post-mortem synthesis, and stakeholder clarity.',
                'competencies': [
                    ('CAR-COMM-01', 'Ambiguity Disambiguation in Requirements', 'Formulating clarifying questions for underspecified briefs.', 'APPLY'),
                    ('CAR-COMM-02', 'Post-Mortem & Incident Framing', 'Drafting blameless post-mortem root cause summaries.', 'CREATE'),
                ],
            },
            {
                'slug': 'engineering-quality-standards',
                'name': 'Engineering Quality & Standards',
                'description': 'Technical debt triage, code review judgment, and security hygiene.',
                'competencies': [
                    ('CAR-ENG-01', 'Technical Debt Triage & Prioritization', 'Balancing immediate delivery velocity vs maintainability.', 'EVALUATE'),
                    ('CAR-ENG-02', 'Security, Privacy & OWASP Baseline', 'Identifying vulnerabilities and data privacy boundaries.', 'UNDERSTAND'),
                ],
            },
        ],
    },
]


class Command(BaseCommand):
    help = 'Seeds the 8 core ZENTIQ skill domains, subdomains, and measurable competencies.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--overwrite',
            action='store_true',
            default=False,
            help='Explicitly force-overwrite existing taxonomy attributes (e.g. name, description, is_active) with seeder defaults.',
        )

    def handle(self, *args, **options):
        overwrite = options.get('overwrite', False)
        mode_str = "with overwrite enabled" if overwrite else "in safe insert-only mode"
        self.stdout.write(self.style.NOTICE(f'Starting ZENTIQ skill taxonomy seeding ({mode_str})...'))

        created_domains = 0
        updated_domains = 0
        created_subdomains = 0
        updated_subdomains = 0
        created_competencies = 0
        updated_competencies = 0

        with transaction.atomic():
            for item in TAXONOMY_DATA:
                subdomains_data = item.get('subdomains', [])
                domain_fields = {
                    'name': item['name'],
                    'category': item['category'],
                    'description': item['description'],
                    'icon_key': item.get('icon_key', ''),
                    'display_order': item.get('display_order', 0),
                    'is_active': True,
                }
                domain, d_created = Domain.objects.get_or_create(
                    slug=item['slug'],
                    defaults=domain_fields,
                )
                if d_created:
                    created_domains += 1
                elif overwrite:
                    for attr, val in domain_fields.items():
                        setattr(domain, attr, val)
                    domain.save()
                    updated_domains += 1

                for s_idx, s_item in enumerate(subdomains_data, start=1):
                    competencies_data = s_item.get('competencies', [])
                    subdomain_fields = {
                        'name': s_item['name'],
                        'description': s_item.get('description', ''),
                        'display_order': s_idx,
                        'is_active': True,
                    }
                    subdomain, s_created = Subdomain.objects.get_or_create(
                        domain=domain,
                        slug=s_item['slug'],
                        defaults=subdomain_fields,
                    )
                    if s_created:
                        created_subdomains += 1
                    elif overwrite:
                        for attr, val in subdomain_fields.items():
                            setattr(subdomain, attr, val)
                        subdomain.save()
                        updated_subdomains += 1

                    for comp_code, comp_name, comp_desc, bloom_level in competencies_data:
                        competency_fields = {
                            'subdomain': subdomain,
                            'name': comp_name,
                            'description': comp_desc,
                            'bloom_level': bloom_level,
                            'is_active': True,
                        }
                        competency, c_created = Competency.objects.get_or_create(
                            code=comp_code,
                            defaults=competency_fields,
                        )
                        if c_created:
                            created_competencies += 1
                        elif overwrite:
                            for attr, val in competency_fields.items():
                                setattr(competency, attr, val)
                            competency.save()
                            updated_competencies += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully seeded taxonomy: {created_domains} domains created ({updated_domains} updated), '
                f'{created_subdomains} subdomains created ({updated_subdomains} updated), '
                f'{created_competencies} competencies created ({updated_competencies} updated).'
            )
        )
