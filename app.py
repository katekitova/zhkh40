import json
import os
import re
from copy import deepcopy
from datetime import date
from difflib import SequenceMatcher
from io import BytesIO
from markupsafe import Markup, escape as markup_escape
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_file, session, url_for

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
    TERMINATION_NOTICE_FORM_DEFAULTS,
)


app = Flask(__name__)
app.secret_key = os.environ.get("JKH40_SECRET_KEY", "jkh40-local-secret")
DOCX_NAMESPACE = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
DOCX_RELATIONSHIP_NAMESPACE = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
DOCX_RELATIONSHIP_ID_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
DOCX_ANCHOR_ATTR = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}anchor"
DOCX_HYPERLINK_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
ADMIN_CONTENT_FILE = Path(app.root_path) / "data" / "admin_content.json"
DEFAULT_ABOUT_INTRO = (
    "Сайт сделан как практический помощник по вопросам ЖКХ в Калуге: здесь можно найти разъяснения, "
    "документы, маршруты действий и перейти к нужному разделу без долгого поиска."
)
DEFAULT_FOOTER_DISCLAIMER = "Информация носит исключительно справочный характер."
PDF_FONT_CACHE = None
TERMINATION_NOTICE_DOC_PATH = "docs/management/templates/Уведомление о расторжении договора с УК.docx"

