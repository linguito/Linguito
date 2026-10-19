
from django.core.management.base import BaseCommand

from api.models import Language, Unit, Skill, Lesson, Exercise


COURSE = [
    {
        "title": "Introductions and Basic English",
        "description": "Learn greetings, basic words, pronouns and simple sentences.",
        "color": "#58CC02",
        "skills": [
            ("Basics 1", "egg", [
                ("boy", "ولد"), ("girl", "بنت"),
                ("water", "ماء"), ("book", "كتاب")
            ], "The boy drinks water.", "الولد يشرب الماء.",
             ("The boy ", " water.", "drinks")),
            ("Phrases", "speech", [
                ("hello", "مرحبا"), ("please", "من فضلك"),
                ("thanks", "شكرا"), ("goodbye", "إلى اللقاء")
            ], "Hello, how are you?", "مرحبا، كيف حالك؟",
             ("Good ", "!", "morning")),
            ("Basics 2", "coffee", [
                ("I", "أنا"), ("you", "أنت"),
                ("he", "هو"), ("she", "هي")
            ], "She is a student.", "هي طالبة.",
             ("She ", " a student.", "is")),
        ],
    },
    {
        "title": "Food and Everyday Conversations",
        "description": "Talk about food, drinks and everyday needs.",
        "color": "#1CB0F6",
        "skills": [
            ("Food", "bread", [
                ("bread", "خبز"), ("milk", "حليب"),
                ("apple", "تفاحة"), ("tea", "شاي")
            ], "I eat bread.", "أنا آكل الخبز.",
             ("I ", " bread.", "eat")),
            ("Animals", "bear", [
                ("cat", "قطة"), ("dog", "كلب"),
                ("bird", "طائر"), ("fish", "سمكة")
            ], "The cat is small.", "القطة صغيرة.",
             ("The cat is ", ".", "small")),
            ("Plurals", "sparkles", [
                ("books", "كتب"), ("apples", "تفاحات"),
                ("cars", "سيارات"), ("students", "طلاب")
            ], "Two books are here.", "يوجد كتابان هنا.",
             ("Two ", " are here.", "books")),
        ],
    },
    {
        "title": "Places and Directions",
        "description": "Learn transport, numbers and useful questions.",
        "color": "#FFC800",
        "skills": [
            ("Travel", "plane", [
                ("bus", "حافلة"), ("train", "قطار"),
                ("taxi", "سيارة أجرة"), ("station", "محطة")
            ], "I take the bus.", "أستقل الحافلة.",
             ("I take the ", ".", "bus")),
            ("Numbers", "target", [
                ("one", "واحد"), ("two", "اثنان"),
                ("three", "ثلاثة"), ("ten", "عشرة")
            ], "I have two books.", "لدي كتابان.",
             ("I have ", " books.", "two")),
            ("Questions", "help", [
                ("where", "أين"), ("what", "ماذا"),
                ("when", "متى"), ("how", "كيف")
            ], "Where is the station?", "أين المحطة؟",
             ("", " is the station?", "Where")),
        ],
    },
    {
        "title": "Daily Life and Hobbies",
        "description": "Talk about hobbies, weather and family.",
        "color": "#CE82FF",
        "skills": [
            ("Hobbies", "music", [
                ("read", "يقرأ"), ("swim", "يسبح"),
                ("dance", "يرقص"), ("football", "كرة القدم")
            ], "I play football.", "أنا ألعب كرة القدم.",
             ("I play ", ".", "football")),
            ("Weather", "sun", [
                ("sunny", "مشمس"), ("rainy", "ممطر"),
                ("cold", "بارد"), ("hot", "حار")
            ], "It is sunny today.", "الجو مشمس اليوم.",
             ("It is ", " today.", "sunny")),
            ("Family", "heart", [
                ("mother", "أم"), ("father", "أب"),
                ("sister", "أخت"), ("brother", "أخ")
            ], "My sister is kind.", "أختي لطيفة.",
             ("My ", " is kind.", "sister")),
        ],
    },
]


def make_exercises(skill_data, lesson_order):
    title, icon, words, sentence, arabic_sentence, blank = skill_data
    offset = (lesson_order - 1) % len(words)
    target_en, target_ar = words[offset]

    distractors = [
        en for en, ar in words
        if en != target_en
    ][:3]

    options = [
        {"text": target_en, "correct": True},
        *[{"text": word, "correct": False} for word in distractors],
    ]

    correct_words = sentence.split()
    word_bank = correct_words + [
        word for word in ["today.", "at", "school.", "very"]
        if word not in correct_words
    ][:3]

    blank_prefix, blank_suffix, blank_word = blank
    blank_options = [blank_word] + [
        word for word in [w[0] for w in words]
        if word != blank_word
    ][:3]

    return [
        {
            "type": "multiple_choice",
            "prompt": "Choose the correct English word.",
            "order": 1,
            "content": {
                "question": target_ar,
                "options": options,
            },
        },
        {
            "type": "translate",
            "prompt": "Build the English sentence.",
            "order": 2,
            "content": {
                "source_text": arabic_sentence,
                "correct_words": correct_words,
                "word_bank": word_bank,
            },
        },
        {
            "type": "match_pairs",
            "prompt": "Match the English words to Arabic.",
            "order": 3,
            "content": {
                "pairs": [
                    {"left": en, "right": ar}
                    for en, ar in words
                ],
            },
        },
        {
            "type": "fill_blank",
            "prompt": "Complete the English sentence.",
            "order": 4,
            "content": {
                "sentence_parts": [blank_prefix, blank_suffix],
                "correct_word": blank_word,
                "options": blank_options,
            },
        },
        {
            "type": "type_answer",
            "prompt": "Write the English translation.",
            "order": 5,
            "content": {
                "prompt_text": arabic_sentence,
                "accepted_answers": [sentence],
            },
        },
    ]


class Command(BaseCommand):
    help = "Safely add the English course without deleting existing course data."

    def handle(self, *args, **options):
        english, _ = Language.objects.get_or_create(
            code="en",
            defaults={
                "name": "English",
                "flag_icon": "🇬🇧",
            },
        )

        for unit_order, unit_data in enumerate(COURSE, start=1):
            unit, _ = Unit.objects.get_or_create(
                language=english,
                order=unit_order,
                defaults={
                    "title": unit_data["title"],
                    "description": unit_data["description"],
                    "hex_color": unit_data["color"],
                },
            )

            for skill_order, skill_data in enumerate(
                unit_data["skills"], start=1
            ):
                title, icon, words, sentence, arabic_sentence, blank = skill_data

                skill, _ = Skill.objects.get_or_create(
                    unit=unit,
                    order=skill_order,
                    defaults={
                        "title": title,
                        "icon": icon,
                        "total_crowns": 5,
                    },
                )

                for lesson_order in (1, 2):
                    lesson, _ = Lesson.objects.get_or_create(
                        skill=skill,
                        order=lesson_order,
                        defaults={
                            "title": f"{title} - Lesson {lesson_order}",
                            "xp_reward": 10,
                        },
                    )

                    # Never delete or overwrite existing exercises.
                    if lesson.exercises.exists():
                        continue

                    for exercise_data in make_exercises(
                        skill_data, lesson_order
                    ):
                        Exercise.objects.create(
                            lesson=lesson,
                            type=exercise_data["type"],
                            prompt=exercise_data["prompt"],
                            order=exercise_data["order"],
                            content=exercise_data["content"],
                        )

        self.stdout.write(
            self.style.SUCCESS(
                "English course added. Existing user progress was not reset."
            )
        )
