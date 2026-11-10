"""Build the one-page checkpoint document from the measured EDA summary."""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache/matplotlib"))

from matplotlib.font_manager import FontProperties, findfont
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, HRFlowable, Table, TableStyle


def main():
    summary = json.loads((ROOT / "reports/eda_summary.json").read_text())
    pdfmetrics.registerFont(TTFont("DejaVu", findfont(FontProperties(family="DejaVu Sans"))))
    pdfmetrics.registerFont(TTFont("DejaVuBold", findfont(FontProperties(family="DejaVu Sans", weight="bold"))))
    pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVuBold")
    styles = {
        "title": ParagraphStyle("title", fontName="DejaVuBold", fontSize=18, leading=23,
                                textColor=colors.HexColor("#20354a"), spaceAfter=7),
        "meta": ParagraphStyle("meta", fontName="DejaVu", fontSize=9, leading=13,
                               textColor=colors.HexColor("#596675"), spaceAfter=12),
        "heading": ParagraphStyle("heading", fontName="DejaVuBold", fontSize=10.6, leading=14,
                                  textColor=colors.HexColor("#20354a"), spaceBefore=11, spaceAfter=4),
        "body": ParagraphStyle("body", fontName="DejaVu", fontSize=10.4, leading=14.5,
                               textColor=colors.HexColor("#202832"), alignment=TA_LEFT),
        "source": ParagraphStyle("source", fontName="DejaVu", fontSize=8, leading=11,
                                 textColor=colors.HexColor("#596675"), spaceBefore=12),
    }
    styles["table"] = ParagraphStyle("table", fontName="DejaVu", fontSize=9.2, leading=12.5,
                                    textColor=colors.HexColor("#202832"))
    story = []

    def add(text, style="body"):
        story.append(Paragraph(text, styles[style]))

    add("Research Assistant для научных статей", "title")
    add("Практическая ценность проекта | Чекпойнт 2<br/>"
        "Новиков Артемий, Кирилл Лебедев | Куратор: Тимофей Соборнов", "meta")
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#c9d4de")))

    add("Задача пользователя", "heading")
    add("Исследователю нужно проверить утверждение: найти исходную работу и подтверждающий "
        "фрагмент. Ассистент должен принимать статью, искать по ней и её источникам и давать "
        "ответ со ссылками на фрагменты, которые пользователь может проверить.")

    add("Реализуемость", "heading")
    add(f"Проверены сбор и EDA {summary['n']} аннотаций cs.IR/cs.CL за январь-март 2025 года "
        f"на CPU; сбор выполнен 10.11.2026. XML занимают {summary['raw_xml_mib']:g} МиБ. "
        "Первый поисковый прототип можно ограничить аннотациями. Проверка утверждений "
        "потребует доступных полных текстов. Поиск, генерация ответов и их стоимость ещё не проверены.")

    add("Риски внедрения и планируемые меры", "heading")
    add("Серьёзность оценена качественно по последствиям для достоверности ответа, "
        "конфиденциальности и доступности сервиса.")
    risks = [
        ("Ошибка подтверждения<br/><b>Критическая</b>",
         "Ложный вывод получает видимость обоснования. Проверять соответствие ответа фрагментам; "
         "при нехватке подтверждений сообщать об этом."),
        ("Нет полного текста<br/><b>Высокая</b>",
         "Часть утверждений нельзя проверить по аннотации. Показывать покрытие источников и статус "
         "доступности каждого текста."),
        ("Устаревший источник<br/><b>Высокая</b>",
         "Изменение версии или отзыв может сделать подтверждение неактуальным. Хранить ID, версию, "
         "дату сбора и пометки об отзыве; проверять обновления."),
        ("Утечка загруженного PDF<br/><b>Высокая</b>",
         "Пользователь может загрузить неопубликованную работу. Обрабатывать её локально; "
         "передачу внешнему сервису включать только по явному выбору пользователя."),
        ("Рост времени и затрат<br/><b>Средняя</b>",
         "Расширение графа увеличивает объём обработки. Ограничить число источников, кешировать "
         "результаты; измерить задержку и стоимость полного сценария."),
    ]
    table_rows = [[Paragraph("<b>Риск / серьёзность</b>", styles["table"]),
                   Paragraph("<b>Последствие / мера</b>", styles["table"])]]
    table_rows += [[Paragraph(a, styles["table"]), Paragraph(b, styles["table"])] for a, b in risks]
    table = Table(table_rows, colWidths=[144, A4[0]-104-144], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#e8eef3")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LINEBELOW", (0,0), (-1,-1), .4, colors.HexColor("#cbd5dd")),
        ("LEFTPADDING", (0,0), (-1,-1), 6), ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(table)

    add("Как заказчик проверяет пользу", "heading")
    add("На одинаковых заданиях сравнить ручной поиск и ассистента: время до проверенного "
        "подтверждения, долю выполненных заданий и корректность ссылок. После разметки "
        "релевантности сравнить BM25, биэнкодер и кросс-энкодер по Recall@k и nDCG@k. "
        "Дополнительно измерить задержку и стоимость задания. Качество поиска и ответов, "
        "экономия времени и эффективность мер пока не измерены.")

    add('Основание: EDA.ipynb. Источник: '
        '<link href="https://export.arxiv.org/api/query" color="#355c80">arXiv API</link>. '
        'Условия: <link href="https://info.arxiv.org/help/api/tou.html" '
        'color="#355c80">info.arxiv.org/help/api/tou.html</link>.', "source")

    def footer(canvas, doc):
        canvas.setFont("DejaVu", 8)
        canvas.setFillColor(colors.HexColor("#74808b"))
        canvas.drawString(46, 25, "Проект 181 | DL / PRO")
        canvas.drawRightString(A4[0] - 46, 25, str(doc.page))

    target = ROOT / "practical_value.pdf"
    doc = SimpleDocTemplate(str(target), pagesize=A4, rightMargin=46, leftMargin=46,
                            topMargin=39, bottomMargin=43,
                            title="Практическая ценность Research Assistant",
                            author="Новиков Артемий, Кирилл Лебедев")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    from pypdf import PdfReader
    pages = len(PdfReader(target).pages)
    if pages != 1:
        raise RuntimeError(f"Expected one page, got {pages}")
    print(f"Created {target}: {pages} page")


if __name__ == "__main__":
    main()
