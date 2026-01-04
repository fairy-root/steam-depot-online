import asyncio
import aiohttp
import aiofiles
import os
import vdf
import json
import zipfile
import threading
from functools import partial
from tkinter import END, Text, Scrollbar, messagebox, filedialog
import customtkinter as ctk
import sys
from typing import Any, Dict, List, Optional, Tuple
from io import BytesIO
import subprocess
import re
from datetime import datetime, timezone

# --- PIL Check ---
try:
    from PIL import Image, ImageTk

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    ImageTk = None
    Image = None

# --- Platform-specific asyncio policy ---
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# --- CustomTkinter Global Settings ---
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# --- Global Localization Manager Placeholder ---
_LOC_MANAGER: Optional["LocalizationManager"] = None


def tr(text: str) -> str:
    """Translation lookup function."""
    if _LOC_MANAGER:
        return _LOC_MANAGER.get_string(text)
    return text


# --- Helper for Tooltips ---
class Tooltip:
    def __init__(self, widget: ctk.CTkBaseClass, text: str):
        self.widget = widget
        self.text = text
        self.tip_window = None
        self.id = None
        self.x = 0
        self.y = 0
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)

    def enter(self, event=None):
        self.schedule()

    def leave(self, event=None):
        self.unschedule()
        self.hide()

    def schedule(self):
        self.unschedule()
        self.id = self.widget.after(500, self.show)

    def unschedule(self):
        id = self.id
        self.id = None
        if id:
            self.widget.after_cancel(id)

    def show(self):
        if self.tip_window or not self.text:
            return
        x, y, cx, cy = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 20
        self.tip_window = ctk.CTkToplevel(self.widget)
        self.tip_window.wm_overrideredirect(True)
        self.tip_window.wm_geometry(f"+{x}+{y}")
        label = ctk.CTkLabel(
            self.tip_window,
            text=self.text,
            fg_color="#333333",
            text_color="white",
            corner_radius=5,
        )
        label.pack(ipadx=1, padx=5, pady=2)

    def hide(self):
        if self.tip_window:
            self.tip_window.destroy()
        self.tip_window = None


# --- Settings Manager ---
class SettingsManager:
    """Manages application settings, including loading from and saving to a config file."""

    def __init__(self, config_file: str = "settings.json"):
        self.config_file = config_file
        self._settings: Dict[str, Any] = {}
        self._load_settings()

    def _load_settings(self) -> None:
        self._settings = {
            "window_geometry": "1320x750",
            "appearance_mode": "dark",
            "color_theme": "blue",
            "download_path": os.path.join(os.getcwd(), "Games"),
            "strict_validation": True,
            "selected_repos": {},
            "app_update_check_on_startup": True,
            "language": "en",
            "github_api_token": "",
            "use_github_api_token": False,
        }
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    loaded_settings = json.load(f)
                    self._settings.update(loaded_settings)
            except (json.JSONDecodeError, IOError):
                pass

        configured_path = self._settings.get("download_path")
        if configured_path and not os.path.exists(configured_path):
            try:
                os.makedirs(configured_path, exist_ok=True)
            except OSError:
                self._settings["download_path"] = os.path.join(os.getcwd(), "Games")
                os.makedirs(self._settings["download_path"], exist_ok=True)

    def save_settings(self) -> None:
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=4)
        except IOError:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._settings[key] = value


