"""Reference vocabularies: departments, topics, venues, agencies, SDG rules."""
from __future__ import annotations

import re

DEPARTMENTS = {
    "CSE": ("Computer Science & Engineering", "Computing",
            ["Machine Learning", "Deep Learning", "Federated Learning", "Natural Language Processing", "Computer Vision",
             "Large Language Models", "Graph Neural Networks", "Cloud Computing", "Edge Computing", "Blockchain",
             "Software Engineering", "Information Retrieval", "Recommender Systems", "Reinforcement Learning"],
            ["fake news detection", "medical image segmentation", "crop disease detection", "traffic forecasting",
             "task scheduling in data centres", "code review automation", "regional-language question answering",
             "sign language recognition", "e-learning analytics", "legal document search", "student dropout prediction"]),
    "AIDS": ("Artificial Intelligence & Data Science", "Computing",
             ["Explainable AI", "Time Series Forecasting", "Causal Inference", "MLOps", "Healthcare Analytics",
              "Graph Analytics", "Data Mining", "Large Language Models", "Machine Learning", "Generative AI"],
             ["hospital readmission prediction", "rainfall forecasting", "credit risk scoring", "energy demand forecasting",
              "drug–drug interaction prediction", "customer churn analysis", "air-quality forecasting",
              "clinical note summarisation", "retail demand planning"]),
    "CYS": ("Cyber Security", "Computing",
            ["Intrusion Detection", "Cryptography", "Malware Analysis", "Network Security", "Privacy-Preserving ML",
             "IoT Security", "Digital Forensics", "Post-Quantum Cryptography", "Blockchain"],
            ["smart-grid attack detection", "Android malware classification", "phishing URL detection",
             "secure vehicular communication", "ransomware early warning", "UPI fraud detection",
             "medical IoT authentication", "deepfake forensics"]),
    "ECE": ("Electronics & Communication Engineering", "Engineering",
            ["VLSI Design", "Wireless Communication", "6G Networks", "Signal Processing", "Internet of Things", "LoRaWAN",
             "Antenna Design", "Embedded Systems", "Reconfigurable Intelligent Surfaces", "Biomedical Signal Processing",
             "Wireless Sensor Networks"],
            ["rural broadband access", "ECG arrhythmia detection", "smart agriculture monitoring", "low-power wearables",
             "vehicle-to-everything links", "satellite IoT backhaul", "indoor localisation", "fall detection for the elderly",
             "flood early-warning sensing"]),
    "EEE": ("Electrical & Electronics Engineering", "Engineering",
            ["Power Electronics", "Smart Grid", "Renewable Energy Integration", "Electric Vehicles",
             "Battery Management Systems", "Control Systems", "Microgrids", "Power Quality", "Green Hydrogen"],
            ["rooftop solar integration", "EV charging stations", "rural microgrid planning", "grid frequency regulation",
             "battery state-of-health estimation", "wind–solar hybrid plants", "electric two-wheelers",
             "harmonic mitigation in distribution feeders"]),
    "MECH": ("Mechanical Engineering", "Engineering",
             ["Additive Manufacturing", "Computational Fluid Dynamics", "Robotics", "Composite Materials",
              "Thermal Engineering", "Tribology", "Finite Element Analysis", "Digital Twins", "Industry 4.0"],
             ["lightweight automotive brackets", "battery thermal management", "agricultural harvesting robots",
              "turbine blade cooling", "prosthetic limb design", "predictive maintenance of CNC machines",
              "biodegradable packaging", "heat exchangers for solar dryers"]),
    "CIVIL": ("Civil Engineering", "Engineering",
              ["Structural Health Monitoring", "Sustainable Construction Materials", "Geotechnical Engineering",
               "Water Resources", "Transportation Engineering", "Remote Sensing & GIS", "Climate Resilience"],
              ["bridge damage detection", "fly-ash concrete", "landslide susceptibility mapping", "urban flood modelling",
               "pavement condition assessment", "groundwater recharge planning", "metro rail ridership",
               "coastal erosion monitoring"]),
    "CHEM": ("Chemistry", "Sciences",
             ["Catalysis", "Green Chemistry", "Nanomaterials", "Electrochemistry", "Polymer Chemistry",
              "Computational Chemistry", "Photocatalysis", "Green Hydrogen"],
             ["dye degradation in textile effluents", "CO2 reduction", "biodegradable polymers", "sodium-ion batteries",
              "heavy-metal sensing in water", "hydrogen evolution", "drug-delivery carriers", "corrosion inhibition"]),
    "PHY": ("Physics", "Sciences",
            ["Condensed Matter", "Quantum Computing", "Photonics", "Thin Films", "Spintronics", "Astrophysics",
             "Materials Simulation"],
            ["perovskite solar cells", "quantum key distribution", "gas sensing", "fibre-optic sensing",
             "exoplanet atmospheres", "topological insulators", "LED efficiency"]),
    "MATH": ("Mathematics", "Sciences",
             ["Graph Theory", "Optimization", "Fuzzy Systems", "Numerical Methods", "Statistics",
              "Mathematical Modelling", "Cryptography"],
             ["epidemic spread", "supply network design", "decision making under uncertainty", "tumour growth",
              "traffic flow", "portfolio selection", "network reliability"]),
    "BIO": ("Biotechnology", "Life Sciences",
            ["Genomics", "Bioinformatics", "Drug Discovery", "Microbiology", "Tissue Engineering", "Biosensors",
             "Plant Biotechnology"],
            ["antimicrobial resistance", "diabetic wound healing", "rice blast resistance", "cancer biomarkers",
             "probiotic formulations", "tuberculosis diagnostics", "millet nutrition"]),
    "MGMT": ("Management Studies", "Management",
             ["Supply Chain Analytics", "Marketing Analytics", "Fintech", "Organisational Behaviour",
              "Sustainability Management", "Entrepreneurship", "Business Analytics"],
             ["MSME digital adoption", "rural e-commerce", "employee well-being", "green supply chains",
              "UPI adoption", "women-led start-ups", "consumer trust in online reviews"]),
    "ENV": ("Environmental Science", "Sciences",
            ["Climate Resilience", "Remote Sensing & GIS", "Water Resources", "Air Quality", "Biodiversity",
             "Glaciology", "Ecology"],
            ["Himalayan glacier retreat", "forest-fire risk mapping", "spring-shed revival", "urban heat islands",
             "river water quality", "carbon sequestration in forests", "landslide early warning"]),
}

