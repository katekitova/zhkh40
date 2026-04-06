import re
from copy import deepcopy
from datetime import date
from difflib import SequenceMatcher
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from flask import Flask, abort, jsonify, render_template, request, send_file, url_for

from site_data import (
    ABOUT_BLOCKS,
    CALCULATOR_CONFIG,
    CHAT_KNOWLEDGE_BASE,
    CHAT_SCENARIOS,
    COMPLAINT_GUIDES,
    CONTACT_BLOCK,
    DOCUMENT_TOOLS,
    DOUBLE_RECEIPT_STEPS,
    FAQ_ITEMS,
    HOME_IMPORTANT_ITEMS,
    HOME_NEWS_ITEMS,
    HOME_POPULAR_QUERIES,
    HOME_SERVICE_CARDS,
    LEGAL_SOURCES,
    LEGAL_DOCUMENTS,
    MANAGEMENT_GUIDES,
    MANAGEMENT_STEPS,
    NAV_ITEMS,
    RECALC_FORM_DEFAULTS,
    SITE,
    TARIFF_GUIDES,
)


app = Flask(__name__)
DOCX_NAMESPACE = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

WORD_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)
RUSSIAN_SUFFIXES = (
    "иями",
    "ями",
    "ами",
    "ого",
    "ему",
    "ому",
    "ее",
    "ие",
    "ые",
    "ое",
    "ей",
    "ий",
    "ый",
    "ой",
    "ем",
    "им",
    "ым",
    "ом",
    "ах",
    "ях",
    "ия",
    "ья",
    "ью",
    "ию",
    "ать",
    "ять",
    "ить",
    "еть",
    "ешь",
    "ете",
    "ут",
    "ют",
    "ит",
    "ят",
    "ал",
    "ял",
    "ов",
    "ев",
    "ам",
    "ям",
    "а",
    "я",
    "ы",
    "и",
    "е",
    "у",
    "ю",
    "о",
)

def admin_default_content():
    return {
        "site": {
            "tagline": SITE.get("tagline", ""),
        },
        "about_intro": DEFAULT_ABOUT_INTRO,
        "contact_block": {
            "title": CONTACT_BLOCK.get("title", ""),
            "description": CONTACT_BLOCK.get("description", ""),
            "email": CONTACT_BLOCK.get("email", ""),
        },
        "about_blocks": deepcopy(ABOUT_BLOCKS[:1]),
        "footer_disclaimer": DEFAULT_FOOTER_DISCLAIMER,
        "document_meta": {},
    }