WORD_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)
DOCX_INLINE_TOKEN_RE = re.compile(
    r"(?P<email>\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b)"
    r"|(?P<url>(?:https?://|www\.)[^\s<>()]+|(?<![@/])\b(?:[a-z0-9-]+\.)+(?:ru|рф|com|org|net|gov|edu)(?:/[^\s<>()]*)?)"
    r"|(?P<phone>(?:\+7|8)\s*\(?\d{3,5}\)?(?:[\s\-]*\d){5,10})",
    re.IGNORECASE,
)
LEGAL_INLINE_LINK_ALIASES = {
    '"Жилищный кодекс Российской Федерации" от 29.12.2004 N 188-ФЗ (ред. от 20.02.2026)': "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791&rnd=KWdYUw#DRXr5GVU35yBYN8t",
    "Жилищный кодекс Российской Федерации от 29.12.2004 N 188-ФЗ (ред. от 20.02.2026)": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791&rnd=KWdYUw#DRXr5GVU35yBYN8t",
    "ст. 162, ч. 8.2 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#dst101154",
    "ч. 8.1 ст. 162 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#dst101153",
    "ст. 199 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#14db416f7441199d612af5491ddc1b45ed664a10",
    "ст. 44": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#b50101afd08dee7f41764d59277937373a2f7655",
    "46 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#219c3257c1aa4b0fb9896079a0f295343e523d37",
    "ст. 45 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#0007bd8e825a6eadd1de1cccb256d04cb5d980c3",
    "ч. 1 ст. 162 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#14e9738be002fe3ab76c0d580b863aac1ac65fb7",
    "ч. 4 ст. 45 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#0007bd8e825a6eadd1de1cccb256d04cb5d980c3",
    "п. 19–22 Постановления Правительства № 416": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=465381",
    "п. 19-22 Постановления Правительства № 416": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=465381",
    "ч. 7 ст. 162 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#14e9738be002fe3ab76c0d580b863aac1ac65fb7",
    "п. 4 Приказа Минстроя № 938/пр": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=196698",
    "ч. 1 ст. 136 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#c54c4b4eca86f1ed570b752292a0b371ba18f888",
    "ст. 1102 ГК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=9027-0&req=doc&base=LAW&n=508506&rnd=KWdYUw#flGs5GVmD11lSrGm",
    "ч. 1.1 ст. 46 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#219c3257c1aa4b0fb9896079a0f295343e523d37",
    "ст. 39": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#d68ab414b0cbed034202ad14c34387f4c35cd2d0",
    "158 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#fc0ab0537d457cf86182567350b816e931051853",
    "ч. 6 ст. 162 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#14e9738be002fe3ab76c0d580b863aac1ac65fb7",
    "ч. 8.2 ст. 162 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#dst101154",
    "ч. 1 ст. 46 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#219c3257c1aa4b0fb9896079a0f295343e523d37",
    "п. 18 Постановления Правительства РФ № 416": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=465381",
    "п. 2 ст. 198 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#5ecf4f803986f14fb302bfac58d59273acde7f0a",
    ". 2 ст. 198 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#5ecf4f803986f14fb302bfac58d59273acde7f0a",
    "Приказ Минстроя № 938/пр": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=196698",
    "п. 19, 20 Постановления Правительства РФ № 416": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=465381",
    "п. 19–20 ПП РФ № 416": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=465381",
    "ч. 3 ст. 48 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#78e68a78236a193f84f0f5f80b6a57f6ca4910f5",
    "ст. 135–140 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#9dfd36b6ecfa3c97f3929a2f92f0f740fd222dfa",
    "ст. 135-140 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#9dfd36b6ecfa3c97f3929a2f92f0f740fd222dfa",
    "ч. 3 ст. 45 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#0007bd8e825a6eadd1de1cccb256d04cb5d980c3",
    "ст. 8 Федерального закона № 129-ФЗ": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=32881",
    "ст. 161 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#853d11d89ec7459243ea093f5d76ecf2be2e9f02",
    "ч. 3 ст. 200 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#467b389869892d3f6e74b6442369d8fc0cd6d7c2",
    "ч. 7 ст. 155 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#f1496f9a8499f6af89acfad1fd88365f93314e67",
    "ст. 7.22": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=34661",
    "7.23.3 КоАП РФ": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=34661",
    "п. 36 Постановления Пленума Верховного Суда РФ № 22 от 27.06.2017": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=218822",
    "ст. 162": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#14e9738be002fe3ab76c0d580b863aac1ac65fb7",
    "198 ЖК РФ": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791#5ecf4f803986f14fb302bfac58d59273acde7f0a",
    "п. 24 Правил осуществления деятельности по управлению МКД (утв. Постановлением Правительства РФ № 416": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=465381",
    "п. 24 Правил осуществления деятельности по управлению МКД (утв. Постановлением Правительства РФ № 416)": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=465381",
    'Приказа Минстроя России от 30.04.2025 N 266/пр "Об утверждении Требований к оформлению протокола общего собрания собственников помещений в многоквартирном доме и Порядка направления подлинников решений и протокола общего собрания собственников помещений в многоквартирном доме в уполномоченный исполнительный орган субъекта Российской Федерации, осуществляющий государственный жилищный надзор"': "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=506700",
    'Приказ Минстроя России от 30.04.2025 N 266/пр "Об утверждении Требований к оформлению протокола общего собрания собственников помещений в многоквартирном доме и Порядка направления подлинников решений и протокола общего собрания собственников помещений в многоквартирном доме в уполномоченный исполнительный орган субъекта Российской Федерации, осуществляющий государственный жилищный надзор"': "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=506700",
}
LEGAL_INLINE_LINK_PATTERN = re.compile(
    "|".join(re.escape(item) for item in sorted(LEGAL_INLINE_LINK_ALIASES, key=len, reverse=True))
)
MINSTROY_266_CASE_TEXT = (
    'Приказа Минстроя России от 30.04.2025 N 266/пр "Об утверждении Требований к оформлению '
    "протокола общего собрания собственников помещений в многоквартирном доме и Порядка направления "
    "подлинников решений и протокола общего собрания собственников помещений в многоквартирном доме в "
    "уполномоченный исполнительный орган субъекта Российской Федерации, осуществляющий государственный "
    'жилищный надзор"'
)
MINSTROY_266_NOM_TEXT = (
    'Приказ Минстроя России от 30.04.2025 N 266/пр "Об утверждении Требований к оформлению протокола '
    "общего собрания собственников помещений в многоквартирном доме и Порядка направления подлинников "
    "решений и протокола общего собрания собственников помещений в многоквартирном доме в уполномоченный "
    "исполнительный орган субъекта Российской Федерации, осуществляющий государственный жилищный надзор\""
)
DOCX_TEXT_REPLACEMENTS = {
    "Приказа Минстроя РФ № 44/пр от 28.01.2019": MINSTROY_266_CASE_TEXT,
    "Приказ Минстроя РФ № 44/пр от 28.01.2019": MINSTROY_266_NOM_TEXT,
    "Приказа Минстроя России № 44/пр от 28.01.2019": MINSTROY_266_CASE_TEXT,
    "Приказ Минстроя России № 44/пр от 28.01.2019": MINSTROY_266_NOM_TEXT,
    "Приказа Минстроя № 44/пр": MINSTROY_266_CASE_TEXT,
    "Приказ Минстроя № 44/пр": MINSTROY_266_NOM_TEXT,
    "Приказа Минстроя РФ № 44/пр": MINSTROY_266_CASE_TEXT,
    "Приказ Минстроя РФ № 44/пр": MINSTROY_266_NOM_TEXT,
}
INLINE_DOC_LINK_ALIASES = {
    '"Жилищный кодекс Российской Федерации" от 29.12.2004 N 188-ФЗ (ред. от 20.02.2026)': "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791",
    "Жилищный кодекс Российской Федерации от 29.12.2004 N 188-ФЗ (ред. от 20.02.2026)": "https://www.consultant.ru/cons/cgi/online.cgi?from=51057-0&req=doc&base=LAW&n=511791",
    "Как сменить одну управляющую компанию на другую": "docs/management/Инструкция_ «Пошаговый план перехода из одной УК в другую».docx",
    "Как сменить управляющую компанию на другую": "docs/management/Инструкция_ «Пошаговый план перехода из одной УК в другую».docx",
    "Как сменить управляющую компанию": "docs/management/Инструкция_ «Пошаговый план перехода из одной УК в другую».docx",
    "Как сменить управляющую компанию:": "docs/management/Инструкция_ «Пошаговый план перехода из одной УК в другую».docx",
    "Как сменить управляющую компанию?": "docs/management/Инструкция_ «Пошаговый план перехода из одной УК в другую».docx",
    "Как сменить одну УК на другую": "docs/management/Инструкция_ «Пошаговый план перехода из одной УК в другую».docx",
    "Как создать ТСЖ и уйти от УК": "docs/management/Инструкция_ «Как создать ТСЖ и уйти от УК».docx",
    "Подробные инструкции по переходу вы найдёте в соответствующих разделах нашего сайта": "/knowledge#management",
    "Сравнение УК и ТСЖ: какой способ управления выбрать?": "docs/management/УК или ТСЖ_ какой способ управления домом выбрать_.docx",
    "Что делать при двойных квитанциях после смены УК": "docs/management/Двойные квитанции после смены управляющей компании_ что делать и кому платить.docx",
    "Как вернуть накопленные средства, если старая УК не передаёт деньги": "/faq#faq-accordion",
    "Правила предоставления коммунальных услуг №354": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=522272",
    "Правила предоставления коммунальных услуг № 354": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=522272",
    "Правила осуществления деятельности по управлению МКД №416": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=465381",
    "Правила осуществления деятельности по управлению МКД № 416": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=465381",
    "Постановление Губернатора Калужской области №708 от 15.12.2025": "http://publication.pravo.gov.ru/document/4000202512190007?index=1",
    "Постановление Губернатора Калужской области № 708 от 15.12.2025": "http://publication.pravo.gov.ru/document/4000202512190007?index=1",
    "Постановление Губернатора Калужской области № 708 от 15.12.2025 (приложение 2, город Калуга).": "http://publication.pravo.gov.ru/document/4000202512190007?index=1",
    "Постановление Губернатора Калужской области №708 от 15.12.2025 (приложение 2, город Калуга).": "http://publication.pravo.gov.ru/document/4000202512190007?index=1",
    "Приказ Министерства конкурентной политики Калужской области № 456-РК от 19.12.2025": "https://mkp.admoblkaluga.ru/upload/oiv/min-konkur/tariff/komissiya/2025/19-12-2025/EE/Prikaz_456-RK.docx",
    "Приказ Министерства конкурентной политики Калужской области № 456-РК от 19.12.2025.": "https://mkp.admoblkaluga.ru/upload/oiv/min-konkur/tariff/komissiya/2025/19-12-2025/EE/Prikaz_456-RK.docx",
    "Приказ Министерства конкурентной политики Калужской области № 456-РК от 19.12.2025. Таблицы 1 и 2 (городские населённые пункты, газовые и электроплиты, электроотопление).": "https://mkp.admoblkaluga.ru/upload/oiv/min-konkur/tariff/komissiya/2025/19-12-2025/EE/Prikaz_456-RK.docx",
    "Как составить претензию в УК": "docs/complaints/6. Образец жалоб по всем ситуациям.docx",
    "Образец жалобы в ГЖИ": "docs/complaints/3. Как правильно подать жалобу в ГЖИ.docx",
    "Заявление на перерасчёт": "/documents/recalculation",
    "Заявление на перерасчет": "/documents/recalculation",
    "Уведомление о расторжении договора с УК": "/documents/termination-notice",
    "Постановление Правительства РФ № 416 – правила осуществления деятельности по управлению МКД.": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=465381",
    "Постановление Правительства РФ № 416 - правила осуществления деятельности по управлению МКД.": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=465381",
    "Федеральный закон № 129-ФЗ – о государственной регистрации юридических лиц (для ТСЖ).": "https://www.consultant.ru/cons/cgi/online.cgi?from=9027-0&req=doc&base=LAW&n=508506&rnd=KWdYUw#flGs5GVmD11lSrGm",
    "Федеральный закон № 129-ФЗ - о государственной регистрации юридических лиц (для ТСЖ).": "https://www.consultant.ru/cons/cgi/online.cgi?from=9027-0&req=doc&base=LAW&n=508506&rnd=KWdYUw#flGs5GVmD11lSrGm",
    "Постановление Правительства РФ № 416 от 15.05.2013 «О порядке осуществления деятельности по управлению многоквартирными домами» (передача документации, уведомления).": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=465381",
    "Постановление Правительства РФ № 416 от 15.05.2013 \"О порядке осуществления деятельности по управлению многоквартирными домами\" (передача документации, уведомления).": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=465381",
    "Приказ Минстроя России от 30.04.2025 N 266/пр \"Об утверждении Требований к оформлению протокола общего собрания собственников помещений в многоквартирном доме и Порядка направления подлинников решений и протокола общего собрания собственников помещений в многоквартирном доме в уполномоченный исполнительный орган субъекта Российской Федерации, осуществляющий государственный жилищный надзор\" (Зарегистрировано в Минюсте России 30.05.2025 N 82451)": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=506700",
    "Приказ Минстроя России от 30.04.2025 N 266/пр \"Об утверждении Требований к оформлению протокола общего собрания собственников помещений в многоквартирном доме и Порядка направления подлинников решений и протокола общего собрания собственников помещений в многоквартирном доме в уполномоченный исполнительный орган субъекта Российской Федерации, осуществляющий государственный жилищный надзор\" (Зарегистрировано в Минюсте России 30.05.2025 N 82451).": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=506700",
    "Приказ Минстроя России от 30.04.2025 № 266/пр «Об утверждении Требований к оформлению протокола общего собрания собственников помещений в многоквартирном доме и Порядка направления подлинников решений и протокола общего собрания собственников помещений в многоквартирном доме в уполномоченный исполнительный орган субъекта Российской Федерации, осуществляющий государственный жилищный надзор» (Зарегистрировано в Минюсте России 30.05.2025 № 82451).": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=506700",
    "Приказ Минстроя России от 30.04.2025 N 266/пр \"Об утверждении Требований к оформлению протокола общего собрания собственников помещений в многоквартирном доме и Порядка направления подлинников решений и протокола общего собрания собственников помещений в многоквартирном доме в уполномоченный исполнительный орган субъекта Российской Федерации, осуществляющий государственный жилищный надзор\"": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=506700",
    "Приказ Минстроя России от 30.04.2025 N 266/пр \"Об утверждении Требований к оформлению протокола общего собрания собственников помещений в многоквартирном доме и Порядка направления подлинников решений и протокола общего собрания собственников помещений в многоквартирном доме в уполномоченный исполнительный орган субъекта Российской Федерации, осуществляющий государственный жилищный надзор\".": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=506700",
    "Приказ Минстроя России от 30.04.2025 № 266/пр «Об утверждении Требований к оформлению протокола общего собрания собственников помещений в многоквартирном доме и Порядка направления подлинников решений и протокола общего собрания собственников помещений в многоквартирном доме в уполномоченный исполнительный орган субъекта Российской Федерации, осуществляющий государственный жилищный надзор».": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=506700",
    "Приказ Минстроя России № 44/пр от 28.01.2019 «Об утверждении требований к оформлению протоколов общих собраний собственников помещений в многоквартирных домах».": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=506700",
    "Приказ Минстроя России № 44/пр от 28.01.2019 \"Об утверждении требований к оформлению протоколов общих собраний собственников помещений в многоквартирных домах\".": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=506700",
    "Постановление Правительства РФ № 491 от 13.08.2006 (состав технической документации).": "https://www.consultant.ru/cons/cgi/online.cgi?req=doc&base=LAW&n=62293",
}
INLINE_DOC_LINK_PLACEHOLDERS = {"оформить гиперссылками"}
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


