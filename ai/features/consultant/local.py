from __future__ import annotations

import re

from ai.features.consultant.attachments import prepare_attachment_context
from ai.tools.catalog import (
    CONTACT_TG,
    CONTACT_WA,
    SERVICE_CATALOG,
    contains_any,
    contains_any_word,
    detect_service,
    format_price_label,
)


def previous_service(messages):
    for item in reversed(messages[:-1]):
        content = item.get("content", "").lower()
        found = detect_service(content)
        if found:
            return found
        for service in SERVICE_CATALOG:
            for label in service["name"].values():
                if label.lower() in content:
                    return service
    return None


def prefer_local_price_reply(text: str) -> bool:
    """Use deterministic local replies for catalog chips and website questions.

    OpenAI sometimes answers "хочу сайт" without the public starting prices.
    """
    cleaned = normalize_user_text(text)
    if not cleaned:
        return False
    if detect_service(cleaned):
        return True
    return contains_any(
        cleaned,
        (
            "сайт",
            "website",
            "websites",
            "landing",
            "лендинг",
            "визитк",
            "business-card site",
            "business card site",
            "интернет-магазин",
            "online store",
            "internet store",
        ),
    )


def is_price_followup(text):
    cleaned = text.strip()
    return contains_any(
        cleaned,
        (
            "а сколько",
            "а цена",
            "а это сколько",
            "а она сколько",
            "сколько это",
            "это сколько",
            "а по цене",
            "и цена",
            "and the price",
            "how much is it",
            "what about the price",
            "ал баға",
            "қанша тұрады",
            "бағасы қанша",
        ),
    ) or (
        len(cleaned) <= 24
        and contains_any(
            cleaned, ("цен", "сколько", "price", "cost", "баға", "қанша", "стоим", "стоит")
        )
    )