def load_admin_content():
    defaults = admin_default_content()
    if not ADMIN_CONTENT_FILE.exists():
        return defaults

    try:
        saved = json.loads(ADMIN_CONTENT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults

    if not isinstance(saved, dict):
        return defaults

    result = deepcopy(defaults)
    for key in ("site", "contact_block", "document_meta"):
        if isinstance(saved.get(key), dict):
            result[key].update(saved[key])

    if isinstance(saved.get("about_intro"), str) and saved["about_intro"].strip():
        result["about_intro"] = saved["about_intro"].strip()

    if isinstance(saved.get("footer_disclaimer"), str) and saved["footer_disclaimer"].strip():
        result["footer_disclaimer"] = saved["footer_disclaimer"].strip()

    if isinstance(saved.get("about_blocks"), list) and saved["about_blocks"]:
        custom_blocks = []
        for block in saved["about_blocks"]:
            if isinstance(block, dict):
                custom_blocks.append(
                    {
                        "title": str(block.get("title", "")).strip(),
                        "description": str(block.get("description", "")).strip(),
                    }
                )
        if custom_blocks:
            result["about_blocks"] = custom_blocks

    return result


def save_admin_content(content):
    ADMIN_CONTENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    ADMIN_CONTENT_FILE.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_document_overrides(section_name, items):
    admin_content = load_admin_content()
    overrides = admin_content.get("document_meta", {})
    prepared = deepcopy(items)

    for index, item in enumerate(prepared):
        override = overrides.get(f"{section_name}:{index}", {})
        if not isinstance(override, dict):
            continue
        for field in ("title", "summary", "current_rate", "future_rate", "formula", "label"):
            if isinstance(override.get(field), str) and override[field].strip():
                item[field] = override[field].strip()

    return prepared


def get_site_content():
    site = deepcopy(SITE)
    site.update(load_admin_content().get("site", {}))
    return site


def get_about_intro():
    return load_admin_content().get("about_intro", DEFAULT_ABOUT_INTRO)


def get_contact_block():
    contact_block = deepcopy(CONTACT_BLOCK)
    contact_block.update(load_admin_content().get("contact_block", {}))
    return contact_block


def get_about_blocks():
    custom_blocks = load_admin_content().get("about_blocks")
    if isinstance(custom_blocks, list) and custom_blocks:
        return deepcopy(custom_blocks)
    return deepcopy(ABOUT_BLOCKS[:1])


def get_footer_disclaimer():
    return load_admin_content().get("footer_disclaimer", DEFAULT_FOOTER_DISCLAIMER)


def get_tariff_guides():
    return apply_document_overrides("tariff_guides", TARIFF_GUIDES)


def get_management_guides():
    return apply_document_overrides("management_guides", MANAGEMENT_GUIDES)


def get_complaint_guides():
    return apply_document_overrides("complaint_guides", COMPLAINT_GUIDES)


def get_legal_documents():
    return apply_document_overrides("legal_documents", LEGAL_DOCUMENTS)


def get_document_tools():
    return apply_document_overrides("document_tools", DOCUMENT_TOOLS)


def get_all_document_collections():
    return {
        "tariff_guides": get_tariff_guides(),
        "management_guides": get_management_guides(),
        "complaint_guides": get_complaint_guides(),
        "legal_documents": get_legal_documents(),
        "document_tools": get_document_tools(),
    }



def build_navigation(active_page):
    return [{"endpoint": endpoint, "label": label, "active": endpoint == active_page} for endpoint, label in NAV_ITEMS]


def normalize_doc_reference(value):
    if not value or not isinstance(value, str):
        return None

    normalized = value.strip().replace("\\", "/")
    if normalized.startswith("/static/"):
        normalized = normalized[len("/static/") :]
    elif normalized.startswith("static/"):
        normalized = normalized[len("static/") :]

    if not normalized.startswith("docs/"):
        return None

    return normalized


def collect_docx_registry():
    registry = {}
    collections = list(get_all_document_collections().values()) + [CHAT_KNOWLEDGE_BASE]

    for entries in collections:
        for entry in entries:
            if not isinstance(entry, dict):
                continue

            candidates = []
            if isinstance(entry.get("file"), str):
                candidates.append((entry["file"], entry.get("title") or entry.get("label")))
            if isinstance(entry.get("href"), str):
                candidates.append((entry["href"], entry.get("title") or entry.get("label")))

            links = entry.get("links", []) if isinstance(entry.get("links"), list) else []
            for link in links:
                if isinstance(link, dict) and isinstance(link.get("href"), str):
                    candidates.append((link["href"], link.get("label") or entry.get("title")))

            for raw_path, title in candidates:
                normalized = normalize_doc_reference(raw_path)
                if normalized and normalized.lower().endswith(".docx"):
                    registry.setdefault(
                        normalized,
                        {
                            "title": title or Path(normalized).stem,
                            "filename": Path(normalized).name,
                        },
                    )

    return registry


def resolve_document_href(value):
    normalized = normalize_doc_reference(value)
    if normalized and normalized.lower().endswith(".docx") and (Path(app.static_folder) / normalized).exists():
        return url_for("docx_preview", file=normalized)
    if normalized:
        return url_for("static", filename=normalized)
    return value


def transform_links(links):
    transformed = []
    for item in links or []:
        if not isinstance(item, dict):
            continue
        transformed.append({**item, "href": resolve_document_href(item.get("href"))})
    return transformed


def extract_docx_paragraphs(static_path):
    target = Path(app.static_folder, *static_path.split("/"))
    if not target.exists():
        raise FileNotFoundError(static_path)

    with ZipFile(target) as archive:
        xml_bytes = archive.read("word/document.xml")

    root = ET.fromstring(xml_bytes)
    paragraphs = []
    for paragraph in root.findall(".//w:p", DOCX_NAMESPACE):
        parts = []
        for node in paragraph.iter():
            tag = node.tag.rsplit("}", 1)[-1]
            if tag == "t" and node.text:
                parts.append(node.text)
            elif tag == "tab":
                parts.append("    ")
            elif tag in {"br", "cr"}:
                parts.append(" ")

        line = "".join(parts).strip()
        if line:
            paragraphs.append(line)

    return paragraphs


def prepare_chat_scenarios():
    prepared = deepcopy(CHAT_SCENARIOS)
    for scenario in prepared:
        for node in scenario.get("nodes", {}).values():
            result = node.get("result")
            if isinstance(result, dict):
                result["links"] = transform_links(result.get("links", []))
    return prepared




@app.context_processor
def utility_processor():
    return {
        "doc_preview_url": resolve_document_href,
        "footer_disclaimer": get_footer_disclaimer(),
        "admin_logged_in": bool(session.get("admin_logged_in")),
    }


def render_page(template_name, active_page, **context):
    return render_template(
        template_name,
        site=get_site_content(),
        current_year=date.today().year,
        nav_items=build_navigation(active_page),
        active_page=active_page,
        **context,
    )


def admin_required():
    if not session.get("admin_logged_in"):
        flash("??????? ??????? ? ???????.", "warning")
        return False
    return True


def build_admin_document_groups():
    section_titles = {
        "tariff_guides": "??????",
        "management_guides": "????? ?? ? ???",
        "complaint_guides": "??????",
        "legal_documents": "???????? ?????????",
        "document_tools": "????? ? ??????? ?????????",
    }
    groups = []
    for section_name, items in get_all_document_collections().items():
        group_items = []
        for index, item in enumerate(items):
            file_ref = normalize_doc_reference(item.get("file") or item.get("href"))
            group_items.append(
                {
                    "section": section_name,
                    "index": index,
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "file": file_ref,
                    "filename": Path(file_ref).name if file_ref else "???? ?? ????????",
                    "preview_href": resolve_document_href(file_ref) if file_ref else "#",
                }
            )
        groups.append({"key": section_name, "title": section_titles.get(section_name, section_name), "items": group_items})
    return groups


def normalize_text(value):
    return " ".join(WORD_RE.findall((value or "").lower().replace("ё", "е")))


def stem_token(token):
    token = (token or "").lower().replace("ё", "е")
    for suffix in RUSSIAN_SUFFIXES:
        if len(token) > len(suffix) + 2 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def tokenize(value):
    return WORD_RE.findall((value or "").lower().replace("ё", "е"))


def stemmed_tokens(value):
    return {stem_token(token) for token in tokenize(value) if token}


def score_chat_entry(query, entry):
    normalized_query = normalize_text(query)
    if not normalized_query:
        return 0

    query_tokens = set(tokenize(normalized_query))
    query_stems = stemmed_tokens(normalized_query)
    phrases = [entry["title"]] + entry.get("keywords", [])
    best_score = 0

    for phrase in phrases:
        normalized_phrase = normalize_text(phrase)
        if not normalized_phrase:
            continue

        phrase_tokens = set(tokenize(normalized_phrase))
        phrase_stems = stemmed_tokens(normalized_phrase)
        score = 0

        if normalized_query == normalized_phrase:
            score += 1.3
        elif normalized_phrase in normalized_query or normalized_query in normalized_phrase:
            score += 0.9

        token_overlap = len(query_tokens & phrase_tokens)
        stem_overlap = len(query_stems & phrase_stems)

        if phrase_tokens:
            score += token_overlap / len(phrase_tokens)
        if phrase_stems:
            score += (stem_overlap / len(phrase_stems)) * 1.15

        similarity_weight = 0.5 if token_overlap or stem_overlap or normalized_phrase in normalized_query or normalized_query in normalized_phrase else 0.12
        score += SequenceMatcher(None, normalized_query, normalized_phrase).ratio() * similarity_weight
        best_score = max(best_score, score)

    return best_score


def find_best_chat_answer(query):
    normalized_query = normalize_text(query)
    if not normalized_query:
        return {
            "matched": False,
            "title": "Я не понял вопрос",
            "answer": "Напишите вопрос короче и конкретнее. Например: 'нет горячей воды' или 'как написать жалобу'.",
            "links": [
                {"label": "Открыть базу знаний", "href": url_for("knowledge")},
                {"label": "Перейти в ЧАВО", "href": url_for("faq")},
            ],
        }

    best_score = 0
    best_entry = None
    for entry in CHAT_KNOWLEDGE_BASE:
        score = score_chat_entry(normalized_query, entry)
        if score > best_score:
            best_score = score
            best_entry = entry

    if not best_entry or best_score < 0.45:
        return {
            "matched": False,
            "title": "Я не понял вопрос",
            "answer": "Попробуйте написать короче и точнее. Например: 'нет отопления', 'двойные квитанции' или 'жалоба в УК'.",
            "links": [
                {"label": "Открыть базу знаний", "href": url_for("knowledge")},
                {"label": "Перейти в ЧАВО", "href": url_for("faq")},
            ],
        }

    return {
        "matched": True,
        "title": best_entry["title"],
        "answer": best_entry["answer"],
        "links": transform_links(best_entry.get("links", [])),
        "scenario": best_entry.get("scenario"),
        "score": round(best_score, 3),
    }


def detect_scenario(query, explicit):
    if explicit:
        return explicit

    query_lower = (query or "").lower()
    if any(word in query_lower for word in ["тариф", "квитанц", "начислен", "стоимост", "электроэнерг", "тко", "газ"]):
        return "tariffs"
    if any(word in query_lower for word in ["смена ук", "тсж", "управляющ", "двойн", "осс", "собрание"]):
        return "change_uk"
    if any(word in query_lower for word in ["жалоб", "гжи", "прокурат", "грязн", "крыш", "тишин", "санитар", "бездейств"]):
        return "complaints"
    if any(word in query_lower for word in ["отоп", "холодно", "батар"]):
        return "heating"
    if any(word in query_lower for word in ["показан", "счетчик", "счётчик"]):
        return "readings"
    if any(word in query_lower for word in ["вода", "горяч", "холодн"]):
        return "water"
    if any(word in query_lower for word in ["канализ", "засор", "запах"]):
        return "sewer"
    return CHAT_SCENARIOS[0]["slug"]


def collect_search_results(query):
    if not query:
        return []

    query_lower = query.lower()
    results = []

    for scenario in CHAT_SCENARIOS:
        nodes_text = " ".join(node.get("prompt", "") for node in scenario["nodes"].values())
        haystack = f"{scenario['title']} {scenario['summary']} {nodes_text}".lower()
        if query_lower in haystack:
            results.append(
                {
                    "category": "Сценарий",
                    "title": scenario["title"],
                    "description": scenario["summary"],
                    "href": url_for("chat", scenario=scenario["slug"]),
                }
            )

    for guide in get_tariff_guides():
        haystack = f"{guide['title']} {guide['summary']} {' '.join(guide['tags'])} {guide['formula']}".lower()
        if query_lower in haystack:
            results.append(
                {
                    "category": "Тарифы",
                    "title": guide["title"],
                    "description": guide["summary"],
                    "href": resolve_document_href(guide["file"]),
                }
            )

    for guide in get_management_guides():
        haystack = f"{guide['title']} {guide['summary']} {guide['badge']}".lower()
        if query_lower in haystack:
            results.append(
                {
                    "category": "УК / ТСЖ",
                    "title": guide["title"],
                    "description": guide["summary"],
                    "href": resolve_document_href(guide["file"]),
                }
            )

    for guide in get_complaint_guides():
        haystack = f"{guide['title']} {guide['summary']} {guide['badge']}".lower()
        if query_lower in haystack:
            results.append(
                {
                    "category": "Жалобы",
                    "title": guide["title"],
                    "description": guide["summary"],
                    "href": resolve_document_href(guide["file"]),
                }
            )

    for item in FAQ_ITEMS:
        haystack = f"{item['question']} {item['answer']}".lower()
        if query_lower in haystack:
            results.append(
                {
                    "category": "ЧАВО",
                    "title": item["question"],
                    "description": item["answer"],
                    "href": url_for("faq"),
                }
            )

    for tool in get_document_tools():
        haystack = f"{tool['title']} {tool['summary']}".lower()
        if query_lower in haystack:
            results.append(
                {
                    "category": "Документы",
                    "title": tool["title"],
                    "description": tool["summary"],
                    "href": resolve_document_href(tool["href"]),
                }
            )

    for item in get_legal_documents():
        haystack = f"{item['title']} {item['summary']} {item['type']}".lower()
        if query_lower in haystack:
            results.append(
                {
                    "category": "Правовые документы",
                    "title": item["title"],
                    "description": item["summary"],
                    "href": resolve_document_href(item["file"]),
                }
            )

    for source in LEGAL_SOURCES:
        haystack = f"{source['title']} {source['description']}".lower()
        if query_lower in haystack:
            results.append(
                {
                    "category": "Нормативная база",
                    "title": source["title"],
                    "description": source["description"],
                    "href": source["url"],
                }
            )

    return results


def get_recalc_form_data(source):
    fields = {}
    for key, default_value in RECALC_FORM_DEFAULTS.items():
        value = source.get(key, default_value)
        fields[key] = value.strip() if isinstance(value, str) else value
    return fields


def build_recalc_paragraphs(form_data):
    period_from = form_data["period_from"]
    period_to = form_data["period_to"]
    return [
        {"text": "Заявление на перерасчёт по ЖКХ", "align": "center", "bold": True},
        {"text": ""},
        {"text": f"Кому: {form_data['recipient']}"},
        {"text": f"От кого: {form_data['applicant']}"},
        {"text": f"Адрес помещения: {form_data['address']}"},
        {"text": ""},
        {"text": "Заявление", "align": "center", "bold": True},
        {"text": f"Прошу произвести перерасчёт размера платы за коммунальные услуги за период с {period_from} по {period_to}."},
        {"text": f"Причина перерасчёта: {form_data['reason']}"},
        {"text": f"Основание: {form_data['basis']}"},
        {"text": ""},
        {"text": "Приложения: копии обращений, акты, фотофиксация, подтверждающие документы."},
        {"text": ""},
        {"text": "Дата: ____________________        Подпись: ____________________"},
    ]


def _paragraph_xml(paragraph):
    text = escape(paragraph["text"])
    align = paragraph.get("align")
    bold = paragraph.get("bold", False)
    paragraph_props = f"<w:pPr><w:jc w:val=\"{align}\"/></w:pPr>" if align else ""
    run_props = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return "<w:p>" + paragraph_props + "<w:r>" + run_props + f"<w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


def build_docx(paragraphs):
    document_body = "".join(_paragraph_xml(paragraph) for paragraph in paragraphs)
    document_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document xmlns:wpc=\"http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas\" xmlns:mc=\"http://schemas.openxmlformats.org/markup-compatibility/2006\" xmlns:o=\"urn:schemas-microsoft-com:office:office\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\" xmlns:m=\"http://schemas.openxmlformats.org/officeDocument/2006/math\" xmlns:v=\"urn:schemas-microsoft-com:vml\" xmlns:wp14=\"http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing\" xmlns:wp=\"http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing\" xmlns:w10=\"urn:schemas-microsoft-com:office:word\" xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\" xmlns:w14=\"http://schemas.microsoft.com/office/word/2010/wordml\" xmlns:wpg=\"http://schemas.microsoft.com/office/word/2010/wordprocessingGroup\" xmlns:wpi=\"http://schemas.microsoft.com/office/word/2010/wordprocessingInk\" xmlns:wne=\"http://schemas.microsoft.com/office/2006/wordml\" xmlns:wps=\"http://schemas.microsoft.com/office/word/2010/wordprocessingShape\" mc:Ignorable=\"w14 wp14\"><w:body>"
        + document_body +
        "<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\"/><w:pgMar w:top=\"1134\" w:right=\"1134\" w:bottom=\"1134\" w:left=\"1134\" w:header=\"708\" w:footer=\"708\" w:gutter=\"0\"/></w:sectPr></w:body></w:document>"
    )

    content_types_xml = """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"><Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/><Default Extension=\"xml\" ContentType=\"application/xml\"/><Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/><Override PartName=\"/word/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml\"/><Override PartName=\"/docProps/core.xml\" ContentType=\"application/vnd.openxmlformats-package.core-properties+xml\"/><Override PartName=\"/docProps/app.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.extended-properties+xml\"/></Types>"""
    rels_xml = """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/><Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties\" Target=\"docProps/core.xml\"/><Relationship Id=\"rId3\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties\" Target=\"docProps/app.xml\"/></Relationships>"""
    app_xml = """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Properties xmlns=\"http://schemas.openxmlformats.org/officeDocument/2006/extended-properties\" xmlns:vt=\"http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes\"><Application>???40.??</Application></Properties>"""
    core_xml = """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<cp:coreProperties xmlns:cp=\"http://schemas.openxmlformats.org/package/2006/metadata/core-properties\" xmlns:dc=\"http://purl.org/dc/elements/1.1/\" xmlns:dcterms=\"http://purl.org/dc/terms/\" xmlns:dcmitype=\"http://purl.org/dc/dcmitype/\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\"><dc:title>Заявление на перерасчёт по ЖКХ</dc:title><dc:creator>???40.??</dc:creator></cp:coreProperties>"""
    styles_xml = """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<w:styles xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:style w:type=\"paragraph\" w:default=\"1\" w:styleId=\"Normal\"><w:name w:val=\"Normal\"/><w:qFormat/><w:rPr><w:rFonts w:ascii=\"Calibri\" w:hAnsi=\"Calibri\" w:eastAsia=\"Calibri\" w:cs=\"Calibri\"/><w:sz w:val=\"24\"/><w:szCs w:val=\"24\"/></w:rPr></w:style></w:styles>"""

    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", rels_xml)
        archive.writestr("docProps/app.xml", app_xml)
        archive.writestr("docProps/core.xml", core_xml)
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/styles.xml", styles_xml)
    buffer.seek(0)
    return buffer