def apply_docx_text_replacements(value):
    text = str(value or "")
    for before, after in DOCX_TEXT_REPLACEMENTS.items():
        if before in text:
            text = text.replace(before, after)
    return text


def _split_trailing_punctuation(value):
    punctuation = ".,;:!?)]}"
    trailing = ""
    token = value

    while token and token[-1] in punctuation:
        trailing = token[-1] + trailing
        token = token[:-1]

    return token, trailing


def _build_phone_href(value):
    digits = re.sub(r"\D", "", value)
    if not digits:
        return None

    if len(digits) == 11 and digits.startswith("8"):
        return "+7" + digits[1:]
    if len(digits) == 11 and digits.startswith("7"):
        return "+7" + digits[1:]
    if value.strip().startswith("+"):
        return "+" + digits
    return "+" + digits


def linkify_docx_text(value):
    if value is None:
        return Markup("")

    text = apply_docx_text_replacements(value)
    cursor = 0
    chunks = []

    while cursor < len(text):
        legal_match = LEGAL_INLINE_LINK_PATTERN.search(text, cursor)
        token_match = DOCX_INLINE_TOKEN_RE.search(text, cursor)

        match = None
        match_kind = None
        if legal_match and token_match:
            if legal_match.start() <= token_match.start():
                match = legal_match
                match_kind = "legal"
            else:
                match = token_match
                match_kind = "token"
        elif legal_match:
            match = legal_match
            match_kind = "legal"
        elif token_match:
            match = token_match
            match_kind = "token"
        else:
            chunks.append(markup_escape(text[cursor:]))
            break

        start, end = match.span()
        if start > cursor:
            chunks.append(markup_escape(text[cursor:start]))

        if match_kind == "legal":
            legal_text = match.group(0)
            href = LEGAL_INLINE_LINK_ALIASES.get(legal_text)
            if href:
                chunks.append(
                    Markup('<a class="docx-inline-link" href="{href}" target="_blank" rel="noopener noreferrer">{text}</a>').format(
                        href=markup_escape(href),
                        text=markup_escape(legal_text),
                    )
                )
            else:
                chunks.append(markup_escape(legal_text))
            cursor = end
            continue

        token = match.group(0)
        token_core, trailing = _split_trailing_punctuation(token)
        if not token_core:
            chunks.append(markup_escape(token))
            cursor = end
            continue

        group = match.lastgroup
        href = None
        external = False

        if group == "email":
            href = f"mailto:{token_core}"
        elif group == "phone":
            normalized_phone = _build_phone_href(token_core)
            href = f"tel:{normalized_phone}" if normalized_phone else None
        elif group == "url":
            href = token_core if token_core.lower().startswith(("http://", "https://")) else f"https://{token_core}"
            external = True

        if href:
            attrs = Markup(' target="_blank" rel="noopener noreferrer"') if external else Markup("")
            chunks.append(
                Markup('<a class="docx-inline-link" href="{href}"{attrs}>{text}</a>').format(
                    href=markup_escape(href),
                    attrs=attrs,
                    text=markup_escape(token_core),
                )
            )
            if trailing:
                chunks.append(markup_escape(trailing))
        else:
            chunks.append(markup_escape(token))

        cursor = end

    return Markup("").join(chunks)