RISING = {  # topic -> year it starts taking off
    "Large Language Models": 2022, "Generative AI": 2022, "Federated Learning": 2019, "Post-Quantum Cryptography": 2021,
    "Electric Vehicles": 2018, "Green Hydrogen": 2021, "Reconfigurable Intelligent Surfaces": 2020,
    "Quantum Computing": 2019, "Explainable AI": 2019, "Graph Neural Networks": 2019, "Digital Twins": 2020,
    "MLOps": 2021, "Battery Management Systems": 2019, "Climate Resilience": 2019, "6G Networks": 2021,
    "Privacy-Preserving ML": 2020, "Causal Inference": 2020,
}
DECLINING = {"Cloud Computing", "Fuzzy Systems", "Thin Films", "Wireless Sensor Networks", "Data Mining",
             "Power Quality", "Tribology"}


def topic_weight(topic: str, year: int) -> float:
    if topic in RISING:
        s = RISING[topic]
        if year < s - 1:
            return 0.0 if topic in ("Large Language Models", "Generative AI") else 0.15
        return min(3.2, 0.7 + 0.55 * (year - s))
    if topic in DECLINING:
        return max(0.25, 1.7 - 0.13 * (year - 2015))
    return 1.0


VENUES = {
    "Computing": {
        "journal": [("IEEE Access", "Q1"), ("Expert Systems with Applications", "Q1"), ("Neurocomputing", "Q1"),
                    ("Applied Soft Computing", "Q1"), ("IEEE Transactions on Neural Networks and Learning Systems", "Q1"),
                    ("Pattern Recognition Letters", "Q2"), ("Multimedia Tools and Applications", "Q2"),
                    ("The Journal of Supercomputing", "Q2"), ("Cluster Computing", "Q2"),
                    ("Computers & Security", "Q1"), ("SN Computer Science", "Q3"),
                    ("International Journal of Information Technology", "Q3"),
                    ("Journal of Intelligent & Fuzzy Systems", "Q3"), ("International Journal of Advanced Computer Science and Applications", "Q4")],
        "conference": ["IEEE ICASSP", "ACM CIKM", "IEEE INDICON", "COMSNETS", "IEEE TENCON", "ICACCI", "ICCCNT",
                       "Procedia Computer Science (ICMLDE)", "IEEE BigData", "ACM CODS-COMAD", "NeurIPS Workshops"],
    },
    "Engineering": {
        "journal": [("IEEE Transactions on Industrial Electronics", "Q1"), ("IEEE Internet of Things Journal", "Q1"),
                    ("IEEE Access", "Q1"), ("Energy", "Q1"), ("Applied Energy", "Q1"), ("Sensors", "Q2"),
                    ("Electronics", "Q2"), ("Wireless Personal Communications", "Q3"),
                    ("Journal of Electrical Engineering & Technology", "Q3"), ("International Journal of Electronics", "Q3"),
                    ("Microsystem Technologies", "Q3"), ("Journal of Circuits, Systems and Computers", "Q4"),
                    ("Construction and Building Materials", "Q1"), ("Journal of Manufacturing Processes", "Q1"),
                    ("Materials Today: Proceedings", "Q4")],
        "conference": ["IEEE PEDES", "IEEE INDICON", "IEEE TENCON", "IEEE ICC Workshops", "COMSNETS", "IEEE VTC",
                       "IEEE PESGRE", "ICCCNT", "Springer LNEE (ICEE)", "ASME IMECE"],
    },
    "Sciences": {
        "journal": [("Journal of Materials Chemistry A", "Q1"), ("ACS Applied Materials & Interfaces", "Q1"),
                    ("Physical Review B", "Q1"), ("Chemical Engineering Journal", "Q1"), ("Scientific Reports", "Q1"),
                    ("RSC Advances", "Q2"), ("Journal of Alloys and Compounds", "Q1"), ("ChemistrySelect", "Q3"),
                    ("Journal of Molecular Structure", "Q2"), ("Optik", "Q2"), ("Physica Scripta", "Q2"),
                    ("Indian Journal of Physics", "Q3"), ("Journal of the Indian Chemical Society", "Q4"),
                    ("Mathematics", "Q2"), ("Applied Mathematics and Computation", "Q1"), ("Soft Computing", "Q2"),
                    ("Science of the Total Environment", "Q1"), ("Environmental Monitoring and Assessment", "Q2"),
                    ("Journal of Earth System Science", "Q3")],
        "conference": ["DAE Solid State Physics Symposium", "AIP Conference Proceedings (ICMSE)",
                       "International Conference on Nanoscience", "Springer Proceedings in Mathematics",
                       "EGU General Assembly"],
    },
    "Life Sciences": {
        "journal": [("Frontiers in Microbiology", "Q1"), ("International Journal of Biological Macromolecules", "Q1"),
                    ("Scientific Reports", "Q1"), ("PLOS ONE", "Q1"), ("Biosensors and Bioelectronics", "Q1"),
                    ("3 Biotech", "Q2"), ("Journal of Biomolecular Structure and Dynamics", "Q2"),
                    ("Molecular Biology Reports", "Q2"), ("Indian Journal of Microbiology", "Q3"),
                    ("Current Science", "Q4")],
        "conference": ["InBix Bioinformatics Conference", "Annual Meeting of the Society of Biological Chemists (India)"],
    },
    "Management": {
        "journal": [("Journal of Business Research", "Q1"), ("Technological Forecasting and Social Change", "Q1"),
                    ("International Journal of Production Economics", "Q1"), ("Benchmarking: An International Journal", "Q2"),
                    ("Journal of Retailing and Consumer Services", "Q1"), ("Global Business Review", "Q2"),
                    ("Vision: The Journal of Business Perspective", "Q3"), ("Indian Journal of Marketing", "Q4")],
        "conference": ["IIM Indore Doctoral Colloquium", "Academy of Management Annual Meeting",
                       "International Conference on Business Analytics (ICBA)"],
    },
}
CHAPTER_VENUES = ["Springer Lecture Notes in Networks and Systems", "CRC Press — Handbook chapter",
                  "Elsevier — Advances in Computers", "IGI Global — book chapter", "Springer Studies in Computational Intelligence",
                  "Wiley — Smart Systems series"]


