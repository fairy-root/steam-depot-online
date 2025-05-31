import asyncio
import aiohttp
import aiofiles
import os
import vdf
import json
import zipfile
import threading
from functools import partial
from tkinter import END, Text, Scrollbar, messagebox
import customtkinter as ctk
import sys
from typing import Any, Dict, List, Optional, Tuple
from io import BytesIO


try:
    from PIL import Image, ImageTk

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    ImageTk = None
    Image = None


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class ManifestDownloader(ctk.CTk):
    """
    Main application class for Steam Depot Online (SDO).
    Handles UI setup, game searching, manifest downloading, and processing.
    """

    def __init__(self) -> None:
        super().__init__()
        self.title("Steam Depot Online (SDO)")
        self.geometry("1180x630")
        self.minsize(1080, 590)
        self.resizable(True, True)

        if not PIL_AVAILABLE:
            messagebox.showwarning(
                "Missing Library",
                "Pillow (PIL) library is not installed. Images will not be displayed in game details. Please install it using: pip install Pillow",
            )

        self.repos: Dict[str, str] = self.load_repositories()

        self.selected_repos: Dict[str, bool] = {
            repo: (repo_type == "Branch") for repo, repo_type in self.repos.items()
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

        self.setup_ui()
        self._start_initial_app_list_load()

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
                        self.after(
                            0,
                            lambda: self._append_progress_direct(
                                f"Initialization: Failed to load Steam app list (Status: {response.status}). Search by name may not work. You can still search by AppID.",
                                "red",
                            ),
                        )

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            self.after(
                0,
                lambda: self._append_progress_direct(
                    f"Initialization: Error fetching Steam app list: {self.stack_Error(e)}. Search by name may not work.",
                    "red",
                ),
            )
        except json.JSONDecodeError:
            self.after(
                0,
                lambda: self._append_progress_direct(
                    "Initialization: Failed to decode Steam app list response. Search by name may not work.",
                    "red",
                ),
            )
        except Exception as e:
            self.after(
                0,
                lambda: self._append_progress_direct(
                    f"Initialization: Unexpected error loading Steam app list: {self.stack_Error(e)}.",
                    "red",
                ),
            )

        self.after(0, lambda: self.search_button.configure(state="normal"))

        self.after(0, self._update_dynamic_content_start_index)

    def _update_dynamic_content_start_index(self) -> None:
        """Stores the index after initial messages for selective clearing."""

        self._dynamic_content_start_index = self.progress_text.index(END)

    def load_repositories(self) -> Dict[str, str]:
        if os.path.exists("repositories.json"):
            try:
                with open("repositories.json", "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                messagebox.showerror(
                    "Load Error", "Failed to load repositories.json. Using empty list."
                )
                return {}
        return {}

    def save_repositories(self) -> None:
        try:
            with open("repositories.json", "w", encoding="utf-8") as f:
                json.dump(self.repos, f, indent=4)
        except IOError:
            messagebox.showerror("Save Error", "Failed to save repositories.json.")

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
        ctk.CTkLabel(
            encrypted_label_frame,
            text="Encrypted Repositories:",
            text_color="cyan",
            font=("Helvetica", 12.6),
        ).pack(padx=9, pady=(9, 4.5), side="left")
        ctk.CTkButton(
            encrypted_label_frame,
            text="Select All",
            width=72,
            command=lambda: self.toggle_all_repos("encrypted"),
        ).pack(padx=18, pady=(9, 4.5), side="left")
        self.encrypted_scroll = ctk.CTkScrollableFrame(
            encrypted_frame, width=240, height=135
        )
        self.encrypted_scroll.pack(padx=9, pady=4.5, fill="both", expand=True)

        decrypted_frame = ctk.CTkFrame(repos_container)
        decrypted_frame.pack(side="left", fill="both", expand=True, padx=(3, 3))
        decrypted_label_frame = ctk.CTkFrame(decrypted_frame)
        decrypted_label_frame.pack(fill="x")
        ctk.CTkLabel(
            decrypted_label_frame,
            text="Decrypted Repositories:",
            text_color="cyan",
            font=("Helvetica", 12.6),
        ).pack(padx=9, pady=(9, 4.5), side="left")
        ctk.CTkButton(
            decrypted_label_frame,
            text="Select All",
            width=72,
            command=lambda: self.toggle_all_repos("decrypted"),
        ).pack(padx=18, pady=(9, 4.5), side="left")
        self.decrypted_scroll = ctk.CTkScrollableFrame(
            decrypted_frame, width=240, height=135
        )
        self.decrypted_scroll.pack(padx=9, pady=4.5, fill="both", expand=True)

        branch_frame = ctk.CTkFrame(repos_container)
        branch_frame.pack(side="left", fill="both", expand=True, padx=(3, 0))
        branch_label_frame = ctk.CTkFrame(branch_frame)
        branch_label_frame.pack(fill="x")
        ctk.CTkLabel(
            branch_label_frame,
            text="Branch Repositories:",
            text_color="cyan",
            font=("Helvetica", 12.6),
        ).pack(padx=9, pady=(9, 4.5), side="left")
        ctk.CTkButton(
            branch_label_frame,
            text="Select All",
            width=72,
            command=lambda: self.toggle_all_repos("branch"),
        ).pack(padx=28, pady=(9, 4.5), side="left")
        self.branch_scroll = ctk.CTkScrollableFrame(branch_frame, width=240, height=135)
        self.branch_scroll.pack(padx=9, pady=4.5, fill="both", expand=True)

        self.refresh_repo_checkboxes()

        add_repo_button = ctk.CTkButton(
            repo_frame, text="Add Repo", width=90, command=self.open_add_repo_window
        )
        add_repo_button.pack(padx=9, pady=4.5, side="right")
        delete_repo_button = ctk.CTkButton(
            repo_frame, text="Delete Repo", width=90, command=self.delete_repo
        )
        delete_repo_button.pack(padx=9, pady=4.5, side="right")
        info_button = ctk.CTkButton(
            repo_frame, text="Info", width=90, command=self.open_info_window
        )
        info_button.pack(padx=9, pady=4.5, side="right")

        self.strict_validation_var = ctk.BooleanVar(value=True)
        self.strict_validation_checkbox = ctk.CTkCheckBox(
            repo_frame,
            text="Strict Validation (Require Key.vdf / Non Branch Repo)",
            text_color="orange",
            variable=self.strict_validation_var,
            font=("Helvetica", 12.6),
        )
        self.strict_validation_checkbox.pack(padx=9, pady=4.5, side="left", anchor="w")

        input_frame = ctk.CTkFrame(left_frame, corner_radius=9)
        input_frame.pack(padx=0, pady=9, fill="x", expand=False)
        ctk.CTkLabel(
            input_frame,
            text="Enter Game Name or AppID:",
            text_color="cyan",
            font=("Helvetica", 14.4),
        ).pack(padx=9, pady=4.5, anchor="w")
        self.game_input = ctk.CTkEntry(
            input_frame, placeholder_text="e.g. 123456 or Game Name", width=270
        )
        self.game_input.pack(padx=9, pady=4.5, side="left", expand=True, fill="x")
        ctk.CTkButton(
            input_frame, text="Paste", width=90, command=self.paste_from_clipboard
        ).pack(padx=9, pady=4.5, side="left")
        self.search_button = ctk.CTkButton(
            input_frame,
            text="Search",
            width=90,
            command=self.search_game,
            state="disabled",
        )
        self.search_button.pack(padx=9, pady=4.5, side="left")
        self.download_button = ctk.CTkButton(
            input_frame,
            text="Download",
            width=90,
            command=self.download_manifest,
            state="disabled",
        )
        self.download_button.pack(padx=9, pady=4.5, side="left")

        self.results_frame = ctk.CTkFrame(left_frame, corner_radius=9)
        self.results_frame.pack(padx=0, pady=9, fill="both", expand=True)
        self.results_label = ctk.CTkLabel(
            self.results_frame,
            text="Search Results:",
            text_color="cyan",
            font=("Helvetica", 14.4),
        ).pack(padx=9, pady=4.5, anchor="w")
        self.results_var = ctk.StringVar(value=None)
        self.results_radio_buttons: List[ctk.CTkRadioButton] = []
        self.results_container = ctk.CTkScrollableFrame(
            self.results_frame, width=774, height=90
        )
        self.results_container.pack(padx=9, pady=4.5, fill="both", expand=True)

        right_frame = ctk.CTkFrame(main_container)
        right_frame.pack(side="right", fill="both", expand=False, padx=(9, 0))
        progress_frame = ctk.CTkFrame(right_frame, corner_radius=9)
        progress_frame.pack(padx=0, pady=9, fill="both", expand=True)
        ctk.CTkLabel(
            progress_frame,
            text="Progress:",
            text_color="cyan",
            font=("Helvetica", 14.4),
        ).pack(padx=9, pady=4.5, anchor="w")
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
            "game_title", font=("Helvetica", 12, "bold"), foreground="cyan", spacing3=5
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

    def _append_progress_direct(
        self,
        message: str,
        color: str = "default",
        tags: Optional[Tuple[str, ...]] = None,
    ) -> None:
        """Appends a message directly to the progress text on the current (main) thread."""
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
        self.progress_text.configure(state="normal")
        self.progress_text.delete("1.0", END)
        self.image_references.clear()

        self._dynamic_content_start_index = self.progress_text.index(END)
        self.progress_text.configure(state="disabled")

    def paste_from_clipboard(self) -> None:
        try:
            clipboard_text: str = self.clipboard_get()
            self.game_input.delete(0, END)
            self.game_input.insert(0, clipboard_text)
            self.append_progress("Pasted text from clipboard.", "green")
        except Exception as e:
            messagebox.showerror("Paste Error", f"Failed to paste from clipboard: {e}")

    def search_game(self) -> None:
        user_input: str = self.game_input.get().strip()
        if not user_input:
            messagebox.showwarning("Input Error", "Please enter a game name or AppID.")
            return

        if self.search_thread and self.search_thread.is_alive():
            self.cancel_search = True
            self.append_progress("Cancelling previous search...", "yellow")

        for widget in self.results_container.winfo_children():
            widget.destroy()
        self.results_radio_buttons.clear()
        self.results_var.set(None)
        self.download_button.configure(state="disabled")

        self._clear_and_reinitialize_progress_area()

        self._append_progress_direct(f"Searching for '{user_input}'...", "cyan")

        self.cancel_search = False
        self.search_thread = threading.Thread(
            target=self.run_search, args=(user_input,), daemon=True
        )
        self.search_thread.start()

    def run_search(self, user_input: str) -> None:
        search_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(search_loop)
        try:
            loop_result = search_loop.run_until_complete(
                self.async_search_game(user_input)
            )
        finally:
            search_loop.close()

    async def async_search_game(self, user_input: str) -> None:

        games_found: List[Dict[str, Any]] = []
        max_results = 200

        async with aiohttp.ClientSession() as session:
            if user_input.isdigit():
                appid_to_search = user_input
                self.append_progress(
                    f"Fetching details for AppID: {appid_to_search}...", "default"
                )
                url = f"https://store.steampowered.com/api/appdetails?appids={appid_to_search}&l=english"
                try:
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
                                    f"No game found or API error for AppID {appid_to_search}.",
                                    "red",
                                )
                        else:
                            self.append_progress(
                                f"Failed to fetch details for AppID {appid_to_search} (Status: {response.status}).",
                                "red",
                            )
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    self.append_progress(
                        f"Error fetching AppID {appid_to_search}: {self.stack_Error(e)}",
                        "red",
                    )
                except json.JSONDecodeError:
                    self.append_progress(
                        f"Failed to decode JSON for AppID {appid_to_search}.", "red"
                    )
            else:
                if not self.app_list_loaded_event.is_set():
                    self.append_progress(
                        "Steam app list is not yet loaded. Please wait or try AppID.",
                        "yellow",
                    )
                    return
                search_term_lower = user_input.lower()
                for app_info in self.steam_app_list:
                    if self.cancel_search:
                        self.append_progress("\nName search cancelled.", "yellow")
                        return
                    if search_term_lower in app_info.get("name", "").lower():
                        games_found.append(
                            {"appid": str(app_info["appid"]), "name": app_info["name"]}
                        )
                        if len(games_found) >= max_results:
                            self.append_progress(
                                f"Max results ({max_results}). Refine search.", "yellow"
                            )
                            break

        if self.cancel_search:
            self.append_progress("\nSearch cancelled.", "yellow")
            return
        if not games_found:
            self.append_progress(
                "\nNo matching games found. Please try another name or AppID.", "red"
            )
            return

        self.appid_to_game.clear()
        for idx, game in enumerate(games_found, 1):
            if self.cancel_search:
                self.append_progress("\nSearch cancelled.", "yellow")
                return
            appid, game_name = str(game.get("appid", "Unknown")), game.get(
                "name", "Unknown Game"
            )
            self.appid_to_game[appid] = game_name
            self.after(0, partial(self.create_radio_button, idx, appid, game_name))
        self.append_progress(f"\nFound {len(games_found)} game(s). Select one.", "cyan")

    def create_radio_button(self, idx: int, appid: str, game_name: str) -> None:
        display_text: str = f"{idx}. {game_name} (AppID: {appid})"
        rb = ctk.CTkRadioButton(
            self.results_container,
            text=display_text,
            variable=self.results_var,
            value=appid,
            command=self.enable_download,
        )
        rb.pack(anchor="w", padx=10, pady=2)
        self.results_radio_buttons.append(rb)

    def enable_download(self) -> None:
        selected_appid_val: Optional[str] = self.results_var.get()
        if selected_appid_val and selected_appid_val in self.appid_to_game:
            self.selected_appid = selected_appid_val
            self.selected_game_name = self.appid_to_game[selected_appid_val]

            self._clear_and_reinitialize_progress_area()

            self.download_button.configure(state="normal")

            threading.Thread(
                target=self.run_display_game_details,
                args=(self.selected_appid, self.selected_game_name),
                daemon=True,
            ).start()
        else:
            self.append_progress("Selected game not found in mapping.", "red")
            self.download_button.configure(state="disabled")

    def run_display_game_details(self, appid: str, game_name: str) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.async_display_game_details(appid, game_name))
        finally:
            loop.close()

    async def _download_image_async(
        self, session: aiohttp.ClientSession, url: str
    ) -> Optional[bytes]:
        """Helper to download an image."""
        if not PIL_AVAILABLE:
            return None
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    return await response.read()
                else:

                    if response.status != 404:
                        self.append_progress(
                            f"Failed to download image (Status {response.status}): {url}",
                            "yellow",
                            ("game_detail_section",),
                        )
                    return None
        except Exception as e:
            self.append_progress(
                f"Error downloading image {url}: {self.stack_Error(e)}",
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
                f"Error processing image for UI: {self.stack_Error(e)}",
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
                tasks.append(
                    asyncio.create_task(self._download_image_async(session, logo_url))
                )
                tasks.append(
                    asyncio.create_task(self._download_image_async(session, header_url))
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
                        f"Failed to decode JSON for AppID {appid} details.",
                        "red",
                        ("game_detail_section",),
                    )
            elif isinstance(appdetails_response, Exception):
                self.append_progress(
                    f"Error fetching AppID {appid} details: {self.stack_Error(appdetails_response)}",
                    "red",
                    ("game_detail_section",),
                )
            else:
                self.append_progress(
                    f"Failed to fetch AppID {appid} details (Status: {appdetails_response.status}).",
                    "red",
                    ("game_detail_section",),
                )

        self.append_progress(
            f"{game_name}",
            "game_title",
            ("game_detail_section",),
        )

        if PIL_AVAILABLE:
            header_max_width = self.progress_text.winfo_width() - 12
            if header_max_width <= 50:
                header_max_width = 320

            if logo_data:
                self.after(
                    0, partial(self._process_and_insert_image_ui, logo_data, 200, 200)
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
                genres = "Genres: " + ", ".join([g["description"] for g in genres_list])
                description_parts.append(genres)

            release_date_info = game_api_data.get("release_date", {})
            if release_date_info.get("date"):
                description_parts.append(f"Release Date: {release_date_info['date']}")

        if description_parts:
            self.after(
                100,
                lambda d=description_parts: self.append_progress(
                    "\n" + "\n".join(d),
                    "game_description",
                    ("game_detail_section",),
                ),
            )

        elif not game_api_data and not description_parts:
            self.after(
                100,
                lambda: self.append_progress(
                    "No detailed text information found for this game.",
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
                "Repository Selection", "Please select at least one repository."
            )
            return
        if not self.selected_appid or not self.selected_game_name:
            messagebox.showwarning("Selection Error", "Please select a game first.")
            return

        self.download_button.configure(state="disabled")

        self._clear_and_reinitialize_progress_area()

        self.append_progress(
            f"Starting download for {self.selected_game_name} (AppID: {self.selected_appid})...",
            "blue",
        )

        self.cancel_search = False
        threading.Thread(
            target=self.run_download,
            args=(self.selected_appid, self.selected_game_name, selected_repo_list),
            daemon=True,
        ).start()

    def run_download(
        self, appid: str, game_name: str, selected_repos: List[str]
    ) -> None:
        download_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(download_loop)
        try:
            download_loop.run_until_complete(
                self.async_download_and_process(appid, game_name, selected_repos)
            )
        finally:
            download_loop.close()
            self.after(0, lambda: self.download_button.configure(state="normal"))

    async def async_download_and_process(
        self, appid: str, game_name: str, selected_repos: List[str]
    ) -> None:
        collected_depots, output_path_or_processing_dir, source_was_branch = (
            await self._perform_download_operations(appid, game_name, selected_repos)
        )
        if self.cancel_search:
            self.append_progress("\nDownload cancelled.", "yellow")
            return

        if source_was_branch:
            if output_path_or_processing_dir and os.path.isfile(
                output_path_or_processing_dir
            ):
                self.append_progress(f"\nBranch repo download successful.", "green")
                self.append_progress(
                    f"Output saved directly to: {output_path_or_processing_dir}", "blue"
                )
            else:
                self.append_progress(
                    "\nBranch repo download completed, but the expected zip file was not found or path was invalid.",
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
                async with aiofiles.open(
                    lua_file_path, "w", encoding="utf-8"
                ) as lua_file:
                    await lua_file.write(lua_script)
                self.append_progress(
                    f"\nGenerated {game_name} unlock file: {lua_file_path}", "blue"
                )
            except Exception as e:
                self.append_progress(
                    f"\nFailed to write Lua script: {self.stack_Error(e)}", "red"
                )
            self.zip_outcome(processing_dir, selected_repos)
            if not collected_depots and self.strict_validation_var.get():
                self.append_progress(
                    "\nWarning: Strict validation was on, but no decryption keys were found. LUA script is minimal.",
                    "yellow",
                )
            elif not collected_depots and not self.strict_validation_var.get():
                self.append_progress(
                    "\nNo decryption keys found (strict validation was off). Files downloaded if available. LUA script is minimal.",
                    "yellow",
                )
        else:
            if not self.cancel_search:
                self.append_progress(
                    "\nDownload process failed or was interrupted before any files could be saved or path was invalid.",
                    "red",
                )
            if output_path_or_processing_dir:
                self.append_progress(
                    f"Returned path was: {output_path_or_processing_dir}", "red"
                )

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
                            f"\nDownload cancelled by user for: {path}", "yellow"
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
                                f"\nDownload interrupted by user for: {path}", "yellow"
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
                        f"\nRetrying download cycle for: {path} (Cycle {attempt + 2}/{overall_attempts})",
                        "yellow",
                    )
                    await asyncio.sleep(1)
        if not self.cancel_search:
            self.print_colored_ui(f"\nMaximum attempts exceeded for: {path}", "red")
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
                        f"Manifest file {path} already exists. Using local.", "default"
                    )
                if path.lower().endswith((".vdf")):
                    try:
                        async with aiofiles.open(
                            file_save_path, "rb"
                        ) as f_existing_bytes:
                            content_bytes = await f_existing_bytes.read()
                            should_download = False
                            self.print_colored_ui(
                                f"Using local VDF file: {path}", "default"
                            )
                    except Exception as e_read:
                        self.print_colored_ui(
                            f"Could not read existing local file {path}: {e_read}, attempting download.",
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
                            f"\nFile download/update successful: {path}", "green"
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
                                f"Extracted {new_keys_count} new keys from {path}",
                                "magenta",
                            )
                        elif not depots_data and os.path.basename(path.lower()) in [
                            "key.vdf",
                            "config.vdf",
                        ]:
                            self.print_colored_ui(
                                f"No 'depots' section or empty in {path}", "yellow"
                            )
                    except Exception as e_vdf:
                        self.print_colored_ui(
                            f"\nFailed to parse VDF content for {path}: {self.stack_Error(e_vdf)}",
                            "red",
                        )
            elif should_download and not os.path.exists(file_save_path):
                self.print_colored_ui(f"\nFailed to download file: {path}", "red")
        except KeyboardInterrupt:
            self.print_colored_ui(
                f"\nProcessing interrupted by user for: {path}", "yellow"
            )
            self.cancel_search = True
        except Exception as e:
            self.print_colored_ui(
                f"\nProcessing failed for {path}: {self.stack_Error(e)}", "red"
            )
        return collected_depots

    async def _fetch_branch_zip_content(
        self, repo_full_name: str, app_id: str
    ) -> Optional[bytes]:
        url = f"https://github.com/{repo_full_name}/archive/refs/heads/{app_id}.zip"
        self.print_colored_ui(f"Attempting to download branch zip: {url}", "default")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=600)
                ) as r:
                    if r.status == 200:
                        self.print_colored_ui(
                            f"Successfully started downloading branch zip for AppID {app_id} from {repo_full_name}.",
                            "green",
                        )
                        content = await r.read()
                        self.print_colored_ui(
                            f"Finished downloading branch zip for AppID {app_id}.",
                            "green",
                        )
                        return content
                    else:
                        self.print_colored_ui(
                            f"Failed to download branch zip (Status: {r.status}) from {url}",
                            "red",
                        )
                        return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            self.print_colored_ui(
                f"Error downloading branch zip from {url}: {self.stack_Error(e)}", "red"
            )
            return None
        except Exception as e:
            self.print_colored_ui(
                f"Unexpected error fetching branch zip {url}: {self.stack_Error(e)}",
                "red",
            )
            return None

    async def _perform_download_operations(
        self, app_id_input: str, game_name: str, selected_repos: List[str]
    ) -> Tuple[List[Tuple[str, str]], Optional[str], bool]:
        app_id_list = [s for s in app_id_input.strip().split("-") if s.isdecimal()]
        if not app_id_list:
            self.print_colored_ui(f"\nInvalid AppID format: {app_id_input}", "red")
            return [], None, False
        app_id = app_id_list[0]
        sanitized_game_name = (
            "".join(c if c.isalnum() or c in " -_" else "" for c in game_name).strip()
            or f"AppID_{app_id}"
        )
        output_base_dir, final_output_name_stem = (
            "./Games",
            f"{sanitized_game_name} - {app_id}",
        )
        try:
            os.makedirs(output_base_dir, exist_ok=True)
        except OSError as e:
            self.print_colored_ui(
                f"Error creating base output directory {output_base_dir}: {self.stack_Error(e)}",
                "red",
            )
            return [], None, False
        overall_collected_depots: List[Tuple[str, str]] = []
        for repo_full_name in selected_repos:
            if self.cancel_search:
                self.print_colored_ui("\nDownload process cancelled by user.", "yellow")
                return overall_collected_depots, None, False
            repo_type = self.repos.get(repo_full_name)
            if not repo_type:
                self.print_colored_ui(
                    f"Repository {repo_full_name} not found in known repos. Skipping.",
                    "yellow",
                )
                continue
            if repo_type == "Branch":
                self.print_colored_ui(
                    f"\nProcessing BRANCH repository: {repo_full_name} for AppID: {app_id}",
                    "cyan",
                )
                final_branch_zip_path = os.path.join(
                    output_base_dir, f"{final_output_name_stem}.zip"
                )
                if os.path.exists(final_branch_zip_path):
                    self.print_colored_ui(
                        f"Branch ZIP already exists: {final_branch_zip_path}. Skipping download.",
                        "blue",
                    )
                    return [], final_branch_zip_path, True
                zip_content = await self._fetch_branch_zip_content(
                    repo_full_name, app_id
                )
                if self.cancel_search:
                    self.print_colored_ui(
                        "\nDownload cancelled during branch zip fetch.", "yellow"
                    )
                    return [], None, False
                if zip_content:
                    try:
                        async with aiofiles.open(final_branch_zip_path, "wb") as f_zip:
                            await f_zip.write(zip_content)
                            self.print_colored_ui(
                                f"Successfully saved branch download to {final_branch_zip_path}",
                                "green",
                            )
                            return [], final_branch_zip_path, True
                    except Exception as e_save:
                        self.print_colored_ui(
                            f"Failed to save branch zip to {final_branch_zip_path}: {self.stack_Error(e_save)}",
                            "red",
                        )
                else:
                    self.print_colored_ui(
                        f"Failed to download content for branch repo {repo_full_name}, AppID {app_id}. Trying next repo.",
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
                    f"Error creating processing directory {processing_dir_non_branch}: {self.stack_Error(e_mkdir)}. Skipping repo.",
                    "red",
                )
                continue
            self.print_colored_ui(
                f"\nSearching NON-BRANCH repository: {repo_full_name} for AppID: {app_id} (Type: {repo_type})",
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
                                f"AppID {app_id} not found as a branch in {repo_full_name} (Status: {r_b.status}). Trying next repo.",
                                "yellow",
                            )
                            continue
                        r_b_json = await r_b.json()
                        commit_data, sha, tree_url_base, date = (
                            r_b_json.get("commit", {}),
                            None,
                            None,
                            "Unknown date",
                        )
                        sha, tree_url_base = commit_data.get("sha"), commit_data.get(
                            "commit", {}
                        ).get("tree", {}).get("url")
                        date = (
                            commit_data.get("commit", {})
                            .get("author", {})
                            .get("date", "Unknown date")
                        )
                        if not sha or not tree_url_base:
                            self.print_colored_ui(
                                f"Invalid branch data (missing SHA or tree URL) for {repo_full_name}/{app_id}. Trying next repo.",
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
                                    f"Failed to get tree data for {repo_full_name}/{app_id} (Status: {r_t.status}). Trying next repo.",
                                    "red",
                                )
                                continue
                            r_t_json = await r_t.json()
                            if r_t_json.get("truncated"):
                                self.print_colored_ui(
                                    f"Warning: File tree for {repo_full_name}/{app_id} is truncated by GitHub API. Some files may be missed.",
                                    "yellow",
                                )
                            tree_items = r_t_json.get("tree", [])
                            if not tree_items:
                                self.print_colored_ui(
                                    f"No files found in tree for {repo_full_name}/{app_id}. Trying next repo.",
                                    "yellow",
                                )
                                continue
                            files_dl_proc_this_repo, key_file_found_proc = False, False
                            if self.strict_validation_var.get():
                                self.print_colored_ui(
                                    f"STRICT MODE: Processing branch {app_id} in {repo_full_name}...",
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
                                            f"STRICT: Found key file '{key_short_name}' at: {actual_key_file_path}",
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
                                                "STRICT: Keys obtained from primary 'key.vdf'.",
                                                "green",
                                            )
                                            break
                                if self.cancel_search:
                                    break
                                if not key_file_found_proc:
                                    self.print_colored_ui(
                                        f"STRICT: No Key.vdf or Config.vdf found or processed successfully in {repo_full_name}/{app_id}. This repo may not yield usable data in strict mode.",
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
                                    f"NON-STRICT MODE: Downloading all files from branch {app_id} in {repo_full_name}...",
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
                                    f"\nDownload cancelled during processing of {repo_full_name}.",
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
                                    f"\nData successfully processed for AppID {app_id} in {repo_full_name}. Last update: {date}",
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
                                        f"AppID {app_id} not successfully processed in {repo_full_name} with current settings. Trying next repo.",
                                        "yellow",
                                    )
                except (
                    aiohttp.ClientError,
                    asyncio.TimeoutError,
                    json.JSONDecodeError,
                ) as e:
                    self.print_colored_ui(
                        f"\nNetwork/API error with {repo_full_name}: {self.stack_Error(e)}. Trying next repo.",
                        "red",
                    )
                except KeyboardInterrupt:
                    self.print_colored_ui(
                        f"\nSearch interrupted by user for repository: {repo_full_name}",
                        "yellow",
                    )
                    self.cancel_search = True
                    break
            if self.cancel_search:
                break
        if self.cancel_search:
            self.print_colored_ui(
                "\nDownload process terminated by user request.", "yellow"
            )
            return overall_collected_depots, None, False
        self.print_colored_ui(
            f"\nAppID {app_id} could not be successfully processed from any selected repository with current settings.",
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
            for root, _, files in os.walk(processing_dir):
                [
                    all_manifest_files_in_dir.append(os.path.join(root, f_name))
                    for f_name in files
                    if f_name.lower().endswith(".manifest")
                ]

            def sort_key_manifest(filepath: str) -> Tuple[int, str]:
                filename, depot_id_str, manifest_id_val, depot_id_int = (
                    os.path.basename(filepath),
                    filename.split("_")[0] if "_" in filename else "",
                    "",
                    0,
                )
                if filename.lower().endswith(".manifest"):
                    manifest_id_val = (
                        filename[len(depot_id_str) + 1 : -len(".manifest")]
                        if depot_id_str and len(filename.split("_")) > 1
                        else ""
                    )
                try:
                    depot_id_int = int(depot_id_str) if depot_id_str.isdigit() else 0
                except ValueError:
                    self.print_colored_ui(
                        f"Warning: Non-numeric depot ID '{depot_id_str}' in manifest filename '{filename}'. Using 0 for sorting.",
                        "yellow",
                    )
                return (depot_id_int, manifest_id_val)

            try:
                all_manifest_files_in_dir.sort(key=sort_key_manifest)
            except Exception as e_sort:
                self.print_colored_ui(
                    f"Warning: Could not fully sort manifest files for LUA generation due to naming or error: {self.stack_Error(e_sort)}",
                    "yellow",
                )
            for manifest_full_path in all_manifest_files_in_dir:
                manifest_filename, parts = os.path.basename(
                    manifest_full_path
                ), manifest_filename.split("_")
                depot_id_from_file, manifest_gid_val = (
                    parts[0] if parts and parts[0].isdigit() else ""
                ), ""
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
                            f"Could not parse Manifest GID from: {manifest_filename}",
                            "yellow",
                        )
                else:
                    self.print_colored_ui(
                        f"Could not parse DepotID from: {manifest_filename}", "yellow"
                    )
        return "\n".join(lua_lines)

    def zip_outcome(
        self, processing_dir: str, selected_repos_for_zip: List[str]
    ) -> None:
        if not os.path.isdir(processing_dir):
            self.print_colored_ui(
                f"Processing directory {processing_dir} not found for zipping. Skipping zip.",
                "red",
            )
            return
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
        final_zip_name, final_zip_path = final_zip_base_name + (
            " - encrypted.zip" if is_encrypted_source else ".zip"
        ), os.path.join(final_zip_parent_dir, final_zip_name)
        if os.path.exists(final_zip_path):
            try:
                os.remove(final_zip_path)
                self.print_colored_ui(
                    f"Removed existing zip: {final_zip_path}", "yellow"
                )
            except OSError as e_del_zip:
                self.print_colored_ui(
                    f"Error removing existing zip {final_zip_path}: {self.stack_Error(e_del_zip)}. Archiving may fail.",
                    "red",
                )
        try:
            with zipfile.ZipFile(final_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(processing_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        if (
                            strict_mode_active
                            and os.path.basename(file.lower()) in key_files_to_exclude
                        ):
                            self.print_colored_ui(
                                f"Excluding {file} from zip (strict mode active).",
                                "yellow",
                            )
                            continue
                        zipf.write(
                            file_path, os.path.relpath(file_path, start=processing_dir)
                        )
            self.print_colored_ui(f"\nZipped outcome to {final_zip_path}", "cyan")
            try:
                import shutil

                shutil.rmtree(processing_dir)
                self.print_colored_ui(
                    f"Source folder {processing_dir} deleted successfully.", "green"
                )
            except OSError as e_del:
                self.print_colored_ui(
                    f"Error deleting source folder {processing_dir}: {self.stack_Error(e_del)}",
                    "red",
                )
        except (zipfile.BadZipFile, OSError, FileNotFoundError) as e_zip:
            self.print_colored_ui(
                f"Error creating zip file {final_zip_path}: {self.stack_Error(e_zip)}",
                "red",
            )
        except Exception as e_generic_zip:
            self.print_colored_ui(
                f"An unexpected error occurred during zipping: {self.stack_Error(e_generic_zip)}",
                "red",
            )

    def on_closing(self) -> None:
        if messagebox.askokcancel("Quit", "Do you want to quit?"):
            self.cancel_search = True
            if self.initial_load_thread and self.initial_load_thread.is_alive():
                self.print_colored_ui(
                    "Attempting to stop initial app list loading...", "yellow"
                )
            if self.search_thread and self.search_thread.is_alive():
                self.print_colored_ui("Attempting to stop search thread...", "yellow")
            self.destroy()

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
            self.print_colored_ui(f"No {repo_type} repositories to toggle.", "yellow")
            return

        new_state: bool = not all_relevant_selected

        for repo_name, stored_repo_type in self.repos.items():
            if (
                stored_repo_type.lower() == repo_type.lower()
                and repo_name in self.repo_vars
            ):
                self.repo_vars[repo_name].set(new_state)

        action_str: str = "Selected" if new_state else "Deselected"
        self.print_colored_ui(
            f"{action_str} all {repo_type} repositories.",
            "blue",
        )

    def open_add_repo_window(self) -> None:
        if (
            hasattr(self, "add_repo_window_ref")
            and self.add_repo_window_ref.winfo_exists()
        ):
            self.add_repo_window_ref.focus()
            return
        self.add_repo_window_ref = ctk.CTkToplevel(self)
        self.add_repo_window_ref.title("Add Repository")
        self.add_repo_window_ref.geometry("400x220")
        self.add_repo_window_ref.resizable(False, False)
        self.add_repo_window_ref.transient(self)
        self.add_repo_window_ref.grab_set()
        ctk.CTkLabel(
            self.add_repo_window_ref, text="Repository Name (e.g., user/repo):"
        ).pack(padx=10, pady=(10, 2))
        self.repo_name_entry = ctk.CTkEntry(self.add_repo_window_ref, width=360)
        self.repo_name_entry.pack(padx=10, pady=(0, 5))
        self.repo_name_entry.focus()
        ctk.CTkLabel(self.add_repo_window_ref, text="Repository Type:").pack(
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
            self.add_repo_window_ref, text="Add", command=self.add_repo, width=100
        ).pack(padx=10, pady=10)
        self.add_repo_window_ref.protocol(
            "WM_DELETE_WINDOW", self.add_repo_window_ref.destroy
        )

    def add_repo(self) -> None:
        if (
            not hasattr(self, "add_repo_window_ref")
            or not self.add_repo_window_ref.winfo_exists()
        ):
            self.print_colored_ui("Add repo window not available.", "red")
            return
        repo_name, repo_state = (
            self.repo_name_entry.get().strip(),
            self.repo_state_var.get(),
        )
        if not repo_name:
            messagebox.showwarning(
                "Input Error",
                "Please enter repository name.",
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
                "Input Error",
                "Repository name must be in 'user/repo' format without spaces, leading/trailing slashes.",
                parent=self.add_repo_window_ref,
            )
            return
        if repo_name in self.repos:
            messagebox.showwarning(
                "Input Error",
                f"Repository '{repo_name}' already exists.",
                parent=self.add_repo_window_ref,
            )
            return
        self.repos[repo_name], self.save_repositories(), self.refresh_repo_checkboxes()
        self.print_colored_ui(f"Added repository: {repo_name} ({repo_state})", "green")
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
                "Selection Error",
                "Please select at least one repository to delete by checking its box.",
            )
            return
        if not messagebox.askyesno(
            "Confirm Deletion",
            f"Are you sure you want to delete these {len(repos_to_delete)} repositories?\n\n- "
            + "\n- ".join(repos_to_delete),
        ):
            return
        deleted_count = sum(
            1
            for repo in repos_to_delete
            if repo in self.repos and self.repos.pop(repo, None)
        )
        if deleted_count > 0:
            self.save_repositories(), self.refresh_repo_checkboxes(), self.print_colored_ui(
                f"Deleted {deleted_count} repositories: {', '.join(repos_to_delete)}",
                "red",
            )
        else:
            self.print_colored_ui(
                "No matching repositories found in data to delete.", "yellow"
            )

    def refresh_repo_checkboxes(self) -> None:

        [
            w.destroy()
            for sf in [self.encrypted_scroll, self.decrypted_scroll, self.branch_scroll]
            for w in sf.winfo_children()
        ]

        new_repo_vars = {}

        sorted_repo_names = sorted(self.repos.keys())

        for repo_name in sorted_repo_names:
            repo_state = self.repos[repo_name]

            is_selected_default = self.repo_vars.get(
                repo_name, ctk.BooleanVar(value=(repo_state == "Branch"))
            ).get()

            var = ctk.BooleanVar(value=is_selected_default)
            new_repo_vars[repo_name] = var

            target_scroll_frame = None
            if repo_state == "Encrypted":
                target_scroll_frame = self.encrypted_scroll
            elif repo_state == "Decrypted":
                target_scroll_frame = self.decrypted_scroll
            elif repo_state == "Branch":
                target_scroll_frame = self.branch_scroll
            else:
                self.print_colored_ui(
                    f"Unknown repo state '{repo_state}' for '{repo_name}'. Assigning to Decrypted section.",
                    "yellow",
                )
                target_scroll_frame = self.decrypted_scroll

            if target_scroll_frame:
                cb = ctk.CTkCheckBox(target_scroll_frame, text=repo_name, variable=var)
                cb.pack(anchor="w", padx=10, pady=2)

        self.repo_vars = new_repo_vars

    def open_info_window(self) -> None:
        if hasattr(self, "info_window_ref") and self.info_window_ref.winfo_exists():
            self.info_window_ref.focus()
            return
        self.info_window_ref = ctk.CTkToplevel(self)
        self.info_window_ref.title("App Information")
        self.info_window_ref.geometry("650x500")
        self.info_window_ref.resizable(True, True)
        self.info_window_ref.transient(self)
        self.info_window_ref.grab_set()
        info_text_frame = ctk.CTkFrame(self.info_window_ref)
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
            ("Steam Depot Online (SDO) - Version: 1.5.5\n", "title"),
            ("Author: ", "bold"),
            ("FairyRoot\n", "highlight"),
            ("Contact (Telegram): ", "normal"),
            ("t.me/FairyRoot\n\n", "url"),
            ("Overview:\n", "subtitle"),
            (
                "SDO fetches Steam game data from GitHub repositories. For 'Encrypted' and 'Decrypted' repo types, it can generate Lua scripts (for emulators) and zips the results. For 'Branch' repo types, it downloads and saves the GitHub branch zip directly. All successful outputs are placed in:\n`./Games/{GameName}-{AppID}.zip`\n\n",
                "normal",
            ),
            ("Key Features:\n", "subtitle"),
            (
                "- Add/delete GitHub repositories (user/repo format) with types: Encrypted, Decrypted, Branch.\n",
                "normal",
            ),
            ("- Select multiple repositories for download attempts.\n", "normal"),
            (
                "- Toggle 'Strict Validation' for non-Branch repositories (see below).\n",
                "normal",
            ),
            (
                "- Search games by Name (uses Steam's full app list) or directly by AppID (uses Steam API).\n",
                "normal",
            ),
            (
                "- View detailed game info (description, logo/header images, links) upon selection using Steam API.\n",
                "normal",
            ),
            (
                "- Download process priorities: For non-Branch, it attempts selected repos in order until success. Branch types are also attempted in order.\n",
                "normal",
            ),
            (
                "- Generates .lua scripts for Steam emulators (for non-Branch types that yield decryption keys).\n",
                "normal",
            ),
            (
                "- Zips downloaded files and .lua script (for non-Branch types). Branch types are saved as downloaded .zip.\n\n",
                "normal",
            ),
            ("1. Repository Types Explained:\n", "subtitle"),
            ("   - Decrypted Repositories: ", "bold"),
            (
                "(Often preferred)\n     Usually contain necessary decryption keys (e.g., `key.vdf`). Games from these are more likely to be ready for use with emulators. Output is a tool-generated ZIP: `./Games/{GameName}-{AppID}.zip` containing processed files and a .lua script.\n",
                "normal",
            ),
            ("   - Encrypted Repositories: ", "bold"),
            (
                "\n     May have the latest game manifests but decryption keys within their `key.vdf`/`config.vdf` might be hashed, partial, or invalid. A .lua script is generated (can be minimal if no valid keys found). Output is a tool-generated ZIP like Decrypted ones.\n",
                "note",
            ),
            ("   - Branch Repositories: ", "bold"),
            (
                "\n     (Selected by default for new repos and on startup)\n     Downloads a direct .zip archive of an entire AppID-named branch from a GitHub repository (e.g., `main` or `1245620`). This downloaded .zip is saved *as is* directly to `./Games/{GameName}-{AppID}.zip`. **No .lua script is generated by SDO, and no further zipping or file processing is performed by SDO for this type.** 'Strict Validation' does not apply.\n\n",
                "normal",
            ),
            (
                "   *Recommendation for Playable Games:* Prioritize 'Decrypted' repositories. 'Branch' repos provide raw game data zips which might be useful for archival or manual setup.\n",
                "normal",
            ),
            (
                "   *For Latest Manifests (Advanced Users):* 'Encrypted' repos might offer newer files, but you may need to source decryption keys elsewhere.\n\n",
                "normal",
            ),
            ("2. 'Strict Validation' Checkbox:\n", "subtitle"),
            (
                "   - Applies ONLY to 'Encrypted'/'Decrypted' (non-Branch) repositories.\n",
                "note",
            ),
            ("   - Checked (Default): ", "bold"),
            (
                "SDO requires a `key.vdf` or `config.vdf` to be present in the GitHub branch. It will prioritize downloading and parsing these key files. If valid decryption keys are found, associated `.manifest` files are also downloaded. The final tool-generated ZIP will *exclude* the `key.vdf`/`config.vdf` itself.\n",
                "normal",
            ),
            ("   - Unchecked: ", "bold"),
            (
                "SDO downloads all files from the GitHub branch. If `key.vdf`/`config.vdf` are present, they are parsed for keys. All downloaded files, *including* any `key.vdf`/`config.vdf`, WILL be included in the final tool-generated ZIP.\n\n",
                "normal",
            ),
            ("3. How to Use:\n", "subtitle"),
            (
                "   1. Add GitHub repositories via 'Add Repo' (e.g., `SomeUser/SomeRepo`). Select the correct type (Encrypted, Decrypted, Branch).\n",
                "normal",
            ),
            (
                "   2. Select checkboxes for repositories you want to use for downloads.\n",
                "normal",
            ),
            (
                "   3. Configure 'Strict Validation' as needed (affects non-Branch downloads).\n",
                "normal",
            ),
            (
                "   4. Enter a game name or AppID and click 'Search'. Wait for the initial app list to load on first use.\n",
                "normal",
            ),
            (
                "   5. Select a game from the search results. Game details (images, text) will appear in the Progress panel.\n",
                "normal",
            ),
            (
                "   6. Click 'Download'. SDO will attempt to fetch from selected repos. The final output for any successful download will be `./Games/{GameName}-{AppID}.zip`.\n\n",
                "normal",
            ),
            ("4. Potential Issues & Notes:\n", "subtitle"),
            (
                "   - Image Display: Game logo/header requires Pillow (`pip install Pillow`). If not installed, images won't show.\n",
                "note",
            ),
            (
                "   - 'Content is still encrypted' (in-game error, non-Branch output): The game files were downloaded, but valid decryption keys were not found or applied correctly by the emulator. Try a different 'Decrypted' repository or ensure your emulator setup is correct.\n",
                "normal",
            ),
            (
                "   - Rate-limiting: GitHub or Steam APIs may temporarily limit requests if used excessively. Wait or consider a VPN for GitHub CDN access if issues persists.\n",
                "normal",
            ),
            ("   - Internet: A stable internet connection is required.\n", "normal"),
            (
                "   - Repository Order: The order of repositories in `repositories.json` (added order) can influence which one is tried first, but selection is primary. The tool iterates through *selected* repos.\n\n",
                "normal",
            ),
        ]
        for text, tag_name in info_content:
            info_textbox.insert("end", text, tag_name)
        info_textbox.tag_add("center_title", "1.0", "1.end")
        info_textbox.tag_configure("center_title", justify="center")
        info_textbox.configure(state="disabled")
        self.info_window_ref.protocol("WM_DELETE_WINDOW", self.info_window_ref.destroy)
        self.info_window_ref.after(100, self.info_window_ref.focus_force)


if __name__ == "__main__":
    app = ManifestDownloader()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