def normalize_inline_link_key(value):
    if not isinstance(value, str):
        return ""
    return " ".join(WORD_RE.findall(value.lower().replace("ё", "е")))


def build_inline_doc_link_map(docx_registry):
    link_map = {}

    def register_alias(alias, href):
        key = normalize_inline_link_key(alias)
        if key and href:
            link_map.setdefault(key, href)

    for static_path, meta in docx_registry.items():
        href = url_for("docx_preview", file=static_path)
        title = meta.get("title") if isinstance(meta, dict) else None

        if isinstance(title, str) and title.strip():
            register_alias(title, href)
            if ":" in title:
                register_alias(title.split(":", 1)[0], href)

        register_alias(Path(static_path).stem.replace("_", " "), href)

    for alias, target in INLINE_DOC_LINK_ALIASES.items():
        register_alias(alias, resolve_document_href(target))

    return link_map


def _normalize_docx_part_href(href):
    if not isinstance(href, str):
        return None

    normalized = href.strip()
    if not normalized:
        return None

    lowered = normalized.lower()
    if lowered.startswith(("http://", "https://", "mailto:", "tel:", "#")):
        return normalized
    if lowered.startswith("www."):
        return f"https://{normalized}"
    return resolve_document_href(normalized)


def _prepare_docx_parts(parts):
    prepared_parts = []

    for part in parts or []:
        if not isinstance(part, dict):
            continue

        text = apply_docx_text_replacements(part.get("text"))
        if text == "":
            continue

        prepared_part = {"text": text}
        href = _normalize_docx_part_href(part.get("href"))
        if href:
            prepared_part["href"] = href
        prepared_parts.append(prepared_part)

    return prepared_parts


def prepare_docx_preview_content(content, link_map):
    prepared = []

    for block in content:
        block_type = block.get("type")

        if block_type == "table":
            prepared_rows = []
            for row in block.get("rows", []):
                prepared_cells = []
                for cell in row:
                    if isinstance(cell, dict):
                        prepared_cell = {**cell, "text": apply_docx_text_replacements(cell.get("text"))}
                        if isinstance(cell.get("parts"), list):
                            prepared_parts = _prepare_docx_parts(cell.get("parts"))
                            if prepared_parts:
                                prepared_cell["parts"] = prepared_parts
                            else:
                                prepared_cell.pop("parts", None)
                        prepared_cells.append(prepared_cell)
                    else:
                        prepared_cells.append(apply_docx_text_replacements(cell))

                if prepared_cells:
                    prepared_rows.append(prepared_cells)

            prepared.append({**block, "rows": prepared_rows})
            continue

        if block_type != "paragraph":
            prepared.append(block)
            continue

        text = apply_docx_text_replacements((block.get("text") or "").strip())
        prepared_block = {**block, "text": text}

        if isinstance(block.get("parts"), list):
            prepared_parts = _prepare_docx_parts(block.get("parts"))
            if prepared_parts:
                prepared_block["parts"] = prepared_parts
            else:
                prepared_block.pop("parts", None)

        normalized = normalize_inline_link_key(text)
        if normalized in INLINE_DOC_LINK_PLACEHOLDERS:
            continue

        link_href = link_map.get(normalized)
        if link_href:
            prepared.append({**prepared_block, "link_href": link_href})
            continue

        prepared.append(prepared_block)

    return prepared


def _append_docx_part(parts, text, href=None):
    if not text:
        return

    normalized_href = href if isinstance(href, str) and href.strip() else None
    if parts and parts[-1].get("href") == normalized_href:
        parts[-1]["text"] += text
        return

    part = {"text": text}
    if normalized_href:
        part["href"] = normalized_href
    parts.append(part)


