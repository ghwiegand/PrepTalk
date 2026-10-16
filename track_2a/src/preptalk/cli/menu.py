"""Arrow-key main menu with inline, scrollable dropdowns. No model calls."""

import shutil
import textwrap

from . import catalog
from .keys import KeyReader
from .orb import FPS

SITUATIONS = {
    "de": ("Vorstellungsgespräch", "Online-Interview", "Schnuppergespräch", "Nachgespräch", "Assessment", "Telefonanruf"),
    "fr": ("Entretien", "Entretien en ligne", "Entretien de stage", "Entretien de suivi", "Assessment", "Appel téléphonique"),
    "it": ("Colloquio", "Colloquio online", "Colloquio di stage", "Colloquio di seguito", "Assessment", "Telefonata"),
}
SITUATION_KEYS = ("apprenticeship_interview", "online_interview", "trial_interview", "follow_up_interview",
                  "assessment", "phone_call_trial")
LANGUAGES = (("de", "Deutsch"), ("fr", "Français"), ("it", "Italiano"))


def label(kind, item, choices, lang):
    posting = choices["posting"][item["posting_id"]] if kind == "scenario" else item
    occupation = posting["occupation"].get(f"name_{lang}") or posting["occupation"]["name_de"]
    company = posting["company"]
    text = f"{occupation} · {company['name']} · {company.get('place', '')}"
    if kind == "scenario":
        situation = dict(zip(SITUATION_KEYS, SITUATIONS[lang])).get(item["situation"], item["situation"])
        text = f"{situation} · {text} [{item['lang']}]"
    return text


def draw(ui, focus, scenario, posting, mode, choices, dropdown, cursor, status):
    """Compose menu content inside the same fixed panes used by the conversation."""
    if ui.interactive:
        ui.ensure_view()
    rows = [(ui.text["main_menu"], "1"), ("", None)]
    focus_line = 0
    settings = ((ui.text["scenario"], scenario or ui.text["none"]),
                (ui.text["posting"], posting or ui.text["none"]),
                (ui.text["menu_language"], ui.text["language"]),
                (ui.text["menu_mode"], ui.text[f"mode_{mode}"]),
                (ui.text["start_voice" if mode == "voice" else "start_chat"], None))
    for row, (title, value) in enumerate(settings):
        if row == 4:
            rows.append(("", None))
        marker = "›" if row == focus else " "
        suffix = f"  {value}  {'▴' if dropdown and row == focus else '▾'}" if value is not None else ""
        if row < 2 and choices and (scenario if row == 0 else posting):
            kind, key = ("scenario", scenario) if row == 0 else ("posting", posting)
            item = choices[kind].get(key)
            if item:
                suffix = f"  {key} · {label(kind, item, choices, ui.lang)}  ▾"
        line = textwrap.shorten(f"{title}{suffix}", width=max(2, ui.width - 6), placeholder="…")
        if row == focus:
            focus_line = len(rows)
        rows.append((f"{marker} {line}", "1;36" if row == focus else None))
        if dropdown and row == focus:
            capacity = max(1, min(8, shutil.get_terminal_size().lines - 21))
            start = max(0, min(cursor - capacity // 2, len(dropdown) - capacity))
            box_width = max(6, ui.width - 8)
            rows.append(("  ┌" + "─" * box_width + "┐", None))
            selected = (scenario, posting, ui.lang, mode)[row]
            for index in range(start, min(start + capacity, len(dropdown))):
                key, title = dropdown[index]
                marker = "›" if index == cursor else " "
                check = " ✓" if key == selected else ""
                line = textwrap.shorten(f"{title}{check}", width=max(2, box_width - 4), placeholder="…")
                line = "  │ " + f"{marker} {line}".ljust(box_width - 2) + " │"
                if index == cursor:
                    focus_line = len(rows)
                rows.append((line, "1;36" if index == cursor else None))
            rows.append(("  └" + "─" * box_width + "┘", None))
            rows.append((f"{cursor + 1}/{len(dropdown)}", "2"))
    footer = []
    if dropdown and focus == 0:
        footer.append((ui.text["scenario_hint"], "2"))
    footer.append((status or ui.text["dropdown_help" if dropdown else "menu_help"], "2"))
    ui.menu(rows, footer, focus_line)


def main_menu(ui, scenario=None, posting=None, mode="chat"):
    choices, dropdown, status = None, None, ""
    focus, cursor = 0, 0
    with KeyReader() as keyboard:
        try:
            while True:
                draw(ui, focus, scenario, posting, mode, choices, dropdown, cursor, status)
                key = keyboard.read(timeout=1 / FPS)
                if key == "quit":
                    return None
                if key == "back":
                    if dropdown:
                        dropdown = None
                        continue
                    return None
                status = ""
                size = len(dropdown) if dropdown else 5
                position = cursor if dropdown else focus
                if key in ("up", "down", "home", "end", "page_up", "page_down"):
                    if key in ("up", "down"):
                        position = (position + (1 if key == "down" else -1)) % size
                    elif key in ("home", "end"):
                        position = 0 if key == "home" else size - 1
                    else:
                        position = max(0, min(size - 1, position + (8 if key == "page_down" else -8)))
                    if dropdown:
                        cursor = position
                    else:
                        focus = position
                elif key in ("space", "enter", "right"):
                    if dropdown:
                        selected = dropdown[cursor][0]
                        if focus == 0:
                            scenario = selected
                            if selected:
                                posting = None
                        elif focus == 1:
                            posting = selected
                            if selected:
                                scenario = None
                        elif focus == 2:
                            ui.lang = selected
                        else:
                            mode = selected
                        dropdown = None
                    elif focus == 4:
                        return scenario, posting, ui.lang, mode
                    else:
                        if focus == 2:
                            dropdown = list(LANGUAGES)
                            selected = ui.lang
                        elif focus == 3:
                            dropdown = [(value, ui.text[f"mode_{value}"]) for value in ("chat", "voice")]
                            selected = mode
                        else:
                            if choices is None:
                                draw(ui, focus, scenario, posting, mode, choices, None, 0, ui.text["loading_choices"])
                                try:
                                    choices = catalog.load()
                                except (OSError, ValueError, KeyError):
                                    status = ui.text["catalog_error"]
                                    continue
                            kind, selected = ("scenario", scenario) if focus == 0 else ("posting", posting)
                            dropdown = [(None, ui.text["none"])] + [
                                (item["id"], f"{item['id']} · {label(kind, item, choices, ui.lang)}")
                                for item in sorted(choices[kind].values(), key=lambda item: item["id"])]
                        cursor = next((i for i, (value, _) in enumerate(dropdown) if value == selected), 0)
        except KeyboardInterrupt:
            return None