@app.route("/")
def home():
    return render_page("home.html", "home", page_title="Главная", popular_queries=HOME_POPULAR_QUERIES, service_cards=HOME_SERVICE_CARDS, important_items=HOME_IMPORTANT_ITEMS, news_items=HOME_NEWS_ITEMS)


@app.route("/chat")
def chat():
    query = request.args.get("q", "").strip()
    selected_scenario = request.args.get("scenario", "").strip()
    return render_page("chat.html", "home", page_title="Чат-бот", chat_scenarios=CHAT_SCENARIOS, initial_query=query, selected_scenario=selected_scenario)


@app.post("/api/chat/message")
def api_chat_message():
    payload = request.get_json(silent=True) or {}
    query = (payload.get("query") or "").strip()
    return jsonify(find_best_chat_answer(query))


@app.route("/knowledge")
def knowledge():
    return render_page(
        "knowledge.html",
        "knowledge",
        page_title="База знаний",
        tariff_guides=TARIFF_GUIDES,
        management_guides=MANAGEMENT_GUIDES,
        complaint_guides=COMPLAINT_GUIDES,
        document_tools=DOCUMENT_TOOLS,
        legal_documents=LEGAL_DOCUMENTS,
        legal_sources=LEGAL_SOURCES,
    )


@app.route("/calculator")
def calculator():
    return render_page(
        "calculator.html",
        "calculator",
        page_title="Калькулятор тарифов",
        calculator_config=CALCULATOR_CONFIG,
        tariff_guides=TARIFF_GUIDES,
    )