# --- Localization Manager ---
class LocalizationManager:
    def __init__(self, app_instance: "ManifestDownloader", lang_dir: str = "lang"):
        self.app = app_instance
        self.lang_dir = lang_dir
        self.translations: Dict[str, Dict[str, str]] = {}
        self.current_language: str = "en"
        self._load_all_translations()

    def _load_all_translations(self) -> None:
        if not os.path.exists(self.lang_dir):
            os.makedirs(self.lang_dir, exist_ok=True)
            self.app.after(
                100,
                partial(
                    self.app.append_progress,
                    tr(
                        "Warning: Language directory '{lang_dir}' not found. Created an empty one. Please add translation files."
                    ).format(lang_dir=self.lang_dir),
                    "yellow",
                ),
            )

        any_translation_loaded = False
        for filename in os.listdir(self.lang_dir):
            if filename.endswith(".json"):
                lang_code = filename[:-5]
                filepath = os.path.join(self.lang_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        self.translations[lang_code] = json.load(f)
                        any_translation_loaded = True
                except (json.JSONDecodeError, IOError) as e:
                    self.app.after(
                        100,
                        partial(
                            self.app.append_progress,
                            tr("Error loading language file {filename}: {e}").format(
                                filename=filename, e=e
                            ),
                            "red",
                        ),
                    )

        if not any_translation_loaded:
            self.app.after(
                100,
                partial(
                    self.app.append_progress,
                    tr(
                        "Warning: No translation files found in '{lang_dir}' directory. Using default English keys."
                    ).format(lang_dir=self.lang_dir),
                    "yellow",
                ),
            )
            if "en" not in self.translations:
                self.translations["en"] = {}

    def get_string(self, key: str) -> str:
        lang_translations = self.translations.get(self.current_language, {})
        return lang_translations.get(key, key)

    def set_language(self, lang_code: str) -> None:
        if lang_code not in self.translations and lang_code != "en":
            self.app.append_progress(
                tr("Language '{lang_code}' not found.").format(lang_code=lang_code),
                "red",
            )
        self.current_language = lang_code
        self.app.settings_manager.set("language", lang_code)

    def get_available_languages(self) -> Dict[str, str]:
        display_names = {
            "en": "English",
            "fr": "Français",
            "cn": "中文",
            "de": "Deutsch",
            "es": "Español",
            "it": "Italiano",
            "jp": "日本語",
            "ko": "한국어",
            "pt": "Português",
            "ru": "Русский",
            "tr": "Türkçe",
            "zh": "简体中文",
            "ar": "العربية",
            "bg": "Български",
            "ca": "Català",
            "cs": "Čeština",
            "da": "Dansk",
            "el": "Ελληνικά",
            "eo": "Esperanto",
            "fa": "فارسی",
            "fi": "Suomi",
            "he": "עברית",
            "in": "हिंदी",
            "hr": "Hrvatski",
            "hu": "Magyar",
            "id": "Bahasa Indonesia",
            "is": "Íslenska",
            "lt": "Lietuvių",
            "lv": "Latviešu",
            "nl": "Nederlands",
            "no": "Norsk",
            "pl": "Polski",
            "pt-br": "Português do Brasil",
            "ro": "Română",
            "sk": "Slovenčina",
            "sl": "Slovenščina",
            "sv": "Svenska",
            "th": "ไทย",
            "uk": "Українська",
            "vi": "Tiếng Việt",
            "zh-cn": "简体中文",
            "zh-tw": "繁體中文",
            "af": "Afrikaans",
        }
        available = {"en": display_names.get("en", "English")}
        for code in sorted(self.translations.keys()):
            available[code] = display_names.get(code, code)
        return available


# --- Main Application Class ---
class ManifestDownloader(ctk.CTk):
    """
    Main application class for Steam Depot Online (SDO).
    Handles UI setup, game searching, manifest downloading, and processing.
    """

    APP_VERSION = "2.0.2"
    GITHUB_RELEASES_API = (
        "https://api.github.com/repos/fairy-root/steam-depot-online/releases/latest"
    )

    def __init__(self) -> None:
        super().__init__()

        self.settings_manager = SettingsManager()
        global _LOC_MANAGER
        self.localization_manager = LocalizationManager(self)
        _LOC_MANAGER = self.localization_manager
        self.localization_manager.set_language(
            self.settings_manager.get("language", "en")
        )

        self.current_progress_tab_name: str = tr("Progress")
        self.current_downloaded_tab_name: str = tr("Downloaded Manifests")

        self.title(tr("Steam Depot Online (SDO)"))
        self.geometry(self.settings_manager.get("window_geometry"))
        self.minsize(1080, 590)
        self.resizable(True, True)

        ctk.set_appearance_mode(self.settings_manager.get("appearance_mode"))
        ctk.set_default_color_theme(self.settings_manager.get("color_theme"))

        if not PIL_AVAILABLE:
            messagebox.showwarning(
                tr("Missing Library"),
                tr(
                    "Pillow (PIL) library is not installed. Images will not be displayed in game details. Please install it using: pip install Pillow"
                ),
            )

        self.repos: Dict[str, str] = self.load_repositories()
        saved_selected_repos = self.settings_manager.get("selected_repos", {})
        self.selected_repos: Dict[str, bool] = {
            repo: saved_selected_repos.get(repo, (repo_type == "Branch"))
            for repo, repo_type in self.repos.items()
        }
        self.repo_vars: Dict[str, ctk.BooleanVar] = {}

        self.appid_to_game: Dict[str, str] = {}
        self.selected_appid: Optional[str] = None
        self.selected_game_name: Optional[str] = None
        self.search_thread: Optional[threading.Thread] = None
        self.cancel_search: bool = False

        self.steam_app_list: List[Dict[str, Any]] = []
        self.app_list_loaded_event = threading.Event()
        self.initial_load_thread: Optional[threading.Thread] = None

        self.image_references: List[ctk.CTkImage] = []
        self._dynamic_content_start_index: str = "1.0"
        self.progress_text: Optional[Text] = None
        self.rate_limit_display_label: Optional[ctk.CTkLabel] = None

        self.setup_ui()
        self._refresh_ui_texts()
        self._start_initial_app_list_load()
        self._bind_shortcuts()

        if self.settings_manager.get("app_update_check_on_startup"):
            threading.Thread(target=self.run_update_check, daemon=True).start()

    def _get_github_headers(self) -> Optional[Dict[str, str]]:
        if self.settings_manager.get("use_github_api_token"):
            token = self.settings_manager.get("github_api_token")
            if token:
                return {
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github.v3+json",
                }
        return None

    def _start_initial_app_list_load(self) -> None:
        self.initial_load_thread = threading.Thread(
            target=self._run_initial_app_list_load, daemon=True
        )
        self.initial_load_thread.start()

    def _run_initial_app_list_load(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._async_load_steam_app_list())
        finally:
            loop.close()

    async def _async_load_steam_app_list(self) -> None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://raw.githubusercontent.com/dgibbs64/SteamCMD-AppID-List/main/steamcmd_appid.json",
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status == 200:
                        data = await response.json(content_type=None)
                        self.steam_app_list = data.get("applist", {}).get("apps", [])
                        self.app_list_loaded_event.set()
                        self.append_progress(
                            tr("Steam app list loaded successfully."), "green"
                        )
                    else:
                        self.append_progress(
                            tr(
                                "Initialization: Failed to load Steam app list (Status: {response_status}). Search by name may not work. You can still search by AppID."
                            ).format(response_status=response.status),
                            "red",
                        )
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            self.append_progress(
                tr(
                    "Initialization: Error fetching Steam app list: {error}. Search by name may not work."
                ).format(error=self.stack_Error(e)),
                "red",
            )
        except json.JSONDecodeError:
            self.append_progress(
                tr(
                    "Initialization: Failed to decode Steam app list response. Search by name may not work."
                ),
                "red",
            )
        except Exception as e:
            self.append_progress(
                tr(
                    "Initialization: Unexpected error loading Steam app list: {error}."
                ).format(error=self.stack_Error(e)),
                "red",
            )

        self.after(0, lambda: self.search_button.configure(state="normal"))
        self.after(0, self._update_dynamic_content_start_index)

    def _update_dynamic_content_start_index(self) -> None:
        if self.progress_text:
            self._dynamic_content_start_index = self.progress_text.index(END)

    def load_repositories(self, filepath: Optional[str] = None) -> Dict[str, str]:
        path = filepath if filepath else "repositories.json"
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    repos = json.load(f)
                    cleaned_repos = {
                        k: v
                        for k, v in repos.items()
                        if isinstance(k, str) and isinstance(v, str)
                    }
                    return cleaned_repos
            except (json.JSONDecodeError, IOError):
                messagebox.showerror(
                    tr("Load Error"),
                    tr("Failed to load repositories.json. Using empty list."),
                )
                return {}
        return {}

    def save_repositories(self, filepath: Optional[str] = None) -> None:
        path = filepath if filepath else "repositories.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.repos, f, indent=4)
        except IOError:
            messagebox.showerror(
                tr("Save Error"), tr("Failed to save repositories.json.")
            )

        saved_selected_repos_state = {
            name: var.get() for name, var in self.repo_vars.items()
        }
        self.settings_manager.set("selected_repos", saved_selected_repos_state)
        self.settings_manager.save_settings()

    def setup_ui(self) -> None:
        main_container = ctk.CTkFrame(self)
        main_container.pack(fill="both", expand=True, padx=18, pady=9)

        left_frame = ctk.CTkFrame(main_container)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 9))

        repo_frame = ctk.CTkFrame(left_frame, corner_radius=9)
        repo_frame.pack(padx=0, pady=9, fill="both", expand=False)

        repos_container = ctk.CTkFrame(repo_frame)
        repos_container.pack(padx=9, pady=4.5, fill="both", expand=True)

        encrypted_frame = ctk.CTkFrame(repos_container)
        encrypted_frame.pack(side="left", fill="both", expand=True, padx=(0, 3))
        encrypted_label_frame = ctk.CTkFrame(encrypted_frame)
        encrypted_label_frame.pack(fill="x")
        self.encrypted_label = ctk.CTkLabel(
            encrypted_label_frame,
            text=tr("Encrypted Repositories:"),
            text_color="cyan",
            font=("Helvetica", 12.6),
        )
        self.encrypted_label.pack(padx=9, pady=(9, 4.5), side="left")
        self.select_all_enc_button = ctk.CTkButton(
            encrypted_label_frame,
            text=tr("Select All"),
            width=72,
            command=lambda: self.toggle_all_repos("encrypted"),
        )
        self.select_all_enc_button.pack(padx=18, pady=(9, 4.5), side="left")
        Tooltip(
            self.select_all_enc_button,
            tr("Toggle selection for all Encrypted repositories."),
        )
        self.encrypted_scroll = ctk.CTkScrollableFrame(
            encrypted_frame, width=240, height=135
        )
        self.encrypted_scroll.pack(padx=9, pady=4.5, fill="both", expand=True)

        decrypted_frame = ctk.CTkFrame(repos_container)
        decrypted_frame.pack(side="left", fill="both", expand=True, padx=(3, 3))
        decrypted_label_frame = ctk.CTkFrame(decrypted_frame)
        decrypted_label_frame.pack(fill="x")
        self.decrypted_label = ctk.CTkLabel(
            decrypted_label_frame,
            text=tr("Decrypted Repositories:"),
            text_color="cyan",
            font=("Helvetica", 12.6),
        )
        self.decrypted_label.pack(padx=9, pady=(9, 4.5), side="left")
        self.select_all_dec_button = ctk.CTkButton(
            decrypted_label_frame,
            text=tr("Select All"),
            width=72,
            command=lambda: self.toggle_all_repos("decrypted"),
        )
        self.select_all_dec_button.pack(padx=18, pady=(9, 4.5), side="left")
        Tooltip(
            self.select_all_dec_button,
            tr("Toggle selection for all Decrypted repositories."),
        )
        self.decrypted_scroll = ctk.CTkScrollableFrame(
            decrypted_frame, width=240, height=135
        )
        self.decrypted_scroll.pack(padx=9, pady=4.5, fill="both", expand=True)

        branch_frame = ctk.CTkFrame(repos_container)
        branch_frame.pack(side="left", fill="both", expand=True, padx=(3, 0))
        branch_label_frame = ctk.CTkFrame(branch_frame)
        branch_label_frame.pack(fill="x")
        self.branch_label = ctk.CTkLabel(
            branch_label_frame,
            text=tr("Branch Repositories:"),
            text_color="cyan",
            font=("Helvetica", 12.6),
        )
        self.branch_label.pack(padx=9, pady=(9, 4.5), side="left")
        self.select_all_branch_button = ctk.CTkButton(
            branch_label_frame,
            text=tr("Select All"),
            width=72,
            command=lambda: self.toggle_all_repos("branch"),
        )
        self.select_all_branch_button.pack(padx=28, pady=(9, 4.5), side="left")
        Tooltip(
            self.select_all_branch_button,
            tr("Toggle selection for all Branch repositories."),
        )
        self.branch_scroll = ctk.CTkScrollableFrame(branch_frame, width=240, height=135)
        self.branch_scroll.pack(padx=9, pady=4.5, fill="both", expand=True)

        self.refresh_repo_checkboxes()

        self.add_repo_button = ctk.CTkButton(
            repo_frame, text=tr("Add Repo"), width=90, command=self.open_add_repo_window
        )
        self.add_repo_button.pack(padx=9, pady=4.5, side="right")
        Tooltip(self.add_repo_button, tr("Add a new GitHub repository to the list."))

        self.delete_repo_button = ctk.CTkButton(
            repo_frame, text=tr("Delete Repo"), width=90, command=self.delete_repo
        )
        self.delete_repo_button.pack(padx=9, pady=4.5, side="right")
        Tooltip(
            self.delete_repo_button, tr("Delete selected repositories from the list.")
        )

        self.settings_button = ctk.CTkButton(
            repo_frame, text=tr("Settings"), width=90, command=self.open_settings_window
        )
        self.settings_button.pack(padx=9, pady=4.5, side="right")
        Tooltip(
            self.settings_button,
            tr("Open application settings, including info, themes, and more."),
        )

        self.output_folder_button = ctk.CTkButton(
            repo_frame,
            text=tr("Output Folder"),
            width=90,
            command=lambda: self.open_path_in_explorer(
                self.settings_manager.get("download_path")
            ),
        )
        self.output_folder_button.pack(padx=9, pady=4.5, side="right")
        Tooltip(
            self.output_folder_button,
            tr("Open the default download output folder where game zips are saved."),
        )

        self.strict_validation_var = ctk.BooleanVar(
            value=self.settings_manager.get("strict_validation")
        )
        self.strict_validation_checkbox = ctk.CTkCheckBox(
            repo_frame,
            text=tr("Strict Validation (Require Key.vdf / Non Branch Repo)"),
            text_color="orange",
            variable=self.strict_validation_var,
            font=("Helvetica", 12.6),
            command=self.save_strict_validation_setting,
        )
        self.strict_validation_checkbox.pack(padx=9, pady=4.5, side="left", anchor="w")
        Tooltip(
            self.strict_validation_checkbox,
            tr(
                "When checked, for non-Branch repos, only downloads manifest files and attempts to extract keys if key.vdf/config.vdf is found. Key files are excluded from final zip. When unchecked, all files are downloaded, and key files are included."
            ),
        )

        input_frame = ctk.CTkFrame(left_frame, corner_radius=9)
        input_frame.pack(padx=0, pady=9, fill="x", expand=False)
        self.game_input_label = ctk.CTkLabel(
            input_frame,
            text=tr("Enter Game Name or AppID:"),
            text_color="cyan",
            font=("Helvetica", 14.4),
        )
        self.game_input_label.pack(padx=9, pady=4.5, anchor="w")
        self.game_input = ctk.CTkEntry(
            input_frame, placeholder_text=tr("e.g. 123456 or Game Name"), width=270
        )
        self.game_input.pack(padx=9, pady=4.5, side="left", expand=True, fill="x")
        Tooltip(
            self.game_input,
            tr(
                "Enter a game name (e.g., 'Portal 2') or AppID (e.g., '620'). For batch download, enter multiple AppIDs separated by commas or newlines."
            ),
        )

        self.paste_button = ctk.CTkButton(
            input_frame, text=tr("Paste"), width=90, command=self.paste_from_clipboard
        )
        self.paste_button.pack(padx=9, pady=4.5, side="left")
        Tooltip(self.paste_button, tr("Paste text from clipboard into the input field."))

        self.search_button = ctk.CTkButton(
            input_frame,
            text=tr("Search"),
            width=90,
            command=self.search_game,
            state="disabled",
        )
        self.search_button.pack(padx=9, pady=4.5, side="left")
        Tooltip(
            self.search_button,
            tr("Search for games matching the entered name or AppID."),
        )

        self.download_button = ctk.CTkButton(
            input_frame,
            text=tr("Download"),
            width=90,
            command=self.download_manifest,
            state="disabled",
        )
        self.download_button.pack(padx=9, pady=4.5, side="left")
        Tooltip(
            self.download_button,
            tr("Download manifests/data for the selected game or all entered AppIDs."),
        )

        download_type_frame = ctk.CTkFrame(left_frame, corner_radius=9)
        download_type_frame.pack(padx=0, pady=(0, 9), fill="x", expand=False)
        self.download_type_label = ctk.CTkLabel(
            download_type_frame,
            text=tr("Select appid(s) to download:"),
            font=("Helvetica", 12.6),
        )
        self.download_type_label.pack(padx=9, pady=4.5, anchor="w")

        self.download_mode_var = ctk.StringVar(value="selected_game")
        self.radio_download_selected = ctk.CTkRadioButton(
            download_type_frame,
            text=tr("Selected game in search results"),
            variable=self.download_mode_var,
            value="selected_game",
        )
        self.radio_download_selected.pack(padx=9, pady=2, anchor="w")
        Tooltip(
            self.radio_download_selected,
            tr("Download only the game selected from the search results (if any)."),
        )

        self.radio_download_all_input = ctk.CTkRadioButton(
            download_type_frame,
            text=tr("All AppIDs in input field"),
            variable=self.download_mode_var,
            value="all_input_appids",
        )
        self.radio_download_all_input.pack(padx=9, pady=2, anchor="w")
        Tooltip(
            self.radio_download_all_input,
            tr(
                "Download all AppIDs found in the 'Enter Game Name or AppID' field, ignoring search results. Useful for batch downloads.\nNote: If multiple AppIDs are entered, all will be downloaded sequentially, skipping individual game details."
            ),
        )

        self.results_frame = ctk.CTkFrame(left_frame, corner_radius=9)
        self.results_frame.pack(padx=0, pady=9, fill="both", expand=True)
        self.results_label = ctk.CTkLabel(
            self.results_frame,
            text=tr("Search Results:"),
            text_color="cyan",
            font=("Helvetica", 14.4),
        )
        self.results_label.pack(padx=9, pady=4.5, anchor="w")
        self.results_var = ctk.StringVar(value=None)
        self.results_radio_buttons: List[ctk.CTkRadioButton] = []
        self.results_container = ctk.CTkScrollableFrame(
            self.results_frame, width=774, height=90
        )
        self.results_container.pack(padx=9, pady=4.5, fill="both", expand=True)

        right_frame = ctk.CTkFrame(main_container)
        right_frame.pack(side="right", fill="both", expand=False, padx=(9, 0))

        self.main_tabview = ctk.CTkTabview(right_frame, width=400)
        self.main_tabview.pack(fill="both", expand=True, padx=0, pady=9)

        self.progress_tab = self.main_tabview.add(self.current_progress_tab_name)
        self.downloaded_tab = self.main_tabview.add(self.current_downloaded_tab_name)

        try:
            self.main_tabview.set(self.current_progress_tab_name)
        except ValueError:
            if self.main_tabview._name_list:
                self.main_tabview.set(self.main_tabview._name_list[0])

        progress_frame = ctk.CTkFrame(self.progress_tab, corner_radius=9)
        progress_frame.pack(padx=0, pady=9, fill="both", expand=True)
        text_container = ctk.CTkFrame(progress_frame, corner_radius=9)
        text_container.pack(padx=9, pady=4.5, fill="both", expand=True)
        self.scrollbar = Scrollbar(text_container)
        self.scrollbar.pack(side="right", fill="y")
        self.progress_text = Text(
            text_container,
            wrap="word",
            height=180,
            state="disabled",
            bg="#2B2B2B",
            fg="white",
            insertbackground="white",
            yscrollcommand=self.scrollbar.set,
            font=("Helvetica", 10),
        )
        self.progress_text.pack(padx=4.5, pady=4.5, fill="both", expand=True)
        self.scrollbar.config(command=self.progress_text.yview)

        for color_name, color_code in {
            "green": "green",
            "red": "red",
            "blue": "deepskyblue",
            "yellow": "yellow",
            "cyan": "cyan",
            "magenta": "magenta",
            "default": "white",
        }.items():
            self.progress_text.tag_configure(color_name, foreground=color_code)

        self.progress_text.tag_configure("game_detail_section")
        self.progress_text.tag_configure(
            "game_title",
            font=("Helvetica", 12, "bold"),
            foreground="cyan",
            spacing3=5,
            justify="center",
        )
        self.progress_text.tag_configure(
            "game_image_line", justify="center", spacing1=5, spacing3=5
        )
        self.progress_text.tag_configure(
            "game_description",
            lmargin1=10,
            lmargin2=10,
            font=("Helvetica", 9),
            spacing3=3,
        )
        self.progress_text.tag_configure(
            "game_genres",
            lmargin1=10,
            lmargin2=10,
            font=("Helvetica", 9, "italic"),
            spacing3=3,
        )
        self.progress_text.tag_configure(
            "game_release_date",
            lmargin1=10,
            lmargin2=10,
            font=("Helvetica", 9),
            spacing3=3,
        )
        self._setup_downloaded_manifests_tab()

    def _setup_downloaded_manifests_tab(self) -> None:
        tab_frame = self.main_tabview.tab(self.current_downloaded_tab_name)
        if not tab_frame:
            self.append_progress(
                f"Error: Could not find downloaded tab frame for '{self.current_downloaded_tab_name}'",
                "red",
            )
            return
        for widget in tab_frame.winfo_children():
            widget.destroy()

        frame = ctk.CTkFrame(tab_frame, corner_radius=9)
        frame.pack(padx=0, pady=9, fill="both", expand=True)

        control_frame = ctk.CTkFrame(frame)
        control_frame.pack(fill="x", padx=9, pady=9)

        self.downloaded_manifests_label = ctk.CTkLabel(
            control_frame, text=tr("Downloaded Manifests"), font=("Helvetica", 14.4)
        )
        self.downloaded_manifests_label.pack(side="left", padx=5, pady=5)
        self.refresh_list_button = ctk.CTkButton(
            control_frame,
            text=tr("Refresh List"),
            command=self.display_downloaded_manifests,
        )
        self.refresh_list_button.pack(side="right", padx=5, pady=5)
        Tooltip(
            self.refresh_list_button,
            tr("Scan the download folder for zipped outcomes and update the list."),
        )

        self.downloaded_manifests_container = ctk.CTkScrollableFrame(
            frame, corner_radius=9
        )
        self.downloaded_manifests_container.pack(
            padx=9, pady=9, fill="both", expand=True
        )
        self.display_downloaded_manifests()

    def display_downloaded_manifests(self) -> None:
        for widget in self.downloaded_manifests_container.winfo_children():
            widget.destroy()

        download_path = self.settings_manager.get("download_path")
        if not os.path.isdir(download_path):
            self.append_progress(
                tr(f"Download path '{download_path}' does not exist."), "red"
            )
            ctk.CTkLabel(
                self.downloaded_manifests_container,
                text=tr("Download folder not found or configured incorrectly."),
                text_color="red",
            ).pack(pady=10)
            return

        self.append_progress(tr("Scanning downloaded manifests..."), "default")
        self.update_idletasks()

        found_zips = []
        try:
            for item in os.listdir(download_path):
                if item.endswith(".zip"):
                    full_path = os.path.join(download_path, item)
                    found_zips.append({"filename": item, "filepath": full_path})
        except Exception as e:
            self.append_progress(
                tr("Error scanning downloaded manifests: {e}").format(
                    e=self.stack_Error(e)
                ),
                "red",
            )
            ctk.CTkLabel(
                self.downloaded_manifests_container,
                text=tr(f"Error scanning folder: {e}"),
                text_color="red",
            ).pack(pady=10)
            return

        if not found_zips:
            ctk.CTkLabel(
                self.downloaded_manifests_container,
                text=tr("No downloaded manifests found."),
                text_color="yellow",
            ).pack(pady=10)
            self.append_progress(tr("No downloaded manifests found."), "yellow")
            return

        found_zips.sort(key=lambda x: x["filename"].lower())

        self.append_progress(
            tr("Found {count} downloaded manifests.").format(count=len(found_zips)),
            "green",
        )

        header_frame = ctk.CTkFrame(
            self.downloaded_manifests_container, fg_color="transparent"
        )
        header_frame.pack(fill="x", padx=5, pady=(5, 0))
        ctk.CTkLabel(
            header_frame,
            text=tr("Game Name"),
            font=("Helvetica", 11, "bold"),
            width=200,
            anchor="w",
        ).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            header_frame,
            text=tr("AppID"),
            font=("Helvetica", 11, "bold"),
            width=80,
            anchor="w",
        ).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            header_frame,
            text=tr("Action"),
            font=("Helvetica", 11, "bold"),
            width=80,
            anchor="w",
        ).pack(side="left")

        for zip_info in found_zips:
            filename = zip_info["filename"]
            filepath = zip_info["filepath"]
            base_name = filename.rsplit(".zip", 1)[0]
            if base_name.endswith(" - encrypted"):
                base_name = base_name.rsplit(" - encrypted", 1)[0]

            parts = base_name.rsplit(" - ", 1)
            game_name_display = parts[0] if len(parts) > 1 else base_name
            appid_display = parts[1] if len(parts) > 1 else "N/A"

            row_frame = ctk.CTkFrame(
                self.downloaded_manifests_container, fg_color="transparent"
            )
            row_frame.pack(fill="x", pady=2, padx=5)

            ctk.CTkLabel(
                row_frame,
                text=game_name_display,
                width=200,
                anchor="w",
                text_color="white",
            ).pack(side="left", padx=(0, 10))
            ctk.CTkLabel(
                row_frame, text=appid_display, width=80, anchor="w", text_color="gray"
            ).pack(side="left", padx=(0, 10))

            open_file_button = ctk.CTkButton(
                row_frame,
                text=tr("ZIP"),
                width=80,
                command=partial(self.open_path_in_explorer, filepath),
                font=("Helvetica", 10),
            )
            open_file_button.pack(side="left")
            Tooltip(open_file_button, tr(f"Open the zip file '{filename}'"))

    def open_path_in_explorer(self, path_to_open: str) -> None:
        if not os.path.exists(path_to_open):
            messagebox.showerror(
                tr("Error"),
                tr("File not found: {filepath}").format(filepath=path_to_open),
            )
            return
        try:
            if sys.platform == "win32":
                os.startfile(path_to_open)
            elif sys.platform == "darwin":
                subprocess.run(["open", path_to_open])
            else:
                subprocess.run(["xdg-open", path_to_open])
        except Exception as e:
            messagebox.showerror(tr("Error"), tr("Could not open path: {e}").format(e=e))
            self.append_progress(
                tr("Error opening path {path_to_open}: {error}").format(
                    path_to_open=path_to_open, error=self.stack_Error(e)
                ),
                "red",
            )

    def _append_progress_direct(
        self,
        message: str,
        color: str = "default",
        tags: Optional[Tuple[str, ...]] = None,
    ) -> None:
        if self.progress_text is None:
            return
        self.progress_text.configure(state="normal")
        final_tags = (color,)
        if tags:
            final_tags += tags
        self.progress_text.insert(END, message + "\n", final_tags)
        self.progress_text.see(END)
        self.progress_text.configure(state="disabled")

    def append_progress(
        self,
        message: str,
        color: str = "default",
        tags: Optional[Tuple[str, ...]] = None,
    ) -> None:
        self.after(0, partial(self._append_progress_direct, message, color, tags))

    def _clear_and_reinitialize_progress_area(self) -> None:
        if self.progress_text:
            self.progress_text.configure(state="normal")
            self.progress_text.delete("1.0", END)
            self.image_references.clear()
            self._dynamic_content_start_index = self.progress_text.index(END)
            self.progress_text.configure(state="disabled")

        for widget in self.results_container.winfo_children():
            widget.destroy()
        self.results_radio_buttons.clear()
        self.results_var.set(None)
        self.selected_appid = None
        self.selected_game_name = None
        self.download_button.configure(state="disabled")

    def _bind_shortcuts(self) -> None:
        self.bind("<Control-v>", lambda e: self.paste_from_clipboard())
        self.bind("<Control-V>", lambda e: self.paste_from_clipboard())
        self.game_input.bind("<Return>", lambda e: self.search_game())

    def paste_from_clipboard(self) -> None:
        try:
            clipboard_text: str = self.clipboard_get()
            self.game_input.delete(0, END)
            self.game_input.insert(0, clipboard_text)
            self.append_progress(tr("Pasted text from clipboard."), "green")
        except Exception as e:
            messagebox.showerror(
                tr("Paste Error"), tr("Failed to paste from clipboard: {e}").format(e=e)
            )

    def save_strict_validation_setting(self) -> None:
        self.settings_manager.set("strict_validation", self.strict_validation_var.get())
        self.settings_manager.save_settings()
        self.append_progress(tr("Strict validation setting saved."), "default")

    def search_game(self) -> None:
        user_input: str = self.game_input.get().strip()
        if not user_input:
            messagebox.showwarning(
                tr("Input Error"), tr("Please enter a game name or AppID.")
            )
            return

        potential_appids = [
            s.strip()
            for s in user_input.replace(",", "\n").splitlines()
            if s.strip().isdigit()
        ]
        if len(potential_appids) > 1:
            self.download_mode_var.set("all_input_appids")
            self.append_progress(
                tr(
                    "Multiple AppIDs detected. Automatically setting download mode to 'All AppIDs in input field'."
                ),
                "yellow",
            )
            self.download_button.configure(state="normal")
            return

        if self.search_thread and self.search_thread.is_alive():
            self.cancel_search = True
            self.append_progress(tr("Cancelling previous search..."), "yellow")

        self._clear_and_reinitialize_progress_area()
        self.cancel_search = False
        self.search_thread = threading.Thread(
            target=self.run_search, args=(user_input,), daemon=True
        )
        self.search_thread.start()

    def run_search(self, user_input: str) -> None:
        search_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(search_loop)
        try:
            search_loop.run_until_complete(self.async_search_game(user_input))
        finally:
            search_loop.close()

    async def async_search_game(self, user_input: str) -> None:
        games_found: List[Dict[str, Any]] = []
        max_results = 200

        if user_input.isdigit():
            appid_to_search = user_input
            url = f"https://store.steampowered.com/api/appdetails?appids={appid_to_search}&l=english"
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url, timeout=aiohttp.ClientTimeout(total=15)
                    ) as response:
                        if response.status == 200:
                            response_data = await response.json()
                            if response_data and response_data.get(
                                appid_to_search, {}
                            ).get("success"):
                                game_data = response_data[appid_to_search]["data"]
                                game_name = game_data.get(
                                    "name", f"AppID {appid_to_search}"
                                )
                                games_found.append(
                                    {"appid": appid_to_search, "name": game_name}
                                )
                            else:
                                self.append_progress(
                                    tr(
                                        "No game found or API error for AppID {appid_to_search}."
                                    ).format(appid_to_search=appid_to_search),
                                    "red",
                                )
                        else:
                            self.append_progress(
                                tr(
                                    "Failed to fetch details for AppID {appid_to_search} (Status: {response_status})."
                                ).format(
                                    appid_to_search=appid_to_search,
                                    response_status=response.status,
                                ),
                                "red",
                            )
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                self.append_progress(
                    tr("Error fetching AppID {appid_to_search}: {error}").format(
                        appid_to_search=appid_to_search, error=self.stack_Error(e)
                    ),
                    "red",
                )
            except json.JSONDecodeError:
                self.append_progress(
                    tr("Failed to decode JSON for AppID {appid_to_search}.").format(
                        appid_to_search=appid_to_search
                    ),
                    "red",
                )
        else:
            if not self.app_list_loaded_event.is_set():
                self.append_progress(
                    tr("Steam app list is not yet loaded. Please wait or try AppID."),
                    "yellow",
                )
                return

            search_term_lower = user_input.lower()
            for app_info in self.steam_app_list:
                if self.cancel_search:
                    self.append_progress(tr("\nName search cancelled."), "yellow")
                    return
                if search_term_lower in app_info.get("name", "").lower():
                    games_found.append(
                        {"appid": str(app_info["appid"]), "name": app_info["name"]}
                    )
                    if len(games_found) >= max_results:
                        self.append_progress(
                            tr(
                                "Max results ({max_results}) reached. Please refine your search."
                            ).format(max_results=max_results),
                            "yellow",
                        )
                        break

        if self.cancel_search:
            self.append_progress(tr("\nSearch cancelled by user action."), "yellow")
            return
        if not games_found:
            self.append_progress(
                tr("\nNo matching games found. Please try another name or AppID."), "red"
            )
            return

        self.appid_to_game.clear()
        capsule_tasks = []
        game_data_for_ui = []

        for idx, game in enumerate(games_found, 1):
            if self.cancel_search:
                self.append_progress(tr("\nSearch display cancelled."), "yellow")
                return
            appid, game_name = str(game.get("appid", "Unknown")), game.get(
                "name", tr("Unknown Game")
            )
            self.appid_to_game[appid] = game_name
            capsule_url = f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/capsule_231x87.jpg"
            if PIL_AVAILABLE:
                capsule_tasks.append(self._download_image_async(capsule_url))
            else:
                capsule_tasks.append(asyncio.sleep(0, result=None))
            game_data_for_ui.append((idx, appid, game_name))

        capsule_results = await asyncio.gather(*capsule_tasks, return_exceptions=True)

        for i, (idx, appid, game_name) in enumerate(game_data_for_ui):
            if self.cancel_search:
                break
            image_data_result = capsule_results[i]
            image_data = (
                image_data_result
                if not isinstance(image_data_result, Exception)
                else None
            )
            if isinstance(image_data_result, Exception):
                self.append_progress(
                    f"Error loading capsule for {game_name}: {image_data_result}", "red"
                )
            self.after(
                0, partial(self.create_radio_button, idx, appid, game_name, image_data)
            )

        self.append_progress(
            tr(
                "\nFound {len_games_found} game(s). Select one from the list above."
            ).format(len_games_found=len(games_found)),
            "cyan",
        )

    def create_radio_button(
        self, idx: int, appid: str, game_name: str, capsule_image_data: Optional[bytes]
    ) -> None:
        display_text: str = f"{game_name} (AppID: {appid})"
        rb_frame = ctk.CTkFrame(self.results_container, fg_color="transparent")
        rb_frame.pack(anchor="w", padx=10, pady=2, fill="x")

        image_width, image_height = 80, 30
        if PIL_AVAILABLE and capsule_image_data:
            try:
                pil_image = Image.open(BytesIO(capsule_image_data))
                pil_image = pil_image.resize(
                    (image_width, image_height), Image.Resampling.LANCZOS
                )
                capsule_ctk_image = ctk.CTkImage(
                    light_image=pil_image,
                    dark_image=pil_image,
                    size=(image_width, image_height),
                )
                self.image_references.append(capsule_ctk_image)
                image_label = ctk.CTkLabel(rb_frame, text="", image=capsule_ctk_image)
                image_label.pack(side="left", padx=(0, 5))
            except Exception as e:
                self.append_progress(
                    tr("Error creating capsule image for {appid}: {error}").format(
                        appid=appid, error=self.stack_Error(e)
                    ),
                    "red",
                )
                no_image_label = ctk.CTkLabel(
                    rb_frame,
                    text="[X]",
                    width=image_width,
                    height=image_height,
                    text_color="gray",
                    font=("Helvetica", 8),
                )
                no_image_label.pack(side="left", padx=(0, 5))
        elif PIL_AVAILABLE:
            no_image_label = ctk.CTkLabel(
                rb_frame,
                text="[No Image]",
                width=image_width,
                height=image_height,
                text_color="gray",
                font=("Helvetica", 8),
            )
            no_image_label.pack(side="left", padx=(0, 5))

        rb = ctk.CTkRadioButton(
            rb_frame,
            text=display_text,
            variable=self.results_var,
            value=appid,
            command=self.enable_download,
        )
        rb.pack(side="left", anchor="w", expand=True)
        self.results_radio_buttons.append(rb)

    def enable_download(self) -> None:
        selected_appid_val: Optional[str] = self.results_var.get()
        if selected_appid_val and selected_appid_val in self.appid_to_game:
            self.selected_appid = selected_appid_val
            self.selected_game_name = self.appid_to_game[selected_appid_val]

            if self.progress_text:
                self.progress_text.configure(state="normal")
                self.progress_text.delete("1.0", END)
                self.image_references.clear()
                self.progress_text.configure(state="disabled")

            self.download_button.configure(state="normal")
            self.download_mode_var.set("selected_game")
            threading.Thread(
                target=self.run_display_game_details,
                args=(self.selected_appid, self.selected_game_name),
                daemon=True,
            ).start()
        else:
            self.append_progress(
                tr("Selected game not found in mapping. This is unexpected."), "red"
            )
            self.download_button.configure(state="disabled")

    def run_display_game_details(self, appid: str, game_name: str) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.async_display_game_details(appid, game_name))
        finally:
            loop.close()

    async def _download_image_async(self, url: str) -> Optional[bytes]:
        if not PIL_AVAILABLE:
            return None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        return await response.read()
                    elif response.status == 404:
                        return None
                    else:
                        self.append_progress(
                            tr(
                                "Failed to download image (Status {response_status}): {url}"
                            ).format(response_status=response.status, url=url),
                            "yellow",
                            ("game_detail_section",),
                        )
                        return None
        except Exception as e:
            self.append_progress(
                tr("Error downloading image {url}: {error}").format(
                    url=url, error=self.stack_Error(e)
                ),
                "red",
                ("game_detail_section",),
            )
            return None

    def _process_and_insert_image_ui(
        self, image_bytes: Optional[bytes], max_width: int, max_height: int
    ) -> None:
        if not image_bytes or not PIL_AVAILABLE or not ImageTk or not Image:
            return
        if self.progress_text is None:
            return

        try:
            pil_image = Image.open(BytesIO(image_bytes))
            width, height = pil_image.size
            if width > max_width or height > max_height:
                ratio = min(max_width / width, max_height / height)
                new_width = int(width * ratio)
                new_height = int(height * ratio)
                pil_image = pil_image.resize(
                    (new_width, new_height), Image.Resampling.LANCZOS
                )

            ctk_image = ctk.CTkImage(
                light_image=pil_image,
                dark_image=pil_image,
                size=(pil_image.width, pil_image.height),
            )
            self.image_references.append(ctk_image)

            self.progress_text.configure(state="normal")
            self.progress_text.insert(
                END, "\n", ("game_detail_section", "game_image_line")
            )
            self.progress_text.window_create(
                END,
                window=ctk.CTkLabel(
                    self.progress_text, text="", image=ctk_image, compound="center"
                ),
            )
            self.progress_text.insert(
                END, "\n", ("game_detail_section", "game_image_line")
            )
            self.progress_text.configure(state="disabled")
            self.progress_text.see(END)
        except Exception as e:
            self._append_progress_direct(
                tr("Error processing image for UI: {error}").format(
                    error=self.stack_Error(e)
                ),
                "red",
                ("game_detail_section",),
            )

    async def async_display_game_details(self, appid: str, game_name: str) -> None:
        logo_url = f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/logo.png"
        header_url = f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg"
        appdetails_url = (
            f"https://store.steampowered.com/api/appdetails?appids={appid}&l=english"
        )
        logo_data: Optional[bytes] = None
        header_data: Optional[bytes] = None
        game_api_data: Optional[Dict[str, Any]] = None

        async with aiohttp.ClientSession() as session:
            tasks = []
            if PIL_AVAILABLE:
                tasks.append(asyncio.create_task(self._download_image_async(logo_url)))
                tasks.append(
                    asyncio.create_task(self._download_image_async(header_url))
                )
            tasks.append(
                asyncio.create_task(
                    session.get(appdetails_url, timeout=aiohttp.ClientTimeout(total=20))
                )
            )
            results = await asyncio.gather(*tasks, return_exceptions=True)

            result_idx = 0
            if PIL_AVAILABLE:
                logo_result = results[result_idx]
                result_idx += 1
                if not isinstance(logo_result, Exception):
                    logo_data = logo_result
                header_result = results[result_idx]
                result_idx += 1
                if not isinstance(header_result, Exception):
                    header_data = header_result

            appdetails_response_or_exc = results[result_idx]
            if not isinstance(appdetails_response_or_exc, Exception):
                appdetails_response = appdetails_response_or_exc
                if appdetails_response.status == 200:
                    try:
                        api_json = await appdetails_response.json()
                        if api_json and api_json.get(appid, {}).get("success"):
                            game_api_data = api_json[appid]["data"]
                        else:
                            self.append_progress(
                                tr(
                                    "Could not retrieve valid data for AppID {appid} from Steam API."
                                ).format(appid=appid),
                                "yellow",
                                ("game_detail_section",),
                            )
                    except json.JSONDecodeError:
                        self.append_progress(
                            tr(
                                "Failed to decode JSON for AppID {appid} details."
                            ).format(appid=appid),
                            "red",
                            ("game_detail_section",),
                        )
                else:
                    self.append_progress(
                        tr(
                            "Failed to fetch AppID {appid} details (Status: {status})."
                        ).format(appid=appid, status=appdetails_response.status),
                        "red",
                        ("game_detail_section",),
                    )
            elif isinstance(appdetails_response_or_exc, Exception):
                self.append_progress(
                    tr("Error fetching AppID {appid} details: {error}").format(
                        appid=appid, error=self.stack_Error(appdetails_response_or_exc)
                    ),
                    "red",
                    ("game_detail_section",),
                )

        self.append_progress(f"{game_name}", "game_title", ("game_detail_section",))

        if PIL_AVAILABLE:
            header_max_width = (
                self.progress_text.winfo_width() - 20 if self.progress_text else 350
            )
            if header_max_width <= 50:
                header_max_width = 350
            if logo_data:
                self.after(
                    0, partial(self._process_and_insert_image_ui, logo_data, 330, 200)
                )
            if header_data:
                self.after(
                    0,
                    partial(
                        self._process_and_insert_image_ui,
                        header_data,
                        header_max_width,
                        250,
                    ),
                )

        description_parts = []
        if game_api_data:
            if short_desc := game_api_data.get("short_description"):
                description_parts.append(f"{short_desc}")
            if genres_list := game_api_data.get("genres", []):
                description_parts.append(
                    tr("Genres: ") + ", ".join([g["description"] for g in genres_list])
                )
            if release_date_info := game_api_data.get("release_date", {}):
                if release_date_info.get("date"):
                    description_parts.append(
                        tr("Release Date: ") + f"{release_date_info['date']}"
                    )

        if description_parts:
            self.after(
                100,
                lambda d_parts=description_parts: self.append_progress(
                    "\n" + "\n\n".join(d_parts),
                    "game_description",
                    ("game_detail_section",),
                ),
            )
        elif not game_api_data and not description_parts:
            self.after(
                100,
                lambda: self.append_progress(
                    tr("No detailed text information found for this game."),
                    "yellow",
                    ("game_detail_section",),
                ),
            )

    def download_manifest(self) -> None:
        selected_repo_list: List[str] = [
            repo for repo, var in self.repo_vars.items() if var.get()
        ]
        if not selected_repo_list:
            messagebox.showwarning(
                tr("Repository Selection"), tr("Please select at least one repository.")
            )
            return

        appids_to_download: List[Tuple[str, str]] = []
        if self.download_mode_var.get() == "selected_game":
            if not self.selected_appid or not self.selected_game_name:
                messagebox.showwarning(
                    tr("Selection Error"),
                    tr("Please select a game first from search results."),
                )
                return
            appids_to_download.append((self.selected_appid, self.selected_game_name))
        else:
            user_input = self.game_input.get().strip()
            unique_appids_str, seen_appids = [], set()
            for s in user_input.replace(",", "\n").splitlines():
                stripped_s = s.strip()
                if stripped_s.isdigit() and stripped_s not in seen_appids:
                    unique_appids_str.append(stripped_s)
                    seen_appids.add(stripped_s)
            if not unique_appids_str:
                messagebox.showwarning(
                    tr("Input Error"),
                    tr(
                        "Please enter valid AppIDs in the input field for batch download mode."
                    ),
                )
                return
            for appid_str in unique_appids_str:
                game_name = self.appid_to_game.get(appid_str)
                if not game_name and self.app_list_loaded_event.is_set():
                    if found_app_info := next(
                        (
                            app
                            for app in self.steam_app_list
                            if str(app.get("appid")) == appid_str
                        ),
                        None,
                    ):
                        game_name = found_app_info.get("name")
                appids_to_download.append(
                    (appid_str, game_name if game_name else f"AppID_{appid_str}")
                )

        if not appids_to_download:
            messagebox.showerror(
                tr("Error"), tr("No AppIDs selected or found for download.")
            )
            return

        self.download_button.configure(state="disabled")
        self._clear_and_reinitialize_progress_area()
        self.cancel_search = False
        threading.Thread(
            target=self.run_batch_download,
            args=(appids_to_download, selected_repo_list),
            daemon=True,
        ).start()

    def run_batch_download(
        self, appids_to_download: List[Tuple[str, str]], selected_repos: List[str]
    ) -> None:
        download_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(download_loop)
        try:
            total_appids = len(appids_to_download)
            for i, (appid, game_name) in enumerate(appids_to_download):
                if self.cancel_search:
                    self.append_progress(
                        tr("Batch download process cancelled by user."), "yellow"
                    )
                    break
                self.append_progress(
                    tr(
                        "\n--- Downloading AppID: {current_appid} ({game_name}) - {index}/{total_appids} ---"
                    ).format(
                        current_appid=appid,
                        game_name=game_name,
                        index=i + 1,
                        total_appids=total_appids,
                    ),
                    "blue",
                )
                collected_depots, output_path_or_processing_dir, source_was_branch = (
                    download_loop.run_until_complete(
                        self._perform_download_operations(
                            appid, game_name, selected_repos
                        )
                    )
                )
                if self.cancel_search:
                    self.append_progress(
                        tr(
                            "\nDownload cancelled during processing of AppID {appid}."
                        ).format(appid=appid),
                        "yellow",
                    )
                    break
                if not source_was_branch:
                    if output_path_or_processing_dir and os.path.isdir(
                        output_path_or_processing_dir
                    ):
                        processing_dir = output_path_or_processing_dir
                        lua_script: str = self.parse_vdf_to_lua(
                            collected_depots, appid, processing_dir
                        )
                        lua_file_path: str = os.path.join(
                            processing_dir, f"{appid}.lua"
                        )
                        try:
                            download_loop.run_until_complete(
                                self._write_lua_file(lua_file_path, lua_script)
                            )
                            self.append_progress(
                                tr(
                                    "\nGenerated LUA unlock script: {lua_file_path}"
                                ).format(lua_file_path=lua_file_path),
                                "blue",
                            )
                        except Exception as e:
                            self.append_progress(
                                tr(
                                    "\nFailed to write LUA script {lua_file_path}: {error}"
                                ).format(
                                    lua_file_path=lua_file_path,
                                    error=self.stack_Error(e),
                                ),
                                "red",
                            )

                        final_zip_path = self.zip_outcome(
                            processing_dir, selected_repos
                        )
                        if not collected_depots and self.strict_validation_var.get():
                            self.append_progress(
                                tr(
                                    "\nWarning: Strict validation was ON, but no decryption keys were found/extracted. LUA script will be minimal and game may not work."
                                ),
                                "yellow",
                            )
                        elif (
                            not collected_depots
                            and not self.strict_validation_var.get()
                        ):
                            self.append_progress(
                                tr(
                                    "\nNotice: No decryption keys found/extracted (strict validation was OFF). All downloaded files (if any) are included. Game may not work without keys."
                                ),
                                "yellow",
                            )
                        elif final_zip_path:
                            self.append_progress(
                                tr(
                                    "\nSuccessfully processed and zipped non-Branch repo for AppID {appid} to {final_zip_path}"
                                ).format(appid=appid, final_zip_path=final_zip_path),
                                "green",
                            )
                    else:
                        if not self.cancel_search:
                            self.append_progress(
                                tr(
                                    "\nDownload/processing failed for AppID {appid} (non-Branch). No files to package."
                                ).format(appid=appid),
                                "red",
                            )
                            if output_path_or_processing_dir:
                                self.append_progress(
                                    tr(
                                        "  Problematic path was: {output_path_or_processing_dir}"
                                    ).format(
                                        output_path_or_processing_dir=output_path_or_processing_dir
                                    ),
                                    "red",
                                )
                elif source_was_branch:
                    if output_path_or_processing_dir and os.path.isfile(
                        output_path_or_processing_dir
                    ):
                        self.append_progress(
                            f"\nBranch repository download successful for AppID {appid}.",
                            "green",
                        )
                        self.append_progress(
                            f"  Output saved directly to: {output_path_or_processing_dir}",
                            "blue",
                        )
                    else:
                        self.append_progress(
                            tr(
                                "\nBranch repository download for AppID {appid} seems complete, but the expected zip file was not found or path was invalid."
                            ).format(appid=appid),
                            "red",
                        )
                self.append_progress("---", "default")
            self.append_progress(tr("\nBatch download process finished."), "green")
            self.after(0, self.display_downloaded_manifests)
        finally:
            download_loop.close()
            self.after(0, lambda: self.download_button.configure(state="normal"))

    async def _write_lua_file(self, path: str, content: str) -> None:
        async with aiofiles.open(path, "w", encoding="utf-8") as lua_file:
            await lua_file.write(content)

    def print_colored_ui(self, text: str, color: str) -> None:
        self.append_progress(text, color)

    def stack_Error(self, e: Exception) -> str:
        return f"{type(e).__name__}: {e}"

    async def get(self, sha: str, path: str, repo: str) -> Optional[bytes]:
        url_list: List[str] = [
            f"https://gcore.jsdelivr.net/gh/{repo}@{sha}/{path}",
            f"https://fastly.jsdelivr.net/gh/{repo}@{sha}/{path}",
            f"https://cdn.jsdelivr.net/gh/{repo}@{sha}/{path}",
            f"https://ghproxy.org/https://raw.githubusercontent.com/{repo}/{sha}/{path}",
            f"https://raw.dgithub.xyz/{repo}/{sha}/{path}",
            f"https://raw.githubusercontent.com/{repo}/{sha}/{path}",
        ]
        max_retries_per_url, overall_attempts = 1, 2
        github_auth_headers = self._get_github_headers()

        async with aiohttp.ClientSession() as session:
            for attempt in range(overall_attempts):
                if self.cancel_search:
                    break
                for url in url_list:
                    if self.cancel_search:
                        self.print_colored_ui(
                            tr(
                                "\nDownload cancelled by user for: {path} from {url_short}"
                            ).format(path=path, url_short=url.split("/")[2]),
                            "yellow",
                        )
                        return None

                    current_request_headers = {}
                    if "raw.githubusercontent.com" in url and github_auth_headers:
                        current_request_headers = github_auth_headers.copy()
                        if (
                            "Accept" in current_request_headers
                            and "json" in current_request_headers["Accept"]
                        ):
                            del current_request_headers["Accept"]

                    for retry_num in range(max_retries_per_url + 1):
                        if self.cancel_search:
                            return None
                        try:
                            self.print_colored_ui(
                                f"... Trying {url.split('/')[2]} for {os.path.basename(path)} (Attempt {retry_num+1})",
                                "default",
                            )
                            async with session.get(
                                url,
                                headers=current_request_headers,
                                ssl=False,
                                timeout=aiohttp.ClientTimeout(total=20),
                            ) as r:
                                if r.status == 200:
                                    self.print_colored_ui(
                                        f"OK from {url.split('/')[2]}", "green"
                                    )
                                    return await r.read()
                                if r.status == 404:
                                    self.print_colored_ui(
                                        f"404 from {url.split('/')[2]}", "yellow"
                                    )
                                    break
                                self.print_colored_ui(
                                    f"Status {r.status} from {url.split('/')[2]}",
                                    "yellow",
                                )
                        except (aiohttp.ClientError, asyncio.TimeoutError) as e_req:
                            self.print_colored_ui(
                                f"Error with {url.split('/')[2]}: {self.stack_Error(e_req)}",
                                "yellow",
                            )
                        except KeyboardInterrupt:
                            self.print_colored_ui(
                                tr("\nDownload interrupted by user for: {path}").format(
                                    path=path
                                ),
                                "yellow",
                            )
                            self.cancel_search = True
                            return None
                        if self.cancel_search:
                            return None
                        if retry_num < max_retries_per_url:
                            await asyncio.sleep(0.5)

                if self.cancel_search:
                    return None
                if attempt < overall_attempts - 1:
                    self.print_colored_ui(
                        tr(
                            "\nRetrying download cycle for: {path} (Cycle {attempt_plus_2}/{overall_attempts})"
                        ).format(
                            path=path,
                            attempt_plus_2=attempt + 2,
                            overall_attempts=overall_attempts,
                        ),
                        "yellow",
                    )
                    await asyncio.sleep(1)
        if not self.cancel_search:
            self.print_colored_ui(
                tr(
                    "\nMaximum attempts exceeded for: {path}. File could not be downloaded."
                ).format(path=path),
                "red",
            )
        return None

    async def get_manifest(
        self, sha: str, path: str, processing_dir: str, repo: str
    ) -> List[Tuple[str, str]]:
        collected_depots: List[Tuple[str, str]] = []
        try:
            file_save_path = os.path.join(processing_dir, path)
            parent_dir = os.path.dirname(file_save_path)
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)
            content_bytes: Optional[bytes] = None
            should_download = True

            if os.path.exists(file_save_path):
                if path.lower().endswith(".manifest"):
                    should_download = False
                    self.print_colored_ui(
                        tr(
                            "Manifest file {path} already exists. Using local version."
                        ).format(path=path),
                        "default",
                    )
                elif path.lower().endswith((".vdf")):
                    try:
                        async with aiofiles.open(
                            file_save_path, "rb"
                        ) as f_existing_bytes:
                            content_bytes = await f_existing_bytes.read()
                        should_download = False
                        self.print_colored_ui(
                            tr(
                                "Key/Config VDF file {path} already exists. Using local version for key extraction."
                            ).format(path=path),
                            "default",
                        )
                    except Exception as e_read:
                        self.print_colored_ui(
                            tr(
                                "Could not read existing local file {path}: {error}. Attempting fresh download."
                            ).format(path=path, error=self.stack_Error(e_read)),
                            "yellow",
                        )
                        content_bytes = None
                        should_download = True

            if should_download and not self.cancel_search:
                self.print_colored_ui(
                    tr(
                        "Downloading: {path} from repo {repo} (commit: {sha_short})"
                    ).format(path=path, repo=repo, sha_short=sha[:7]),
                    "default",
                )
                content_bytes = await self.get(sha, path, repo)

            if self.cancel_search:
                return collected_depots
            if content_bytes:
                if should_download:
                    async with aiofiles.open(file_save_path, "wb") as f_new:
                        await f_new.write(content_bytes)
                    self.print_colored_ui(
                        tr("\nFile downloaded and saved: {path}").format(path=path),
                        "green",
                    )
                if path.lower().endswith((".vdf")):
                    try:
                        vdf_content_str = content_bytes.decode(
                            encoding="utf-8", errors="ignore"
                        )
                        depots_config = vdf.loads(vdf_content_str)
                        depots_data = depots_config.get("depots", {})
                        if not isinstance(depots_data, dict):
                            depots_data = {}
                        new_keys_count = 0
                        for depot_id_str, depot_info in depots_data.items():
                            if (
                                isinstance(depot_info, dict)
                                and "DecryptionKey" in depot_info
                            ):
                                key_tuple = (
                                    str(depot_id_str),
                                    depot_info["DecryptionKey"],
                                )
                                if key_tuple not in collected_depots:
                                    collected_depots.append(key_tuple)
                                    new_keys_count += 1
                        if new_keys_count > 0:
                            self.print_colored_ui(
                                tr(
                                    "Extracted {new_keys_count} new decryption keys from {path}"
                                ).format(new_keys_count=new_keys_count, path=path),
                                "magenta",
                            )
                        elif not depots_data and os.path.basename(path.lower()) in [
                            "key.vdf",
                            "config.vdf",
                        ]:
                            self.print_colored_ui(
                                tr(
                                    "Warning: No 'depots' section or section is empty in {path}."
                                ).format(path=path),
                                "yellow",
                            )
                    except Exception as e_vdf:
                        self.print_colored_ui(
                            tr(
                                "\nFailed to parse VDF content for {path}: {error}. This file may be malformed or not a standard VDF."
                            ).format(path=path, error=self.stack_Error(e_vdf)),
                            "red",
                        )
            elif should_download and not os.path.exists(file_save_path):
                self.print_colored_ui(
                    tr("\nFailed to download or find local file: {path}").format(
                        path=path
                    ),
                    "red",
                )
        except KeyboardInterrupt:
            self.print_colored_ui(
                tr("\nFile processing interrupted by user for: {path}").format(
                    path=path
                ),
                "yellow",
            )
            self.cancel_search = True
        except Exception as e:
            self.print_colored_ui(
                tr("\nAn error occurred while processing file {path}: {error}").format(
                    path=path, error=self.stack_Error(e)
                ),
                "red",
            )
        return collected_depots

    async def _fetch_branch_zip_content(
        self, repo_full_name: str, app_id: str
    ) -> Optional[bytes]:
        api_url = f"https://api.github.com/repos/{repo_full_name}/zipball/{app_id}"
        github_auth_headers = self._get_github_headers()
        request_headers = {}
        if github_auth_headers:
            request_headers.update(github_auth_headers)
        self.print_colored_ui(
            tr("Attempting to download branch zip (API): {url}").format(url=api_url)
            + (" " + tr("(with token)") if github_auth_headers else tr("(no token)")),
            "default",
        )
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    api_url,
                    headers=request_headers,
                    timeout=aiohttp.ClientTimeout(total=600),
                ) as r:
                    if r.status == 200:
                        self.print_colored_ui(
                            tr(
                                "Successfully started downloading branch zip for AppID {app_id} from {repo_full_name}."
                            ).format(app_id=app_id, repo_full_name=repo_full_name),
                            "green",
                        )
                        content = await r.read()
                        self.print_colored_ui(
                            tr(
                                "Finished downloading branch zip content for AppID {app_id} (Size: {size_kb:.2f} KB)."
                            ).format(app_id=app_id, size_kb=len(content) / 1024),
                            "green",
                        )
                        return content
                    else:
                        error_message = tr(
                            "Failed to download branch zip (Status: {status}) from {url}"
                        ).format(status=r.status, url=api_url)
                        if r.status == 401 and github_auth_headers:
                            error_message += " - " + tr(
                                "Unauthorized. Check token permissions or if token is valid."
                            )
                        elif r.status == 404:
                            error_message += " - " + tr(
                                "Not Found. Ensure repository '{repo_full_name}' and branch '{app_id}' exist."
                            ).format(repo_full_name=repo_full_name, app_id=app_id)
                        self.print_colored_ui(error_message, "red")
                        if r.status != 404:
                            try:
                                self.print_colored_ui(
                                    f"  Response: {(await r.text())[:200]}...", "red"
                                )
                            except:
                                pass
                        return None
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                self.print_colored_ui(
                    tr(
                        "Network or Timeout error downloading branch zip from {url}: {error}"
                    ).format(url=api_url, error=self.stack_Error(e)),
                    "red",
                )
                return None
            except Exception as e:
                self.print_colored_ui(
                    tr("Unexpected error fetching branch zip {url}: {error}").format(
                        url=api_url, error=self.stack_Error(e)
                    ),
                    "red",
                )
                return None

    async def _perform_download_operations(
        self, app_id_input: str, game_name: str, selected_repos: List[str]
    ) -> Tuple[List[Tuple[str, str]], Optional[str], bool]:
        app_id_match = re.match(r"^\d+", app_id_input)
        if not app_id_match:
            self.print_colored_ui(
                tr(
                    "\nInvalid AppID format for download: {app_id_input}. Expected numeric AppID."
                ).format(app_id_input=app_id_input),
                "red",
            )
            return [], None, False
        app_id = app_id_match.group(0)
        sanitized_game_name = (
            "".join(c if c.isalnum() or c in " -_" else "" for c in game_name).strip()
            or f"AppID_{app_id}"
        )
        output_base_dir = self.settings_manager.get("download_path")
        final_output_name_stem = f"{sanitized_game_name} - {app_id}"
        try:
            os.makedirs(output_base_dir, exist_ok=True)
        except OSError as e:
            self.print_colored_ui(
                tr(
                    "Error creating base output directory {output_base_dir}: {error}"
                ).format(output_base_dir=output_base_dir, error=self.stack_Error(e)),
                "red",
            )
            return [], None, False

        overall_collected_depots: List[Tuple[str, str]] = []
        github_auth_headers = self._get_github_headers()

        for repo_full_name in selected_repos:
            if self.cancel_search:
                self.print_colored_ui(
                    tr(
                        "\nDownload process cancelled by user before processing repo: {repo_full_name}."
                    ).format(repo_full_name=repo_full_name),
                    "yellow",
                )
                return overall_collected_depots, None, False
            repo_type = self.repos.get(repo_full_name)
            if not repo_type:
                self.print_colored_ui(
                    tr(
                        "Repository {repo_full_name} type not found in local list. Skipping."
                    ).format(repo_full_name=repo_full_name),
                    "yellow",
                )
                continue

            if repo_type == "Branch":
                self.print_colored_ui(
                    tr(
                        "\nProcessing BRANCH repository: {repo_full_name} for AppID: {app_id}"
                    ).format(repo_full_name=repo_full_name, app_id=app_id),
                    "cyan",
                )
                final_branch_zip_path = os.path.join(
                    output_base_dir, f"{final_output_name_stem}.zip"
                )
                if os.path.exists(final_branch_zip_path):
                    self.print_colored_ui(
                        tr(
                            "Branch ZIP already exists: {final_branch_zip_path}. Skipping download for this repo."
                        ).format(final_branch_zip_path=final_branch_zip_path),
                        "blue",
                    )
                    return [], final_branch_zip_path, True
                zip_content = await self._fetch_branch_zip_content(
                    repo_full_name, app_id
                )
                if self.cancel_search:
                    self.print_colored_ui(
                        tr(
                            "\nDownload cancelled during branch zip fetch from {repo_full_name}."
                        ).format(repo_full_name=repo_full_name),
                        "yellow",
                    )
                    return [], None, False
                if zip_content:
                    try:
                        async with aiofiles.open(final_branch_zip_path, "wb") as f_zip:
                            await f_zip.write(zip_content)
                        self.print_colored_ui(
                            tr(
                                "Successfully saved branch download from {repo_full_name} to {final_branch_zip_path}"
                            ).format(
                                repo_full_name=repo_full_name,
                                final_branch_zip_path=final_branch_zip_path,
                            ),
                            "green",
                        )
                        return [], final_branch_zip_path, True
                    except Exception as e_save:
                        self.print_colored_ui(
                            tr(
                                "Failed to save downloaded branch zip to {final_branch_zip_path}: {error}"
                            ).format(
                                final_branch_zip_path=final_branch_zip_path,
                                error=self.stack_Error(e_save),
                            ),
                            "red",
                        )
                else:
                    self.print_colored_ui(
                        tr(
                            "Failed to download content for branch repo {repo_full_name}, AppID {app_id}. Trying next selected repo."
                        ).format(repo_full_name=repo_full_name, app_id=app_id),
                        "yellow",
                    )
                continue

            processing_dir_non_branch = os.path.join(
                output_base_dir, f"_{final_output_name_stem}_temp"
            )
            try:
                os.makedirs(processing_dir_non_branch, exist_ok=True)
            except OSError as e_mkdir:
                self.print_colored_ui(
                    tr(
                        "Error creating temporary processing directory {processing_dir_non_branch}: {error}. Skipping repo {repo_full_name}."
                    ).format(
                        processing_dir_non_branch=processing_dir_non_branch,
                        error=self.stack_Error(e_mkdir),
                        repo_full_name=repo_full_name,
                    ),
                    "red",
                )
                continue

            self.print_colored_ui(
                tr(
                    "\nSearching NON-BRANCH repository: {repo_full_name} for AppID: {app_id} (Type: {repo_type})"
                ).format(
                    repo_full_name=repo_full_name, app_id=app_id, repo_type=repo_type
                ),
                "cyan",
            )
            branch_api_url = (
                f"https://api.github.com/repos/{repo_full_name}/branches/{app_id}"
            )
            repo_specific_collected_depots: List[Tuple[str, str]] = []

            async with aiohttp.ClientSession() as session:
                try:
                    current_api_headers = (
                        github_auth_headers.copy() if github_auth_headers else {}
                    )
                    async with session.get(
                        branch_api_url,
                        headers=current_api_headers,
                        ssl=False,
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as r_branch:
                        if r_branch.status != 200:
                            status_msg = tr(
                                "AppID {app_id} not found as a branch in {repo_full_name} (Status: {status})."
                            ).format(
                                app_id=app_id,
                                repo_full_name=repo_full_name,
                                status=r_branch.status,
                            )
                            if r_branch.status == 401 and current_api_headers:
                                status_msg += " " + tr("Auth failed. Check token.")
                            elif r_branch.status == 404:
                                status_msg += " " + tr("Branch likely does not exist.")
                            self.print_colored_ui(
                                status_msg + tr(" Trying next selected repo."), "yellow"
                            )
                            continue

                        branch_json = await r_branch.json()
                        commit_data = branch_json.get("commit", {})
                        sha = commit_data.get("sha")
                        tree_url_base = (
                            commit_data.get("commit", {}).get("tree", {}).get("url")
                        )
                        commit_date = (
                            commit_data.get("commit", {})
                            .get("author", {})
                            .get("date", tr("Unknown date"))
                        )
                        if not sha or not tree_url_base:
                            self.print_colored_ui(
                                tr(
                                    "Invalid branch data (missing SHA or tree URL) for {repo_full_name}/{app_id}. Trying next selected repo."
                                ).format(repo_full_name=repo_full_name, app_id=app_id),
                                "red",
                            )
                            continue

                        tree_url_recursive = f"{tree_url_base}?recursive=1"
                        async with session.get(
                            tree_url_recursive,
                            headers=current_api_headers,
                            ssl=False,
                            timeout=aiohttp.ClientTimeout(total=30),
                        ) as r_tree:
                            if r_tree.status != 200:
                                self.print_colored_ui(
                                    tr(
                                        "Failed to get file tree data for {repo_full_name}/{app_id} (Commit SHA: {sha}, Status: {status}). Trying next selected repo."
                                    ).format(
                                        repo_full_name=repo_full_name,
                                        app_id=app_id,
                                        sha=sha[:7],
                                        status=r_tree.status,
                                    ),
                                    "red",
                                )
                                continue
                            tree_json = await r_tree.json()
                            if tree_json.get("truncated"):
                                self.print_colored_ui(
                                    tr(
                                        "Warning: File tree for {repo_full_name}/{app_id} is TRUNCATED by GitHub API. Some files may be missed. Consider repos with smaller AppID branches."
                                    ).format(
                                        repo_full_name=repo_full_name, app_id=app_id
                                    ),
                                    "yellow",
                                )
                            tree_items = tree_json.get("tree", [])
                            if not tree_items:
                                self.print_colored_ui(
                                    tr(
                                        "No files found in tree for {repo_full_name}/{app_id} (Commit SHA: {sha}). Trying next selected repo."
                                    ).format(
                                        repo_full_name=repo_full_name,
                                        app_id=app_id,
                                        sha=sha[:7],
                                    ),
                                    "yellow",
                                )
                                continue

                            files_downloaded_or_processed_this_repo = False
                            key_file_found_and_processed_successfully = False

                            if self.strict_validation_var.get():
                                self.print_colored_ui(
                                    tr(
                                        "STRICT MODE: Processing branch {app_id} in {repo_full_name} (Commit: {sha_short}, Date: {commit_date})"
                                    ).format(
                                        app_id=app_id,
                                        repo_full_name=repo_full_name,
                                        sha_short=sha[:7],
                                        commit_date=commit_date,
                                    ),
                                    "magenta",
                                )
                                key_file_paths_in_tree = {}
                                for item in tree_items:
                                    if item.get("type") == "blob":
                                        item_path, item_basename_lower = item.get(
                                            "path", ""
                                        ), os.path.basename(
                                            item.get("path", "").lower()
                                        )
                                        if item_basename_lower in [
                                            "key.vdf",
                                            "config.vdf",
                                        ]:
                                            key_file_paths_in_tree[item_path] = (
                                                item_basename_lower
                                            )
                                prioritized_key_files = sorted(
                                    key_file_paths_in_tree.keys(),
                                    key=lambda p: (
                                        key_file_paths_in_tree[p] != "key.vdf",
                                        p,
                                    ),
                                )
                                for actual_key_file_path in prioritized_key_files:
                                    if self.cancel_search:
                                        break
                                    key_short_name = key_file_paths_in_tree[
                                        actual_key_file_path
                                    ]
                                    self.print_colored_ui(
                                        tr(
                                            "STRICT: Found potential key file '{key_short_name}' at: {actual_key_file_path}. Attempting to process."
                                        ).format(
                                            key_short_name=key_short_name,
                                            actual_key_file_path=actual_key_file_path,
                                        ),
                                        "default",
                                    )
                                    depot_keys_from_vdf = await self.get_manifest(
                                        sha,
                                        actual_key_file_path,
                                        processing_dir_non_branch,
                                        repo_full_name,
                                    )
                                    if depot_keys_from_vdf:
                                        for dk in depot_keys_from_vdf:
                                            if dk not in repo_specific_collected_depots:
                                                repo_specific_collected_depots.append(
                                                    dk
                                                )
                                        (
                                            files_downloaded_or_processed_this_repo,
                                            key_file_found_and_processed_successfully,
                                        ) = (True, True)
                                        self.print_colored_ui(
                                            tr(
                                                "STRICT: Successfully processed keys from '{actual_key_file_path}'."
                                            ).format(
                                                actual_key_file_path=actual_key_file_path
                                            ),
                                            "green",
                                        )
                                        if key_short_name == "key.vdf":
                                            break
                                if self.cancel_search:
                                    break
                                if not key_file_found_and_processed_successfully:
                                    self.print_colored_ui(
                                        tr(
                                            "STRICT: No Key.vdf or Config.vdf found or processed successfully for keys in {repo_full_name}/{app_id}. This repo may not yield usable decryption data in strict mode. Manifests will still be downloaded if found."
                                        ).format(
                                            repo_full_name=repo_full_name, app_id=app_id
                                        ),
                                        "yellow",
                                    )
                                for item in tree_items:
                                    if self.cancel_search:
                                        break
                                    item_path = item.get("path", "")
                                    if item.get(
                                        "type"
                                    ) == "blob" and item_path.lower().endswith(
                                        ".manifest"
                                    ):
                                        await self.get_manifest(
                                            sha,
                                            item_path,
                                            processing_dir_non_branch,
                                            repo_full_name,
                                        )
                                        if os.path.exists(
                                            os.path.join(
                                                processing_dir_non_branch, item_path
                                            )
                                        ):
                                            files_downloaded_or_processed_this_repo = (
                                                True
                                            )
                            else:  # NON-STRICT
                                self.print_colored_ui(
                                    tr(
                                        "NON-STRICT MODE: Downloading all files from branch {app_id} in {repo_full_name} (Commit: {sha_short}, Date: {commit_date})"
                                    ).format(
                                        app_id=app_id,
                                        repo_full_name=repo_full_name,
                                        sha_short=sha[:7],
                                        commit_date=commit_date,
                                    ),
                                    "magenta",
                                )
                                for item in tree_items:
                                    if self.cancel_search:
                                        break
                                    item_path = item.get("path", "")
                                    if item.get("type") == "blob":
                                        keys_from_file = await self.get_manifest(
                                            sha,
                                            item_path,
                                            processing_dir_non_branch,
                                            repo_full_name,
                                        )
                                        if keys_from_file:
                                            for dk in keys_from_file:
                                                if (
                                                    dk
                                                    not in repo_specific_collected_depots
                                                ):
                                                    repo_specific_collected_depots.append(
                                                        dk
                                                    )
                                        if os.path.exists(
                                            os.path.join(
                                                processing_dir_non_branch, item_path
                                            )
                                        ):
                                            files_downloaded_or_processed_this_repo = (
                                                True
                                            )

                            if self.cancel_search:
                                self.print_colored_ui(
                                    tr(
                                        "\nDownload cancelled during file processing of {repo_full_name}."
                                    ).format(repo_full_name=repo_full_name),
                                    "yellow",
                                )
                                break

                            repo_considered_successful = False
                            if not self.cancel_search:
                                if self.strict_validation_var.get():
                                    repo_considered_successful = (
                                        bool(repo_specific_collected_depots)
                                        and files_downloaded_or_processed_this_repo
                                    )
                                else:
                                    repo_considered_successful = (
                                        files_downloaded_or_processed_this_repo
                                    )

                            if repo_considered_successful:
                                self.print_colored_ui(
                                    tr(
                                        "\nData successfully processed for AppID {app_id} from {repo_full_name}. (Commit Date: {commit_date})"
                                    ).format(
                                        app_id=app_id,
                                        repo_full_name=repo_full_name,
                                        commit_date=commit_date,
                                    ),
                                    "green",
                                )
                                for dk_tuple in repo_specific_collected_depots:
                                    if dk_tuple not in overall_collected_depots:
                                        overall_collected_depots.append(dk_tuple)
                                return (
                                    overall_collected_depots,
                                    processing_dir_non_branch,
                                    False,
                                )
                            else:
                                if not self.cancel_search:
                                    self.print_colored_ui(
                                        tr(
                                            "AppID {app_id} could not be successfully processed from {repo_full_name} with current settings. Files in processing dir (if any) will be from this attempt. Trying next selected repo."
                                        ).format(
                                            app_id=app_id, repo_full_name=repo_full_name
                                        ),
                                        "yellow",
                                    )
                except (
                    aiohttp.ClientError,
                    asyncio.TimeoutError,
                    json.JSONDecodeError,
                ) as e_api:
                    self.print_colored_ui(
                        tr(
                            "\nNetwork/API error while processing {repo_full_name}: {error}. Trying next selected repo."
                        ).format(
                            repo_full_name=repo_full_name, error=self.stack_Error(e_api)
                        ),
                        "red",
                    )
                except KeyboardInterrupt:
                    self.print_colored_ui(
                        tr(
                            "\nProcessing interrupted by user for repository: {repo_full_name}"
                        ).format(repo_full_name=repo_full_name),
                        "yellow",
                    )
                    self.cancel_search = True
                    break
            if self.cancel_search:
                break

        if self.cancel_search:
            self.print_colored_ui(
                tr("\nDownload process terminated by user request."), "yellow"
            )
            return overall_collected_depots, None, False

        self.print_colored_ui(
            tr(
                "\nAppID {app_id} ({game_name}) could not be successfully processed from ANY selected repository with current settings."
            ).format(app_id=app_id, game_name=game_name),
            "red",
        )
        return overall_collected_depots, None, False

    def parse_vdf_to_lua(
        self, depot_info: List[Tuple[str, str]], appid: str, processing_dir: str
    ) -> str:
        lua_lines: List[str] = [f"addappid({appid})"]
        processed_depots_for_setmanifest = set()

        for depot_id, decryption_key in depot_info:
            lua_lines.append(f'addappid({depot_id},1,"{decryption_key}")')
            processed_depots_for_setmanifest.add(depot_id)

        if os.path.isdir(processing_dir):
            all_manifest_files_in_dir: List[str] = []
            for root, _unused_dirs, files in os.walk(processing_dir):
                for f_name in files:
                    if f_name.lower().endswith(".manifest"):
                        all_manifest_files_in_dir.append(os.path.join(root, f_name))

            def sort_key_manifest(filepath: str) -> Tuple[int, str]:
                filename = os.path.basename(filepath)
                name_no_suffix = filename.rsplit(".manifest", 1)[0]
                parts = name_no_suffix.split("_", 1)
                depot_id_str, manifest_gid_val = parts[0], (
                    parts[1] if len(parts) > 1 else ""
                )
                try:
                    depot_id_int = int(depot_id_str) if depot_id_str.isdigit() else 0
                except ValueError:
                    depot_id_int = 0
                    self.print_colored_ui(
                        tr(
                            "Warning: Non-numeric depot ID prefix '{depot_id_str}' in manifest filename '{filename}'. Using 0 for sorting."
                        ).format(depot_id_str=depot_id_str, filename=filename),
                        "yellow",
                    )
                return (depot_id_int, manifest_gid_val)

            try:
                all_manifest_files_in_dir.sort(key=sort_key_manifest)
            except Exception as e_sort:
                self.print_colored_ui(
                    tr(
                        "Warning: Could not fully sort manifest files for LUA generation due to naming or error: {error}. LUA script might be sub-optimal."
                    ).format(error=self.stack_Error(e_sort)),
                    "yellow",
                )

            for manifest_full_path in all_manifest_files_in_dir:
                manifest_filename = os.path.basename(manifest_full_path)
                name_no_suffix = manifest_filename.rsplit(".manifest", 1)[0]
                parts = name_no_suffix.split("_", 1)
                depot_id_from_file, manifest_gid_val = parts[0], (
                    parts[1] if len(parts) > 1 else ""
                )

                if depot_id_from_file.isdigit():
                    if depot_id_from_file not in processed_depots_for_setmanifest:
                        lua_lines.append(f"addappid({depot_id_from_file})")
                        processed_depots_for_setmanifest.add(depot_id_from_file)
                    if manifest_gid_val:
                        lua_lines.append(
                            f'setManifestid({depot_id_from_file},"{manifest_gid_val}",0)'
                        )
                    else:
                        self.print_colored_ui(
                            tr(
                                "Could not parse Manifest GID from filename: {manifest_filename}. setManifestid entry will be skipped."
                            ).format(manifest_filename=manifest_filename),
                            "yellow",
                        )
                else:
                    self.print_colored_ui(
                        tr(
                            "Could not parse numeric DepotID from manifest filename: {manifest_filename}. Entry skipped."
                        ).format(manifest_filename=manifest_filename),
                        "yellow",
                    )
        return "\n".join(lua_lines)

    def zip_outcome(
        self, processing_dir: str, selected_repos_for_zip: List[str]
    ) -> Optional[str]:
        if not os.path.isdir(processing_dir):
            self.print_colored_ui(
                tr(
                    "Processing directory {processing_dir} not found for zipping. Skipping zip creation."
                ).format(processing_dir=processing_dir),
                "red",
            )
            return None
        is_encrypted_source = any(
            self.repos.get(repo_name, "") == "Encrypted"
            for repo_name in selected_repos_for_zip
        )
        strict_mode_active = self.strict_validation_var.get()
        key_files_to_exclude_in_strict = ["key.vdf", "config.vdf"]
        base_name_from_dir = os.path.basename(os.path.normpath(processing_dir))
        final_zip_base_name = (
            base_name_from_dir[1:-5]
            if base_name_from_dir.startswith("_")
            and base_name_from_dir.endswith("_temp")
            else base_name_from_dir
        )
        final_zip_parent_dir = os.path.dirname(processing_dir)
        final_zip_name_suffix = " - encrypted.zip" if is_encrypted_source else ".zip"
        final_zip_name = final_zip_base_name + final_zip_name_suffix
        final_zip_path = os.path.join(final_zip_parent_dir, final_zip_name)

        if os.path.exists(final_zip_path):
            try:
                os.remove(final_zip_path)
                self.print_colored_ui(
                    tr(
                        "Removed existing zip file: {final_zip_path} before creating new one."
                    ).format(final_zip_path=final_zip_path),
                    "yellow",
                )
            except OSError as e_del_zip:
                self.print_colored_ui(
                    tr(
                        "Error removing existing zip {final_zip_path}: {error}. Archiving may fail or append to old data."
                    ).format(
                        final_zip_path=final_zip_path, error=self.stack_Error(e_del_zip)
                    ),
                    "red",
                )
                return None
        try:
            with zipfile.ZipFile(
                final_zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6
            ) as zipf:
                for root, _unused_dirs, files in os.walk(processing_dir):
                    for file in files:
                        file_path_abs, file_basename_lower = (
                            os.path.join(root, file),
                            file.lower(),
                        )
                        if (
                            strict_mode_active
                            and file_basename_lower in key_files_to_exclude_in_strict
                        ):
                            self.print_colored_ui(
                                tr(
                                    "Excluding '{file}' from final zip (Strict Validation is ON)."
                                ).format(file=file),
                                "yellow",
                            )
                            continue
                        archive_name = os.path.relpath(
                            file_path_abs, start=processing_dir
                        )
                        zipf.write(file_path_abs, archive_name)
            self.print_colored_ui(
                tr("\nSuccessfully created outcome zip: {final_zip_path}").format(
                    final_zip_path=final_zip_path
                ),
                "cyan",
            )
            try:
                import shutil

                shutil.rmtree(processing_dir)
                self.print_colored_ui(
                    tr(
                        "Temporary source folder {processing_dir} deleted successfully."
                    ).format(processing_dir=processing_dir),
                    "green",
                )
            except OSError as e_del_temp:
                self.print_colored_ui(
                    tr(
                        "Error deleting temporary source folder {processing_dir}: {error}. Please remove it manually."
                    ).format(
                        processing_dir=processing_dir,
                        error=self.stack_Error(e_del_temp),
                    ),
                    "red",
                )
            return final_zip_path
        except (zipfile.BadZipFile, OSError, FileNotFoundError) as e_zip:
            self.print_colored_ui(
                tr("Error creating zip file {final_zip_path}: {error}").format(
                    final_zip_path=final_zip_path, error=self.stack_Error(e_zip)
                ),
                "red",
            )
            return None
        except Exception as e_generic_zip:
            self.print_colored_ui(
                tr("An unexpected error occurred during zipping: {error}").format(
                    error=self.stack_Error(e_generic_zip)
                ),
                "red",
            )
            return None

    def on_closing(self) -> None:
        if messagebox.askokcancel(tr("Quit"), tr("Do you want to quit?")):
            self.cancel_search = True
            self.settings_manager.set("window_geometry", self.geometry())
            self.settings_manager.save_settings()
            self.destroy()

    def _refresh_ui_texts(self) -> None:
        self.title(tr("Steam Depot Online (SDO)"))
        self.encrypted_label.configure(text=tr("Encrypted Repositories:"))
        self.select_all_enc_button.configure(text=tr("Select All"))
        Tooltip(
            self.select_all_enc_button,
            tr("Toggle selection for all Encrypted repositories."),
        )
        self.decrypted_label.configure(text=tr("Decrypted Repositories:"))
        self.select_all_dec_button.configure(text=tr("Select All"))
        Tooltip(
            self.select_all_dec_button,
            tr("Toggle selection for all Decrypted repositories."),
        )
        self.branch_label.configure(text=tr("Branch Repositories:"))
        self.select_all_branch_button.configure(text=tr("Select All"))
        Tooltip(
            self.select_all_branch_button,
            tr("Toggle selection for all Branch repositories."),
        )
        self.add_repo_button.configure(text=tr("Add Repo"))
        Tooltip(self.add_repo_button, tr("Add a new GitHub repository to the list."))
        self.delete_repo_button.configure(text=tr("Delete Repo"))
        Tooltip(
            self.delete_repo_button, tr("Delete selected repositories from the list.")
        )
        self.settings_button.configure(text=tr("Settings"))
        Tooltip(
            self.settings_button,
            tr("Open application settings, including info, themes, and more."),
        )
        self.output_folder_button.configure(text=tr("Output Folder"))
        Tooltip(
            self.output_folder_button,
            tr("Open the default download output folder where game zips are saved."),
        )
        self.strict_validation_checkbox.configure(
            text=tr("Strict Validation (Require Key.vdf / Non Branch Repo)")
        )
        Tooltip(
            self.strict_validation_checkbox,
            tr(
                "When checked, for non-Branch repos, only downloads manifest files and attempts to extract keys if key.vdf/config.vdf is found. Key files are excluded from final zip. When unchecked, all files are downloaded, and key files are included."
            ),
        )
        self.game_input_label.configure(text=tr("Enter Game Name or AppID:"))
        self.game_input.configure(placeholder_text=tr("e.g. 123456 or Game Name"))
        Tooltip(
            self.game_input,
            tr(
                "Enter a game name (e.g., 'Portal 2') or AppID (e.g., '620'). For batch download, enter multiple AppIDs separated by commas or newlines."
            ),
        )
        self.paste_button.configure(text=tr("Paste"))
        Tooltip(self.paste_button, tr("Paste text from clipboard into the input field."))
        self.search_button.configure(text=tr("Search"))
        Tooltip(
            self.search_button,
            tr("Search for games matching the entered name or AppID."),
        )
        self.download_button.configure(text=tr("Download"))
        Tooltip(
            self.download_button,
            tr("Download manifests/data for the selected game or all entered AppIDs."),
        )
        self.download_type_label.configure(text=tr("Select appid(s) to download:"))
        self.radio_download_selected.configure(
            text=tr("Selected game in search results")
        )
        Tooltip(
            self.radio_download_selected,
            tr("Download only the game selected from the search results (if any)."),
        )
        self.radio_download_all_input.configure(text=tr("All AppIDs in input field"))
        Tooltip(
            self.radio_download_all_input,
            tr(
                "Download all AppIDs found in the 'Enter Game Name or AppID' field, ignoring search results. Useful for batch downloads.\nNote: If multiple AppIDs are entered, all will be downloaded sequentially, skipping individual game details."
            ),
        )
        self.results_label.configure(text=tr("Search Results:"))

        target_progress_tab_title = tr("Progress")
        target_downloaded_tab_title = tr("Downloaded Manifests")

        if (
            hasattr(self, "current_progress_tab_name")
            and target_progress_tab_title != self.current_progress_tab_name
        ):
            try:
                if self.main_tabview.tab(self.current_progress_tab_name) is not None:
                    self.main_tabview.rename(
                        self.current_progress_tab_name, target_progress_tab_title
                    )
                    self.current_progress_tab_name = target_progress_tab_title
                else:
                    self.append_progress(
                        f"Tab '{self.current_progress_tab_name}' not found for renaming.",
                        "yellow",
                    )
            except Exception as e:
                self.append_progress(
                    f"Error renaming progress tab from '{self.current_progress_tab_name}' to '{target_progress_tab_title}': {e}",
                    "red",
                )

        if (
            hasattr(self, "current_downloaded_tab_name")
            and target_downloaded_tab_title != self.current_downloaded_tab_name
        ):
            try:
                if self.main_tabview.tab(self.current_downloaded_tab_name) is not None:
                    self.main_tabview.rename(
                        self.current_downloaded_tab_name, target_downloaded_tab_title
                    )
                    self.current_downloaded_tab_name = target_downloaded_tab_title
                else:
                    self.append_progress(
                        f"Tab '{self.current_downloaded_tab_name}' not found for renaming.",
                        "yellow",
                    )
            except Exception as e:
                self.append_progress(
                    f"Error renaming downloaded tab from '{self.current_downloaded_tab_name}' to '{target_downloaded_tab_title}': {e}",
                    "red",
                )

        self._setup_downloaded_manifests_tab()
        if hasattr(self, "main_tabview") and hasattr(self, "current_progress_tab_name"):
            try:
                tab_exists = any(
                    name == self.current_progress_tab_name
                    for name in self.main_tabview._name_list
                )
                if (
                    tab_exists
                    and self.main_tabview.get() != self.current_progress_tab_name
                ):
                    self.main_tabview.set(self.current_progress_tab_name)
            except Exception as e:
                self.append_progress(
                    f"Error setting active tab to '{self.current_progress_tab_name}': {e}",
                    "yellow",
                )

        if (
            hasattr(self, "settings_window_ref")
            and self.settings_window_ref.winfo_exists()
        ):
            current_settings_tab = self.settings_window_ref.children.get(
                "!ctktabview", None
            )
            current_selected_tab_name = (
                current_settings_tab.get()
                if current_settings_tab
                and isinstance(current_settings_tab, ctk.CTkTabview)
                else None
            )
            self.settings_window_ref.destroy()
            self.open_settings_window()
            if (
                current_selected_tab_name
                and hasattr(self, "settings_window_ref")
                and self.settings_window_ref.winfo_exists()
            ):
                new_settings_tabview = self.settings_window_ref.children.get(
                    "!ctktabview", None
                )
                if new_settings_tabview and isinstance(
                    new_settings_tabview, ctk.CTkTabview
                ):
                    try:
                        new_general_tab_title = tr("General Settings")
                        new_settings_tabview.set(new_general_tab_title)
                    except ValueError:
                        if new_settings_tabview._name_list:
                            new_settings_tabview.set(new_settings_tabview._name_list[0])

    def toggle_all_repos(self, repo_type_to_toggle: str) -> None:
        if repo_type_to_toggle.lower() not in ["encrypted", "decrypted", "branch"]:
            self.print_colored_ui(
                tr(
                    "Invalid repository type specified for toggle: {repo_type_to_toggle}."
                ).format(repo_type_to_toggle=repo_type_to_toggle),
                "red",
            )
            return
        (
            all_relevant_currently_selected,
            relevant_repos_count,
            repos_of_type_to_process,
        ) = (True, 0, [])
        for repo_name, stored_repo_type_in_map in self.repos.items():
            if stored_repo_type_in_map.lower() == repo_type_to_toggle.lower():
                relevant_repos_count += 1
                repos_of_type_to_process.append(repo_name)
                if repo_name in self.repo_vars and not self.repo_vars[repo_name].get():
                    all_relevant_currently_selected = False
        if relevant_repos_count == 0:
            self.print_colored_ui(
                tr("No {repo_type_to_toggle} repositories found to toggle.").format(
                    repo_type_to_toggle=repo_type_to_toggle
                ),
                "yellow",
            )
            return
        new_selection_state: bool = not all_relevant_currently_selected
        for repo_name in repos_of_type_to_process:
            if repo_name in self.repo_vars:
                self.repo_vars[repo_name].set(new_selection_state)
        action_str: str = tr("Selected") if new_selection_state else tr("Deselected")
        self.print_colored_ui(
            tr("{action_str} all {repo_type_to_toggle} repositories.").format(
                action_str=action_str, repo_type_to_toggle=repo_type_to_toggle
            ),
            "blue",
        )
        self.save_repositories()

    def open_add_repo_window(self) -> None:
        if (
            hasattr(self, "add_repo_window_ref")
            and self.add_repo_window_ref is not None
            and self.add_repo_window_ref.winfo_exists()
        ):
            self.add_repo_window_ref.focus_force()
            return
        self.add_repo_window_ref = ctk.CTkToplevel(self)
        self.add_repo_window_ref.title(tr("Add Repository"))
        self.add_repo_window_ref.geometry("400x220")
        self.add_repo_window_ref.resizable(False, False)
        self.add_repo_window_ref.transient(self)
        self.add_repo_window_ref.grab_set()
        ctk.CTkLabel(
            self.add_repo_window_ref, text=tr("Repository Name (e.g., user/repo):")
        ).pack(padx=10, pady=(10, 2))
        self.repo_name_entry = ctk.CTkEntry(self.add_repo_window_ref, width=360)
        self.repo_name_entry.pack(padx=10, pady=(0, 5))
        self.repo_name_entry.focus()
        ctk.CTkLabel(self.add_repo_window_ref, text=tr("Repository Type:")).pack(
            padx=10, pady=(10, 2)
        )
        self.repo_state_var = ctk.StringVar(value="Branch")
        ctk.CTkOptionMenu(
            self.add_repo_window_ref,
            variable=self.repo_state_var,
            values=["Encrypted", "Decrypted", "Branch"],
            width=360,
        ).pack(padx=10, pady=(0, 10))
        ctk.CTkButton(
            self.add_repo_window_ref, text=tr("Add"), command=self.add_repo, width=100
        ).pack(padx=10, pady=10)
        self.add_repo_window_ref.protocol(
            "WM_DELETE_WINDOW", lambda: self._destroy_add_repo_window()
        )
        self.add_repo_window_ref.bind("<Return>", lambda e: self.add_repo())
        self.add_repo_window_ref.bind(
            "<Escape>", lambda e: self._destroy_add_repo_window()
        )

    def _destroy_add_repo_window(self) -> None:
        if (
            hasattr(self, "add_repo_window_ref")
            and self.add_repo_window_ref is not None
        ):
            self.add_repo_window_ref.destroy()
            self.add_repo_window_ref = None

    def add_repo(self) -> None:
        if (
            not hasattr(self, "add_repo_window_ref")
            or self.add_repo_window_ref is None
            or not self.add_repo_window_ref.winfo_exists()
        ):
            self.print_colored_ui(tr("Add repository window is not available."), "red")
            return
        repo_name, repo_state = (
            self.repo_name_entry.get().strip(),
            self.repo_state_var.get(),
        )
        if not repo_name:
            messagebox.showwarning(
                tr("Input Error"),
                tr("Please enter the repository name."),
                parent=self.add_repo_window_ref,
            )
            return
        if (
            "/" not in repo_name
            or len(repo_name.split("/")) != 2
            or " " in repo_name
            or repo_name.startswith("/")
            or repo_name.endswith("/")
        ):
            messagebox.showwarning(
                tr("Input Error"),
                tr(
                    "Repository name must be in 'owner/repository' format (e.g., 'octocat/Hello-World') without spaces or leading/trailing slashes."
                ),
                parent=self.add_repo_window_ref,
            )
            return
        if repo_name in self.repos:
            messagebox.showwarning(
                tr("Input Error"),
                tr("Repository '{repo_name}' already exists in your list.").format(
                    repo_name=repo_name
                ),
                parent=self.add_repo_window_ref,
            )
            return
        self.repos[repo_name], self.selected_repos[repo_name] = repo_state, (
            repo_state == "Branch"
        )
        self.save_repositories()
        self.refresh_repo_checkboxes()
        self.print_colored_ui(
            tr("Added repository: {repo_name} (Type: {repo_state})").format(
                repo_name=repo_name, repo_state=repo_state
            ),
            "green",
        )
        self._destroy_add_repo_window()

    def delete_repo(self) -> None:
        repos_to_delete_names: List[str] = [
            cb.cget("text")
            for scroll_frame in [
                self.encrypted_scroll,
                self.decrypted_scroll,
                self.branch_scroll,
            ]
            for cb in scroll_frame.winfo_children()
            if isinstance(cb, ctk.CTkCheckBox) and cb.get() == 1
        ]
        if not repos_to_delete_names:
            messagebox.showwarning(
                tr("Selection Error"),
                tr(
                    "Please select at least one repository to delete by checking its box."
                ),
            )
            return
        confirmation_message = tr(
            "Are you sure you want to delete these {len_repos_to_delete} repositories?\n\n- "
        ).format(len_repos_to_delete=len(repos_to_delete_names)) + "\n- ".join(
            repos_to_delete_names
        )
        if not messagebox.askyesno(tr("Confirm Deletion"), confirmation_message):
            return
        deleted_count = 0
        for repo_name_to_delete in repos_to_delete_names:
            if repo_name_to_delete in self.repos:
                del self.repos[repo_name_to_delete]
                if repo_name_to_delete in self.selected_repos:
                    del self.selected_repos[repo_name_to_delete]
                if repo_name_to_delete in self.repo_vars:
                    del self.repo_vars[repo_name_to_delete]
                deleted_count += 1
        if deleted_count > 0:
            self.save_repositories()
            self.refresh_repo_checkboxes()
            self.print_colored_ui(
                tr("Deleted {deleted_count} repositories: {repos_to_delete_str}").format(
                    deleted_count=deleted_count,
                    repos_to_delete_str=", ".join(repos_to_delete_names),
                ),
                "red",
            )
        else:
            self.print_colored_ui(
                tr(
                    "No matching repositories found in the internal list to delete. UI might be out of sync."
                ),
                "yellow",
            )

    def refresh_repo_checkboxes(self) -> None:
        for scroll_frame in [
            self.encrypted_scroll,
            self.decrypted_scroll,
            self.branch_scroll,
        ]:
            for widget in scroll_frame.winfo_children():
                widget.destroy()
        new_repo_vars_cache = {}
        sorted_repo_names = sorted(self.repos.keys())
        for repo_name in sorted_repo_names:
            repo_type = self.repos[repo_name]
            initial_selection_state = self.selected_repos.get(
                repo_name, (repo_type == "Branch")
            )
            var = ctk.BooleanVar(value=initial_selection_state)
            var.trace_add(
                "write",
                lambda name, index, mode, rn=repo_name, v=var: self._update_selected_repo_state(
                    rn, v.get()
                ),
            )
            new_repo_vars_cache[repo_name] = var
            target_scroll_frame = None
            if repo_type == "Encrypted":
                target_scroll_frame = self.encrypted_scroll
            elif repo_type == "Decrypted":
                target_scroll_frame = self.decrypted_scroll
            elif repo_type == "Branch":
                target_scroll_frame = self.branch_scroll
            else:
                self.print_colored_ui(
                    tr(
                        "Warning: Unknown repository type '{repo_type}' for '{repo_name}'. Assigning to Decrypted section for UI."
                    ).format(repo_type=repo_type, repo_name=repo_name),
                    "yellow",
                )
                target_scroll_frame = self.decrypted_scroll
            if target_scroll_frame:
                ctk.CTkCheckBox(target_scroll_frame, text=repo_name, variable=var).pack(
                    anchor="w", padx=10, pady=2
                )
        self.repo_vars = new_repo_vars_cache
        self.save_repositories()

    def _update_selected_repo_state(self, repo_name: str, is_selected: bool) -> None:
        self.selected_repos[repo_name] = is_selected
        self.settings_manager.set("selected_repos", self.selected_repos)
        self.settings_manager.save_settings()
        action = tr("selected") if is_selected else tr("deselected")
        self.append_progress(
            tr("Repository '{repo_name}' {action}.").format(
                repo_name=repo_name, action=action
            ),
            "default",
        )

    def open_settings_window(self) -> None:
        if (
            hasattr(self, "settings_window_ref")
            and self.settings_window_ref is not None
            and self.settings_window_ref.winfo_exists()
        ):
            self.settings_window_ref.destroy()
        self.settings_window_ref = ctk.CTkToplevel(self)
        self.settings_window_ref.title(tr("Settings"))
        self.settings_window_ref.geometry("700x600")
        self.settings_window_ref.resizable(True, True)
        self.settings_window_ref.transient(self)
        self.settings_window_ref.grab_set()
        settings_tabview = ctk.CTkTabview(
            self.settings_window_ref,
            command=lambda: self.settings_window_ref.focus_force(),
        )
        settings_tabview.pack(padx=10, pady=10, fill="both", expand=True)

        general_tab_title = tr("General Settings")
        general_tab = settings_tabview.add(general_tab_title)
        self._setup_general_settings_tab(general_tab)

        repo_settings_tab_title = tr("Repositories")
        repo_settings_tab = settings_tabview.add(repo_settings_tab_title)
        self._setup_repo_settings_tab(repo_settings_tab)

        about_tab_title = tr("About")
        about_tab = settings_tabview.add(about_tab_title)
        self._setup_about_tab(about_tab)

        settings_tabview.set(general_tab_title)
        self.settings_window_ref.protocol(
            "WM_DELETE_WINDOW", lambda: self._destroy_settings_window()
        )
        self.settings_window_ref.after(100, self.settings_window_ref.focus_force)

    def _destroy_settings_window(self):
        if hasattr(self, "settings_window_ref") and self.settings_window_ref:
            self.settings_window_ref.destroy()
            self.settings_window_ref = None

    def _setup_general_settings_tab(self, parent_tab: ctk.CTkFrame) -> None:
        for widget in parent_tab.winfo_children():
            widget.destroy()
        frame = ctk.CTkScrollableFrame(parent_tab)
        frame.pack(fill="both", expand=True, padx=5, pady=5)

        download_frame = ctk.CTkFrame(frame)
        download_frame.pack(fill="x", pady=5, padx=5)
        ctk.CTkLabel(download_frame, text=tr("Download Location:")).pack(
            side="left", padx=5
        )
        self.download_path_entry = ctk.CTkEntry(download_frame, width=300)
        self.download_path_entry.insert(0, self.settings_manager.get("download_path"))
        self.download_path_entry.pack(side="left", expand=True, fill="x", padx=5)
        choose_folder_button = ctk.CTkButton(
            download_frame,
            text=tr("Choose Folder"),
            command=self._choose_download_folder,
        )
        choose_folder_button.pack(side="left", padx=5)
        Tooltip(
            choose_folder_button,
            tr("Select the folder where downloaded games and manifests will be saved."),
        )

        appearance_frame = ctk.CTkFrame(frame)
        appearance_frame.pack(fill="x", pady=5, padx=5)
        ctk.CTkLabel(appearance_frame, text=tr("Appearance Mode:")).pack(
            side="left", padx=5
        )
        current_appearance_mode = self.settings_manager.get("appearance_mode")
        appearance_display_map = {
            "dark": tr("Dark"),
            "light": tr("Light"),
            "system": tr("System"),
        }
        current_display_appearance = appearance_display_map.get(
            current_appearance_mode, current_appearance_mode.capitalize()
        )
        self.appearance_mode_var = ctk.StringVar(value=current_display_appearance)
        translated_appearance_modes = [tr("Dark"), tr("Light"), tr("System")]
        self.appearance_mode_optionmenu = ctk.CTkOptionMenu(
            appearance_frame,
            variable=self.appearance_mode_var,
            values=translated_appearance_modes,
            command=self._change_appearance_mode,
        )
        self.appearance_mode_optionmenu.pack(side="left", padx=5)
        Tooltip(
            self.appearance_mode_optionmenu,
            tr(
                "Change the overall UI theme (Dark, Light, or follow System preferences). Restart may be needed."
            ),
        )

        color_theme_frame = ctk.CTkFrame(frame)
        color_theme_frame.pack(fill="x", pady=5, padx=5)
        ctk.CTkLabel(color_theme_frame, text=tr("Color Theme:")).pack(
            side="left", padx=5
        )
        self.color_theme_var = ctk.StringVar(
            value=self.settings_manager.get("color_theme")
        )
        color_theme_options = ["blue", "green", "dark-blue"]
        self.color_theme_optionmenu = ctk.CTkOptionMenu(
            color_theme_frame,
            variable=self.color_theme_var,
            values=color_theme_options,
            command=self._change_color_theme,
        )
        self.color_theme_optionmenu.pack(side="left", padx=5)
        Tooltip(
            self.color_theme_optionmenu, tr("Change the primary accent color of the UI.")
        )

        lang_frame = ctk.CTkFrame(frame)
        lang_frame.pack(fill="x", pady=5, padx=5)
        ctk.CTkLabel(lang_frame, text=tr("App Language:")).pack(side="left", padx=5)
        available_lang_map = self.localization_manager.get_available_languages()
        available_lang_display_names = list(available_lang_map.values())
        current_lang_code = self.localization_manager.current_language
        current_lang_display_name = available_lang_map.get(
            current_lang_code, current_lang_code
        )
        self.lang_var = ctk.StringVar(value=current_lang_display_name)
        self.lang_optionmenu = ctk.CTkOptionMenu(
            lang_frame,
            variable=self.lang_var,
            values=available_lang_display_names,
            command=self._change_language,
        )
        self.lang_optionmenu.pack(side="left", padx=5)
        Tooltip(
            self.lang_optionmenu,
            tr("Change the display language of the application. Restart may be needed."),
        )

        github_token_outer_frame = ctk.CTkFrame(frame)
        github_token_outer_frame.pack(fill="x", pady=5, padx=5)
        ctk.CTkLabel(
            github_token_outer_frame, text=tr("GitHub API Token (Optional):")
        ).pack(anchor="w", pady=(0, 2))
        github_token_inner_frame = ctk.CTkFrame(github_token_outer_frame)
        github_token_inner_frame.pack(fill="x")
        self.github_token_entry = ctk.CTkEntry(
            github_token_inner_frame, width=350, show="*"
        )
        self.github_token_entry.insert(0, self.settings_manager.get("github_api_token"))
        self.github_token_entry.pack(side="left", expand=True, fill="x", padx=(0, 5))
        Tooltip(
            self.github_token_entry,
            tr(
                "Enter your GitHub Personal Access Token (PAT) to increase rate limits or access private data (if token has permissions). Stored locally in settings.json."
            ),
        )
        self.use_github_token_var = ctk.BooleanVar(
            value=self.settings_manager.get("use_github_api_token")
        )
        use_github_token_cb = ctk.CTkCheckBox(
            github_token_inner_frame,
            text=tr("Use Token"),
            variable=self.use_github_token_var,
        )
        use_github_token_cb.pack(side="left", padx=5)
        Tooltip(
            use_github_token_cb,
            tr(
                "If checked, the application will use the provided GitHub API token for all relevant GitHub requests."
            ),
        )

        # --- Rate Limit Check UI (MODIFIED SECTION) ---
        rate_limit_ui_frame = ctk.CTkFrame(frame)
        rate_limit_ui_frame.pack(pady=(10, 5), padx=5, anchor="w", fill="x")

        check_rate_limit_button = ctk.CTkButton(
            rate_limit_ui_frame,
            text=tr("Check GitHub API Rate Limit"),
            command=self._check_github_rate_limit_ui,
        )
        check_rate_limit_button.pack(side="left", padx=(0, 10))
        Tooltip(
            check_rate_limit_button,
            tr(
                "Check your current GitHub API rate limit status using the configured token (if enabled and set) or unauthenticated."
            ),
        )

        self.rate_limit_display_label = ctk.CTkLabel(
            rate_limit_ui_frame, text=tr("N/A"), font=("Helvetica", 18), width=120, text_color="gray"
        )
        self.rate_limit_display_label.pack(side="left", padx=(0, 5))
        Tooltip(
            self.rate_limit_display_label,
            tr("GitHub API Rate Limit: Remaining/Total. Click button to update."),
        )
        # --- End Rate Limit Check UI ---

        update_check_frame = ctk.CTkFrame(frame)
        update_check_frame.pack(fill="x", pady=10, padx=5)
        self.update_check_var = ctk.BooleanVar(
            value=self.settings_manager.get("app_update_check_on_startup")
        )
        update_check_cb = ctk.CTkCheckBox(
            update_check_frame,
            text=tr("On startup, check for new SDO versions"),
            variable=self.update_check_var,
        )
        update_check_cb.pack(side="left", padx=0, pady=5)
        Tooltip(
            update_check_cb,
            tr("Automatically check for new SDO versions when the application starts."),
        )
        check_now_button = ctk.CTkButton(
            update_check_frame,
            text=tr("Check for Updates Now"),
            command=lambda: threading.Thread(
                target=self.run_update_check, daemon=True
            ).start(),
        )
        check_now_button.pack(side="right", padx=0, pady=5)
        Tooltip(check_now_button, tr("Manually check for a new version of SDO."))
        ctk.CTkLabel(
            frame,
            text=tr("Current App Version: {app_version}").format(
                app_version=self.APP_VERSION
            ),
        ).pack(anchor="w", padx=10, pady=(10, 5))
        save_button = ctk.CTkButton(
            frame, text=tr("Save General Settings"), command=self._save_general_settings
        )
        save_button.pack(pady=15, padx=5)
        Tooltip(
            save_button, tr("Save all settings modified in this 'General Settings' tab.")
        )

    def _update_rate_limit_label(self, text_to_display: str) -> None:
        if (
            hasattr(self, "rate_limit_display_label")
            and self.rate_limit_display_label
            and self.rate_limit_display_label.winfo_exists()
        ):
            self.rate_limit_display_label.configure(text=text_to_display)

    def _check_github_rate_limit_ui(self) -> None:
        if not self.settings_manager.get(
            "use_github_api_token"
        ) or not self.settings_manager.get("github_api_token"):
            msg = tr(
                "GitHub token is not enabled or not set. Cannot check rate limit with token."
            )
            parent_win = (
                self.settings_window_ref
                if hasattr(self, "settings_window_ref")
                and self.settings_window_ref.winfo_exists()
                else self
            )
            if messagebox.askyesno(
                tr("Unauthenticated Check?"),
                msg
                + "\n\n"
                + tr(
                    "Do you want to check the unauthenticated GitHub rate limit (based on your IP)?"
                ),
                parent=parent_win,
            ):
                self.append_progress(
                    tr("Checking unauthenticated GitHub API rate limit..."), "default"
                )
                if (
                    hasattr(self, "rate_limit_display_label")
                    and self.rate_limit_display_label
                ):
                    self.after(0, self._update_rate_limit_label, tr("Checking..."))
                threading.Thread(
                    target=self.run_check_rate_limit, args=(False,), daemon=True
                ).start()
            else:
                if (
                    hasattr(self, "rate_limit_display_label")
                    and self.rate_limit_display_label
                ):
                    self.after(
                        0, self._update_rate_limit_label, tr("N/A (Token not set)")
                    )
            return

        self.append_progress(
            tr("Checking GitHub API rate limit (using token)..."), "default"
        )
        if hasattr(self, "rate_limit_display_label") and self.rate_limit_display_label:
            self.after(0, self._update_rate_limit_label, tr("Checking..."))

        threading.Thread(
            target=self.run_check_rate_limit, args=(True,), daemon=True
        ).start()

    def run_check_rate_limit(self, use_token_override: bool = True) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                self._async_check_github_rate_limit(use_token_override)
            )
        finally:
            loop.close()

    async def _async_check_github_rate_limit(self, use_token_override: bool) -> None:
        final_display_text = tr("N/A")
        request_headers, is_authenticated_check = {}, False

        if use_token_override:
            token_headers = self._get_github_headers()
            if token_headers:
                request_headers, is_authenticated_check = token_headers, True
            else:
                self.append_progress(
                    tr(
                        "Token not available for authenticated check; using unauthenticated."
                    ),
                    "yellow",
                )

        url = "https://api.github.com/rate_limit"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=request_headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        core_limit_data = data.get("resources", {}).get("core", {})
                        if not core_limit_data and not is_authenticated_check:
                            core_limit_data = data.get("rate", {})

                        limit = core_limit_data.get("limit")
                        remaining = core_limit_data.get("remaining")

                        if limit is not None and remaining is not None:
                            auth_status_msg = (
                                tr("(Authenticated)")
                                if is_authenticated_check
                                else tr("(Unauthenticated - IP Based)")
                            )
                            success_message = tr(
                                "GitHub API Rate Limit checked {auth_status_msg}."
                            ).format(auth_status_msg=auth_status_msg)
                            self.append_progress(success_message, "green")
                            final_display_text = f"{remaining}/{limit}"
                        else:
                            self.append_progress(
                                tr(
                                    "Could not retrieve detailed rate limit information from the response."
                                ),
                                "yellow",
                            )
                            final_display_text = tr("Error: Data missing")
                    else:
                        error_message_detail = tr(
                            "Failed to check rate limit (Status: {status})."
                        ).format(status=response.status)
                        self.append_progress(error_message_detail, "red")
                        if response.status == 401 and is_authenticated_check:
                            self.append_progress(
                                tr(
                                    "  Error: Unauthorized. Check your GitHub API token and its permissions."
                                ),
                                "red",
                            )
                        elif response.status == 403:
                            self.append_progress(
                                tr(
                                    "  Error: Forbidden (403). You might have exceeded rate limits or triggered abuse detection."
                                ),
                                "red",
                            )
                        final_display_text = tr("Error: Status {status}").format(
                            status=response.status
                        )
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            self.append_progress(
                tr("Error during GitHub rate limit check: {error}").format(
                    error=self.stack_Error(e)
                ),
                "red",
            )
            final_display_text = tr("Error: Network")
        except json.JSONDecodeError:
            self.append_progress(
                tr("Error decoding GitHub rate limit JSON response."), "red"
            )
            final_display_text = tr("Error: JSON")
        except Exception as e:
            self.append_progress(
                tr("Unexpected error during GitHub rate limit check: {error}").format(
                    error=self.stack_Error(e)
                ),
                "red",
            )
            final_display_text = tr("Error: Unknown")
        finally:
            self.after(0, self._update_rate_limit_label, final_display_text)

    def _setup_repo_settings_tab(self, parent_tab: ctk.CTkFrame) -> None:
        for widget in parent_tab.winfo_children():
            widget.destroy()
        frame = ctk.CTkFrame(parent_tab)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        ctk.CTkLabel(
            frame, text=tr("Manage Repository List"), font=("Helvetica", 14.4, "bold")
        ).pack(pady=(5, 15))
        export_button = ctk.CTkButton(
            frame,
            text=tr("Export Repositories to File"),
            command=self._export_repositories,
            height=30,
        )
        export_button.pack(pady=7, padx=20, fill="x")
        Tooltip(
            export_button,
            tr(
                "Save your current list of repositories (names and types) to a JSON file at a location you choose."
            ),
        )
        import_button = ctk.CTkButton(
            frame,
            text=tr("Import Repositories from File"),
            command=self._import_repositories,
            height=30,
        )
        import_button.pack(pady=7, padx=20, fill="x")
        Tooltip(
            import_button,
            tr(
                "Load a list of repositories from a JSON file. Imported repositories will be added to your current list if they don't already exist. Duplicates by name are ignored."
            ),
        )
        ctk.CTkLabel(
            frame,
            text=tr(
                "Note: Importing will add new repositories from the file. It does not remove existing ones. Repository selection states are managed separately."
            ),
            wraplength=frame.winfo_width() - 60 if frame.winfo_width() > 60 else 600,
            font=("Helvetica", 16, "italic"),
            justify="left",
            text_color="gray",
        ).pack(pady=(15, 5), padx=10, fill="x")

    def _setup_about_tab(self, parent_tab: ctk.CTkFrame) -> None:
        """Sets up the 'About' tab."""
        for widget in parent_tab.winfo_children():
            widget.destroy()
        info_text_frame = ctk.CTkFrame(parent_tab)
        info_text_frame.pack(padx=5, pady=5, fill="both", expand=True)
        info_textbox = Text(
            info_text_frame,
            wrap="word",
            bg="#2B2B2B",
            fg="white",
            font=("Helvetica", 11),
            insertbackground="white",
            padx=10,
            pady=10,
            borderwidth=0,
            exportselection=True,
        )
        info_textbox.pack(side="left", fill="both", expand=True)
        info_scrollbar = ctk.CTkScrollbar(info_text_frame, command=info_textbox.yview)
        info_scrollbar.pack(side="right", fill="y")
        info_textbox.configure(yscrollcommand=info_scrollbar.set)
        tags_config = {
            "bold": {"font": ("Helvetica", 11, "bold")},
            "italic": {"font": ("Helvetica", 11, "italic")},
            "title": {
                "font": ("Helvetica", 14, "bold"),
                "foreground": "cyan",
                "spacing1": 10,
                "spacing3": 15,
                "justify": "center",
            },
            "subtitle": {
                "font": ("Helvetica", 12, "bold"),
                "foreground": "deepskyblue",
                "spacing1": 8,
                "spacing3": 8,
            },
            "highlight": {"foreground": "lawn green"},
            "note": {"foreground": "orange"},
            "normal": {"font": ("Helvetica", 11), "spacing3": 5},
            "url": {
                "font": ("Helvetica", 11),
                "foreground": "light sky blue",
                "underline": True,
            },
            "code": {
                "font": ("Courier New", 10),
                "background": "#404040",
                "foreground": "#E0E0E0",
                "lmargin1": 15,
                "lmargin2": 15,
                "spacing1": 3,
                "spacing3": 3,
            },
        }
        for tag, conf in tags_config.items():
            info_textbox.tag_configure(tag, **conf)
        info_content = [
            (
                tr("Steam Depot Online (SDO) - Version: {version}\n").format(
                    version=self.APP_VERSION
                ),
                "title",
            ),
            (tr("Developed by: "), "bold"),
            ("FairyRoot\n", "highlight"),
            (tr("Contact (Telegram): "), "normal"),
            ("t.me/FairyRoot\n\n", "url"),
            (tr("Overview:"), "subtitle"),
            (
                tr(
                    "Steam Depot Online (SDO) is a tool designed to help users search for Steam games and download associated data from selected GitHub repositories. It primarily targets manifest files and decryption keys which can be used with Steam emulators or for archival purposes. The application offers different processing methods based on the type of repository ('Encrypted', 'Decrypted', 'Branch') and user settings like 'Strict Validation'."
                )
                + "\n\n"
                + tr("Successfully processed non-Branch downloads are zipped into:\n"),
                "normal",
            ),
            (
                f"`{os.path.join(self.settings_manager.get('download_path', 'Games'), '{GameName}-{AppID}.zip')}`\n",
                "code",
            ),
            (
                tr(
                    "Branch type downloads are saved directly as downloaded .zip files to the same location.\n\n"
                ),
                "normal",
            ),
            (tr("Key Features:"), "subtitle"),
            (
                tr(
                    "\n- Add, manage, and delete GitHub repositories (owner/repo format).\n"
                ),
                "normal",
            ),
            (
                tr(
                    "- Categorize repositories as 'Encrypted', 'Decrypted', or 'Branch'.\n"
                ),
                "normal",
            ),
            (tr("- Select multiple repositories for download attempts.\n"), "normal"),
            (
                tr(
                    "- Toggle 'Strict Validation' for non-Branch repositories to control file download and key handling.\n"
                ),
                "normal",
            ),
            (
                tr(
                    "- Search games by Name (uses Steam's full app list) or directly by AppID (uses Steam API for details).\n"
                ),
                "normal",
            ),
            (
                tr(
                    "- Display game details including descriptions and images (requires Pillow library).\n"
                ),
                "normal",
            ),
            (
                tr(
                    "- Generate .lua scripts for common Steam emulators (for non-Branch types if keys are found).\n"
                ),
                "normal",
            ),
            (tr("- Batch download capability by entering multiple AppIDs.\n"), "normal"),
            (
                tr("- View and manage downloaded zip files directly from the app.\n"),
                "normal",
            ),
            (tr("- Theme and language customization.\n"), "normal"),
            (
                tr("- Optional GitHub API Token usage for increased rate limits.\n\n"),
                "normal",
            ),
            (tr("1. Repository Types Explained:"), "subtitle"),
            (tr("\n   - Decrypted Repositories:"), "bold"),
            (
                tr(
                    " (Often preferred for ready-to-use data)\n     These repositories typically contain necessary decryption keys (e.g., in a `key.vdf` or `config.vdf` file). SDO attempts to extract these keys and download associated manifest files. The output is a tool-generated ZIP file containing the processed files and a .lua script.\n"
                ),
                "normal",
            ),
            (tr("   - Encrypted Repositories:"), "bold"),
            (
                tr(
                    "\n     These may host the latest game manifests, but decryption keys within their key files might be hashed, partial, or invalid for direct use. SDO will still attempt to process them, and a .lua script is generated (which could be minimal if no valid keys are found). The output is a tool-generated ZIP similar to Decrypted ones.\n"
                ),
                "note",
            ),
            (tr("   - Branch Repositories:"), "bold"),
            (
                tr(
                    " (Direct archive download)\n     For these repositories, SDO downloads a direct .zip archive of an entire AppID-named branch (e.g., a branch named '1245620') from GitHub. This downloaded .zip is saved *as is* to your output folder. No .lua script is generated by SDO, and no further zipping or file processing (like key extraction or manifest filtering) is performed by SDO for this type. 'Strict Validation' does not apply to Branch repositories.\n"
                ),
                "normal",
            ),
            (
                tr(
                    "   *Recommendation for Playable Games:* Prioritize 'Decrypted' repositories if your goal is to use the data with an emulator. 'Branch' repositories provide raw game data zips which might be useful for archival, manual setup, or if you trust the source's packaging.\n"
                ),
                "normal",
            ),
            (
                tr(
                    "   *For Latest Manifests (Advanced Users):* 'Encrypted' repositories might offer newer game files, but you may need to source valid decryption keys elsewhere if the repository itself doesn't provide usable ones.\n\n"
                ),
                "normal",
            ),
            (tr("2. 'Strict Validation' Checkbox:"), "subtitle"),
            (
                tr(
                    "\n   - This setting applies ONLY to 'Encrypted' and 'Decrypted' (i.e., non-Branch) repository types.\n"
                ),
                "note",
            ),
            (tr("   - Checked (Default):"), "bold"),
            (
                tr(
                    " SDO requires a `key.vdf` or `config.vdf` to be present in the fetched GitHub branch data. It will prioritize downloading and parsing these key files. If valid decryption keys are found, associated `.manifest` files are also downloaded. The final tool-generated ZIP will *exclude* the `key.vdf`/`config.vdf` itself, as the keys are incorporated into the .lua script.\n"
                ),
                "normal",
            ),
            (tr("   - Unchecked:"), "bold"),
            (
                tr(
                    " SDO attempts to download all files from the fetched GitHub branch data. If `key.vdf`/`config.vdf` are present, they are parsed for keys. All downloaded files, *including* any `key.vdf`/`config.vdf`, WILL be included in the final tool-generated ZIP. This might be useful if you want the original key files for manual inspection or use with other tools.\n\n"
                ),
                "normal",
            ),
            (tr("3. GitHub API Token:"), "subtitle"),
            (
                tr(
                    "\n   - You can add a GitHub Personal Access Token (PAT) in the General Settings.\n"
                ),
                "normal",
            ),
            (
                tr(
                    "   - If a token is provided and the 'Use Token' checkbox is enabled, SDO will use this token for all requests to the GitHub API (e.g., fetching branch information, file trees, and downloading branch zips via the API).\n"
                ),
                "normal",
            ),
            (
                tr(
                    "   - Using a token can significantly increase your API rate limit (from ~60 requests/hour per IP to ~5000 requests/hour per token) and may be required to access certain data or avoid public rate limits.\n"
                ),
                "normal",
            ),
            (
                tr(
                    "   - The token is stored locally in the `settings.json` file. Ensure this file is kept secure if you use a token with broad permissions.\n\n"
                ),
                "note",
            ),
            (tr("4. Usage Workflow:"), "subtitle"),
            (
                tr(
                    "\n   1. (Optional) Configure GitHub API Token in Settings if you have one.\n   2. Add GitHub repositories via 'Add Repo' (e.g., `SomeUser/SomeRepo`). Correctly select their type.\n   3. Select the checkboxes for repositories you wish to use for downloads.\n   4. Adjust 'Strict Validation' if needed for non-Branch downloads.\n   5. Enter a game name or AppID(s) and click 'Search'. (Wait for initial Steam app list load on first use if searching by name).\n   6. If searching a single game, select it from the results. Details will appear in the Progress panel.\n   7. Choose your download mode ('Selected game' or 'All AppIDs in input').\n   8. Click 'Download'. Monitor the Progress panel.\n\n"
                ),
                "normal",
            ),
            (tr("5. Potential Issues & Notes:"), "subtitle"),
            (
                tr(
                    "\n   - Image Display: Game logos/headers require the Pillow library (`pip install Pillow`). If not installed, images won't appear in game details.\n"
                ),
                "note",
            ),
            (
                tr(
                    "   - 'Content is still encrypted' (In-game error for non-Branch output): This means the game files were downloaded, but either valid decryption keys were not found/extracted by SDO, or they were not correctly applied by your emulator. Try a different 'Decrypted' repository, verify your emulator setup, or check if the game requires specific key handling.\n"
                ),
                "normal",
            ),
            (
                tr(
                    "   - API Rate Limiting: Both GitHub and Steam APIs have rate limits. If you make too many requests in a short period, you might be temporarily blocked. Using a GitHub token helps with GitHub's limits. For Steam, limits are generally per-IP and less stringent for typical SDO usage.\n"
                ),
                "normal",
            ),
            (
                tr(
                    "   - Internet Connection: A stable internet connection is required for all online operations.\n"
                ),
                "normal",
            ),
            (
                tr(
                    "   - Repository Availability: GitHub repositories can be removed or changed by their owners. What SDO can find depends on the content of the selected repositories at the time of download.\n\n"
                ),
                "normal",
            ),
        ]
        info_textbox.configure(state="normal")
        for text, tag_name in info_content:
            info_textbox.insert("end", text, tag_name)
        info_textbox.configure(state="disabled")
        info_textbox.see("1.0")

    def _choose_download_folder(self) -> None:
        current_path = self.settings_manager.get("download_path")
        parent_window = (
            self.settings_window_ref
            if (
                hasattr(self, "settings_window_ref")
                and self.settings_window_ref
                and self.settings_window_ref.winfo_exists()
            )
            else self
        )
        chosen_path = filedialog.askdirectory(
            parent=parent_window,
            initialdir=current_path if os.path.isdir(current_path) else os.getcwd(),
            title=tr("Select Download Folder"),
        )
        if chosen_path:
            self.download_path_entry.delete(0, END)
            self.download_path_entry.insert(0, chosen_path)
            self.append_progress(
                tr(
                    "Download path updated to: {chosen_path}. Changes will be saved when you click 'Save General Settings'."
                ).format(chosen_path=chosen_path),
                "default",
            )

    def _change_appearance_mode(self, new_appearance_mode_display: str) -> None:
        reverse_map = {tr("Dark"): "dark", tr("Light"): "light", tr("System"): "system"}
        actual_mode = reverse_map.get(
            new_appearance_mode_display, new_appearance_mode_display.lower()
        )
        current_ctk_mode = ctk.get_appearance_mode().lower()
        if actual_mode.lower() != current_ctk_mode:
            ctk.set_appearance_mode(actual_mode)
            self.settings_manager.set("appearance_mode", actual_mode)
            self.append_progress(
                tr(
                    "Appearance mode set to: {new_appearance_mode_display}. Some changes may require a restart to fully apply."
                ).format(new_appearance_mode_display=new_appearance_mode_display),
                "yellow",
            )
        parent_win = (
            self.settings_window_ref
            if hasattr(self, "settings_window_ref")
            and self.settings_window_ref.winfo_exists()
            else self
        )
        messagebox.showinfo(
            tr("Appearance Mode Change"),
            tr(
                "Appearance mode changed to {new_appearance_mode_display}. A restart might be needed for all UI elements to update correctly."
            ).format(new_appearance_mode_display=new_appearance_mode_display),
            parent=parent_win,
        )

    def _change_color_theme(self, new_color_theme: str) -> None:
        current_theme = self.settings_manager.get("color_theme")
        if new_color_theme.lower() != current_theme.lower():
            try:
                ctk.set_default_color_theme(new_color_theme)
                self.settings_manager.set("color_theme", new_color_theme)
                self.append_progress(
                    tr(
                        "Color theme set to: {new_color_theme}. A restart might be needed for all elements to reflect the new theme."
                    ).format(new_color_theme=new_color_theme),
                    "default",
                )
                parent_win = (
                    self.settings_window_ref
                    if hasattr(self, "settings_window_ref")
                    and self.settings_window_ref.winfo_exists()
                    else self
                )
                messagebox.showinfo(
                    tr("Color Theme Change"),
                    tr(
                        "Color theme changed to {new_color_theme}. Please restart the application for changes to fully apply to all UI components."
                    ).format(new_color_theme=new_color_theme),
                    parent=parent_win,
                )
            except Exception as e:
                self.append_progress(f"Error changing theme: {e}", "red")

    def _change_language(self, new_language_display_name: str) -> None:
        available_languages_map = self.localization_manager.get_available_languages()
        selected_lang_code = next(
            (
                code
                for code, display_name in available_languages_map.items()
                if display_name == new_language_display_name
            ),
            None,
        )
        if selected_lang_code:
            if selected_lang_code != self.localization_manager.current_language:
                self.localization_manager.set_language(selected_lang_code)
                self._refresh_ui_texts()
                self.append_progress(
                    tr(
                        "Language changed to {new_language_display_name}. Some elements might require an application restart to fully update."
                    ).format(new_language_display_name=new_language_display_name),
                    "yellow",
                )
                parent_win = (
                    self.settings_window_ref
                    if hasattr(self, "settings_window_ref")
                    and self.settings_window_ref.winfo_exists()
                    else self
                )
                messagebox.showinfo(
                    tr("Language Change"),
                    tr(
                        "Language has been changed to {new_language_display_name}. A restart is recommended for all changes to take effect."
                    ).format(new_language_display_name=new_language_display_name),
                    parent=parent_win,
                )
            else:
                self.append_progress(
                    tr("Language is already set to {new_language_display_name}.").format(
                        new_language_display_name=new_language_display_name
                    ),
                    "default",
                )
        else:
            self.append_progress(
                tr(
                    "Could not set language. '{new_language_display_name}' not recognized."
                ).format(new_language_display_name=new_language_display_name),
                "red",
            )

    def _save_general_settings(self) -> None:
        new_download_path = self.download_path_entry.get()
        if not os.path.isdir(new_download_path):
            try:
                os.makedirs(new_download_path, exist_ok=True)
                self.settings_manager.set("download_path", new_download_path)
            except OSError as e:
                messagebox.showerror(
                    tr("Save Error"),
                    tr(
                        "Invalid download path: {path}\nError: {error}\nPath not saved."
                    ).format(path=new_download_path, error=e),
                    parent=self.settings_window_ref,
                )
                self.append_progress(
                    tr(
                        "Failed to save download path: {new_download_path}. Error: {e}"
                    ).format(new_download_path=new_download_path, e=e),
                    "red",
                )
                self.download_path_entry.delete(0, END)
                self.download_path_entry.insert(
                    0, self.settings_manager.get("download_path")
                )
        else:
            self.settings_manager.set("download_path", new_download_path)
        self.settings_manager.set("github_api_token", self.github_token_entry.get())
        self.settings_manager.set(
            "use_github_api_token", self.use_github_token_var.get()
        )
        self.settings_manager.set(
            "app_update_check_on_startup", self.update_check_var.get()
        )
        self.settings_manager.save_settings()
        self.append_progress(tr("General settings saved successfully."), "green")
        self.display_downloaded_manifests()
        if (
            hasattr(self, "settings_window_ref")
            and self.settings_window_ref.winfo_exists()
        ):
            messagebox.showinfo(
                tr("Settings Saved"),
                tr("General settings have been saved."),
                parent=self.settings_window_ref,
            )

    def run_update_check(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.async_check_for_updates())
        finally:
            loop.close()

    async def async_check_for_updates(self) -> None:
        self.append_progress(tr("Checking for SDO updates..."), "default")
        request_headers = (
            self._get_github_headers() if self._get_github_headers() else {}
        )
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.GITHUB_RELEASES_API,
                    headers=request_headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
            latest_version_tag_raw = data.get("tag_name", "v0.0.0")
            latest_version_tag = re.sub(r"[^0-9.]", "", latest_version_tag_raw).strip(
                "."
            )
            release_url = data.get(
                "html_url", "https://github.com/fairy-root/steam-depot-online/releases"
            )
            try:
                current_version_parts = list(map(int, self.APP_VERSION.split(".")))
                latest_version_parts = list(map(int, latest_version_tag.split(".")))
                if latest_version_parts > current_version_parts:
                    update_message = tr(
                        "A new version of SDO ({latest_version}) is available! Your current version is {current_version}.\n\nDownload from: {release_url}"
                    ).format(
                        latest_version=latest_version_tag,
                        current_version=self.APP_VERSION,
                        release_url=release_url,
                    )
                    self.append_progress(update_message, "green")
                    parent_win = (
                        self.settings_window_ref
                        if hasattr(self, "settings_window_ref")
                        and self.settings_window_ref.winfo_exists()
                        else self
                    )
                    messagebox.showinfo(
                        tr("Update Available!"), update_message, parent=parent_win
                    )
                else:
                    self.append_progress(
                        tr(
                            "Update check completed. You are using the latest version ({current_version})."
                        ).format(current_version=self.APP_VERSION),
                        "default",
                    )
            except ValueError:
                self.append_progress(
                    tr(
                        "Could not compare versions. Current: {current_version}, Latest fetched: {latest_version_tag_raw}."
                    ).format(
                        current_version=self.APP_VERSION,
                        latest_version_tag_raw=latest_version_tag_raw,
                    ),
                    "yellow",
                )
        except aiohttp.ClientResponseError as e_http:
            self.append_progress(
                tr(
                    "Failed to check for updates (HTTP Error {status}): {error_message}"
                ).format(status=e_http.status, error_message=e_http.message),
                "red",
            )
        except (aiohttp.ClientError, asyncio.TimeoutError) as e_net:
            self.append_progress(
                tr("Network error while checking for updates: {error}").format(
                    error=self.stack_Error(e_net)
                ),
                "red",
            )
        except json.JSONDecodeError:
            self.append_progress(
                tr("Failed to decode update information from GitHub."), "red"
            )
        except Exception as e_other:
            self.append_progress(
                tr(
                    "An unexpected error occurred while checking for updates: {error}"
                ).format(error=self.stack_Error(e_other)),
                "red",
            )

    def _export_repositories(self) -> None:
        parent_window = (
            self.settings_window_ref
            if (
                hasattr(self, "settings_window_ref")
                and self.settings_window_ref
                and self.settings_window_ref.winfo_exists()
            )
            else self
        )
        filepath = filedialog.asksaveasfilename(
            parent=parent_window,
            defaultextension=".json",
            filetypes=[(tr("JSON files"), "*.json")],
            title=tr("Select destination to export repositories.json"),
            initialfile="repositories_export.json",
        )
        if filepath:
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(self.repos, f, indent=4)
                self.append_progress(
                    tr("Repositories exported successfully to: {filepath}").format(
                        filepath=filepath
                    ),
                    "green",
                )
                messagebox.showinfo(
                    tr("Export Successful"),
                    tr("Repositories exported to:\n{filepath}").format(
                        filepath=filepath
                    ),
                    parent=parent_window,
                )
            except Exception as e:
                messagebox.showerror(
                    tr("Export Error"),
                    tr("Failed to export repositories: {e}").format(e=e),
                    parent=parent_window,
                )
                self.append_progress(
                    tr("Failed to export repositories to {filepath}: {e}").format(
                        filepath=filepath, e=e
                    ),
                    "red",
                )

    def _import_repositories(self) -> None:
        parent_window = (
            self.settings_window_ref
            if (
                hasattr(self, "settings_window_ref")
                and self.settings_window_ref
                and self.settings_window_ref.winfo_exists()
            )
            else self
        )
        filepath = filedialog.askopenfilename(
            parent=parent_window,
            defaultextension=".json",
            filetypes=[(tr("JSON files"), "*.json")],
            title=tr("Select repositories.json file to import"),
        )
        if filepath:
            try:
                imported_repos = self.load_repositories(filepath)
                if not imported_repos and not os.path.exists(filepath):
                    messagebox.showerror(
                        tr("Import Error"),
                        tr("File not found or empty: {filepath}").format(
                            filepath=filepath
                        ),
                        parent=parent_window,
                    )
                    return
                if not imported_repos and os.path.exists(filepath):
                    messagebox.showwarning(
                        tr("Import Warning"),
                        tr(
                            "File {filepath} is empty or does not contain valid repository data."
                        ).format(filepath=filepath),
                        parent=parent_window,
                    )
                newly_added_count, skipped_duplicates_count = 0, 0
                for repo_name, repo_type in imported_repos.items():
                    if repo_name not in self.repos:
                        self.repos[repo_name], self.selected_repos[repo_name] = (
                            repo_type,
                            (repo_type == "Branch"),
                        )
                        newly_added_count += 1
                    else:
                        skipped_duplicates_count += 1
                if newly_added_count > 0:
                    self.save_repositories()
                    self.refresh_repo_checkboxes()
                    self.append_progress(
                        tr(
                            "Successfully imported {newly_added_count} new repositories from: {filepath}."
                        ).format(newly_added_count=newly_added_count, filepath=filepath)
                        + (
                            tr(" Skipped {skipped_duplicates_count} duplicates.").format(
                                skipped_duplicates_count=skipped_duplicates_count
                            )
                            if skipped_duplicates_count > 0
                            else ""
                        ),
                        "green",
                    )
                    messagebox.showinfo(
                        tr("Import Successful"),
                        tr("{newly_added_count} new repositories imported. ").format(
                            newly_added_count=newly_added_count
                        )
                        + (
                            tr(
                                "{skipped_duplicates_count} duplicates were skipped."
                            ).format(skipped_duplicates_count=skipped_duplicates_count)
                            if skipped_duplicates_count > 0
                            else ""
                        )
                        + tr("\nPlease review the repository list."),
                        parent=parent_window,
                    )
                elif skipped_duplicates_count > 0 and newly_added_count == 0:
                    self.append_progress(
                        tr(
                            "Import complete. No new repositories were added from {filepath} as they already exist (checked by name)."
                        ).format(filepath=filepath),
                        "default",
                    )
                    messagebox.showinfo(
                        tr("Import Information"),
                        tr(
                            "No new repositories were added. All repositories in the file already exist in your list."
                        ),
                        parent=parent_window,
                    )
                else:
                    self.append_progress(
                        tr(
                            "Import from {filepath} resulted in no changes to the repository list."
                        ).format(filepath=filepath),
                        "default",
                    )
            except Exception as e:
                messagebox.showerror(
                    tr("Import Error"),
                    tr("Failed to import repositories from {filepath}: {e}").format(
                        filepath=filepath, e=e
                    ),
                    parent=parent_window,
                )
                self.append_progress(
                    tr("Failed to import repositories from {filepath}: {e}").format(
                        filepath=filepath, e=e
                    ),
                    "red",
                )


# --- Main execution ---
if __name__ == "__main__":
    app = ManifestDownloader()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