def _trim_docx_parts(parts):
    trimmed = []

    for part in parts or []:
        text = part.get("text") if isinstance(part, dict) else None
        if text is None or text == "":
            continue
        item = {"text": text}
        href = part.get("href")
        if href:
            item["href"] = href
        trimmed.append(item)

    while trimmed:
        start_text = trimmed[0]["text"].lstrip()
        if start_text:
            trimmed[0]["text"] = start_text
            break
        trimmed.pop(0)

    while trimmed:
        end_text = trimmed[-1]["text"].rstrip()
        if end_text:
            trimmed[-1]["text"] = end_text
            break
        trimmed.pop()

    return trimmed


def _extract_docx_relationships(archive):
    if "word/_rels/document.xml.rels" not in archive.namelist():
        return {}

    try:
        rel_root = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
    except ET.ParseError:
        return {}

    relationships = {}
    for relationship in rel_root.findall("rel:Relationship", DOCX_RELATIONSHIP_NAMESPACE):
        rel_id = relationship.attrib.get("Id")
        rel_type = relationship.attrib.get("Type")
        target = relationship.attrib.get("Target")
        target_mode = (relationship.attrib.get("TargetMode") or "").lower()
        if not rel_id or not target:
            continue
        if rel_type == DOCX_HYPERLINK_REL_TYPE or target_mode == "external":
            relationships[rel_id] = target

    return relationships


def _extract_docx_parts(node, relationships, current_href=None, output=None):
    parts = output if output is not None else []

    for child in list(node):
        tag = child.tag.rsplit("}", 1)[-1]

        if tag == "hyperlink":
            rel_id = child.attrib.get(DOCX_RELATIONSHIP_ID_ATTR)
            hyperlink_href = relationships.get(rel_id) if rel_id else None
            if not hyperlink_href:
                anchor = child.attrib.get(DOCX_ANCHOR_ATTR)
                if anchor:
                    hyperlink_href = f"#{anchor}"
            _extract_docx_parts(child, relationships, hyperlink_href or current_href, parts)
            continue

        if tag == "t":
            _append_docx_part(parts, child.text or "", current_href)
            continue

        if tag == "tab":
            _append_docx_part(parts, "    ", current_href)
            continue

        if tag in {"br", "cr"}:
            _append_docx_part(parts, " ", current_href)
            continue

        _extract_docx_parts(child, relationships, current_href, parts)

    return parts


def _extract_docx_paragraph_data(node, relationships):
    raw_parts = _extract_docx_parts(node, relationships)
    if not raw_parts:
        return None

    text = "".join(part.get("text", "") for part in raw_parts).strip()
    if not text:
        return None

    paragraph_data = {"text": text}
    if any(part.get("href") for part in raw_parts):
        paragraph_data["parts"] = _trim_docx_parts(raw_parts)

    return paragraph_data


def classify_docx_paragraph(text, is_first=False):
    compact = " ".join(text.split())
    normalized = compact.lower()

    if is_first:
        return "title"
    if normalized.startswith("актуально на "):
        return "meta"
    if compact.startswith("*"):
        return "note"
    if compact.endswith(":") and len(compact) <= 90:
        return "heading"
    if len(compact) <= 80 and compact.count(" ") <= 7 and not compact.endswith("."):
        return "heading"
    return "paragraph"


def extract_docx_content(static_path):
    target = Path(app.static_folder, *static_path.split("/"))
    if not target.exists():
        raise FileNotFoundError(static_path)

    with ZipFile(target) as archive:
        xml_bytes = archive.read("word/document.xml")
        relationships = _extract_docx_relationships(archive)

    root = ET.fromstring(xml_bytes)
    body = root.find("w:body", DOCX_NAMESPACE)
    if body is None:
        return []

    content = []
    paragraph_index = 0

    for child in list(body):
        tag = child.tag.rsplit("}", 1)[-1]

        if tag == "p":
            paragraph_data = _extract_docx_paragraph_data(child, relationships)
            if not paragraph_data:
                continue

            text = paragraph_data["text"]
            paragraph_block = {
                "type": "paragraph",
                "style": classify_docx_paragraph(text, is_first=paragraph_index == 0),
                "text": text,
            }
            if paragraph_data.get("parts"):
                paragraph_block["parts"] = paragraph_data["parts"]

            content.append(paragraph_block)
            paragraph_index += 1
            continue

        if tag != "tbl":
            continue

        rows = []
        for row in child.findall("w:tr", DOCX_NAMESPACE):
            cells = []
            for cell in row.findall("w:tc", DOCX_NAMESPACE):
                fragments = []
                cell_parts = []
                for paragraph in cell.findall("w:p", DOCX_NAMESPACE):
                    paragraph_data = _extract_docx_paragraph_data(paragraph, relationships)
                    if not paragraph_data:
                        continue

                    if fragments:
                        _append_docx_part(cell_parts, "\n")

                    parts = paragraph_data.get("parts")
                    if parts:
                        for part in parts:
                            _append_docx_part(cell_parts, part.get("text", ""), part.get("href"))
                    else:
                        _append_docx_part(cell_parts, paragraph_data["text"])

                    fragments.append(paragraph_data["text"])

                cell_text = "\n".join(fragments).strip()
                if cell_text:
                    if any(part.get("href") for part in cell_parts):
                        cells.append({"text": cell_text, "parts": _trim_docx_parts(cell_parts)})
                    else:
                        cells.append(cell_text)

            if cells:
                rows.append(cells)

        if rows:
            content.append({"type": "table", "rows": rows})

    return content


def extract_docx_paragraphs(static_path):
    return [block["text"] for block in extract_docx_content(static_path) if block.get("type") == "paragraph"]


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


@app.template_filter("docx_linkify")
def docx_linkify_filter(value):
    return linkify_docx_text(value)


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
        flash("Сначала войдите в админку.", "warning")
        return False
    return True


def build_admin_document_groups():
    section_titles = {
        "tariff_guides": "Тарифы",
        "management_guides": "Смена УК и ТСЖ",
        "complaint_guides": "Жалобы",
        "legal_documents": "Правовые документы",
        "document_tools": "Формы и рабочие документы",
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
                    "filename": Path(file_ref).name if file_ref else "Файл не привязан",
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


def get_termination_notice_form_data(source):
    fields = {}
    for key, default_value in TERMINATION_NOTICE_FORM_DEFAULTS.items():
        value = source.get(key, default_value)
        fields[key] = value.strip() if isinstance(value, str) else value
    return fields


RU_MONTHS = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}