@app.route("/coming-soon")
def coming_soon():
    return render_page("coming_soon.html", "home", page_title="Скоро будет")


@app.route("/documents/preview")
def docx_preview():
    file_ref = request.args.get("file", "").strip()
    static_path = normalize_doc_reference(file_ref)
    docx_registry = collect_docx_registry()
    if not static_path or static_path not in docx_registry:
        abort(404)

    document_meta = docx_registry[static_path]

    return render_page(
        "docx_preview.html",
        "knowledge",
        page_title=document_meta["title"],
        doc_title=document_meta["title"],
        doc_download_url=url_for("static", filename=static_path),
        doc_open_url=url_for("static", filename=static_path, _external=True),
        doc_filename=document_meta["filename"],
    )


@app.route("/faq")
def faq():
    return render_page(
        "faq.html",
        "faq",
        page_title="ЧАВО",
        faq_items=FAQ_ITEMS,
        management_steps=MANAGEMENT_STEPS,
        double_receipt_steps=DOUBLE_RECEIPT_STEPS,
        management_guides=MANAGEMENT_GUIDES[:4],
        complaint_guides=COMPLAINT_GUIDES[:8],
    )


@app.route("/about")
def about():
    return render_page(
        "about.html",
        "about",
        page_title="О проекте",
        about_blocks=ABOUT_BLOCKS,
        legal_documents=LEGAL_DOCUMENTS,
        legal_sources=LEGAL_SOURCES,
        contact_block=CONTACT_BLOCK,
    )