def venue_group(field: str) -> str:
    return field if field in VENUES else "Sciences"


EXTERNAL_AFFILS = [
    ("IIT Madras", "India"), ("IIT Bombay", "India"), ("IIT Delhi", "India"), ("IIT Kharagpur", "India"),
    ("IISc Bengaluru", "India"), ("IIIT Hyderabad", "India"), ("Anna University", "India"),
    ("University of Hyderabad", "India"), ("TIFR Mumbai", "India"), ("CSIR-NCL Pune", "India"),
    ("ISRO Space Applications Centre", "India"), ("IIT Roorkee", "India"), ("Jadavpur University", "India"),
    ("National University of Singapore", "Singapore"), ("University of Melbourne", "Australia"),
    ("Technical University of Munich", "Germany"), ("University of Glasgow", "United Kingdom"),
    ("KAIST", "South Korea"), ("University of Tokyo", "Japan"), ("Aalto University", "Finland"),
    ("Monash University", "Australia"), ("University of Toronto", "Canada"), ("Imperial College London", "United Kingdom"),
    ("ETH Zurich", "Switzerland"), ("UC San Diego", "United States"), ("Khalifa University", "UAE"),
    ("Universiti Malaya", "Malaysia"), ("Queensland University of Technology", "Australia"),
    ("University of Twente", "Netherlands"), ("Texas A&M University", "United States"),
]