def _str_value(value, fallback=""):
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _format_ru_doc_date(value):
    raw = _str_value(value, "")
    if not raw:
        return "«_» _________ 20 ___ г."
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        return raw
    month_name = RU_MONTHS.get(parsed.month, "")
    return f"«{parsed.day:02d}» {month_name} {parsed.year} г."


def _company_name(value):
    cleaned = _str_value(value, "").strip().strip("«»\" ")
    if cleaned.lower().startswith("ооо"):
        cleaned = cleaned[3:].strip().strip("«»\" ")
    return cleaned


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


def build_termination_notice_paragraphs(form_data):
    recipient_company = _company_name(form_data.get("recipient_company", form_data.get("recipient", "")))
    recipient_address = _str_value(form_data.get("recipient_address", ""))
    applicant_name = _str_value(form_data.get("applicant_name", form_data.get("applicant", "")))
    applicant_address = _str_value(form_data.get("applicant_address", form_data.get("address", "")))
    applicant_phone = _str_value(form_data.get("applicant_phone", ""))
    authority_protocol_number = _str_value(form_data.get("authority_protocol_number", form_data.get("protocol_number", "")))
    authority_protocol_date = _format_ru_doc_date(form_data.get("authority_protocol_date", form_data.get("protocol_date", "")))
    oss_meeting_date = _format_ru_doc_date(form_data.get("oss_meeting_date", form_data.get("protocol_date", "")))
    house_city = _str_value(form_data.get("house_city", ""))
    house_street = _str_value(form_data.get("house_street", ""))
    house_building = _str_value(form_data.get("house_building", ""))
    contract_number = _str_value(form_data.get("contract_number", ""))
    contract_date = _format_ru_doc_date(form_data.get("contract_date", form_data.get("protocol_date", "")))
    termination_effective_date = _format_ru_doc_date(form_data.get("termination_effective_date", form_data.get("termination_date", "")))
    new_manager_name = _company_name(form_data.get("new_manager_name", form_data.get("new_manager", "")))
    new_manager_inn = _str_value(form_data.get("new_manager_inn", ""))
    new_manager_license = _str_value(form_data.get("new_manager_license", ""))
    basis = _str_value(form_data.get("basis", ""))
    evidence_pages = _str_value(form_data.get("evidence_pages", "___"))
    sign_date = _format_ru_doc_date(form_data.get("sign_date", ""))
    signer_name = _str_value(form_data.get("signer_name", applicant_name))

    return [
        {"text": f"Руководителю ООО «{recipient_company}» (наименование управляющей компании) Адрес: {recipient_address}"},
        {"text": f"от {applicant_name} (Ф.И.О. уполномоченного лица – председателя совета МКД или иного лица, определённого протоколом ОСС) проживающего(ей) по адресу: {applicant_address} тел.: {applicant_phone}"},
        {"text": f"действующего на основании протокола общего собрания собственников помещений МКД № {authority_protocol_number} от {authority_protocol_date}"},
        {"text": ""},
        {"text": "УВЕДОМЛЕНИЕ", "align": "center", "bold": True},
        {"text": "о расторжении договора управления многоквартирным домом", "align": "center", "bold": True},
        {"text": ""},
        {"text": f"Настоящим уведомляю Вас о том, что {oss_meeting_date} было проведено общее собрание собственников помещений многоквартирного дома, расположенного по адресу: г. {house_city}, ул. {house_street}, д. {house_building} (далее – МКД)."},
        {"text": f"По итогам проведения собрания принято решение о расторжении договора управления МКД № {contract_number} от {contract_date}, заключённого между собственниками помещений в МКД и Вашей организацией."},
        {"text": "Решение принято на основании: (выбрать и оставить нужный пункт, остальные удалить)"},
        {"text": "пункта 8.2 статьи 162 Жилищного кодекса РФ – в связи с невыполнением управляющей организацией условий договора управления (доказательства прилагаются);"},
        {"text": "пункта 8.2 статьи 162 Жилищного кодекса РФ – в связи с изменением способа управления МКД (создание ТСЖ / переход на непосредственное управление);"},
        {"text": "части 6 статьи 162 Жилищного кодекса РФ – по окончании срока действия договора (отказ от автоматического продления)."},
        {"text": f"Выбранное основание: {basis}"},
        {"text": f"В качестве новой управляющей организации выбрано ООО «{new_manager_name}» (ИНН {new_manager_inn}, номер лицензии {new_manager_license})."},
        {"text": "В связи с вышеизложенным и в соответствии с частью 10 статьи 162 Жилищного кодекса РФ, а также пунктом 19 Правил осуществления деятельности по управлению многоквартирными домами (утверждены Постановлением Правительства РФ № 416 от 15.05.2013) требую:"},
        {"text": f"Считать договор управления МКД № {contract_number} от {contract_date} расторгнутым с момента получения настоящего уведомления (или: с {termination_effective_date} – указать дату в соответствии с условиями договора)."},
        {"text": f"В течение 3 (трёх) рабочих дней с даты получения настоящего уведомления передать по акту техническую документацию на МКД, ключи от помещений, входящих в состав общего имущества, электронные коды доступа к оборудованию и иные технические средства, необходимые для эксплуатации и управления домом, в адрес новой управляющей организации ООО «{new_manager_name}»."},
        {"text": "Прекратить выставление платёжных документов собственникам помещений в МКД с даты расторжения договора."},
        {"text": "Настоящее уведомление направлено в соответствии с пунктом 18 Правил осуществления деятельности по управлению многоквартирными домами (утверждены Постановлением Правительства РФ № 416 от 15.05.2013) в течение 5 рабочих дней с даты составления протокола общего собрания."},
        {"text": "Приложения:", "bold": True},
        {"text": f"Копия протокола общего собрания собственников помещений в МКД № {authority_protocol_number} от {authority_protocol_date} (с приложениями)."},
        {"text": f"Копия договора управления № {contract_number} от {contract_date}."},
        {"text": f"Доказательства невыполнения условий договора (при досрочном расторжении по ч. 8.2 ст. 162 ЖК РФ) – на {evidence_pages} листах."},
        {"text": ""},
        {"text": f"Дата: {sign_date}"},
        {"text": f"Уполномоченное лицо: _________________________ / {signer_name} (подпись) (Ф.И.О.)"},
    ]