@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    return render_page("search.html", "knowledge", page_title="Поиск", query=query, results=collect_search_results(query))


@app.route("/favicon.ico")
def favicon():
    return send_file(Path(app.static_folder) / "img" / "favicon.png", mimetype="image/png")


@app.route("/documents/recalculation")
def recalculation_document():
    form_data = get_recalc_form_data({})
    return render_page("document_preview.html", "knowledge", page_title="Образец заявления", form_data=form_data, print_mode=False, preview_title="Образец заявления на перерасчёт по ЖКХ")


@app.route("/documents/recalculation/fill")
def recalculation_fill():
    return render_page("document_fill.html", "knowledge", page_title="Форма заполнения", default_form=get_recalc_form_data({}))


@app.route("/documents/recalculation/print")
def recalculation_print():
    form_data = get_recalc_form_data(request.args)
    return render_page("document_preview.html", "knowledge", page_title="Печатная версия", form_data=form_data, print_mode=True, preview_title="Печатная версия заявления")


@app.post("/documents/recalculation/export-docx")
def recalculation_export_docx():
    form_data = get_recalc_form_data(request.form)
    document = build_docx(build_recalc_paragraphs(form_data))
    return send_file(document, as_attachment=True, download_name="zayavlenie-na-pereraschet-jkh.docx", mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = (request.form.get("password") or "").strip()
        if password == os.environ.get("JKH40_ADMIN_PASSWORD", "admin"):
            session["admin_logged_in"] = True
            flash("???? ????????.", "success")
            return redirect(url_for("admin_dashboard"))
        flash("???????? ??????.", "error")

    return render_page("admin_login.html", "about", page_title="???? ? ???????")


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("admin_logged_in", None)
    flash("?? ????? ?? ???????.", "success")
    return redirect(url_for("admin_login"))


@app.route("/admin")
def admin_dashboard():
    if not admin_required():
        return redirect(url_for("admin_login"))

    admin_content = load_admin_content()
    return render_page(
        "admin_dashboard.html",
        "about",
        page_title="???????",
        admin_content=admin_content,
        admin_document_groups=build_admin_document_groups(),
        admin_password_is_default=os.environ.get("JKH40_ADMIN_PASSWORD", "admin") == "admin",
    )


@app.post("/admin/settings")
def admin_update_settings():
    if not admin_required():
        return redirect(url_for("admin_login"))

    admin_content = load_admin_content()
    admin_content["site"]["tagline"] = (request.form.get("site_tagline") or SITE.get("tagline", "")).strip()
    admin_content["about_intro"] = (request.form.get("about_intro") or DEFAULT_ABOUT_INTRO).strip()
    admin_content["contact_block"]["title"] = (request.form.get("contact_title") or CONTACT_BLOCK.get("title", "")).strip()
    admin_content["contact_block"]["description"] = (request.form.get("contact_description") or CONTACT_BLOCK.get("description", "")).strip()
    admin_content["contact_block"]["email"] = (request.form.get("contact_email") or CONTACT_BLOCK.get("email", "")).strip()
    admin_content["footer_disclaimer"] = (request.form.get("footer_disclaimer") or DEFAULT_FOOTER_DISCLAIMER).strip()
    admin_content["about_blocks"] = [
        {
            "title": (request.form.get("about_card_title") or ABOUT_BLOCKS[0].get("title", "")).strip(),
            "description": (request.form.get("about_card_description") or ABOUT_BLOCKS[0].get("description", "")).strip(),
        }
    ]
    save_admin_content(admin_content)
    flash("?????? ?????????.", "success")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/document")
def admin_update_document():
    if not admin_required():
        return redirect(url_for("admin_login"))

    section = (request.form.get("section") or "").strip()
    try:
        index = int(request.form.get("index", "-1"))
    except ValueError:
        abort(400)

    collections = get_all_document_collections()
    items = collections.get(section)
    if items is None or index < 0 or index >= len(items):
        abort(404)

    item = items[index]
    admin_content = load_admin_content()
    document_meta = admin_content.setdefault("document_meta", {})
    key = f"{section}:{index}"
    document_meta[key] = {
        "title": (request.form.get("title") or item.get("title", "")).strip(),
        "summary": (request.form.get("summary") or item.get("summary", "")).strip(),
    }

    uploaded = request.files.get("replacement_file")
    target_ref = normalize_doc_reference(item.get("file") or item.get("href"))
    if uploaded and uploaded.filename:
        if not target_ref:
            flash("? ????? ???????? ??? ???????????? ????? ??? ??????.", "error")
            return redirect(url_for("admin_dashboard"))

        target_path = Path(app.static_folder) / target_ref
        source_ext = Path(uploaded.filename).suffix.lower()
        target_ext = target_path.suffix.lower()
        if source_ext and source_ext != target_ext:
            flash(f"????? ???? ???? ?? ????: {target_ext}", "error")
            return redirect(url_for("admin_dashboard"))

        target_path.parent.mkdir(parents=True, exist_ok=True)
        uploaded.save(target_path)

    save_admin_content(admin_content)
    flash("???????? ????????.", "success")
    return redirect(url_for("admin_dashboard"))


if __name__ == "__main__":
    app.run(debug=True)


