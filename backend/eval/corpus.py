"""Synthetic evaluation corpus with ground-truth relevance judgments.

Each document is kept short (< ~400 tokens) so it ingests as exactly one
chunk - document-level relevance == chunk-level relevance, which keeps the
ground truth unambiguous.

Doc IDs are stable strings; the harness maps them to DB ids after ingest.
"""

DOCS: dict[str, dict[str, str]] = {
    # ---- factoid docs ----
    "D1": {
        "filename": "atlas_rocket.txt",
        "text": (
            "The Atlas V rocket's first stage, the Common Core Booster, burns "
            "RP-1 kerosene refined for rocket use together with liquid oxygen. "
            "The RD-180 engine produces about 860,000 pounds of thrust at sea level. "
            "Atlas V launches from Cape Canaveral and Vandenberg."
        ),
    },
    "D2": {
        "filename": "marie_curie.txt",
        "text": (
            "Marie Curie won the Nobel Prize in Physics in 1903, shared with Pierre "
            "Curie and Henri Becquerel for work on radioactivity, and the Nobel Prize "
            "in Chemistry in 1911 for the discovery of radium and polonium. She remains "
            "the only person to win Nobel Prizes in two different sciences."
        ),
    },
    "D3": {
        "filename": "eiffel_tower.txt",
        "text": (
            "The Eiffel Tower in Paris stands 330 meters tall including its antennas. "
            "Completed in 1889 for the World's Fair, it was designed by Gustave Eiffel's "
            "engineering company. It was the tallest man-made structure until 1930."
        ),
    },
    "D4": {
        "filename": "photosynthesis.txt",
        "text": (
            "Photosynthesis occurs in the chloroplasts of plant cells, where chlorophyll "
            "captures sunlight. Carbon dioxide and water are converted into glucose and "
            "oxygen. The light-dependent reactions happen in the thylakoid membranes."
        ),
    },
    # ---- multi-hop docs (answer needs BOTH) ----
    "D5": {
        "filename": "helix_voss.txt",
        "text": (
            "Dr. Elena Voss leads the Quantum Optics laboratory at the Helix Institute "
            "in Zurich. Her team of fourteen researchers focuses on photonic quantum "
            "computing and single-photon sources."
        ),
    },
    "D6": {
        "filename": "helix_breakthrough.txt",
        "text": (
            "In March 2024 the Quantum Optics laboratory at the Helix Institute announced "
            "a breakthrough: a room-temperature photonic qubit with 99.2% fidelity, "
            "published in Nature Photonics. The result was achieved with silicon nitride waveguides."
        ),
    },
    # ---- conflicting docs ----
    "D7": {
        "filename": "meridian_census.txt",
        "text": (
            "According to the official 2023 census, the city of Meridian has a population "
            "of 850,000 residents within the city limits. The census bureau published "
            "these figures in January 2024."
        ),
    },
    "D8": {
        "filename": "meridian_survey.txt",
        "text": (
            "The 2024 metropolitan survey estimates Meridian's population at 1.2 million "
            "people across the greater metro area. Urban planners cite rapid suburban "
            "growth as the reason for the higher figure."
        ),
    },
    # ---- noise / distractor docs (share keywords, wrong topic) ----
    "N1": {
        "filename": "rocket_salad_recipe.txt",
        "text": (
            "This rocket salad recipe combines peppery arugula, also called rocket, with "
            "parmesan shavings and lemon dressing. Toss the rocket leaves gently so they "
            "don't bruise. Serve chilled as a starter."
        ),
    },
    "N2": {
        "filename": "tower_of_babel.txt",
        "text": (
            "The Tower of Babel story describes humanity's attempt to build a tower to "
            "heaven. In chess, a rook is sometimes called a tower. None of these towers "
            "have a measured height in meters."
        ),
    },
    "N3": {
        "filename": "curie_lab_safety.txt",
        "text": (
            "The Curie laboratory safety manual requires dosimeters for all staff. Nobel "
            "laureates visiting the lab must complete the same safety induction. Prizes "
            "and awards are displayed in the lobby."
        ),
    },
    "N4": {
        "filename": "zurich_tourism.txt",
        "text": (
            "Zurich tourism highlights the old town, Lake Zurich, and the Helix Institute's "
            "public science museum. Guided laboratory tours run on weekends but the "
            "Quantum Optics lab itself is closed to visitors."
        ),
    },
    "N5": {
        "filename": "census_methods.txt",
        "text": (
            "Census methods vary by country: door-to-door counts, register-based censuses, "
            "and rolling surveys. Population figures for Meridian differ between sources "
            "because city limits and metro areas are counted differently."
        ),
    },
    "N6": {
        "filename": "greenhouse_guide.txt",
        "text": (
            "A greenhouse guide for chloroplast-rich leafy greens: keep humidity high and "
            "temperatures near 22C. Photosynthesis slows when leaves overheat, so provide "
            "shade cloth in summer."
        ),
    },
}

# query_id -> {question, relevant doc ids (ground truth), kind}
QUERIES: dict[str, dict] = {
    "Q1": {
        "question": "What fuel does the Atlas rocket's first stage burn?",
        "relevant": ["D1"],
        "kind": "factoid",
    },
    "Q2": {
        "question": "In which years did Marie Curie win her Nobel Prizes?",
        "relevant": ["D2"],
        "kind": "factoid",
    },
    "Q3": {
        "question": "How tall is the Eiffel Tower?",
        "relevant": ["D3"],
        "kind": "factoid",
    },
    "Q4": {
        "question": "Where in the cell does photosynthesis occur?",
        "relevant": ["D4"],
        "kind": "factoid",
    },
    "Q5": {
        "question": "What breakthrough did Dr. Elena Voss's lab announce and when?",
        "relevant": ["D5", "D6"],
        "kind": "multi-hop",
    },
    "Q6": {
        "question": "What is the capital of the fictional country of Xylophia?",
        "relevant": [],
        "kind": "unanswerable",
    },
    "Q7": {
        "question": "How many moons does the exoplanet Kepler-99b have?",
        "relevant": [],
        "kind": "unanswerable",
    },
    "Q8": {
        "question": "What is the population of Meridian?",
        "relevant": ["D7", "D8"],
        "kind": "conflicting",
    },
    "Q9": {
        "question": "Which lab published the room-temperature photonic qubit result?",
        "relevant": ["D6"],
        "kind": "factoid",
    },
    "Q10": {
        "question": "Tell me about rocket launch thrust and propellant.",
        "relevant": ["D1"],
        "kind": "noisy",  # N1 shares the word "rocket"
    },
}