def _paragraph_xml(paragraph):
    text = escape(paragraph["text"])
    align = paragraph.get("align")
    bold = paragraph.get("bold", False)
    paragraph_props = f"<w:pPr><w:jc w:val=\"{align}\"/></w:pPr>" if align else ""
    run_props = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return "<w:p>" + paragraph_props + "<w:r>" + run_props + f"<w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


def build_docx(paragraphs, title="Заявление на перерасчёт по ЖКХ"):
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
<Properties xmlns=\"http://schemas.openxmlformats.org/officeDocument/2006/extended-properties\" xmlns:vt=\"http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes\"><Application>ЖКХ40.РФ</Application></Properties>"""
    core_xml = f"""<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<cp:coreProperties xmlns:cp=\"http://schemas.openxmlformats.org/package/2006/metadata/core-properties\" xmlns:dc=\"http://purl.org/dc/elements/1.1/\" xmlns:dcterms=\"http://purl.org/dc/terms/\" xmlns:dcmitype=\"http://purl.org/dc/dcmitype/\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\"><dc:title>{escape(title)}</dc:title><dc:creator>ЖКХ40.РФ</dc:creator></cp:coreProperties>"""
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


def get_pdf_fonts():
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError as error:
        raise RuntimeError("Для выгрузки PDF нужно установить библиотеку reportlab.") from error

    global PDF_FONT_CACHE
    if PDF_FONT_CACHE:
        return PDF_FONT_CACHE

    regular_font = "Helvetica"
    bold_font = "Helvetica-Bold"

    regular_candidates = [
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/PTSans.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    ]
    bold_candidates = [
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/PTSans.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ]

    for candidate in regular_candidates:
        if not candidate.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont("JKH40Regular", str(candidate)))
            regular_font = "JKH40Regular"
            break
        except Exception:
            continue

    for candidate in bold_candidates:
        if not candidate.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont("JKH40Bold", str(candidate)))
            bold_font = "JKH40Bold"
            break
        except Exception:
            continue

    PDF_FONT_CACHE = (regular_font, bold_font)
    return PDF_FONT_CACHE


def build_recalc_pdf(form_data):
    try:
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as error:
        raise RuntimeError("Для выгрузки PDF нужно установить библиотеку reportlab.") from error

    regular_font, bold_font = get_pdf_fonts()
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "RecalcTitle",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=15,
        leading=19,
        alignment=TA_CENTER,
        spaceAfter=10,
    )
    body_style = ParagraphStyle(
        "RecalcBody",
        parent=styles["Normal"],
        fontName=regular_font,
        fontSize=11.4,
        leading=16.2,
        spaceAfter=8,
    )
    recipient_style = ParagraphStyle(
        "RecalcRecipient",
        parent=body_style,
        alignment=TA_RIGHT,
    )

    def paragraph(text, style, allow_html=False):
        prepared = text.replace("\n", "<br/>") if allow_html else escape(text).replace("\n", "<br/>")
        return Paragraph(prepared, style)

    story = []
    story.append(
        paragraph(
            f"Руководителю<br/>{escape(form_data['recipient'])}<br/>от {escape(form_data['applicant'])}<br/>{escape(form_data['address'])}",
            recipient_style,
            allow_html=True,
        )
    )
    story.append(Spacer(1, 10))
    story.append(paragraph("Заявление", title_style))
    story.append(
        paragraph(
            f"Прошу произвести перерасчёт размера платы за коммунальные услуги за период с {form_data['period_from']} по {form_data['period_to']}.",
            body_style,
        )
    )
    story.append(paragraph(f"<b>Причина перерасчёта:</b> {escape(form_data['reason'])}", body_style, allow_html=True))
    story.append(paragraph(f"<b>Основание:</b> {escape(form_data['basis'])}", body_style, allow_html=True))
    story.append(
        paragraph(
            "К заявлению могут быть приложены акты замера, фотофиксация, переписка с УК, номер обращения в аварийно-диспетчерскую службу и иные документы.",
            body_style,
        )
    )
    story.append(Spacer(1, 16))

    signature_table = Table(
        [["Дата ____________________", "Подпись ____________________"]],
        colWidths=[80 * mm, 80 * mm],
        hAlign="LEFT",
    )
    signature_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), regular_font),
                ("FONTSIZE", (0, 0), (-1, -1), 11.2),
                ("TEXTCOLOR", (0, 0), (-1, -1), "#213154"),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 18),
            ]
        )
    )
    story.append(signature_table)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title="Заявление на перерасчёт по ЖКХ",
    )
    doc.build(story)
    buffer.seek(0)
    return buffer


def build_termination_notice_pdf(form_data):
    try:
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as error:
        raise RuntimeError("Для выгрузки PDF нужно установить библиотеку reportlab.") from error

    regular_font, bold_font = get_pdf_fonts()
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TerminationTitle",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=13.6,
        leading=17,
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    centered_style = ParagraphStyle(
        "TerminationCentered",
        parent=styles["Normal"],
        fontName=regular_font,
        fontSize=11.4,
        leading=16.2,
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "TerminationBody",
        parent=styles["Normal"],
        fontName=regular_font,
        fontSize=11.4,
        leading=16.2,
        spaceAfter=8,
    )
    def paragraph(text, style, allow_html=False):
        prepared = text.replace("\n", "<br/>") if allow_html else escape(text).replace("\n", "<br/>")
        return Paragraph(prepared, style)

    story = []
    for item in build_termination_notice_paragraphs(form_data):
        text = item.get("text", "")
        if not text:
            story.append(Spacer(1, 8))
            continue

        if item.get("align") == "center":
            style = title_style if item.get("bold") else centered_style
        else:
            style = body_style

        allow_html = False
        if item.get("bold") and item.get("align") != "center":
            text = f"<b>{escape(text)}</b>"
            allow_html = True

        story.append(paragraph(text, style, allow_html=allow_html))

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title="Уведомление о расторжении договора с УК",
    )
    doc.build(story)
    buffer.seek(0)
    return buffer