AGENCIES = {
    # agency: (sector, [schemes], (min_lakh, max_lakh), fields-or-None)
    "SERB": ("government", ["Core Research Grant", "Start-up Research Grant", "MATRICS"], (12, 55), None),
    "ANRF": ("government", ["Core Research Grant", "PM Early Career Research Grant", "ARG-MATRICS"], (15, 70), None),
    "DST": ("government", ["FIST", "Technology Development Programme", "SERI", "WOS-A"], (10, 180), None),
    "DBT": ("government", ["BioCARe", "Rapid Grant for Young Investigators", "Twinning programme"], (20, 90), {"Life Sciences", "Sciences"}),
    "MeitY": ("government", ["R&D in IT", "Chips to Startup", "Cyber Security R&D"], (25, 150), {"Computing", "Engineering"}),
    "DRDO": ("government", ["Extramural Research"], (20, 85), {"Computing", "Engineering", "Sciences"}),
    "ISRO": ("government", ["RESPOND"], (8, 30), {"Engineering", "Sciences", "Computing"}),
    "CSIR": ("government", ["Extramural Research"], (10, 40), {"Sciences", "Life Sciences"}),
    "ICSSR": ("government", ["Major Research Project", "Minor Research Project"], (5, 25), {"Management"}),
    "AICTE": ("government", ["Research Promotion Scheme", "MODROBS"], (8, 20), {"Computing", "Engineering", "Management"}),
    "MoES": ("government", ["Monsoon Mission", "Ocean Services"], (15, 60), {"Sciences"}),
    "Industry": ("industry", ["Sponsored research", "Consultancy"], (3, 45), None),
    "International": ("international", ["Indo-German (DAAD)", "UKIERI", "Indo-Australian Strategic Fund"], (12, 70), None),
    "Internal": ("internal", ["Seed grant"], (1, 6), None),
}

SDG_NAMES = {
    2: "Zero hunger", 3: "Good health", 4: "Quality education", 6: "Clean water", 7: "Clean energy",
    8: "Decent work & growth", 9: "Industry & innovation", 11: "Sustainable cities", 12: "Responsible consumption",
    13: "Climate action", 14: "Life below water", 15: "Life on land", 16: "Peace, justice & institutions",
}
SDG_RULES = [
    (3, r"health|medical|disease|drug|cancer|clinic|biosens|ecg|patient|diabet|tissue|wound|tubercul|hospital|prosthe|antimicrob|fall detection|biomark"),
    (2, r"crop|agri|food|plant|soil|millet|harvest|rice blast"),
    (6, r"water|wastewater|effluent|groundwater|spring-shed"),
    (7, r"energy|solar|battery|grid|renewable|hydrogen|electric vehicle|\bev\b|photovolt|wind|perovskite|microgrid|sodium-ion"),
    (9, r"industr|manufactur|infrastructure|internet of things|iot|6g|5g|additive|digital twin|cnc|broadband|chips|vlsi"),
    (11, r"city|cities|traffic|transport|urban|structural|bridge|metro|pavement|flood"),
    (12, r"recycl|green chem|sustainab|supply chain|waste|biodegrad|packaging"),
    (13, r"climate|carbon|co2|emission|rainfall|glacier|heat island|monsoon"),
    (4, r"e-learning|student|education|dropout"),
    (8, r"fintech|employ|entrepreneur|msme|start-up|economic|upi|credit"),
    (16, r"security|privacy|fraud|forensic|intrusion|malware|fake news|phishing|ransomware|deepfake|cryptograph|legal"),
    (15, r"forest|biodiversity|landslide|ecolog|land use"),
    (14, r"ocean|marine|coastal"),
]