def normalize_user_text(value):
    text = (value or "").lower().strip()
    text = re.sub(r"[!?.…,:;]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def handoff_reply(lang, topic="general"):
    if lang == "en":
        leads = {
            "deadline": "Exact turnaround depends on the brief and current workload — Aigerim confirms that personally.",
            "price": "There is no fixed public price for that exact request — Aigerim will give an individual quote.",
            "general": "I do not have a confident answer for that here — Aigerim will clarify it personally.",
        }
        lead = leads.get(topic, leads["general"])
        return f"{lead} Message her on Telegram {CONTACT_TG} or WhatsApp {CONTACT_WA}."
    if lang == "kz":
        leads = {
            "deadline": "Нақты мерзім брифке және жүктемеге байланысты — мұны Айгерим жеке нақтылайды.",
            "price": "Бұл сұраққа ашық прайста бекітілген баға жоқ — Айгерим жеке есеп береді.",
            "general": "Бұл жерде нақты жауап бере алмаймын — Айгерим жеке нақтылайды.",
        }
        lead = leads.get(topic, leads["general"])
        return f"{lead} Telegram {CONTACT_TG} немесе WhatsApp {CONTACT_WA} арқылы жазыңыз."
    leads = {
        "deadline": "Точный срок зависит от брифа и текущей загрузки — это Айгерим подтверждает лично.",
        "price": "По этому запросу в открытом прайсе фиксированной цены нет — Айгерим сделает индивидуальный расчёт.",
        "general": "По этому вопросу у меня нет уверенного ответа здесь — это лучше уточнить у Айгерим.",
    }
    lead = leads.get(topic, leads["general"])
    return f"{lead} Напишите ей в Telegram {CONTACT_TG} или WhatsApp {CONTACT_WA}."


def local_attachment_reply(messages, lang, attachments):
    names, text_notes, image_parts = prepare_attachment_context(
        attachments, include_image_data=False
    )
    text = (messages[-1].get("content") or "").lower()
    joined = " ".join(text_notes).lower()
    has_image = bool(image_parts)
    file_list = ", ".join(names)

    combined = text + " " + joined
    matched = detect_service(combined)
    if matched is None:
        matched = detect_service(text)

    if matched:
        name = matched["name"][lang]
        raw_price = matched.get("price_kzt")
        if raw_price is None:
            if lang == "en":
                return (
                    f"I received your file(s): {file_list}. "
                    f"This looks closest to {name} — the quote is individual. "
                    "Tell me the goal, and I will confirm the format."
                )
            if lang == "kz":
                return (
                    f"Файл(дар)ыңызды алдым: {file_list}. "
                    f"Мазмұны бойынша ең жақын қызмет — {name}, бағасы жеке есеп. "
                    "Мақсатыңызды жазыңыз, форматты нақтылаймын."
                )
            return (
                f"Получила ваши файлы: {file_list}. "
                f"По содержимому ближе всего «{name}» — цена по индивидуальному расчёту. "
                "Опишите задачу, и я подтвержу формат."
            )
        price = format_price_label(int(raw_price))
        if lang == "en":
            return (
                f"I received your file(s): {file_list}. "
                f"Based on what I can read, this looks closest to {name} — from {price}. "
                "Tell me the goal, and I will confirm the format."
            )
        if lang == "kz":
            return (
                f"Файл(дар)ыңызды алдым: {file_list}. "
                f"Мазмұны бойынша ең жақын қызмет — {name}, бағасы {price} бастап. "
                "Мақсатыңызды жазыңыз, форматты нақтылаймын."
            )
        return (
            f"Получила ваши файлы: {file_list}. "
            f"По содержимому ближе всего «{name}» — от {price}. "
            "Опишите задачу, и я подтвержу формат."
        )

    if has_image:
        if lang == "en":
            return (
                f"I received the image ({file_list}). "
                "I can use it as a reference for an AI photoshoot, animation, character, or product visual. "
                f"Tell me the result you want — or message Aigerim on Telegram {CONTACT_TG} or WhatsApp {CONTACT_WA}."
            )
        if lang == "kz":
            return (
                f"Суретті алдым ({file_list}). "
                "Оны AI-фотосессия, анимация, персонаж немесе тауар визуалы үшін референс ретінде қарастыруға болады. "
                f"Қандай нәтиже керек екенін жазыңыз — немесе Telegram {CONTACT_TG} / WhatsApp {CONTACT_WA} арқылы Айгеримге жазыңыз."
            )
        return (
            f"Получила изображение ({file_list}). "
            "Могу рассматривать его как референс для AI-фотосессии, анимации, персонажа или визуала товара. "
            f"Напишите, какой результат нужен — или напишите Айгерим в Telegram {CONTACT_TG} или WhatsApp {CONTACT_WA}."
        )

    excerpt = ""
    for note in text_notes:
        if "Извлечённое содержимое:" in note:
            excerpt = note.split("Извлечённое содержимое:", 1)[-1].strip()[:220]
            break
        if "Извлечённый текст:" in note:
            excerpt = note.split("Извлечённый текст:", 1)[-1].strip()[:220]
            break
    if excerpt:
        if lang == "en":
            return (
                f"I received the file(s): {file_list}. Here is what I could read: «{excerpt}». "
                "Tell me what you want next — pricing, format, or a direct handoff to Aigerim."
            )
        if lang == "kz":
            return (
                f"Файл(дар)ды алдым: {file_list}. Оқылған үзінді: «{excerpt}». "
                "Әрі қарай не керек — баға, формат па, әлде бірден Айгеримге жазу ма?"
            )
        return (
            f"Получила файл(ы): {file_list}. Вот что удалось прочитать: «{excerpt}». "
            "Скажите, что нужно дальше — цена, формат или сразу контакт Айгерим."
        )

    if lang == "en":
        return (
            f"I received your file(s): {file_list}. "
            "I could not fully extract the content in local mode. "
            f"Describe the task in a sentence, or message Aigerim on Telegram {CONTACT_TG} or WhatsApp {CONTACT_WA}."
        )
    if lang == "kz":
        return (
            f"Файл(дар)ыңызды алдым: {file_list}. "
            "Жергілікті режимде мазмұнды толық оқи алмадым. "
            f"Тапсырманы бір сөйлеммен жазыңыз немесе Telegram {CONTACT_TG} / WhatsApp {CONTACT_WA} арқылы Айгеримге жазыңыз."
        )
    return (
        f"Получила ваши файл(ы): {file_list}. "
        "В локальном режиме не удалось полностью прочитать содержимое. "
        f"Опишите задачу одним предложением — или напишите Айгерим в Telegram {CONTACT_TG} или WhatsApp {CONTACT_WA}."
    )


def local_consultant_reply(messages, lang):
    if lang not in {"ru", "kz", "en"}:
        lang = "ru"
    raw_text = messages[-1]["content"]
    text = normalize_user_text(raw_text)

    wants_deadline = contains_any(
        text,
        (
            "срок",
            "сроки",
            "сколько дн",
            "сколько ден",
            "как долго",
            "когда готов",
            "будет готов",
            "готов заказ",
            "заказ готов",
            "дней",
            "день",
            "deadline",
            "how long",
            "how many day",
            "turnaround",
            "delivery time",
            "қанша күн",
            "қашан дайын",
            "дайын болад",
            "дайын болады",
        ),
    )
    wants_price = contains_any(
        text, ("цен", "сколько", "price", "cost", "баға", "қанша", "стоим", "стоит")
    ) and not wants_deadline
    wants_contact = contains_any(
        text,
        ("связ", "telegram", "whatsapp", "написать", "контакт", "байланыс", "contact", "набрать"),
    )
    wants_list = contains_any(
        text,
        (
            "услуг",
            "прайс",
            "что дела",
            "services",
            "қызмет",
            "offer",
            "что уме",
            "какие есть",
            "что можешь",
            "чем можешь",
            "меню",
        ),
    )
    wants_process = contains_any(
        text,
        (
            "процесс",
            "как работ",
            "как проход",
            "проходит работ",
            "как устроен",
            "этап",
            "порядок",
            "how it works",
            "process",
            "қалай жұмыс",
        ),
    )
    wants_portfolio = contains_any(
        text,
        ("портфол", "примеры работ", "ваши работ", "мои работ", "portfolio", "examples", "жұмыстар", "кейсы"),
    ) or contains_any_word(text, ("работы", "works"))
    wants_website = contains_any(
        text, ("сайт", "website", "landing", "лендинг", "ai-помощник", "ai помощник", "чат-бот", "чатбот")
    ) or contains_any_word(text, ("помощник", "бот"))
    wants_about = contains_any(
        text, ("кто ты", "кто такая", "об айгерим", "о себе", "who are you", "about aigerim", "кімсің", "кімсіз")
    )
    wants_payment = contains_any(text, ("оплат", "payment", "предоплат", "перевод", "каспи", "kaspi"))
    is_thanks = contains_any(text, ("спасибо", "благодар", "рахмет", "thanks", "thank you"))
    greeting_roots = (
        "привет",
        "здравствуй",
        "добрый день",
        "добрый вечер",
        "доброе утро",
        "салам",
        "сәлем",
        "сәлемет",
        "hello",
        "good morning",
        "good afternoon",
        "good evening",
        "hi",
        "hey",
    )
    is_greeting = text in {"hi", "hey", "hello"} or (
        contains_any(text, greeting_roots)
        and len(text) <= 40
        and not wants_price
        and not detect_service(text)
    )

    matched = detect_service(text)
    if matched is None and not is_greeting and (
        is_price_followup(text) or (wants_price and len(text) <= 28)
    ):
        matched = previous_service(messages)

    def service_price_reply(service):
        name = service["name"][lang]
        raw_price = service.get("price_kzt")
        if raw_price is None:
            if lang == "en":
                return (
                    f"{name} is priced individually — there is no fixed public starting price. "
                    "Share your goal, and I will tell you whether this format fits."
                )
            if lang == "kz":
                return (
                    f"{name} — жеке есеп, бекітілген бастапқы баға жоқ. "
                    "Мақсатыңызды айтыңыз — осы формат сізге сай келетінін нақтылаймын."
                )
            return (
                f"«{name}» — индивидуальный расчёт, фиксированной цены «от» нет. "
                "Опишите задачу — уверенно скажу, подходит ли этот формат."
            )
        price = format_price_label(int(raw_price))
        if lang == "en":
            return (
                f"{name} starts from {price}. "
                "The final cost depends on the brief, scope, and complexity. "
                "Share your goal, and I will tell you whether this format fits."
            )
        if lang == "kz":
            return (
                f"{name} — {price} бастап. "
                "Нақты құны брифке, көлемге және күрделілікке байланысты. "
                "Мақсатыңызды айтыңыз — осы формат сізге сай келетінін нақтылаймын."
            )
        return (
            f"«{name}» — от {price}. "
            "Итоговая стоимость зависит от брифа, объёма и сложности. "
            "Опишите задачу — уверенно скажу, подходит ли этот формат."
        )

    if is_greeting:
        if lang == "en":
            return (
                "Hello. I am Aigerim's AI consultant. "
                "Ask about a service, price, process, or portfolio — I will answer clearly."
            )
        if lang == "kz":
            return (
                "Сәлеметсіз бе. Мен Айгеримнің AI-консультантымын. "
                "Қызмет, баға, процесс немесе портфолио туралы сұраңыз — анық жауап беремін."
            )
        return (
            "Здравствуйте. Я AI-консультант Айгерим. "
            "Спросите про услугу, цену, процесс или портфолио — отвечу по делу."
        )

    if is_thanks:
        if lang == "en":
            return "You're welcome. If you have another question, ask — I am here."
        if lang == "kz":
            return "Оқасы жоқ. Тағы сұрағыңыз болса, жазыңыз — осындамын."
        return "Пожалуйста. Если будет ещё вопрос — пишите, я на связи."

    if wants_about:
        if lang == "en":
            return (
                "Aigerim Kabaeva is an AI Creator: AI photos, video, 3D, animation, and design in one style. "
                "I help you choose the format and starting price. What task do you have?"
            )
        if lang == "kz":
            return (
                "Айгерим Кабаева — AI Creator: AI-фото, видео, 3D, анимация және дизайн бір стильде. "
                "Мен формат пен бастапқы бағаны таңдауға көмектесемін. Қандай міндет бар?"
            )
        return (
            "Айгерим Кабаева — AI Creator: AI-фото, видео, 3D, анимация и дизайн в одном стиле. "
            "Я помогаю выбрать формат и стартовую цену. Какая у вас задача?"
        )

    if wants_deadline:
        return handoff_reply(lang, "deadline")

    if wants_payment:
        if lang == "en":
            return (
                "Payment details are confirmed with Aigerim for each project. "
                f"Write on Telegram {CONTACT_TG} or WhatsApp {CONTACT_WA} to finalize this."
            )
        if lang == "kz":
            return (
                "Төлем шарттары әр жоба бойынша Айгериммен нақтыланады. "
                f"Telegram {CONTACT_TG} немесе WhatsApp {CONTACT_WA} арқылы жазыңыз."
            )
        return (
            "Условия оплаты Айгерим подтверждает по каждому проекту отдельно. "
            f"Напишите в Telegram {CONTACT_TG} или WhatsApp {CONTACT_WA} — там это быстро закрывается."
        )

    # Matched catalog services (including websites) always win over the
    # generic "websites" branch — otherwise "Сайт-визитка" never shows 50 000 ₸.
    if matched and not (wants_contact or wants_process or wants_portfolio or wants_list):
        return service_price_reply(matched)

    if wants_website:
        if lang == "en":
            return (
                "Website services are on the public price list: "
                "business-card site from 50 000 ₸, landing page from 100 000 ₸; "
                "stores, corporate, 3D/animated sites and integrations — custom quote. "
                "Pick a format or describe the task — I will point to the right option."
            )
        if lang == "kz":
            return (
                "Сайт қызметтері ашық прайста бар: "
                "сайт-визитка — 50 000 ₸ бастап, лендинг — 100 000 ₸ бастап; "
                "дүкен, корпоративтік, 3D/анимациялық сайттар мен интеграциялар — жеке есеп. "
                "Форматты таңдаңыз немесе міндетті жазыңыз — сәйкес нұсқаны айтамын."
            )
        return (
            "Услуги по сайтам есть в открытом прайсе: "
            "сайт-визитка — от 50 000 ₸, лендинг — от 100 000 ₸; "
            "магазины, корпоративные, 3D/анимационные сайты и интеграции — индивидуальный расчёт. "
            "Выберите формат или опишите задачу — подскажу подходящий вариант."
        )

    if wants_process:
        if lang == "en":
            return (
                "The process is clear: we discuss the goal and format, approve the concept, "
                "create and review iterations, then deliver the final result. "
                "Work is online and turnkey. I can also help you choose the right service."
            )
        if lang == "kz":
            return (
                "Процесс анық: мақсат пен форматты талқылаймыз, тұжырымдаманы бекітеміз, "
                "итерацияларды жасаймыз және көрсетеміз, сосын дайын нәтижені береміз. "
                "Жұмыс онлайн және толық дайын форматта. Қажет қызметті де таңдап беремін."
            )
        return (
            "Процесс понятный: обсуждаем задачу и формат, согласовываем концепцию, "
            "делаем итерации и передаём готовый результат. "
            "Работа онлайн, под ключ. Могу сразу подобрать подходящую услугу."
        )

    if wants_portfolio:
        if lang == "en":
            return (
                "Here is the portfolio: https://t.me/portfolioaigerimkabayeva "
                "Review the work, then tell me what you need — I will point to the right format."
            )
        if lang == "kz":
            return (
                "Портфолио осында: https://t.me/portfolioaigerimkabayeva "
                "Жұмыстарды қарап шығыңыз, сосын не керек екенін айтыңыз — дұрыс форматты көрсетемін."
            )
        return (
            "Портфолио здесь: https://t.me/portfolioaigerimkabayeva "
            "Посмотрите работы и скажите, что нужно получить — подберу точный формат."
        )

    if wants_contact:
        if lang == "en":
            return (
                f"Best contacts: Telegram {CONTACT_TG} "
                f"or WhatsApp {CONTACT_WA}. "
                "Send the idea, deadline, and preferred format — the conversation can start right away."
            )
        if lang == "kz":
            return (
                f"Ыңғайлы байланыс: Telegram {CONTACT_TG} "
                f"немесе WhatsApp {CONTACT_WA}. "
                "Идеяны, мерзімді және форматты жазыңыз — әңгімені бірден бастауға болады."
            )
        return (
            f"Удобные контакты: Telegram {CONTACT_TG} "
            f"или WhatsApp {CONTACT_WA}. "
            "Напишите идею, срок и формат — можно сразу переходить к обсуждению."
        )

    if matched:
        return service_price_reply(matched)

    if wants_price and matched is None and not wants_list:
        return handoff_reply(lang, "price")

    if wants_list:
        if lang == "en":
            return (
                "Starting prices: AI photoshoot from 25,000 ₸, AI video from 45,000 ₸, "
                "3D from 30,000 ₸, photo animation from 15,000 ₸, product cards from 10,000 ₸. "
                "Tell me your task, and I will recommend the best format."
            )
        if lang == "kz":
            return (
                "Бастапқы бағалар: AI-фотосессия — 25 000 ₸ бастап, AI-ролик — 45 000 ₸ бастап, "
                "3D — 30 000 ₸ бастап, фото анимациясы — 15 000 ₸ бастап, тауар карточкасы — 10 000 ₸ бастап. "
                "Міндетіңізді айтыңыз — ең лайықты форматты ұсынамын."
            )
        return (
            "Стартовые цены: AI-фотосессия — от 25 000 ₸, AI-ролик — от 45 000 ₸, "
            "3D — от 30 000 ₸, анимация фото — от 15 000 ₸, карточки товара — от 10 000 ₸. "
            "Скажите задачу — подберу наиболее подходящий формат."
        )

    if lang == "en":
        return (
            "I can help with Aigerim's services, prices, process, and portfolio. "
            "Name the format you need — for example photoshoot, video, 3D, or product cards. "
            f"Or message Aigerim directly on Telegram {CONTACT_TG} or WhatsApp {CONTACT_WA}."
        )
    if lang == "kz":
        return (
            "Айгеримнің қызметтері, бағасы, процесі және портфолиосы бойынша көмектесемін. "
            "Қандай формат керек екенін жазыңыз — фотосессия, ролик, 3D немесе тауар карточкасы. "
            f"Немесе тікелей Айгеримге жазыңыз: Telegram {CONTACT_TG} немесе WhatsApp {CONTACT_WA}."
        )
    return (
        "Могу помочь по услугам Айгерим, ценам, процессу и портфолио. "
        "Назовите нужный формат — например фотосессия, ролик, 3D или карточки товара. "
        f"Или напишите Айгерим напрямую в Telegram {CONTACT_TG} или WhatsApp {CONTACT_WA}."
    )


def consultant_local_fallback(messages, lang, attachments=None):
    attachments = attachments or []
    if attachments:
        return local_attachment_reply(messages, lang, attachments)
    return local_consultant_reply(messages, lang)
