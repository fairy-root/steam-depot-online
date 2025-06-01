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

# --- CustomTkinter Global Settings (default, can be overridden by settings) ---
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# --- Global Localization Manager Placeholder ---
_LOC_MANAGER: Optional["LocalizationManager"] = None


def _(text: str) -> str:
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
        """Loads settings from the JSON config file."""

        self._settings = {
            "window_geometry": "1320x750",
            "appearance_mode": "dark",
            "color_theme": "blue",
            "download_path": os.path.join(os.getcwd(), "Games"),
            "strict_validation": True,
            "selected_repos": {},
            "app_update_check_on_startup": True,
            "language": "en",
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
        """Saves current settings to the JSON config file."""
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=4)
        except IOError:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        """Gets a setting value."""
        return self._settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Sets a setting value."""
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
        """
        Loads all available translation files.
        Expects JSON files named after language codes (e.g., 'en.json', 'fr.json')
        to be present in the 'lang' directory.
        If no files are found, it defaults to using the keys as strings.
        """
        if not os.path.exists(self.lang_dir):
            os.makedirs(self.lang_dir, exist_ok=True)
            self.app.after(
                100,
                partial(
                    self.app.append_progress,
                    _(
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
                            _("Error loading language file {filename}: {e}").format(
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
                    _(
                        "Warning: No translation files found in '{lang_dir}' directory. Using default English keys."
                    ).format(lang_dir=self.lang_dir),
                    "yellow",
                ),
            )

            if "en" not in self.translations:
                self.translations["en"] = {}

    def get_string(self, key: str) -> str:
        """Retrieves a translated string."""
        lang_translations = self.translations.get(self.current_language, {})
        return lang_translations.get(key, key)

    def set_language(self, lang_code: str) -> None:
        """Sets the current language and updates the UI."""
        if lang_code not in self.translations:
            self.app.append_progress(
                _("Language '{lang_code}' not found.").format(lang_code=lang_code),
                "red",
            )
            return

        self.current_language = lang_code
        self.app.settings_manager.set("language", lang_code)
        self.app.settings_manager.save_settings()

    def get_available_languages(self) -> Dict[str, str]:
        """Returns a dict of available language codes to their display names."""

        display_names = {
            "en": "English",
            "fr": "Français",
        }
        return {
            code: display_names.get(code, code)
            for code in sorted(self.translations.keys())
        }


# --- Main Application Class ---
class ManifestDownloader(ctk.CTk):
    """
    Main application class for Steam Depot Online (SDO).
    Handles UI setup, game searching, manifest downloading, and processing.
    """

    APP_VERSION = "2.0.0"
    GITHUB_RELEASES_API = (
        "https://api.github.com/repos/fairy-root/steam-depot-online/releases/latest"
    )

    def __init__(self) -> None:
        super().__init__()

        self.settings_manager = SettingsManager()
        global _LOC_MANAGER
        self.localization_manager = LocalizationManager(self)
        _LOC_MANAGER = self.localization_manager
        self.localization_manager.set_language(self.settings_manager.get("language"))

        self.title(_("Steam Depot Online (SDO)"))
        self.geometry(self.settings_manager.get("window_geometry"))
        self.minsize(1080, 590)
        self.resizable(True, True)

        ctk.set_appearance_mode(self.settings_manager.get("appearance_mode"))
        ctk.set_default_color_theme(self.settings_manager.get("color_theme"))

        if not PIL_AVAILABLE:
            messagebox.showwarning(
                _("Missing Library"),
                _(
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
        self.loop: Optional[asyncio.AbstractEventLoop] = None

        self.steam_app_list: List[Dict[str, Any]] = []
        self.app_list_loaded_event = threading.Event()
        self.initial_load_thread: Optional[threading.Thread] = None

        self.image_references: List[ctk.CTkImage] = []

        self._dynamic_content_start_index: str = "1.0"
        self.progress_text: Optional[Text] = None

        self.setup_ui()
        self._refresh_ui_texts()
        self._start_initial_app_list_load()
        self._bind_shortcuts()

        if self.settings_manager.get("app_update_check_on_startup"):
            threading.Thread(target=self.run_update_check, daemon=True).start()

    def _start_initial_app_list_load(self) -> None:
        """Starts the asynchronous loading of the Steam app list."""
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
                    "https://api.steampowered.com/ISteamApps/GetAppList/v2/",
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        self.steam_app_list = data.get("applist", {}).get("apps", [])
                        self.app_list_loaded_event.set()
                    else:
                        self.append_progress(
                            _(
                                "Initialization: Failed to load Steam app list (Status: {response_status}). Search by name may not work. You can still search by AppID."
                            ).format(response_status=response.status),
                            "red",
                        )

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            self.append_progress(
                _(
                    "Initialization: Error fetching Steam app list: {error}. Search by name may not work."
                ).format(error=self.stack_Error(e)),
                "red",
            )
        except json.JSONDecodeError:
            self.append_progress(
                _(
                    "Initialization: Failed to decode Steam app list response. Search by name may not work."
                ),
                "red",
            )
        except Exception as e:
            self.append_progress(
                _(
                    "Initialization: Unexpected error loading Steam app list: {error}."
                ).format(error=self.stack_Error(e)),
                "red",
            )

        self.after(0, lambda: self.search_button.configure(state="normal"))
        self.after(0, self._update_dynamic_content_start_index)

    def _update_dynamic_content_start_index(self) -> None:
        """Stores the index after initial messages for selective clearing."""
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
                    _("Load Error"),
                    _("Failed to load repositories.json. Using empty list."),
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
                _("Save Error"), _("Failed to save repositories.json.")
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
            text=_("Encrypted Repositories:"),
            text_color="cyan",
            font=("Helvetica", 12.6),
        )
        self.encrypted_label.pack(padx=9, pady=(9, 4.5), side="left")
        self.select_all_enc_button = ctk.CTkButton(
            encrypted_label_frame,
            text=_("Select All"),
            width=72,
            command=lambda: self.toggle_all_repos("encrypted"),
        )
        self.select_all_enc_button.pack(padx=18, pady=(9, 4.5), side="left")
        Tooltip(
            self.select_all_enc_button,
            _("Toggle selection for all Encrypted repositories."),
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
            text=_("Decrypted Repositories:"),
            text_color="cyan",
            font=("Helvetica", 12.6),
        )
        self.decrypted_label.pack(padx=9, pady=(9, 4.5), side="left")
        self.select_all_dec_button = ctk.CTkButton(
            decrypted_label_frame,
            text=_("Select All"),
            width=72,
            command=lambda: self.toggle_all_repos("decrypted"),
        )
        self.select_all_dec_button.pack(padx=18, pady=(9, 4.5), side="left")
        Tooltip(
            self.select_all_dec_button,
            _("Toggle selection for all Decrypted repositories."),
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
            text=_("Branch Repositories:"),
            text_color="cyan",
            font=("Helvetica", 12.6),
        )
        self.branch_label.pack(padx=9, pady=(9, 4.5), side="left")
        self.select_all_branch_button = ctk.CTkButton(
            branch_label_frame,
            text=_("Select All"),
            width=72,
            command=lambda: self.toggle_all_repos("branch"),
        )
        self.select_all_branch_button.pack(padx=28, pady=(9, 4.5), side="left")
        Tooltip(
            self.select_all_branch_button,
            _("Toggle selection for all Branch repositories."),
        )
        self.branch_scroll = ctk.CTkScrollableFrame(branch_frame, width=240, height=135)
        self.branch_scroll.pack(padx=9, pady=4.5, fill="both", expand=True)

        self.refresh_repo_checkboxes()

        self.add_repo_button = ctk.CTkButton(
            repo_frame, text=_("Add Repo"), width=90, command=self.open_add_repo_window
        )
        self.add_repo_button.pack(padx=9, pady=4.5, side="right")
        Tooltip(self.add_repo_button, _("Add a new GitHub repository to the list."))

        self.delete_repo_button = ctk.CTkButton(
            repo_frame, text=_("Delete Repo"), width=90, command=self.delete_repo
        )
        self.delete_repo_button.pack(padx=9, pady=4.5, side="right")
        Tooltip(
            self.delete_repo_button, _("Delete selected repositories from the list.")
        )

        self.settings_button = ctk.CTkButton(
            repo_frame, text=_("Settings"), width=90, command=self.open_settings_window
        )
        self.settings_button.pack(padx=9, pady=4.5, side="right")
        Tooltip(
            self.settings_button,
            _("Open application settings, including info, themes, and more."),
        )

        self.output_folder_button = ctk.CTkButton(
            repo_frame,
            text=_("Output Folder"),
            width=90,
            command=lambda: self.open_path_in_explorer(
                self.settings_manager.get("download_path")
            ),
        )
        self.output_folder_button.pack(padx=9, pady=4.5, side="right")
        Tooltip(
            self.output_folder_button,
            _("Open the default download output folder where game zips are saved."),
        )

        self.strict_validation_var = ctk.BooleanVar(
            value=self.settings_manager.get("strict_validation")
        )
        self.strict_validation_checkbox = ctk.CTkCheckBox(
            repo_frame,
            text=_("Strict Validation (Require Key.vdf / Non Branch Repo)"),
            text_color="orange",
            variable=self.strict_validation_var,
            font=("Helvetica", 12.6),
            command=self.save_strict_validation_setting,
        )
        self.strict_validation_checkbox.pack(padx=9, pady=4.5, side="left", anchor="w")
        Tooltip(
            self.strict_validation_checkbox,
            _(
                "When checked, for non-Branch repos, only downloads manifest files and attempts to extract keys if key.vdf/config.vdf is found. Key files are excluded from final zip. When unchecked, all files are downloaded, and key files are included."
            ),
        )

        input_frame = ctk.CTkFrame(left_frame, corner_radius=9)
        input_frame.pack(padx=0, pady=9, fill="x", expand=False)
        self.game_input_label = ctk.CTkLabel(
            input_frame,
            text=_("Enter Game Name or AppID:"),
            text_color="cyan",
            font=("Helvetica", 14.4),
        )
        self.game_input_label.pack(padx=9, pady=4.5, anchor="w")
        self.game_input = ctk.CTkEntry(
            input_frame, placeholder_text=_("e.g. 123456 or Game Name"), width=270
        )
        self.game_input.pack(padx=9, pady=4.5, side="left", expand=True, fill="x")
        Tooltip(
            self.game_input,
            _(
                "Enter a game name (e.g., 'Portal 2') or AppID (e.g., '620'). For batch download, enter multiple AppIDs separated by commas or newlines."
            ),
        )

        self.paste_button = ctk.CTkButton(
            input_frame, text=_("Paste"), width=90, command=self.paste_from_clipboard
        )
        self.paste_button.pack(padx=9, pady=4.5, side="left")
        Tooltip(self.paste_button, _("Paste text from clipboard into the input field."))

        self.search_button = ctk.CTkButton(
            input_frame,
            text=_("Search"),
            width=90,
            command=self.search_game,
            state="disabled",
        )
        self.search_button.pack(padx=9, pady=4.5, side="left")
        Tooltip(
            self.search_button,
            _("Search for games matching the entered name or AppID."),
        )

        self.download_button = ctk.CTkButton(
            input_frame,
            text=_("Download"),
            width=90,
            command=self.download_manifest,
            state="disabled",
        )
        self.download_button.pack(padx=9, pady=4.5, side="left")
        Tooltip(
            self.download_button,
            _("Download manifests/data for the selected game or all entered AppIDs."),
        )

        download_type_frame = ctk.CTkFrame(left_frame, corner_radius=9)
        download_type_frame.pack(padx=0, pady=(0, 9), fill="x", expand=False)
        self.download_type_label = ctk.CTkLabel(
            download_type_frame,
            text=_("Select appid(s) to download:"),
            font=("Helvetica", 12.6),
        )
        self.download_type_label.pack(padx=9, pady=4.5, anchor="w")

        self.download_mode_var = ctk.StringVar(value="selected_game")
        self.radio_download_selected = ctk.CTkRadioButton(
            download_type_frame,
            text=_("Selected game in search results"),
            variable=self.download_mode_var,
            value="selected_game",
        )
        self.radio_download_selected.pack(padx=9, pady=2, anchor="w")
        Tooltip(
            self.radio_download_selected,
            _("Download only the game selected from the search results (if any)."),
        )

        self.radio_download_all_input = ctk.CTkRadioButton(
            download_type_frame,
            text=_("All AppIDs in input field"),
            variable=self.download_mode_var,
            value="all_input_appids",
        )
        self.radio_download_all_input.pack(padx=9, pady=2, anchor="w")
        Tooltip(
            self.radio_download_all_input,
            _(
                "Download all AppIDs found in the 'Enter Game Name or AppID' field, ignoring search results. Useful for batch downloads.\nNote: If multiple AppIDs are entered, all will be downloaded sequentially, skipping individual game details."
            ),
        )

        self.results_frame = ctk.CTkFrame(left_frame, corner_radius=9)
        self.results_frame.pack(padx=0, pady=9, fill="both", expand=True)
        self.results_label = ctk.CTkLabel(
            self.results_frame,
            text=_("Search Results:"),
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

        self.progress_tab_title = _("Progress")
        self.downloaded_tab_title = _("Downloaded Manifests")

        self.progress_tab = self.main_tabview.add(self.progress_tab_title)
        self.downloaded_tab = self.main_tabview.add(self.downloaded_tab_title)

        self.main_tabview.set(self.progress_tab_title)

        progress_frame = ctk.CTkFrame(
            self.main_tabview.tab(self.progress_tab_title), corner_radius=9
        )
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
        """Sets up the UI for the Downloaded Manifests tab."""

        tab_frame = self.main_tabview.tab(self.downloaded_tab_title)
        for widget in tab_frame.winfo_children():
            widget.destroy()

        frame = ctk.CTkFrame(tab_frame, corner_radius=9)
        frame.pack(padx=0, pady=9, fill="both", expand=True)

        control_frame = ctk.CTkFrame(frame)
        control_frame.pack(fill="x", padx=9, pady=9)

        self.downloaded_manifests_label = ctk.CTkLabel(
            control_frame, text=_("Downloaded Manifests"), font=("Helvetica", 14.4)
        )
        self.downloaded_manifests_label.pack(side="left", padx=5, pady=5)
        self.refresh_list_button = ctk.CTkButton(
            control_frame,
            text=_("Refresh List"),
            command=self.display_downloaded_manifests,
        )
        self.refresh_list_button.pack(side="right", padx=5, pady=5)
        Tooltip(
            self.refresh_list_button,
            _("Scan the download folder for zipped outcomes and update the list."),
        )

        self.downloaded_manifests_container = ctk.CTkScrollableFrame(
            frame, corner_radius=9
        )
        self.downloaded_manifests_container.pack(
            padx=9, pady=9, fill="both", expand=True
        )

        self.display_downloaded_manifests()

    def display_downloaded_manifests(self) -> None:
        """Scans the download directory and displays found zip files."""
        for widget in self.downloaded_manifests_container.winfo_children():
            widget.destroy()

        download_path = self.settings_manager.get("download_path")
        if not os.path.isdir(download_path):
            self.append_progress(
                _(f"Download path '{download_path}' does not exist."), "red"
            )
            ctk.CTkLabel(
                self.downloaded_manifests_container,
                text=_("Download folder not found or configured incorrectly."),
                text_color="red",
            ).pack(pady=10)
            return

        self.append_progress(_("Scanning downloaded manifests..."), "default")
        self.update_idletasks()

        found_zips = []
        try:
            for item in os.listdir(download_path):
                if item.endswith(".zip"):
                    full_path = os.path.join(download_path, item)
                    found_zips.append({"filename": item, "filepath": full_path})
        except Exception as e:
            self.append_progress(
                _("Error scanning downloaded manifests: {e}").format(
                    e=self.stack_Error(e)
                ),
                "red",
            )
            ctk.CTkLabel(
                self.downloaded_manifests_container,
                text=_(f"Error scanning folder: {e}"),
                text_color="red",
            ).pack(pady=10)
            return

        if not found_zips:
            ctk.CTkLabel(
                self.downloaded_manifests_container,
                text=_("No downloaded manifests found."),
                text_color="yellow",
            ).pack(pady=10)
            self.append_progress(_("No downloaded manifests found."), "yellow")
            return

        found_zips.sort(key=lambda x: x["filename"].lower())

        self.append_progress(
            _("Found {count} downloaded manifests.").format(count=len(found_zips)),
            "green",
        )

        header_frame = ctk.CTkFrame(
            self.downloaded_manifests_container, fg_color="transparent"
        )
        header_frame.pack(fill="x", padx=5, pady=(5, 0))
        ctk.CTkLabel(
            header_frame,
            text=_("Game Name"),
            font=("Helvetica", 11, "bold"),
            width=200,
            anchor="w",
        ).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            header_frame,
            text=_("AppID"),
            font=("Helvetica", 11, "bold"),
            width=80,
            anchor="w",
        ).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            header_frame,
            text=_("Action"),
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
                text=_("ZIP"),
                width=80,
                command=partial(self.open_path_in_explorer, filepath),
                font=("Helvetica", 10),
            )
            open_file_button.pack(side="left")
            Tooltip(open_file_button, _(f"Open the zip file '{filename}'"))

    def open_path_in_explorer(self, path_to_open: str) -> None:
        """Opens the given file or directory in the OS explorer."""
        if not os.path.exists(path_to_open):
            messagebox.showerror(
                _("Error"),
                _("File not found: {filepath}").format(filepath=path_to_open),
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
            messagebox.showerror(_("Error"), _("Could not open path: {e}").format(e=e))
            self.append_progress(
                _("Error opening path {path_to_open}: {error}").format(
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
        """Appends a message directly to the progress text on the current (main) thread."""
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
        """
        Public method to append a message to the progress text.
        Always schedules the actual append operation on the main Tkinter thread.
        Safe to call from any background thread.
        """
        self.after(0, partial(self._append_progress_direct, message, color, tags))

    def _clear_and_reinitialize_progress_area(self) -> None:
        """
        Clears the entire progress text area, re-inserts initial messages,
        and resets the dynamic content start index.
        This method MUST be called synchronously on the main Tkinter thread.
        """
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
        """Binds keyboard shortcuts to actions."""
        self.bind("<Control-v>", lambda e: self.paste_from_clipboard())
        self.bind("<Control-V>", lambda e: self.paste_from_clipboard())
        self.game_input.bind("<Return>", lambda e: self.search_game())

    def paste_from_clipboard(self) -> None:
        try:
            clipboard_text: str = self.clipboard_get()
            self.game_input.delete(0, END)
            self.game_input.insert(0, clipboard_text)
            self.append_progress(_("Pasted text from clipboard."), "green")
        except Exception as e:
            messagebox.showerror(
                _("Paste Error"), _("Failed to paste from clipboard: {e}").format(e=e)
            )

    def save_strict_validation_setting(self) -> None:
        """Saves the state of the strict validation checkbox to settings."""
        self.settings_manager.set("strict_validation", self.strict_validation_var.get())
        self.settings_manager.save_settings()
        self.append_progress(_("Strict validation setting saved."), "default")

    def search_game(self) -> None:
        user_input: str = self.game_input.get().strip()
        if not user_input:
            messagebox.showwarning(
                _("Input Error"), _("Please enter a game name or AppID.")
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
                _(
                    "Multiple AppIDs detected. Automatically setting download mode to 'All AppIDs in input field'."
                ),
                "yellow",
            )
            self.download_button.configure(state="normal")
            return

        if self.search_thread and self.search_thread.is_alive():
            self.cancel_search = True
            self.append_progress(_("Cancelling previous search..."), "yellow")

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
                                    _(
                                        "No game found or API error for AppID {appid_to_search}."
                                    ).format(appid_to_search=appid_to_search),
                                    "red",
                                )
                        else:
                            self.append_progress(
                                _(
                                    "Failed to fetch details for AppID {appid_to_search} (Status: {response_status})."
                                ).format(
                                    appid_to_search=appid_to_search,
                                    response_status=response.status,
                                ),
                                "red",
                            )
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                self.append_progress(
                    _("Error fetching AppID {appid_to_search}: {error}").format(
                        appid_to_search=appid_to_search, error=self.stack_Error(e)
                    ),
                    "red",
                )
            except json.JSONDecodeError:
                self.append_progress(
                    _("Failed to decode JSON for AppID {appid_to_search}.").format(
                        appid_to_search=appid_to_search
                    ),
                    "red",
                )
        else:
            if not self.app_list_loaded_event.is_set():
                self.append_progress(
                    _("Steam app list is not yet loaded. Please wait or try AppID."),
                    "yellow",
                )
                return

            search_term_lower = user_input.lower()
            for app_info in self.steam_app_list:
                if self.cancel_search:
                    self.append_progress(_("\nName search cancelled."), "yellow")
                    return
                if search_term_lower in app_info.get("name", "").lower():
                    games_found.append(
                        {"appid": str(app_info["appid"]), "name": app_info["name"]}
                    )
                    if len(games_found) >= max_results:
                        self.append_progress(
                            _("Max results ({max_results}). Refine search.").format(
                                max_results=max_results
                            ),
                            "yellow",
                        )
                        break

        if self.cancel_search:
            self.append_progress(_("\nSearch cancelled."), "yellow")
            return
        if not games_found:
            self.append_progress(
                _("\nNo matching games found. Please try another name or AppID."), "red"
            )
            return

        self.appid_to_game.clear()
        capsule_tasks = []
        game_data_for_ui = []

        for idx, game in enumerate(games_found, 1):
            if self.cancel_search:
                self.append_progress(_("\nSearch cancelled."), "yellow")
                return
            appid, game_name = str(game.get("appid", "Unknown")), game.get(
                "name", _("Unknown Game")
            )
            self.appid_to_game[appid] = game_name

            capsule_url = f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/capsule_231x87.jpg"
            if PIL_AVAILABLE:
                capsule_tasks.append(self._download_image_async(capsule_url))
            else:
                capsule_tasks.append(asyncio.sleep(0, result=None))

            game_data_for_ui.append((idx, appid, game_name))

        capsule_results = await asyncio.gather(*capsule_tasks)

        for i, (idx, appid, game_name) in enumerate(game_data_for_ui):
            image_data = capsule_results[i]
            self.after(
                0, partial(self.create_radio_button, idx, appid, game_name, image_data)
            )

        self.append_progress(
            _("\nFound {len_games_found} game(s). Select one.").format(
                len_games_found=len(games_found)
            ),
            "cyan",
        )

    def create_radio_button(
        self, idx: int, appid: str, game_name: str, capsule_image_data: Optional[bytes]
    ) -> None:
        display_text: str = f"{game_name} (AppID: {appid})"
        rb_frame = ctk.CTkFrame(self.results_container, fg_color="transparent")
        rb_frame.pack(anchor="w", padx=10, pady=2, fill="x")

        image_width, image_height = 80, 30
        capsule_ctk_image = None
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
                    _("Error creating capsule image for {appid}: {error}").format(
                        appid=appid, error=self.stack_Error(e)
                    ),
                    "red",
                )
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

                self.image_references = []
                self.progress_text.configure(state="disabled")

            self.download_button.configure(state="normal")
            self.download_mode_var.set("selected_game")

            threading.Thread(
                target=self.run_display_game_details,
                args=(self.selected_appid, self.selected_game_name),
                daemon=True,
            ).start()
        else:
            self.append_progress(_("Selected game not found in mapping."), "red")
            self.download_button.configure(state="disabled")

    def run_display_game_details(self, appid: str, game_name: str) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.async_display_game_details(appid, game_name))
        finally:
            loop.close()

    async def _download_image_async(self, url: str) -> Optional[bytes]:
        """Helper to download an image by creating its own dedicated session."""
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
                            _(
                                "Failed to download image (Status {response_status}): {url}"
                            ).format(response_status=response.status, url=url),
                            "yellow",
                            ("game_detail_section",),
                        )
                        return None
        except Exception as e:
            self.append_progress(
                _("Error downloading image {url}: {error}").format(
                    url=url, error=self.stack_Error(e)
                ),
                "red",
                ("game_detail_section",),
            )
            return None

    def _process_and_insert_image_ui(
        self, image_bytes: Optional[bytes], max_width: int, max_height: int
    ) -> None:
        """Processes image bytes and inserts into Text widget on the UI thread."""
        if not image_bytes or not PIL_AVAILABLE or not ImageTk or not Image:
            return
        if self.progress_text is None:
            return

        try:
            pil_image = Image.open(BytesIO(image_bytes))

            width, height = pil_image.size
            if width > max_width or height > max_height:
                if width / max_width > height / max_height:
                    new_width = max_width
                    new_height = int(new_width * height / width)
                else:
                    new_height = max_height
                    new_width = int(new_height * width / height)
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
                _("Error processing image for UI: {error}").format(
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
                if not isinstance(results[result_idx], Exception):
                    logo_data = results[result_idx]
                result_idx += 1

                if not isinstance(results[result_idx], Exception):
                    header_data = results[result_idx]
                result_idx += 1

            appdetails_response = results[result_idx]
            if (
                not isinstance(appdetails_response, Exception)
                and appdetails_response.status == 200
            ):
                try:
                    api_json = await appdetails_response.json()
                    if api_json and api_json.get(appid, {}).get("success"):
                        game_api_data = api_json[appid]["data"]
                    else:
                        pass
                except json.JSONDecodeError:
                    self.append_progress(
                        _("Failed to decode JSON for AppID {appid} details.").format(
                            appid=appid
                        ),
                        "red",
                        ("game_detail_section",),
                    )
            elif isinstance(appdetails_response, Exception):
                self.append_progress(
                    _("Error fetching AppID {appid} details: {error}").format(
                        appid=appid, error=self.stack_Error(appdetails_response)
                    ),
                    "red",
                    ("game_detail_section",),
                )
            else:
                self.append_progress(
                    _(
                        "Failed to fetch AppID {appid} details (Status: {status})."
                    ).format(appid=appid, status=appdetails_response.status),
                    "red",
                    ("game_detail_section",),
                )

        self.append_progress(
            f"{game_name}",
            "game_title",
            ("game_detail_section",),
        )

        if PIL_AVAILABLE:
            header_max_width = (
                self.progress_text.winfo_width() - 12 if self.progress_text else 320
            )
            if header_max_width <= 50:
                header_max_width = 320

            if logo_data:
                self.after(
                    0, partial(self._process_and_insert_image_ui, logo_data, 330, 330)
                )
            if header_data:
                self.after(
                    0,
                    partial(
                        self._process_and_insert_image_ui,
                        header_data,
                        header_max_width,
                        600,
                    ),
                )

        description_parts = []
        if game_api_data:
            short_desc = game_api_data.get("short_description")
            if short_desc:
                description_parts.append(f"{short_desc}")

            genres_list = game_api_data.get("genres", [])
            if genres_list:
                genres = _("Genres: ") + ", ".join(
                    [g["description"] for g in genres_list]
                )
                description_parts.append(genres)

            release_date_info = game_api_data.get("release_date", {})
            if release_date_info.get("date"):
                description_parts.append(
                    _("Release Date: ") + f"{release_date_info['date']}"
                )

        if description_parts:

            self.after(
                100,
                lambda d=description_parts: self.append_progress(
                    "\n" + "\n\n".join(d),
                    "game_description",
                    ("game_detail_section",),
                ),
            )
        elif not game_api_data and not description_parts:
            self.after(
                100,
                lambda: self.append_progress(
                    _("No detailed text information found for this game."),
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
                _("Repository Selection"), _("Please select at least one repository.")
            )
            return

        appids_to_download: List[Tuple[str, str]] = []

        if self.download_mode_var.get() == "selected_game":
            if not self.selected_appid or not self.selected_game_name:
                messagebox.showwarning(
                    _("Selection Error"), _("Please select a game first.")
                )
                return
            appids_to_download.append((self.selected_appid, self.selected_game_name))
        else:
            user_input = self.game_input.get().strip()

            unique_appids_str = []
            seen_appids = set()
            for s in user_input.replace(",", "\n").splitlines():
                stripped_s = s.strip()
                if stripped_s.isdigit() and stripped_s not in seen_appids:
                    unique_appids_str.append(stripped_s)
                    seen_appids.add(stripped_s)

            if not unique_appids_str:
                messagebox.showwarning(
                    _("Input Error"),
                    _("Please enter AppIDs in the input field for batch download."),
                )
                return

            for appid_str in unique_appids_str:
                game_name = self.appid_to_game.get(appid_str)
                if not game_name and self.app_list_loaded_event.is_set():

                    found_app_info = next(
                        (
                            app
                            for app in self.steam_app_list
                            if str(app.get("appid")) == appid_str
                        ),
                        None,
                    )
                    if found_app_info:
                        game_name = found_app_info.get("name")

                appids_to_download.append(
                    (appid_str, game_name if game_name else f"AppID_{appid_str}")
                )

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
                    self.append_progress(_("Batch download cancelled."), "yellow")
                    break

                self.append_progress(
                    _(
                        "Downloading AppID: {current_appid} ({index}/{total_appids})"
                    ).format(
                        current_appid=appid, index=i + 1, total_appids=total_appids
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
                    self.append_progress(_("\nDownload cancelled."), "yellow")
                    break

                if source_was_branch:
                    if output_path_or_processing_dir and os.path.isfile(
                        output_path_or_processing_dir
                    ):
                        self.append_progress(
                            _(f"\nBranch repo download successful."), "green"
                        )
                        self.append_progress(
                            _(
                                f"Output saved directly to: {output_path_or_processing_dir}"
                            ),
                            "blue",
                        )
                    else:
                        self.append_progress(
                            _(
                                "\nBranch repo download completed, but the expected zip file was not found or path was invalid."
                            ),
                            "red",
                        )
                elif output_path_or_processing_dir and os.path.isdir(
                    output_path_or_processing_dir
                ):
                    processing_dir = output_path_or_processing_dir
                    lua_script: str = self.parse_vdf_to_lua(
                        collected_depots, appid, processing_dir
                    )
                    lua_file_path: str = os.path.join(processing_dir, f"{appid}.lua")
                    try:

                        download_loop.run_until_complete(
                            self._write_lua_file(lua_file_path, lua_script)
                        )
                        self.append_progress(
                            _(f"\nGenerated {game_name} unlock file: {lua_file_path}"),
                            "blue",
                        )
                    except Exception as e:
                        self.append_progress(
                            _(f"\nFailed to write Lua script: {self.stack_Error(e)}"),
                            "red",
                        )

                    final_zip_path = self.zip_outcome(processing_dir, selected_repos)

                    if not collected_depots and self.strict_validation_var.get():
                        self.append_progress(
                            _(
                                "\nWarning: Strict validation was on, but no decryption keys were found. LUA script is minimal."
                            ),
                            "yellow",
                        )
                    elif not collected_depots and not self.strict_validation_var.get():
                        self.append_progress(
                            _(
                                "\nNo decryption keys found (strict validation was off). Files downloaded if available. LUA script is minimal."
                            ),
                            "yellow",
                        )
                else:
                    if not self.cancel_search:
                        self.append_progress(
                            _(
                                "\nDownload process failed or was interrupted before any files could be saved or path was invalid."
                            ),
                            "red",
                        )
                    if output_path_or_processing_dir:
                        self.append_progress(
                            _(
                                "Returned path was: {output_path_or_processing_dir}"
                            ).format(
                                output_path_or_processing_dir=output_path_or_processing_dir
                            ),
                            "red",
                        )
            self.append_progress(_("Batch download finished."), "green")
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
        async with aiohttp.ClientSession() as session:
            for attempt in range(overall_attempts):
                for url in url_list:
                    if self.cancel_search:
                        self.print_colored_ui(
                            _("\nDownload cancelled by user for: {path}").format(
                                path=path
                            ),
                            "yellow",
                        )
                        return None
                    for _ in range(max_retries_per_url + 1):
                        try:
                            async with session.get(
                                url, ssl=False, timeout=aiohttp.ClientTimeout(total=20)
                            ) as r:
                                if r.status == 200:
                                    return await r.read()
                                if r.status == 404:
                                    break
                        except (aiohttp.ClientError, asyncio.TimeoutError):
                            pass
                        except KeyboardInterrupt:
                            self.print_colored_ui(
                                _("\nDownload interrupted by user for: {path}").format(
                                    path=path
                                ),
                                "yellow",
                            )
                            self.cancel_search = True
                            return None
                        if self.cancel_search:
                            return None
                        await asyncio.sleep(0.5)
                if self.cancel_search:
                    return None
                if attempt < overall_attempts - 1:
                    self.print_colored_ui(
                        _(
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
                _("\nMaximum attempts exceeded for: {path}").format(path=path), "red"
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
            content_bytes, should_download = None, True
            if os.path.exists(file_save_path):
                if path.lower().endswith(".manifest"):
                    should_download = False
                    self.print_colored_ui(
                        _("Manifest file {path} already exists. Using local.").format(
                            path=path
                        ),
                        "default",
                    )
                if path.lower().endswith((".vdf")):
                    try:
                        async with aiofiles.open(
                            file_save_path, "rb"
                        ) as f_existing_bytes:
                            content_bytes = await f_existing_bytes.read()
                            should_download = False
                            self.print_colored_ui(
                                _("Using local VDF file: {path}").format(path=path),
                                "default",
                            )
                    except Exception as e_read:
                        self.print_colored_ui(
                            _(
                                "Could not read existing local file {path}: {error}, attempting download."
                            ).format(path=path, error=self.stack_Error(e_read)),
                            "yellow",
                        )
                        content_bytes = None
                        should_download = True
            if should_download and not self.cancel_search:
                content_bytes = await self.get(sha, path, repo)
            if self.cancel_search:
                return collected_depots
            if content_bytes:
                if should_download:
                    async with aiofiles.open(file_save_path, "wb") as f_new:
                        await f_new.write(content_bytes)
                        self.print_colored_ui(
                            _("\nFile download/update successful: {path}").format(
                                path=path
                            ),
                            "green",
                        )
                if path.lower().endswith((".vdf")):
                    try:
                        depots_config = vdf.loads(
                            content_bytes.decode(encoding="utf-8", errors="ignore")
                        )
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
                                _(
                                    "Extracted {new_keys_count} new keys from {path}"
                                ).format(new_keys_count=new_keys_count, path=path),
                                "magenta",
                            )
                        elif not depots_data and os.path.basename(path.lower()) in [
                            "key.vdf",
                            "config.vdf",
                        ]:
                            self.print_colored_ui(
                                _("No 'depots' section or empty in {path}").format(
                                    path=path
                                ),
                                "yellow",
                            )
                    except Exception as e_vdf:
                        self.print_colored_ui(
                            _(
                                "\nFailed to parse VDF content for {path}: {error}"
                            ).format(path=path, error=self.stack_Error(e_vdf)),
                            "red",
                        )
            elif should_download and not os.path.exists(file_save_path):
                self.print_colored_ui(
                    _("\nFailed to download file: {path}").format(path=path), "red"
                )
        except KeyboardInterrupt:
            self.print_colored_ui(
                _("\nProcessing interrupted by user for: {path}").format(path=path),
                "yellow",
            )
            self.cancel_search = True
        except Exception as e:
            self.print_colored_ui(
                _("\nProcessing failed for {path}: {error}").format(
                    path=path, error=self.stack_Error(e)
                ),
                "red",
            )
        return collected_depots

    async def _fetch_branch_zip_content(
        self, repo_full_name: str, app_id: str
    ) -> Optional[bytes]:
        url = f"https://github.com/{repo_full_name}/archive/refs/heads/{app_id}.zip"
        self.print_colored_ui(
            _("Attempting to download branch zip: {url}").format(url=url), "default"
        )
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=600)
                ) as r:
                    if r.status == 200:
                        self.print_colored_ui(
                            _(
                                "Successfully started downloading branch zip for AppID {app_id} from {repo_full_name}."
                            ).format(app_id=app_id, repo_full_name=repo_full_name),
                            "green",
                        )
                        content = await r.read()
                        self.print_colored_ui(
                            _(
                                "Finished downloading branch zip for AppID {app_id}."
                            ).format(app_id=app_id),
                            "green",
                        )
                        return content
                    else:
                        self.print_colored_ui(
                            _(
                                "Failed to download branch zip (Status: {status}) from {url}"
                            ).format(status=r.status, url=url),
                            "red",
                        )
                        return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            self.print_colored_ui(
                _("Error downloading branch zip from {url}: {error}").format(
                    url=url, error=self.stack_Error(e)
                ),
                "red",
            )
            return None
        except Exception as e:
            self.print_colored_ui(
                _("Unexpected error fetching branch zip {url}: {error}").format(
                    url=url, error=self.stack_Error(e)
                ),
                "red",
            )
            return None

    async def _perform_download_operations(
        self, app_id_input: str, game_name: str, selected_repos: List[str]
    ) -> Tuple[List[Tuple[str, str]], Optional[str], bool]:
        app_id_list = [s for s in app_id_input.strip().split("-") if s.isdecimal()]
        if not app_id_list:
            self.print_colored_ui(
                _("\nInvalid AppID format: {app_id_input}").format(
                    app_id_input=app_id_input
                ),
                "red",
            )
            return [], None, False
        app_id = app_id_list[0]
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
                _(
                    "Error creating base output directory {output_base_dir}: {error}"
                ).format(output_base_dir=output_base_dir, error=self.stack_Error(e)),
                "red",
            )
            return [], None, False
        overall_collected_depots: List[Tuple[str, str]] = []
        for repo_full_name in selected_repos:
            if self.cancel_search:
                self.print_colored_ui(
                    _("\nDownload process cancelled by user."), "yellow"
                )
                return overall_collected_depots, None, False
            repo_type = self.repos.get(repo_full_name)
            if not repo_type:
                self.print_colored_ui(
                    _(
                        "Repository {repo_full_name} not found in known repos. Skipping."
                    ).format(repo_full_name=repo_full_name),
                    "yellow",
                )
                continue
            if repo_type == "Branch":
                self.print_colored_ui(
                    _(
                        "\nProcessing BRANCH repository: {repo_full_name} for AppID: {app_id}"
                    ).format(repo_full_name=repo_full_name, app_id=app_id),
                    "cyan",
                )
                final_branch_zip_path = os.path.join(
                    output_base_dir, f"{final_output_name_stem}.zip"
                )
                if os.path.exists(final_branch_zip_path):
                    self.print_colored_ui(
                        _(
                            "Branch ZIP already exists: {final_branch_zip_path}. Skipping download."
                        ).format(final_branch_zip_path=final_branch_zip_path),
                        "blue",
                    )
                    return [], final_branch_zip_path, True
                zip_content = await self._fetch_branch_zip_content(
                    repo_full_name, app_id
                )
                if self.cancel_search:
                    self.print_colored_ui(
                        _("\nDownload cancelled during branch zip fetch."), "yellow"
                    )
                    return [], None, False
                if zip_content:
                    try:
                        async with aiofiles.open(final_branch_zip_path, "wb") as f_zip:
                            await f_zip.write(zip_content)
                            self.print_colored_ui(
                                _(
                                    "Successfully saved branch download to {final_branch_zip_path}"
                                ).format(final_branch_zip_path=final_branch_zip_path),
                                "green",
                            )
                            return [], final_branch_zip_path, True
                    except Exception as e_save:
                        self.print_colored_ui(
                            _(
                                "Failed to save branch zip to {final_branch_zip_path}: {error}"
                            ).format(
                                final_branch_zip_path=final_branch_zip_path,
                                error=self.stack_Error(e_save),
                            ),
                            "red",
                        )
                else:
                    self.print_colored_ui(
                        _(
                            "Failed to download content for branch repo {repo_full_name}, AppID {app_id}. Trying next repo."
                        ).format(repo_full_name=repo_full_name, app_id=app_id),
                        "yellow",
                    )
                continue
            processing_dir_non_branch = os.path.join(
                output_base_dir, final_output_name_stem
            )
            try:
                os.makedirs(processing_dir_non_branch, exist_ok=True)
            except OSError as e_mkdir:
                self.print_colored_ui(
                    _(
                        "Error creating processing directory {processing_dir_non_branch}: {error}. Skipping repo."
                    ).format(
                        processing_dir_non_branch=processing_dir_non_branch,
                        error=self.stack_Error(e_mkdir),
                    ),
                    "red",
                )
                continue
            self.print_colored_ui(
                _(
                    "\nSearching NON-BRANCH repository: {repo_full_name} for AppID: {app_id} (Type: {repo_type})"
                ).format(
                    repo_full_name=repo_full_name, app_id=app_id, repo_type=repo_type
                ),
                "cyan",
            )
            api_url, repo_specific_collected_depots = (
                f"https://api.github.com/repos/{repo_full_name}/branches/{app_id}",
                [],
            )
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(
                        api_url, ssl=False, timeout=aiohttp.ClientTimeout(total=15)
                    ) as r_b:
                        if r_b.status != 200:
                            self.print_colored_ui(
                                _(
                                    "AppID {app_id} not found as a branch in {repo_full_name} (Status: {status}). Trying next repo."
                                ).format(
                                    app_id=app_id,
                                    repo_full_name=repo_full_name,
                                    status=r_b.status,
                                ),
                                "yellow",
                            )
                            continue
                        r_b_json = await r_b.json()
                        commit_data, sha, tree_url_base, date = (
                            r_b_json.get("commit", {}),
                            None,
                            None,
                            _("Unknown date"),
                        )
                        sha, tree_url_base = commit_data.get("sha"), commit_data.get(
                            "commit", {}
                        ).get("tree", {}).get("url")
                        date = (
                            commit_data.get("commit", {})
                            .get("author", {})
                            .get("date", _("Unknown date"))
                        )
                        if not sha or not tree_url_base:
                            self.print_colored_ui(
                                _(
                                    "Invalid branch data (missing SHA or tree URL) for {repo_full_name}/{app_id}. Trying next repo."
                                ).format(repo_full_name=repo_full_name, app_id=app_id),
                                "red",
                            )
                            continue
                        tree_url_recursive = f"{tree_url_base}?recursive=1"
                        async with session.get(
                            tree_url_recursive,
                            ssl=False,
                            timeout=aiohttp.ClientTimeout(total=30),
                        ) as r_t:
                            if r_t.status != 200:
                                self.print_colored_ui(
                                    _(
                                        "Failed to get tree data for {repo_full_name}/{app_id} (Status: {status}). Trying next repo."
                                    ).format(
                                        repo_full_name=repo_full_name,
                                        app_id=app_id,
                                        status=r_t.status,
                                    ),
                                    "red",
                                )
                                continue
                            r_t_json = await r_t.json()
                            if r_t_json.get("truncated"):
                                self.print_colored_ui(
                                    _(
                                        "Warning: File tree for {repo_full_name}/{app_id} is truncated by GitHub API. Some files may be missed."
                                    ).format(
                                        repo_full_name=repo_full_name, app_id=app_id
                                    ),
                                    "yellow",
                                )
                            tree_items = r_t_json.get("tree", [])
                            if not tree_items:
                                self.print_colored_ui(
                                    _(
                                        "No files found in tree for {repo_full_name}/{app_id}. Trying next repo."
                                    ).format(
                                        repo_full_name=repo_full_name, app_id=app_id
                                    ),
                                    "yellow",
                                )
                                continue
                            files_dl_proc_this_repo, key_file_found_proc = False, False
                            if self.strict_validation_var.get():
                                self.print_colored_ui(
                                    _(
                                        "STRICT MODE: Processing branch {app_id} in {repo_full_name}..."
                                    ).format(
                                        app_id=app_id, repo_full_name=repo_full_name
                                    ),
                                    "magenta",
                                )
                                for key_short_name in ["key.vdf", "config.vdf"]:
                                    if self.cancel_search:
                                        break
                                    actual_key_file_path = next(
                                        (
                                            item.get("path")
                                            for item in tree_items
                                            if item.get("type") == "blob"
                                            and os.path.basename(
                                                item.get("path", "").lower()
                                            )
                                            == key_short_name
                                        ),
                                        None,
                                    )
                                    if actual_key_file_path:
                                        self.print_colored_ui(
                                            _(
                                                "STRICT: Found key file '{key_short_name}' at: {actual_key_file_path}"
                                            ).format(
                                                key_short_name=key_short_name,
                                                actual_key_file_path=actual_key_file_path,
                                            ),
                                            "default",
                                        )
                                        depot_keys_vdf = await self.get_manifest(
                                            sha,
                                            actual_key_file_path,
                                            processing_dir_non_branch,
                                            repo_full_name,
                                        )
                                        if depot_keys_vdf:
                                            [
                                                repo_specific_collected_depots.append(
                                                    dk
                                                )
                                                for dk in depot_keys_vdf
                                                if dk
                                                not in repo_specific_collected_depots
                                            ]
                                            (
                                                files_dl_proc_this_repo,
                                                key_file_found_proc,
                                            ) = (True, True)
                                        if (
                                            key_short_name == "key.vdf"
                                            and key_file_found_proc
                                        ):
                                            self.print_colored_ui(
                                                _(
                                                    "STRICT: Keys obtained from primary 'key.vdf'."
                                                ),
                                                "green",
                                            )
                                            break
                                if self.cancel_search:
                                    break
                                if not key_file_found_proc:
                                    self.print_colored_ui(
                                        _(
                                            "STRICT: No Key.vdf or Config.vdf found or processed successfully in {repo_full_name}/{app_id}. This repo may not yield usable data in strict mode."
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
                                        files_dl_proc_this_repo = (
                                            True
                                            if os.path.exists(
                                                os.path.join(
                                                    processing_dir_non_branch, item_path
                                                )
                                            )
                                            else files_dl_proc_this_repo
                                        )
                            else:
                                self.print_colored_ui(
                                    _(
                                        "NON-STRICT MODE: Downloading all files from branch {app_id} in {repo_full_name}..."
                                    ).format(
                                        app_id=app_id, repo_full_name=repo_full_name
                                    ),
                                    "magenta",
                                )
                                for item in tree_items:
                                    if self.cancel_search:
                                        break
                                    item_path = item.get("path", "")
                                    if item.get("type") == "blob":
                                        keys_file = await self.get_manifest(
                                            sha,
                                            item_path,
                                            processing_dir_non_branch,
                                            repo_full_name,
                                        )
                                        if keys_file:
                                            [
                                                repo_specific_collected_depots.append(
                                                    dk
                                                )
                                                for dk in keys_file
                                                if dk
                                                not in repo_specific_collected_depots
                                            ]
                                        files_dl_proc_this_repo = (
                                            True
                                            if os.path.exists(
                                                os.path.join(
                                                    processing_dir_non_branch, item_path
                                                )
                                            )
                                            else files_dl_proc_this_repo
                                        )
                            if self.cancel_search:
                                self.print_colored_ui(
                                    _(
                                        "\nDownload cancelled during processing of {repo_full_name}."
                                    ).format(repo_full_name=repo_full_name),
                                    "yellow",
                                )
                                break
                            repo_successful = False
                            if not self.cancel_search:
                                repo_successful = (
                                    bool(repo_specific_collected_depots)
                                    if self.strict_validation_var.get()
                                    else files_dl_proc_this_repo
                                )
                            if repo_successful:
                                self.print_colored_ui(
                                    _(
                                        "\nData successfully processed for AppID {app_id} in {repo_full_name}. Last update: {date}"
                                    ).format(
                                        app_id=app_id,
                                        repo_full_name=repo_full_name,
                                        date=date,
                                    ),
                                    "green",
                                )
                                overall_collected_depots.extend(
                                    dk
                                    for dk in repo_specific_collected_depots
                                    if dk not in overall_collected_depots
                                )
                                return (
                                    overall_collected_depots,
                                    processing_dir_non_branch,
                                    False,
                                )
                            else:
                                if not self.cancel_search:
                                    self.print_colored_ui(
                                        _(
                                            "AppID {app_id} could not be successfully processed from any selected repository with current settings. Trying next repo."
                                        ).format(
                                            app_id=app_id, repo_full_name=repo_full_name
                                        ),
                                        "yellow",
                                    )
                except (
                    aiohttp.ClientError,
                    asyncio.TimeoutError,
                    json.JSONDecodeError,
                ) as e:
                    self.print_colored_ui(
                        _(
                            "\nNetwork/API error with {repo_full_name}: {error}. Trying next repo."
                        ).format(
                            repo_full_name=repo_full_name, error=self.stack_Error(e)
                        ),
                        "red",
                    )
                except KeyboardInterrupt:
                    self.print_colored_ui(
                        _(
                            "\nSearch interrupted by user for repository: {repo_full_name}"
                        ).format(repo_full_name=repo_full_name),
                        "yellow",
                    )
                    self.cancel_search = True
                    break
            if self.cancel_search:
                break
        if self.cancel_search:
            self.print_colored_ui(
                _("\nDownload process terminated by user request."), "yellow"
            )
            return overall_collected_depots, None, False
        self.print_colored_ui(
            _(
                "\nAppID {app_id} could not be successfully processed from any selected repository with current settings."
            ).format(app_id=app_id),
            "red",
        )
        return overall_collected_depots, None, False

    def parse_vdf_to_lua(
        self, depot_info: List[Tuple[str, str]], appid: str, processing_dir: str
    ) -> str:
        lua_lines, processed_depots_for_setmanifest = [f"addappid({appid})"], set()
        for depot_id, decryption_key in depot_info:
            lua_lines.append(f'addappid({depot_id},1,"{decryption_key}")')
            processed_depots_for_setmanifest.add(depot_id)
        if os.path.isdir(processing_dir):
            all_manifest_files_in_dir = []
            for root, dirs, files in os.walk(processing_dir):
                [
                    all_manifest_files_in_dir.append(os.path.join(root, f_name))
                    for f_name in files
                    if f_name.lower().endswith(".manifest")
                ]

            def sort_key_manifest(filepath: str) -> Tuple[int, str]:
                filename = os.path.basename(filepath)
                depot_id_str = filename.split("_")[0] if "_" in filename else ""
                manifest_id_val = ""
                if filename.lower().endswith(".manifest"):
                    name_no_suffix = filename[: -len(".manifest")]
                    if depot_id_str and f"{depot_id_str}_" in name_no_suffix:
                        manifest_id_val = name_no_suffix.split(f"{depot_id_str}_", 1)[1]
                try:
                    depot_id_int = int(depot_id_str) if depot_id_str.isdigit() else 0
                except ValueError:
                    self.print_colored_ui(
                        _(
                            "Warning: Non-numeric depot ID '{depot_id_str}' in manifest filename '{filename}'. Using 0 for sorting."
                        ).format(depot_id_str=depot_id_str, filename=filename),
                        "yellow",
                    )
                return (depot_id_int, manifest_id_val)

            try:
                all_manifest_files_in_dir.sort(key=sort_key_manifest)
            except Exception as e_sort:
                self.print_colored_ui(
                    _(
                        "Warning: Could not fully sort manifest files for LUA generation due to naming or error: {error}"
                    ).format(error=self.stack_Error(e_sort)),
                    "yellow",
                )
            for manifest_full_path in all_manifest_files_in_dir:
                manifest_filename = os.path.basename(manifest_full_path)
                parts = manifest_filename.split("_")
                depot_id_from_file = parts[0] if parts and parts[0].isdigit() else ""
                manifest_gid_val = ""
                if manifest_filename.lower().endswith(".manifest"):
                    name_no_suffix = manifest_filename[: -len(".manifest")]
                    if (
                        depot_id_from_file
                        and f"{depot_id_from_file}_" in name_no_suffix
                    ):
                        manifest_gid_val = name_no_suffix.split(
                            f"{depot_id_from_file}_", 1
                        )[1]
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
                            _(
                                "Could not parse Manifest GID from: {manifest_filename}"
                            ).format(manifest_filename=manifest_filename),
                            "yellow",
                        )
                else:
                    self.print_colored_ui(
                        _("Could not parse DepotID from: {manifest_filename}").format(
                            manifest_filename=manifest_filename
                        ),
                        "yellow",
                    )
        return "\n".join(lua_lines)

    def zip_outcome(
        self, processing_dir: str, selected_repos_for_zip: List[str]
    ) -> Optional[str]:
        if not os.path.isdir(processing_dir):
            self.print_colored_ui(
                _(
                    "Processing directory {processing_dir} not found for zipping. Skipping zip."
                ).format(processing_dir=processing_dir),
                "red",
            )
            return None
        is_encrypted_source = any(
            self.repos.get(repo_name, "") == "Encrypted"
            for repo_name in selected_repos_for_zip
        )
        strict_mode_active, key_files_to_exclude = self.strict_validation_var.get(), [
            "key.vdf",
            "config.vdf",
        ]
        final_zip_base_name, final_zip_parent_dir = os.path.basename(
            os.path.normpath(processing_dir)
        ), os.path.dirname(processing_dir)
        final_zip_name_suffix = " - encrypted.zip" if is_encrypted_source else ".zip"
        final_zip_name = final_zip_base_name + final_zip_name_suffix
        final_zip_path = os.path.join(final_zip_parent_dir, final_zip_name)
        if os.path.exists(final_zip_path):
            try:
                os.remove(final_zip_path)
                self.print_colored_ui(
                    _("Removed existing zip: {final_zip_path}").format(
                        final_zip_path=final_zip_path
                    ),
                    "yellow",
                )
            except OSError as e_del_zip:
                self.print_colored_ui(
                    _(
                        "Error removing existing zip {final_zip_path}: {error}. Archiving may fail."
                    ).format(
                        final_zip_path=final_zip_path, error=self.stack_Error(e_del_zip)
                    ),
                    "red",
                )
                return None
        try:
            with zipfile.ZipFile(final_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(processing_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        if (
                            strict_mode_active
                            and os.path.basename(file.lower()) in key_files_to_exclude
                        ):
                            self.print_colored_ui(
                                _(
                                    "Excluding {file} from zip (strict mode active)."
                                ).format(file=file),
                                "yellow",
                            )
                            continue
                        zipf.write(
                            file_path, os.path.relpath(file_path, start=processing_dir)
                        )
            self.print_colored_ui(
                _("\nZipped outcome to {final_zip_path}").format(
                    final_zip_path=final_zip_path
                ),
                "cyan",
            )
            try:
                import shutil

                shutil.rmtree(processing_dir)
                self.print_colored_ui(
                    _("Source folder {processing_dir} deleted successfully.").format(
                        processing_dir=processing_dir
                    ),
                    "green",
                )
            except OSError as e_del:
                self.print_colored_ui(
                    _("Error deleting source folder {processing_dir}: {error}").format(
                        processing_dir=processing_dir, error=self.stack_Error(e_del)
                    ),
                    "red",
                )
            return final_zip_path
        except (zipfile.BadZipFile, OSError, FileNotFoundError) as e_zip:
            self.print_colored_ui(
                _("Error creating zip file {final_zip_path}: {error}").format(
                    final_zip_path=final_zip_path, error=self.stack_Error(e_zip)
                ),
                "red",
            )
            return None
        except Exception as e_generic_zip:
            self.print_colored_ui(
                _("An unexpected error occurred during zipping: {error}").format(
                    error=self.stack_Error(e_generic_zip)
                ),
                "red",
            )
            return None

    def on_closing(self) -> None:
        if messagebox.askokcancel(_("Quit"), _("Do you want to quit?")):
            self.cancel_search = True
            if self.initial_load_thread and self.initial_load_thread.is_alive():
                self.print_colored_ui(
                    _("Attempting to stop initial app list loading..."), "yellow"
                )
            if self.search_thread and self.search_thread.is_alive():
                self.print_colored_ui(
                    _("Attempting to stop search thread..."), "yellow"
                )

            self.settings_manager.set("window_geometry", self.geometry())
            self.settings_manager.save_settings()

            self.destroy()

    def _refresh_ui_texts(self) -> None:
        """Updates all static UI texts with the current language."""
        self.title(_("Steam Depot Online (SDO)"))

        self.encrypted_label.configure(text=_("Encrypted Repositories:"))
        self.select_all_enc_button.configure(text=_("Select All"))
        self.decrypted_label.configure(text=_("Decrypted Repositories:"))
        self.select_all_dec_button.configure(text=_("Select All"))
        self.branch_label.configure(text=_("Branch Repositories:"))
        self.select_all_branch_button.configure(text=_("Select All"))

        self.add_repo_button.configure(text=_("Add Repo"))
        self.delete_repo_button.configure(text=_("Delete Repo"))
        self.settings_button.configure(text=_("Settings"))
        self.output_folder_button.configure(text=_("Output Folder"))
        self.strict_validation_checkbox.configure(
            text=_("Strict Validation (Require Key.vdf / Non Branch Repo)")
        )

        self.game_input_label.configure(text=_("Enter Game Name or AppID:"))
        self.game_input.configure(placeholder_text=_("e.g. 123456 or Game Name"))
        self.paste_button.configure(text=_("Paste"))
        self.search_button.configure(text=_("Search"))
        self.download_button.configure(text=_("Download"))

        self.download_type_label.configure(text=_("Select appid(s) to download:"))
        self.radio_download_selected.configure(
            text=_("Selected game in search results")
        )
        self.radio_download_all_input.configure(text=_("All AppIDs in input field"))

        self.results_label.configure(text=_("Search Results:"))

        self._setup_downloaded_manifests_tab()

    def toggle_all_repos(self, repo_type: str) -> None:
        if repo_type not in ["encrypted", "decrypted", "branch"]:
            return

        all_relevant_selected: bool = True
        relevant_repos_count: int = 0

        for repo_name, stored_repo_type in self.repos.items():
            if stored_repo_type.lower() == repo_type.lower():
                relevant_repos_count += 1
                if repo_name in self.repo_vars and not self.repo_vars[repo_name].get():
                    all_relevant_selected = False
                    break

        if relevant_repos_count == 0:
            self.print_colored_ui(
                _("No {repo_type} repositories to toggle.").format(repo_type=repo_type),
                "yellow",
            )
            return

        new_state: bool = not all_relevant_selected

        for repo_name, stored_repo_type in self.repos.items():
            if (
                stored_repo_type.lower() == repo_type.lower()
                and repo_name in self.repo_vars
            ):
                self.repo_vars[repo_name].set(new_state)

        action_str: str = _("Selected") if new_state else _("Deselected")
        self.print_colored_ui(
            _("{action_str} all {repo_type} repositories.").format(
                action_str=action_str, repo_type=repo_type
            ),
            "blue",
        )
        self.save_repositories()

    def open_add_repo_window(self) -> None:
        if (
            hasattr(self, "add_repo_window_ref")
            and self.add_repo_window_ref.winfo_exists()
        ):
            self.add_repo_window_ref.focus()
            return
        self.add_repo_window_ref = ctk.CTkToplevel(self)
        self.add_repo_window_ref.title(_("Add Repository"))
        self.add_repo_window_ref.geometry("400x220")
        self.add_repo_window_ref.resizable(False, False)
        self.add_repo_window_ref.transient(self)
        self.add_repo_window_ref.grab_set()

        ctk.CTkLabel(
            self.add_repo_window_ref, text=_("Repository Name (e.g., user/repo):")
        ).pack(padx=10, pady=(10, 2))
        self.repo_name_entry = ctk.CTkEntry(self.add_repo_window_ref, width=360)
        self.repo_name_entry.pack(padx=10, pady=(0, 5))
        self.repo_name_entry.focus()

        ctk.CTkLabel(self.add_repo_window_ref, text=_("Repository Type:")).pack(
            padx=10, pady=(10, 2)
        )
        self.repo_state_var = ctk.StringVar(value="Branch")
        ctk.CTkOptionMenu(
            self.add_repo_window_ref,
            variable=self.repo_state_var,
            values=["Encrypted", "Decrypted", "Branch"],
            width=360,
        ).pack(padx=10, pady=(0, 10))

        add_button = ctk.CTkButton(
            self.add_repo_window_ref, text=_("Add"), command=self.add_repo, width=100
        )
        add_button.pack(padx=10, pady=10)
        self.add_repo_window_ref.protocol(
            "WM_DELETE_WINDOW", self.add_repo_window_ref.destroy
        )
        self.add_repo_window_ref.bind("<Return>", lambda e: self.add_repo())

    def add_repo(self) -> None:
        if (
            not hasattr(self, "add_repo_window_ref")
            or not self.add_repo_window_ref.winfo_exists()
        ):
            self.print_colored_ui(_("Add repo window not available."), "red")
            return
        repo_name, repo_state = (
            self.repo_name_entry.get().strip(),
            self.repo_state_var.get(),
        )
        if not repo_name:
            messagebox.showwarning(
                _("Input Error"),
                _("Please enter repository name."),
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
                _("Input Error"),
                _(
                    "Repository name must be in 'user/repo' format without spaces, leading/trailing slashes."
                ),
                parent=self.add_repo_window_ref,
            )
            return
        if repo_name in self.repos:
            messagebox.showwarning(
                _("Input Error"),
                _("Repository '{repo_name}' already exists.").format(
                    repo_name=repo_name
                ),
                parent=self.add_repo_window_ref,
            )
            return
        self.repos[repo_name], self.selected_repos[repo_name] = repo_state, (
            repo_state == "Branch"
        )
        self.save_repositories(), self.refresh_repo_checkboxes()
        self.print_colored_ui(
            _("Added repository: {repo_name} ({repo_state})").format(
                repo_name=repo_name, repo_state=repo_state
            ),
            "green",
        )
        self.add_repo_window_ref.destroy()

    def delete_repo(self) -> None:
        repos_to_delete = [
            cb.cget("text")
            for sf in [self.encrypted_scroll, self.decrypted_scroll, self.branch_scroll]
            for cb in sf.winfo_children()
            if isinstance(cb, ctk.CTkCheckBox) and cb.get() == 1
        ]
        if not repos_to_delete:
            messagebox.showwarning(
                _("Selection Error"),
                _(
                    "Please select at least one repository to delete by checking its box."
                ),
            )
            return
        if not messagebox.askyesno(
            _("Confirm Deletion"),
            _(
                "Are you sure you want to delete these {len_repos_to_delete} repositories?\n\n- "
            ).format(len_repos_to_delete=len(repos_to_delete))
            + "\n- ".join(repos_to_delete),
        ):
            return
        deleted_count = 0
        for repo in repos_to_delete:
            if repo in self.repos:
                del self.repos[repo]
                if repo in self.selected_repos:
                    del self.selected_repos[repo]
                deleted_count += 1

        if deleted_count > 0:
            self.save_repositories(), self.refresh_repo_checkboxes(), self.print_colored_ui(
                _("Deleted {deleted_count} repositories: {repos_to_delete_str}").format(
                    deleted_count=deleted_count,
                    repos_to_delete_str=", ".join(repos_to_delete),
                ),
                "red",
            )
        else:
            self.print_colored_ui(
                _("No matching repositories found in data to delete."), "yellow"
            )

    def refresh_repo_checkboxes(self) -> None:

        for sf in [self.encrypted_scroll, self.decrypted_scroll, self.branch_scroll]:
            for w in sf.winfo_children():
                w.destroy()

        new_repo_vars = {}

        sorted_repo_names = sorted(self.repos.keys())

        for repo_name in sorted_repo_names:
            repo_type = self.repos[repo_name]

            initial_state = self.selected_repos.get(repo_name, (repo_type == "Branch"))
            var = ctk.BooleanVar(value=initial_state)

            var.trace_add(
                "write",
                lambda name, index, mode, r=repo_name, v=var: self._update_selected_repo_state(
                    r, v.get()
                ),
            )
            new_repo_vars[repo_name] = var

            target_scroll_frame = None
            if repo_type == "Encrypted":
                target_scroll_frame = self.encrypted_scroll
            elif repo_type == "Decrypted":
                target_scroll_frame = self.decrypted_scroll
            elif repo_type == "Branch":
                target_scroll_frame = self.branch_scroll
            else:
                self.print_colored_ui(
                    _(
                        "Unknown repo state '{repo_type}' for '{repo_name}'. Assigning to Decrypted section."
                    ).format(repo_type=repo_type, repo_name=repo_name),
                    "yellow",
                )
                target_scroll_frame = self.decrypted_scroll

            if target_scroll_frame:
                cb = ctk.CTkCheckBox(target_scroll_frame, text=repo_name, variable=var)
                cb.pack(anchor="w", padx=10, pady=2)

        self.repo_vars = new_repo_vars

        self.save_repositories()

    def _update_selected_repo_state(self, repo_name: str, is_selected: bool) -> None:
        """Updates the selected_repos state in memory and saves settings."""
        self.selected_repos[repo_name] = is_selected
        self.save_repositories()

    def open_settings_window(self) -> None:

        if (
            hasattr(self, "settings_window_ref")
            and self.settings_window_ref.winfo_exists()
        ):
            self.settings_window_ref.destroy()

        self.settings_window_ref = ctk.CTkToplevel(self)
        self.settings_window_ref.title(_("Settings"))
        self.settings_window_ref.geometry("700x550")
        self.settings_window_ref.resizable(True, True)
        self.settings_window_ref.transient(self)
        self.settings_window_ref.grab_set()

        settings_tabview = ctk.CTkTabview(self.settings_window_ref)
        settings_tabview.pack(padx=10, pady=10, fill="both", expand=True)

        general_tab_title = _("General Settings")
        general_tab = settings_tabview.add(general_tab_title)
        self._setup_general_settings_tab(general_tab)

        repo_settings_tab_title = _("Repositories")
        repo_settings_tab = settings_tabview.add(repo_settings_tab_title)
        self._setup_repo_settings_tab(repo_settings_tab)

        about_tab_title = _("About")
        about_tab = settings_tabview.add(about_tab_title)
        self._setup_about_tab(about_tab)

        settings_tabview.set(general_tab_title)

        self.settings_window_ref.protocol(
            "WM_DELETE_WINDOW", self.settings_window_ref.destroy
        )
        self.settings_window_ref.after(100, self.settings_window_ref.focus_force)

    def _setup_general_settings_tab(self, parent_tab: ctk.CTkFrame) -> None:
        """Sets up the 'General Settings' tab."""

        for widget in parent_tab.winfo_children():
            widget.destroy()

        frame = ctk.CTkFrame(parent_tab)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        download_frame = ctk.CTkFrame(frame)
        download_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(download_frame, text=_("Download Location")).pack(
            side="left", padx=5
        )
        self.download_path_entry = ctk.CTkEntry(download_frame, width=300)
        self.download_path_entry.insert(0, self.settings_manager.get("download_path"))
        self.download_path_entry.pack(side="left", expand=True, fill="x", padx=5)
        choose_folder_button = ctk.CTkButton(
            download_frame,
            text=_("Choose Folder"),
            command=self._choose_download_folder,
        )
        choose_folder_button.pack(side="left", padx=5)
        Tooltip(
            choose_folder_button,
            _("Select the folder where downloaded games and manifests will be saved."),
        )

        appearance_frame = ctk.CTkFrame(frame)
        appearance_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(appearance_frame, text=_("Appearance Mode")).pack(
            side="left", padx=5
        )

        self.appearance_mode_var = ctk.StringVar(
            value=self.settings_manager.get("appearance_mode")
        )

        current_mode_display = {
            "dark": _("Dark"),
            "light": _("Light"),
            "system": _("System"),
        }.get(
            self.settings_manager.get("appearance_mode"),
            self.settings_manager.get("appearance_mode"),
        )

        self.appearance_mode_var.set(current_mode_display)

        translated_appearance_modes = [_("Dark"), _("Light"), _("System")]
        self.appearance_mode_optionmenu = ctk.CTkOptionMenu(
            appearance_frame,
            variable=self.appearance_mode_var,
            values=translated_appearance_modes,
            command=self._change_appearance_mode,
        )
        self.appearance_mode_optionmenu.pack(side="right", padx=5)
        Tooltip(
            self.appearance_mode_optionmenu,
            _(
                "Change the overall UI theme (Dark, Light, or follow System preferences)."
            ),
        )

        color_theme_frame = ctk.CTkFrame(frame)
        color_theme_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(color_theme_frame, text=_("Color Theme")).pack(side="left", padx=5)
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
        self.color_theme_optionmenu.pack(side="right", padx=5)
        Tooltip(
            self.color_theme_optionmenu, _("Change the primary accent color of the UI.")
        )

        lang_frame = ctk.CTkFrame(frame)
        lang_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(lang_frame, text=_("App Language")).pack(side="left", padx=5)

        available_lang_display_names = list(
            self.localization_manager.get_available_languages().values()
        )
        current_lang_display_name = (
            self.localization_manager.get_available_languages().get(
                self.localization_manager.current_language,
                self.localization_manager.current_language,
            )
        )
        self.lang_var = ctk.StringVar(value=current_lang_display_name)
        self.lang_optionmenu = ctk.CTkOptionMenu(
            lang_frame,
            variable=self.lang_var,
            values=available_lang_display_names,
            command=self._change_language,
        )
        self.lang_optionmenu.pack(side="right", padx=5)
        Tooltip(
            self.lang_optionmenu, _("Change the display language of the application.")
        )

        update_check_frame = ctk.CTkFrame(frame)
        update_check_frame.pack(fill="x", pady=5)
        self.update_check_var = ctk.BooleanVar(
            value=self.settings_manager.get("app_update_check_on_startup")
        )
        update_check_cb = ctk.CTkCheckBox(
            update_check_frame,
            text=_("On startup, check for new versions"),
            variable=self.update_check_var,
        )
        update_check_cb.pack(side="left", padx=5, pady=5)
        Tooltip(
            update_check_cb,
            _("Automatically check for new SDO versions when the application starts."),
        )

        check_now_button = ctk.CTkButton(
            update_check_frame,
            text=_("Check for Updates Now"),
            command=lambda: threading.Thread(
                target=self.run_update_check, daemon=True
            ).start(),
        )
        check_now_button.pack(side="right", padx=5)
        Tooltip(check_now_button, _("Manually check for a new version of SDO."))

        ctk.CTkLabel(
            frame,
            text=_("Current App Version: {app_version}").format(
                app_version=self.APP_VERSION
            ),
        ).pack(anchor="w", padx=5, pady=5)

        save_button = ctk.CTkButton(
            frame, text=_("Save Changes"), command=self._save_general_settings
        )
        save_button.pack(pady=10)
        Tooltip(save_button, _("Save all settings in this tab."))

    def _setup_repo_settings_tab(self, parent_tab: ctk.CTkFrame) -> None:
        """Sets up the 'Repositories' settings tab."""

        for widget in parent_tab.winfo_children():
            widget.destroy()

        frame = ctk.CTkFrame(parent_tab)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(
            frame, text=_("Export/Import Repository List"), font=("Helvetica", 14.4)
        ).pack(pady=10)

        export_button = ctk.CTkButton(
            frame, text=_("Export Repositories"), command=self._export_repositories
        )
        export_button.pack(pady=5)
        Tooltip(
            export_button,
            _("Save your current repository list to a JSON file at a chosen location."),
        )

        import_button = ctk.CTkButton(
            frame, text=_("Import Repositories"), command=self._import_repositories
        )
        import_button.pack(pady=5)
        Tooltip(
            import_button,
            _(
                "Load a repository list from a JSON file. Existing repositories will be merged."
            ),
        )

    def _setup_about_tab(self, parent_tab: ctk.CTkFrame) -> None:
        """Sets up the 'About' (formerly Info) tab."""

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
        )
        info_textbox.pack(side="left", fill="both", expand=True)
        info_scrollbar = ctk.CTkScrollbar(info_text_frame, command=info_textbox.yview)
        info_scrollbar.pack(side="right", fill="y")
        info_textbox.configure(yscrollcommand=info_scrollbar.set)
        tags_config = {
            "bold": {"font": ("Helvetica", 11, "bold")},
            "italic": {"font": ("Helvetica", 11, "italic")},
            "title": {
                "font": ("Helvetica", 13, "bold"),
                "foreground": "cyan",
                "spacing1": 5,
                "spacing3": 10,
                "justify": "center",
            },
            "subtitle": {
                "font": ("Helvetica", 11, "bold"),
                "foreground": "deepskyblue",
                "spacing1": 3,
                "spacing3": 5,
            },
            "highlight": {"foreground": "lawn green"},
            "note": {"foreground": "orange"},
            "normal": {"font": ("Helvetica", 11), "spacing3": 3},
            "url": {
                "font": ("Helvetica", 11),
                "foreground": "light sky blue",
                "underline": True,
            },
        }
        for tag, conf in tags_config.items():
            info_textbox.tag_configure(tag, **conf)
        info_content = [
            (
                _("Steam Depot Online (SDO) - Version: {version}\n").format(
                    version=self.APP_VERSION
                ),
                "title",
            ),
            (_("Author: "), "bold"),
            ("FairyRoot\n", "highlight"),
            (_("Contact (Telegram): "), "normal"),
            ("t.me/FairyRoot\n\n", "url"),
            (_("Overview:\n"), "subtitle"),
            (
                _(
                    "SDO fetches Steam game data from GitHub repositories. For 'Encrypted' and 'Decrypted' repo types, it can generate Lua scripts and zips the results. For 'Branch' repo types, it downloads and saves the GitHub branch zip directly. All successful outputs are placed in:\n`./Games/{GameName}-{AppID}.zip`\n\n"
                ),
                "normal",
            ),
            (_("Key Features:\n"), "subtitle"),
            (
                _(
                    "- Add/delete GitHub repositories (user/repo format) with types: Encrypted, Decrypted, Branch.\n"
                ),
                "normal",
            ),
            (_("- Select multiple repositories for download attempts.\n"), "normal"),
            (
                _(
                    "- Toggle 'Strict Validation' for non-Branch repositories (see below).\n"
                ),
                "normal",
            ),
            (
                _(
                    "- Search games by Name (uses Steam's full app list) or directly by AppID (uses Steam API).\n"
                ),
                "normal",
            ),
            (
                _(
                    "- View detailed game info (description, logo/header images, links) upon selection using Steam API.\n"
                ),
                "normal",
            ),
            (
                _(
                    "- Download process priorities: For non-Branch, it attempts selected repos in order until success. Branch types are also attempted in order.\n"
                ),
                "normal",
            ),
            (
                _(
                    "- Generates .lua scripts for Steam emulators (for non-Branch types that yield decryption keys).\n"
                ),
                "normal",
            ),
            (
                _(
                    "- Zips downloaded files and .lua script (for non-Branch types). Branch types are saved as downloaded .zip.\n\n"
                ),
                "normal",
            ),
            (_("1. Repository Types Explained:\n"), "subtitle"),
            (_("   - Decrypted Repositories: "), "bold"),
            (
                _(
                    "(Often preferred)\n     Usually contain necessary decryption keys (e.2., `key.vdf`). Games from these are more likely to be ready for use with emulators. Output is a tool-generated ZIP: `./Games/{GameName}-{AppID}.zip` containing processed files and a .lua script.\n"
                ),
                "normal",
            ),
            (_("   - Encrypted Repositories: "), "bold"),
            (
                _(
                    "\n     May have the latest game manifests but decryption keys within their `key.vdf`/`config.vdf` might be hashed, partial, or invalid. A .lua script is generated (can be minimal if no valid keys found). Output is a tool-generated ZIP like Decrypted ones.\n"
                ),
                "note",
            ),
            (_("   - Branch Repositories: "), "bold"),
            (
                _(
                    "\n     (Selected by default for new repos and on startup)\n     Downloads a direct .zip archive of an entire AppID-named branch from a GitHub repository (e.g., `main` or `1245620`). This downloaded .zip is saved *as is* directly to `./Games/{GameName}-{AppID}.zip`. **No .lua script is generated by SDO, and no further zipping or file processing is performed by SDO for this type.** 'Strict Validation' does not apply.\n\n"
                ),
                "normal",
            ),
            (
                _(
                    "   *Recommendation for Playable Games:* Prioritize 'Decrypted' repositories. 'Branch' repos provide raw game data zips which might be useful for archival or manual setup.\n"
                ),
                "normal",
            ),
            (
                _(
                    "   *For Latest Manifests (Advanced Users):* 'Encrypted' repos might offer newer files, but you may need to source decryption keys elsewhere.\n\n"
                ),
                "normal",
            ),
            (_("2. 'Strict Validation' Checkbox:\n"), "subtitle"),
            (
                _(
                    "   - Applies ONLY to 'Encrypted'/'Decrypted' (non-Branch) repositories.\n"
                ),
                "note",
            ),
            (_("   - Checked (Default): "), "bold"),
            (
                _(
                    "SDO requires a `key.vdf` or `config.vdf` to be present in the GitHub branch. It will prioritize downloading and parsing these key files. If valid decryption keys are found, associated `.manifest` files are also downloaded. The final tool-generated ZIP will *exclude* the `key.vdf`/`config.vdf` itself.\n"
                ),
                "normal",
            ),
            (_("   - Unchecked: "), "bold"),
            (
                _(
                    "SDO downloads all files from the GitHub branch. If `key.vdf`/`config.vdf` are present, they are parsed for keys. All downloaded files, *including* any `key.vdf`/`config.vdf`, WILL be included in the final tool-generated ZIP.\n\n"
                ),
                "normal",
            ),
            (_("3. How to Use:\n"), "subtitle"),
            (
                _(
                    "   1. Add GitHub repositories via 'Add Repo' (e.g., `SomeUser/SomeRepo`). Select the correct type (Encrypted, Decrypted, Branch).\n"
                ),
                "normal",
            ),
            (
                _(
                    "   2. Select checkboxes for repositories you want to use for downloads.\n"
                ),
                "normal",
            ),
            (
                _(
                    "   3. Configure 'Strict Validation' as needed (affects non-Branch downloads).\n"
                ),
                "normal",
            ),
            (
                _(
                    "   4. Enter a game name or AppID and click 'Search'. Wait for the initial app list to load on first use.\n"
                ),
                "normal",
            ),
            (
                _(
                    "   5. Select a game from the search results. Game details (images, text) will appear in the Progress panel.\n"
                ),
                "normal",
            ),
            (
                _(
                    "   6. Click 'Download'. SDO will attempt to fetch from selected repos. The final output for any successful download will be `./Games/{GameName}-{AppID}.zip`.\n\n"
                ),
                "normal",
            ),
            (_("4. Potential Issues & Notes:\n"), "subtitle"),
            (
                _(
                    "   - Image Display: Game logo/header requires Pillow (`pip install Pillow`). If not installed, images won't show.\n"
                ),
                "note",
            ),
            (
                _(
                    "   - 'Content is still encrypted' (in-game error, non-Branch output): The game files were downloaded, but valid decryption keys were not found or applied correctly by the emulator. Try a different 'Decrypted' repository or ensure your emulator setup is correct.\n"
                ),
                "normal",
            ),
            (
                _(
                    "   - Rate-limiting: GitHub or Steam APIs may temporarily limit requests if used excessively. Wait or consider a VPN for GitHub CDN access if issues persists.\n"
                ),
                "normal",
            ),
            (_("   - Internet: A stable internet connection is required.\n"), "normal"),
            (
                _(
                    "   - Repository Order: The order of repositories in `repositories.json` (added order) can influence which one is tried first, but selection is primary. The tool iterates through *selected* repos.\n\n"
                ),
                "normal",
            ),
        ]
        for text, tag_name in info_content:
            info_textbox.insert("end", text, tag_name)
        info_textbox.tag_add("center_title", "1.0", "1.end")
        info_textbox.tag_configure("center_title", justify="center")
        info_textbox.configure(state="disabled")

    def _choose_download_folder(self) -> None:
        """Opens a directory chooser dialog and updates the download path."""
        current_path = self.settings_manager.get("download_path")
        chosen_path = filedialog.askdirectory(
            parent=self.settings_window_ref,
            initialdir=current_path if os.path.isdir(current_path) else os.getcwd(),
            title=_("Select Download Folder"),
        )
        if chosen_path:
            self.download_path_entry.delete(0, END)
            self.download_path_entry.insert(0, chosen_path)
            self.append_progress(
                _("Download path updated to: {chosen_path}").format(
                    chosen_path=chosen_path
                ),
                "default",
            )

    def _change_appearance_mode(self, new_appearance_mode_display: str) -> None:
        """Changes the CTk appearance mode setting and prompts for restart."""

        reverse_map = {_("Dark"): "dark", _("Light"): "light", _("System"): "system"}
        actual_mode = reverse_map.get(
            new_appearance_mode_display, new_appearance_mode_display.lower()
        )

        self.settings_manager.set("appearance_mode", actual_mode)
        self.settings_manager.save_settings()

        messagebox.showinfo(
            _("Appearance Mode Change"),
            _(
                "Appearance mode changed to {new_appearance_mode_display}. Please restart the application for the changes to take full effect."
            ).format(new_appearance_mode_display=new_appearance_mode_display),
            parent=self.settings_window_ref,
        )
        self.append_progress(
            _(
                "Appearance mode set to: {new_appearance_mode_display}. Restart required for full effect."
            ).format(new_appearance_mode_display=new_appearance_mode_display),
            "yellow",
        )

    def _change_color_theme(self, new_color_theme: str) -> None:
        """Changes the CTk color theme and saves the setting."""
        ctk.set_default_color_theme(new_color_theme)
        self.settings_manager.set("color_theme", new_color_theme)
        self.settings_manager.save_settings()
        self.append_progress(
            _("Color theme set to: {new_color_theme}").format(
                new_color_theme=new_color_theme
            ),
            "default",
        )

    def _change_language(self, new_language_display_name: str) -> None:
        """Changes the application language and saves the setting, then refreshes UI."""

        available_languages = self.localization_manager.get_available_languages()
        selected_code = None
        for code, display_name in available_languages.items():
            if display_name == new_language_display_name:
                selected_code = code
                break

        if selected_code:
            old_lang_code = self.localization_manager.current_language
            self.localization_manager.set_language(selected_code)

            if selected_code != old_lang_code:

                self._refresh_ui_texts()

                if (
                    hasattr(self, "settings_window_ref")
                    and self.settings_window_ref.winfo_exists()
                ):
                    self.settings_window_ref.destroy()
                    self.open_settings_window()

                self.append_progress(
                    _(
                        "Language changed to {new_language_display_name}. Please restart the application for full language changes to take effect."
                    ).format(new_language_display_name=new_language_display_name),
                    "yellow",
                )
        else:
            self.append_progress(
                _("Could not set language to {new_language_display_name}.").format(
                    new_language_display_name=new_language_display_name
                ),
                "red",
            )

    def _save_general_settings(self) -> None:
        """Saves all settings from the 'General Settings' tab."""
        self.settings_manager.set("download_path", self.download_path_entry.get())

        self.settings_manager.set(
            "app_update_check_on_startup", self.update_check_var.get()
        )
        self.settings_manager.save_settings()
        self.append_progress(_("Settings saved successfully."), "green")
        self.display_downloaded_manifests()

    def run_update_check(self) -> None:
        """Performs the update check in a background thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.async_check_for_updates())
        finally:
            loop.close()

    async def async_check_for_updates(self) -> None:
        """Asynchronously checks for new versions of the application."""
        self.append_progress(_("Checking for updates..."), "default")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.GITHUB_RELEASES_API, timeout=aiohttp.ClientTimeout(total=10)
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

            current_version_parts = list(map(int, self.APP_VERSION.split(".")))
            latest_version_parts = list(map(int, latest_version_tag.split(".")))

            if latest_version_parts > current_version_parts:
                self.append_progress(
                    _(
                        "A new version ({latest_version}) is available! Current: {current_version}. Download from: {release_url}"
                    ).format(
                        latest_version=latest_version_tag,
                        current_version=self.APP_VERSION,
                        release_url=release_url,
                    ),
                    "green",
                )
            else:
                self.append_progress(
                    _("Update check completed. No new version available."), "default"
                )

        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as e:
            self.append_progress(
                _("Error checking for updates: {error}").format(
                    error=self.stack_Error(e)
                ),
                "red",
            )
        except Exception as e:
            self.append_progress(
                _("Error checking for updates: {error}").format(
                    error=self.stack_Error(e)
                ),
                "red",
            )

    def _export_repositories(self) -> None:
        """Exports the current repository list to a JSON file."""
        filepath = filedialog.asksaveasfilename(
            parent=self.settings_window_ref,
            defaultextension=".json",
            filetypes=[(_("JSON files"), "*.json")],
            title=_("Select destination for repositories.json"),
            initialfile="repositories.json",
        )
        if filepath:
            try:
                self.save_repositories(filepath)
                self.append_progress(
                    _("Repositories exported successfully to: {filepath}").format(
                        filepath=filepath
                    ),
                    "green",
                )
            except Exception as e:
                messagebox.showerror(
                    _("Save Error"),
                    _("Failed to export repositories: {e}").format(e=e),
                    parent=self.settings_window_ref,
                )
                self.append_progress(
                    _("Failed to export repositories: {e}").format(e=e), "red"
                )

    def _import_repositories(self) -> None:
        """Imports a repository list from a JSON file, merging with existing."""
        filepath = filedialog.askopenfilename(
            parent=self.settings_window_ref,
            defaultextension=".json",
            filetypes=[(_("JSON files"), "*.json")],
            title=_("Select repositories.json to import"),
        )
        if filepath:
            try:
                imported_repos = self.load_repositories(filepath)

                self.repos.update(imported_repos)

                for repo_name, repo_type in imported_repos.items():
                    if repo_name not in self.selected_repos:
                        self.selected_repos[repo_name] = repo_type == "Branch"

                self.save_repositories()
                self.refresh_repo_checkboxes()
                self.append_progress(
                    _(
                        "Repositories imported successfully from: {filepath}. Please review and save settings if changes were made."
                    ).format(filepath=filepath),
                    "green",
                )
            except Exception as e:
                messagebox.showerror(
                    _("Load Error"),
                    _("Failed to import repositories: {e}").format(e=e),
                    parent=self.settings_window_ref,
                )
                self.append_progress(
                    _("Failed to import repositories: {e}").format(e=e), "red"
                )


# --- Main execution ---
if __name__ == "__main__":
    app = ManifestDownloader()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