def sdgs_for(text: str) -> list[int]:
    t = text.lower()
    return sorted({goal for goal, pat in SDG_RULES if re.search(pat, t)})


ADJ = ["lightweight", "scalable", "energy-efficient", "robust", "interpretable", "privacy-aware", "low-cost",
       "real-time", "hybrid", "adaptive", "uncertainty-aware", "resource-constrained", "data-efficient", "secure"]
STUDY = ["comparative study", "systematic review", "case study from South India", "benchmark study",
         "field deployment", "large-scale evaluation", "pilot study"]
FRAME = ["hybrid", "two-stage", "multi-objective", "data-driven", "physics-informed", "attention-based", "ensemble"]
SUFFIX = ["Net", "Sense", "Lite", "Guard", "Fuse", "Scope", "Former", "Flow", "Sight", "Mesh"]

FIRST = ["Aarav", "Aditi", "Akash", "Ananya", "Anjali", "Arjun", "Arun", "Bhavana", "Chitra", "Deepak", "Devika", "Divya",
         "Gautam", "Gayathri", "Harini", "Harish", "Ishaan", "Janani", "Karthik", "Kavya", "Keerthana", "Kiran", "Lakshmi",
         "Madhav", "Mahesh", "Manasa", "Meera", "Mohan", "Nandini", "Naveen", "Neha", "Nikhil", "Nisha", "Pallavi",
         "Pooja", "Pradeep", "Pranav", "Priya", "Rahul", "Rajesh", "Ramya", "Ravi", "Rohan", "Sahana", "Sanjay", "Sarita",
         "Shreya", "Siddharth", "Sneha", "Sowmya", "Sriram", "Sudha", "Suresh", "Swathi", "Tanvi", "Tarun", "Uma",
         "Varun", "Vidya", "Vignesh", "Vikram", "Vinay", "Yamini", "Zoya", "Farhan", "Imran", "Ayesha", "Joseph",
         "Mary", "Thomas", "Anil", "Ritu", "Amit", "Sunita", "Gurpreet", "Harpreet", "Debashis", "Sourav", "Ankita",
         "Riya", "Abhishek", "Lavanya", "Pavithra", "Hemant", "Jyoti", "Kunal", "Mitali", "Nirmala", "Omkar", "Parvathy"]
LAST = ["Iyer", "Nair", "Menon", "Pillai", "Rao", "Reddy", "Naidu", "Krishnan", "Subramanian", "Raman", "Sharma", "Verma",
        "Gupta", "Mishra", "Pandey", "Tiwari", "Singh", "Chauhan", "Joshi", "Kulkarni", "Deshpande", "Patil", "Shetty",
        "Hegde", "Bhat", "Kamath", "Das", "Banerjee", "Chatterjee", "Mukherjee", "Sen", "Bose", "Ghosh", "Mehta",
        "Shah", "Patel", "Desai", "Khan", "Ahmed", "Siddiqui", "Thomas", "George", "Varghese", "Kurian", "Mathew",
        "Fernandes", "D'Souza", "Kaur", "Gill", "Saxena", "Agarwal", "Bhattacharya", "Mohanty", "Patnaik", "Sahu",
        "Venkatesh", "Ramesh", "Murthy", "Prasad", "Chandran", "Balakrishnan", "Sundaram", "Ganesan", "Arora", "Kapoor"]
EXT_FIRST = ["James", "Emma", "Lukas", "Sofia", "Hiroshi", "Min-jun", "Olivia", "Noah", "Chen", "Wei", "Aiko", "Mateo",
             "Elena", "Jonas", "Amelia", "Liam", "Fatima", "Omar", "Hannah", "Kai", "Ingrid", "Marco", "Yuki", "Grace"]
EXT_LAST = ["Smith", "Müller", "Rossi", "Tanaka", "Kim", "Chen", "Wang", "García", "Johansson", "Brown", "Nguyen",
            "Schmidt", "Lee", "Martin", "Kowalski", "Okafor", "Haddad", "Wilson", "Novak", "Larsen", "Sato", "Park"]