@app.route("/")
def home():
    return render_page("home.html", "home", page_title="Главная", popular_queries=HOME_POPULAR_QUERIES, service_cards=HOME_SERVICE_CARDS, important_items=HOME_IMPORTANT_ITEMS, news_items=HOME_NEWS_ITEMS)


@app.route("/chat")
def chat():
    query = request.args.get("q", "").strip()
    selected_scenario = request.args.get("scenario", "").strip()
    return render_page(
        "chat.html",
        "home",
        page_title="Чат-бот",
        chat_scenarios=prepare_chat_scenarios(),
        initial_query=query,
        selected_scenario=selected_scenario,
    )


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
    if not static_path:
        abort(404)

    target_path = Path(app.static_folder) / static_path
    if not target_path.exists():
        abort(404)

    document_meta = docx_registry.get(
        static_path,
        {
            "title": Path(static_path).stem.replace("_", " "),
            "filename": Path(static_path).name,
        },
    )
    doc_content = extract_docx_content(static_path)
    paragraph_count = sum(1 for block in doc_content if block.get("type") == "paragraph")
    table_count = sum(1 for block in doc_content if block.get("type") == "table")
    header_meta = ""
    filtered_content = list(doc_content)

    if filtered_content and filtered_content[0].get("type") == "paragraph" and filtered_content[0].get("style") == "title":
        filtered_content = filtered_content[1:]

    if filtered_content and filtered_content[0].get("type") == "paragraph" and filtered_content[0].get("style") == "meta":
        header_meta = filtered_content[0].get("text", "")
        filtered_content = filtered_content[1:]

    inline_link_map = build_inline_doc_link_map(docx_registry)
    filtered_content = prepare_docx_preview_content(filtered_content, inline_link_map)
    doc_fill_url = None
    doc_fill_label = None
    if static_path == TERMINATION_NOTICE_DOC_PATH:
        doc_fill_url = url_for("termination_notice_fill")
        doc_fill_label = "Заполнить форму"

    return render_page(
        "docx_preview.html",
        "knowledge",
        page_title=document_meta["title"],
        doc_title=document_meta["title"],
        doc_download_url=url_for("static", filename=static_path),
        doc_open_url=url_for("static", filename=static_path, _external=True),
        doc_filename=document_meta["filename"],
        doc_content=filtered_content,
        doc_paragraph_count=paragraph_count,
        doc_table_count=table_count,
        doc_header_meta=header_meta,
        doc_fill_url=doc_fill_url,
        doc_fill_label=doc_fill_label,
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
        page_title="О нас",
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


@app.post("/documents/recalculation/export-pdf")
def recalculation_export_pdf():
    form_data = get_recalc_form_data(request.form)
    try:
        document = build_recalc_pdf(form_data)
    except RuntimeError as error:
        flash(str(error), "error")
        return redirect(url_for("recalculation_fill"))
    return send_file(document, as_attachment=True, download_name="zayavlenie-na-pereraschet-jkh.pdf", mimetype="application/pdf")


@app.route("/documents/termination-notice")
def termination_notice_document():
    return redirect(
        url_for(
            "docx_preview",
            file=TERMINATION_NOTICE_DOC_PATH,
        )
    )


@app.route("/documents/termination-notice/fill")
def termination_notice_fill():
    return render_page(
        "termination_fill.html",
        "knowledge",
        page_title="Форма заполнения уведомления",
        default_form=get_termination_notice_form_data({}),
    )


@app.route("/documents/termination-notice/print")
def termination_notice_print():
    form_data = get_termination_notice_form_data(request.args)
    return render_page(
        "termination_preview.html",
        "knowledge",
        page_title="Печатная версия уведомления",
        form_data=form_data,
        print_mode=True,
        preview_title="Печатная версия уведомления",
    )


@app.post("/documents/termination-notice/export-docx")
def termination_notice_export_docx():
    form_data = get_termination_notice_form_data(request.form)
    document = build_docx(
        build_termination_notice_paragraphs(form_data),
        title="Уведомление о расторжении договора с УК",
    )
    return send_file(
        document,
        as_attachment=True,
        download_name="uvedomlenie-o-rastorzhenii-dogovora-s-uk.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.post("/documents/termination-notice/export-pdf")
def termination_notice_export_pdf():
    form_data = get_termination_notice_form_data(request.form)
    try:
        document = build_termination_notice_pdf(form_data)
    except RuntimeError as error:
        flash(str(error), "error")
        return redirect(url_for("termination_notice_fill"))
    return send_file(
        document,
        as_attachment=True,
        download_name="uvedomlenie-o-rastorzhenii-dogovora-s-uk.pdf",
        mimetype="application/pdf",
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = (request.form.get("password") or "").strip()
        if password == os.environ.get("JKH40_ADMIN_PASSWORD", "admin"):
            session["admin_logged_in"] = True
            flash("Вход выполнен.", "success")
            return redirect(url_for("admin_dashboard"))
        flash("Неверный пароль.", "error")

    return render_page("admin_login.html", "about", page_title="Вход в админку")


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("admin_logged_in", None)
    flash("Вы вышли из админки.", "success")
    return redirect(url_for("admin_login"))


@app.route("/admin")
def admin_dashboard():
    if not admin_required():
        return redirect(url_for("admin_login"))

    admin_content = load_admin_content()
    return render_page(
        "admin_dashboard.html",
        "about",
        page_title="Админка",
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
    flash("Тексты обновлены.", "success")
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
            flash("У этого элемента нет привязанного файла для замены.", "error")
            return redirect(url_for("admin_dashboard"))

        target_path = Path(app.static_folder) / target_ref
        source_ext = Path(uploaded.filename).suffix.lower()
        target_ext = target_path.suffix.lower()
        if source_ext and source_ext != target_ext:
            flash(f"Нужен файл того же типа: {target_ext}", "error")
            return redirect(url_for("admin_dashboard"))

        target_path.parent.mkdir(parents=True, exist_ok=True)
        uploaded.save(target_path)

    save_admin_content(admin_content)
    flash("Документ обновлён.", "success")
    return redirect(url_for("admin_dashboard"))


if __name__ == "__main__":
    app.run(debug=True)


