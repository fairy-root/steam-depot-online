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

        self.repos: Dict[str, str] = self.load_repositories()
        self.selected_repos: Dict[str, bool] = {repo: True for repo in self.repos}
        self.repo_vars: Dict[str, ctk.BooleanVar] = {}
        self.appid_to_game: Dict[str, str] = {}
        self.selected_appid: Optional[str] = None
        self.selected_game_name: Optional[str] = None
        self.search_thread: Optional[threading.Thread] = None
        self.cancel_search: bool = False
        self.loop: Optional[asyncio.AbstractEventLoop] = None

        self.setup_ui()

    def load_repositories(self) -> Dict[str, str]:
        """Loads repository data from repositories.json."""
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
        """Saves current repository data to repositories.json."""
        try:
            with open("repositories.json", "w", encoding="utf-8") as f:
                json.dump(self.repos, f, indent=4)
        except IOError:
            messagebox.showerror("Save Error", "Failed to save repositories.json.")

    def setup_ui(self) -> None:
        """Sets up the main user interface components."""
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
        search_button = ctk.CTkButton(
            input_frame, text="Search", width=90, command=self.search_game
        )
        search_button.pack(padx=9, pady=4.5, side="left")
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

    def append_progress(self, message: str, color: str = "default") -> None:
        def inner() -> None:
            self.progress_text.configure(state="normal")
            self.progress_text.insert(END, message + "\n", color)
            self.progress_text.see(END)
            self.progress_text.configure(state="disabled")

        self.after(0, inner)

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

        self.progress_text.configure(state="normal")
        self.progress_text.delete("1.0", END)
        self.progress_text.configure(state="disabled")

        self.cancel_search = False
        self.search_thread = threading.Thread(
            target=self.run_search, args=(user_input,), daemon=True
        )
        self.search_thread.start()

    def run_search(self, user_input: str) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self.async_search_game(user_input))
        finally:
            self.loop.close()

    async def async_search_game(self, user_input: str) -> None:
        self.append_progress(f"Searching for '{user_input}'...", "cyan")
        games: List[Dict[str, Any]] = await self.find_appid_by_name(user_input)
        if self.cancel_search:
            self.append_progress("\nSearch cancelled by user.", "yellow")
            return

        if not games:
            self.append_progress(
                "\nNo matching games found. Please try another name.", "red"
            )
            return

        self.appid_to_game.clear()
        for idx, game in enumerate(games, 1):
            if self.cancel_search:
                self.append_progress("\nSearch cancelled by user.", "yellow")
                return
            appid: str = str(game.get("appid", "Unknown"))
            game_name: str = game.get("name", "Unknown Game")
            self.appid_to_game[appid] = game_name
            self.after(0, partial(self.create_radio_button, idx, appid, game_name))

        self.append_progress(
            f"\nFound {len(games)} matching game(s). Please select one.", "cyan"
        )

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
            self.append_progress(
                f"Selected: {self.selected_game_name} (AppID: {self.selected_appid})",
                "green",
            )
            self.download_button.configure(state="normal")
        else:
            self.append_progress("Selected game not found in mapping.", "red")
            self.download_button.configure(state="disabled")

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
        self.progress_text.configure(state="normal")
        self.progress_text.delete("1.0", END)
        self.progress_text.configure(state="disabled")

        self.cancel_search = False
        threading.Thread(
            target=self.run_download,
            args=(self.selected_appid, self.selected_game_name, selected_repo_list),
            daemon=True,
        ).start()

    def run_download(
        self, appid: str, game_name: str, selected_repos: List[str]
    ) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(
                self.async_download_and_process(appid, game_name, selected_repos)
            )
        finally:
            self.loop.close()

    async def async_download_and_process(
        self, appid: str, game_name: str, selected_repos: List[str]
    ) -> None:
        """
        Asynchronously downloads data based on repository type.
        For "Branch" type, it saves the downloaded zip directly.
        For other types, it processes files, generates Lua, and zips the outcome.
        """

        collected_depots, output_path_or_processing_dir, source_was_branch = (
            await self._perform_download_operations(appid, game_name, selected_repos)
        )

        if self.cancel_search:
            self.append_progress("\nDownload cancelled by user.", "yellow")
            self.after(0, lambda: self.download_button.configure(state="normal"))
            return

        if source_was_branch:
            if output_path_or_processing_dir and os.path.isfile(
                output_path_or_processing_dir
            ):
                self.append_progress(
                    f"\nBranch repository download successful.", "green"
                )
                self.append_progress(
                    f"Output saved directly to: {output_path_or_processing_dir}", "blue"
                )
                self.append_progress(
                    "This is the direct download from the branch repository.", "blue"
                )
            else:
                self.append_progress(
                    "\nBranch repository processing completed, but the expected zip file was not found or path was invalid.",
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
                    f"\n\nGenerated {game_name} unlock file: {lua_file_path}", "blue"
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
            self.append_progress(
                "\nDownload process failed or was interrupted before any files could be saved or path was invalid.",
                "red",
            )
            if output_path_or_processing_dir:
                self.append_progress(
                    f"Returned path: {output_path_or_processing_dir}", "red"
                )

        self.after(0, lambda: self.download_button.configure(state="normal"))

    def print_colored_ui(self, text: str, color: str) -> None:
        self.append_progress(text, color)

    def stack_Error(self, e: Exception) -> str:
        return f"{type(e).__name__}: {e}"

    async def search_game_info(self, search_term: str) -> List[Dict[str, Any]]:
        games: List[Dict[str, Any]] = []
        page: int = 1
        limit: int = 100
        search_term_encoded: str = search_term.replace(" ", "%20")

        async with aiohttp.ClientSession() as session:
            while True:
                if self.cancel_search:
                    self.print_colored_ui(
                        "\nGame info search cancelled by user.", "yellow"
                    )
                    return []
                try:
                    url: str = (
                        f"https://steamui.com/loadGames.php?page={page}&search={search_term_encoded}"
                    )
                    async with session.get(
                        url, timeout=aiohttp.ClientTimeout(total=15)
                    ) as r:
                        if r.status == 200:
                            content: str = await r.text()
                            try:
                                data: Dict[str, Any] = json.loads(content)
                                new_games: List[Dict[str, Any]] = data.get("games", [])
                                if not new_games:
                                    break
                                games.extend(new_games)
                                if len(new_games) < limit:
                                    break
                                page += 1
                            except json.JSONDecodeError:
                                self.print_colored_ui(
                                    "\nFailed to decode JSON response from steamui.com.",
                                    "red",
                                )
                                break
                        else:
                            self.print_colored_ui(
                                f"\nFailed to obtain game information from steamui.com (Status: {r.status})",
                                "red",
                            )
                            break
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    self.print_colored_ui(
                        f"\nError during steamui.com search: {self.stack_Error(e)}",
                        "red",
                    )
                    break
                except KeyboardInterrupt:
                    self.print_colored_ui(
                        "\nGame info search interrupted by user (Ctrl+C).", "yellow"
                    )
                    break
        return games

    async def find_appid_by_name(self, game_name: str) -> List[Dict[str, Any]]:
        games: List[Dict[str, Any]] = await self.search_game_info(game_name)
        if self.cancel_search:
            return []
        if not games:
            self.print_colored_ui(
                f"\nNo matching game found for '{game_name}' on steamui.com.", "red"
            )
        return games

    async def get(self, sha: str, path: str, repo: str) -> Optional[bytes]:
        url_list: List[str] = [
            f"https://gcore.jsdelivr.net/gh/{repo}@{sha}/{path}",
            f"https://fastly.jsdelivr.net/gh/{repo}@{sha}/{path}",
            f"https://cdn.jsdelivr.net/gh/{repo}@{sha}/{path}",
            f"https://ghproxy.org/https://raw.githubusercontent.com/{repo}/{sha}/{path}",
            f"https://raw.dgithub.xyz/{repo}/{sha}/{path}",
            f"https://raw.githubusercontent.com/{repo}/{sha}/{path}",
        ]
        max_retries_per_url: int = 1
        overall_attempts: int = 2

        async with aiohttp.ClientSession() as session:
            for attempt in range(overall_attempts):
                for url in url_list:
                    if self.cancel_search:
                        self.print_colored_ui(
                            f"\nDownload cancelled by user for: {path}", "yellow"
                        )
                        return None
                    for retry_num in range(max_retries_per_url + 1):
                        try:
                            async with session.get(
                                url, ssl=False, timeout=aiohttp.ClientTimeout(total=20)
                            ) as r:
                                if r.status == 200:
                                    return await r.read()
                                else:
                                    if r.status == 404:
                                        break
                        except (aiohttp.ClientError, asyncio.TimeoutError):
                            pass
                        except KeyboardInterrupt:
                            self.print_colored_ui(
                                f"\nDownload interrupted by user for: {path}", "yellow"
                            )
                            return None
                        if retry_num < max_retries_per_url and not self.cancel_search:
                            await asyncio.sleep(0.5)
                        else:
                            break
                if attempt < overall_attempts - 1 and not self.cancel_search:
                    self.print_colored_ui(
                        f"\nRetrying download cycle for: {path} (Cycle {attempt + 2}/{overall_attempts})",
                        "yellow",
                    )
                    await asyncio.sleep(1)
        self.print_colored_ui(f"\nMaximum attempts exceeded for: {path}", "red")
        return None

    async def get_manifest(
        self, sha: str, path: str, processing_dir: str, repo: str
    ) -> List[Tuple[str, str]]:
        collected_depots: List[Tuple[str, str]] = []
        try:
            file_save_path = os.path.join(processing_dir, path)
            os.makedirs(os.path.dirname(file_save_path), exist_ok=True)

            content_bytes: Optional[bytes] = None
            if os.path.exists(file_save_path):
                if path.lower().endswith((".vdf")):
                    try:
                        async with aiofiles.open(
                            file_save_path, "rb"
                        ) as f_existing_bytes:
                            content_bytes = await f_existing_bytes.read()
                    except Exception as e_read:
                        self.print_colored_ui(
                            f"Could not read existing local file {path}: {e_read}, attempting download.",
                            "yellow",
                        )
                        content_bytes = None

            if content_bytes is None and not (
                path.endswith(".manifest") and os.path.exists(file_save_path)
            ):
                content_bytes = await self.get(sha, path, repo)

            if self.cancel_search:
                return collected_depots

            if content_bytes:
                if not os.path.exists(file_save_path) or not path.endswith(".manifest"):
                    async with aiofiles.open(file_save_path, "wb") as f_new:
                        await f_new.write(content_bytes)
                    self.print_colored_ui(
                        f"\nFile download/update successful: {path}", "green"
                    )

                if os.path.basename(path.lower()) in ["key.vdf", "config.vdf"]:
                    try:
                        depots_config = vdf.loads(
                            content_bytes.decode(encoding="utf-8", errors="ignore")
                        )
                        for depot_id_str, depot_info in depots_config.get(
                            "depots", {}
                        ).items():
                            if "DecryptionKey" in depot_info:
                                key_tuple = (
                                    str(depot_id_str),
                                    depot_info["DecryptionKey"],
                                )
                                if key_tuple not in collected_depots:
                                    collected_depots.append(key_tuple)
                        if collected_depots:
                            self.print_colored_ui(
                                f"Extracted {len(collected_depots)} keys from {path}",
                                "magenta",
                            )
                    except Exception as e_vdf:
                        self.print_colored_ui(
                            f"\nFailed to parse VDF content for {path}: {self.stack_Error(e_vdf)}",
                            "red",
                        )
            elif not os.path.exists(file_save_path):
                self.print_colored_ui(f"\nFailed to download file: {path}", "red")

        except KeyboardInterrupt:
            self.print_colored_ui(
                f"\nProcessing interrupted by user for: {path}", "yellow"
            )
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
                            f"Successfully downloaded branch zip for AppID {app_id} from {repo_full_name}.",
                            "green",
                        )
                        return await r.read()
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

    async def _perform_download_operations(
        self, app_id_input: str, game_name: str, selected_repos: List[str]
    ) -> Tuple[List[Tuple[str, str]], Optional[str], bool]:
        """
        Core logic for downloading and processing game data.
        Returns:
            - Tuple of (collected_depots, output_path, source_was_branch_repo)
            - output_path:
                - For Branch: Path to the saved .zip file (e.g., "./Games/Game - AppID.zip")
                - For Non-Branch: Path to the processing directory (e.g., "./Games/Game - AppID/")
                - None on major failure.
        """
        app_id_list: List[str] = [
            s for s in app_id_input.strip().split("-") if s.isdecimal()
        ]
        if not app_id_list:
            self.print_colored_ui(f"\nInvalid AppID format: {app_id_input}", "red")
            return [], None, False
        app_id: str = app_id_list[0]

        sanitized_game_name = "".join(
            c if c.isalnum() or c in " -_" else "" for c in game_name
        )
        output_base_dir = "./Games"
        final_output_name_stem = f"{sanitized_game_name} - {app_id}"

        try:
            os.makedirs(output_base_dir, exist_ok=True)
        except OSError as e:
            self.print_colored_ui(
                f"Error creating base output directory {output_base_dir}: {self.stack_Error(e)}",
                "red",
            )
            return [], None, False

        overall_collected_depots: List[Tuple[str, str]] = []
        source_was_branch_repo: bool = False

        try:
            for repo_full_name in selected_repos:
                if self.cancel_search:
                    self.print_colored_ui(
                        "\nDownload process cancelled by user.", "yellow"
                    )
                    return overall_collected_depots, None, source_was_branch_repo

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
                    zip_content = await self._fetch_branch_zip_content(
                        repo_full_name, app_id
                    )

                    if zip_content:
                        try:
                            async with aiofiles.open(
                                final_branch_zip_path, "wb"
                            ) as f_zip:
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
                            f"Failed to download content for branch repo {repo_full_name}, AppID {app_id}.",
                            "yellow",
                        )
                    continue

                processing_dir_for_non_branch = os.path.join(
                    output_base_dir, final_output_name_stem
                )
                try:
                    os.makedirs(processing_dir_for_non_branch, exist_ok=True)
                except OSError as e_mkdir_non_branch:
                    self.print_colored_ui(
                        f"Error creating processing directory {processing_dir_for_non_branch}: {self.stack_Error(e_mkdir_non_branch)}",
                        "red",
                    )
                    continue

                self.print_colored_ui(
                    f"\nSearching repository: {repo_full_name} for AppID: {app_id} (Type: {repo_type})",
                    "cyan",
                )
                api_url: str = (
                    f"https://api.github.com/repos/{repo_full_name}/branches/{app_id}"
                )

                async with aiohttp.ClientSession() as session:
                    try:
                        async with session.get(
                            api_url, ssl=False, timeout=aiohttp.ClientTimeout(total=15)
                        ) as r_branch:
                            if r_branch.status != 200:
                                self.print_colored_ui(
                                    f"AppID {app_id} not found as a branch in {repo_full_name} (Status: {r_branch.status}).",
                                    "yellow",
                                )
                                continue
                            r_branch_json: Dict[str, Any] = await r_branch.json()
                            commit_data = r_branch_json.get("commit", {})
                            sha: Optional[str] = commit_data.get("sha")
                            tree_url: Optional[str] = (
                                commit_data.get("commit", {}).get("tree", {}).get("url")
                            )
                            date: str = (
                                commit_data.get("commit", {})
                                .get("author", {})
                                .get("date", "Unknown date")
                            )

                            if not sha or not tree_url:
                                self.print_colored_ui(
                                    f"Invalid branch data (missing SHA or tree URL) from GitHub API for {repo_full_name}/{app_id}.",
                                    "red",
                                )
                                continue

                            async with session.get(
                                f"{tree_url}?recursive=1",
                                ssl=False,
                                timeout=aiohttp.ClientTimeout(total=20),
                            ) as r_tree:
                                if r_tree.status != 200:
                                    self.print_colored_ui(
                                        f"Failed to get tree data for {repo_full_name}/{app_id} (Status: {r_tree.status}).",
                                        "red",
                                    )
                                    continue
                                r_tree_json: Dict[str, Any] = await r_tree.json()
                                tree_items: List[Dict[str, Any]] = r_tree_json.get(
                                    "tree", []
                                )
                                if not tree_items:
                                    self.print_colored_ui(
                                        f"No files found in tree for {repo_full_name}/{app_id}.",
                                        "yellow",
                                    )
                                    continue

                                current_repo_collected_depots: List[Tuple[str, str]] = (
                                    []
                                )
                                files_downloaded_or_processed_this_repo: bool = False
                                repo_considered_successful_for_app: bool = False

                                if self.strict_validation_var.get():
                                    self.print_colored_ui(
                                        f"STRICT MODE: Processing branch {app_id} in {repo_full_name}...",
                                        "magenta",
                                    )
                                    preferred_key_filenames: List[str] = [
                                        "key.vdf",
                                        "config.vdf",
                                    ]
                                    found_and_processed_keys_from_pref: List[
                                        Tuple[str, str]
                                    ] = []

                                    for key_short_name in preferred_key_filenames:
                                        if self.cancel_search:
                                            break
                                        actual_key_file_full_path: Optional[str] = None
                                        for item in tree_items:
                                            item_full_path: str = item.get("path", "")
                                            if (
                                                os.path.basename(item_full_path.lower())
                                                == key_short_name
                                            ):
                                                actual_key_file_full_path = (
                                                    item_full_path
                                                )
                                                break
                                        if actual_key_file_full_path:
                                            self.print_colored_ui(
                                                f"STRICT: Found key file '{key_short_name}' at: {actual_key_file_full_path}",
                                                "default",
                                            )
                                            depot_keys_from_vdf = (
                                                await self.get_manifest(
                                                    sha,
                                                    actual_key_file_full_path,
                                                    processing_dir_for_non_branch,
                                                    repo_full_name,
                                                )
                                            )
                                            if depot_keys_from_vdf:
                                                found_and_processed_keys_from_pref.extend(
                                                    dk
                                                    for dk in depot_keys_from_vdf
                                                    if dk
                                                    not in found_and_processed_keys_from_pref
                                                )
                                                files_downloaded_or_processed_this_repo = (
                                                    True
                                                )
                                            if (
                                                key_short_name == "key.vdf"
                                                and found_and_processed_keys_from_pref
                                            ):
                                                self.print_colored_ui(
                                                    f"STRICT: Keys obtained from primary 'key.vdf'.",
                                                    "green",
                                                )
                                                break
                                    if self.cancel_search:
                                        break
                                    current_repo_collected_depots.extend(
                                        found_and_processed_keys_from_pref
                                    )
                                    if not self.cancel_search:
                                        for item in tree_items:
                                            if self.cancel_search:
                                                break
                                            item_full_path: str = item.get("path", "")
                                            if item_full_path.endswith(".manifest"):
                                                await self.get_manifest(
                                                    sha,
                                                    item_full_path,
                                                    processing_dir_for_non_branch,
                                                    repo_full_name,
                                                )
                                                if os.path.exists(
                                                    os.path.join(
                                                        processing_dir_for_non_branch,
                                                        item_full_path,
                                                    )
                                                ):
                                                    files_downloaded_or_processed_this_repo = (
                                                        True
                                                    )
                                    if self.cancel_search:
                                        break
                                    repo_considered_successful_for_app = bool(
                                        current_repo_collected_depots
                                    )
                                else:
                                    self.print_colored_ui(
                                        f"NON-STRICT MODE: Downloading all files from branch {app_id} in {repo_full_name}...",
                                        "magenta",
                                    )
                                    for item in tree_items:
                                        if self.cancel_search:
                                            break
                                        item_full_path: str = item.get("path", "")
                                        item_type: str = item.get("type", "")
                                        if item_type == "blob":
                                            keys_from_this_file = (
                                                await self.get_manifest(
                                                    sha,
                                                    item_full_path,
                                                    processing_dir_for_non_branch,
                                                    repo_full_name,
                                                )
                                            )
                                            if keys_from_this_file:
                                                current_repo_collected_depots.extend(
                                                    dk
                                                    for dk in keys_from_this_file
                                                    if dk
                                                    not in current_repo_collected_depots
                                                )
                                            if os.path.exists(
                                                os.path.join(
                                                    processing_dir_for_non_branch,
                                                    item_full_path,
                                                )
                                            ):
                                                files_downloaded_or_processed_this_repo = (
                                                    True
                                                )
                                    if self.cancel_search:
                                        break
                                    repo_considered_successful_for_app = (
                                        files_downloaded_or_processed_this_repo
                                    )

                                if repo_considered_successful_for_app:
                                    self.print_colored_ui(
                                        f"\nData successfully processed for AppID {app_id} in {repo_full_name}. Last update: {date}",
                                        "green",
                                    )
                                    overall_collected_depots.extend(
                                        dk_repo
                                        for dk_repo in current_repo_collected_depots
                                        if dk_repo not in overall_collected_depots
                                    )
                                    return (
                                        overall_collected_depots,
                                        processing_dir_for_non_branch,
                                        False,
                                    )

                    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                        self.print_colored_ui(
                            f"\nNetwork error accessing {repo_full_name}: {self.stack_Error(e)}",
                            "red",
                        )
                    except KeyboardInterrupt:
                        self.print_colored_ui(
                            f"\nSearch interrupted by user for repository: {repo_full_name}",
                            "yellow",
                        )
                        return overall_collected_depots, None, source_was_branch_repo

                if not self.cancel_search and repo_type != "Branch":
                    self.print_colored_ui(
                        f"\nAppID {app_id} not successfully processed in {repo_full_name} with current validation settings.",
                        "yellow",
                    )

            self.print_colored_ui(
                f"\nAppID {app_id} could not be successfully processed from any selected repository.",
                "red",
            )
            return [], None, False

        except KeyboardInterrupt:
            self.print_colored_ui(
                "\nDownload and process interrupted by user.", "yellow"
            )
            return [], None, source_was_branch_repo
        except Exception as e_outer:
            self.print_colored_ui(
                f"\nUnexpected error in download_and_process: {self.stack_Error(e_outer)}",
                "red",
            )
            return [], None, False

    def parse_vdf_to_lua(
        self, depot_info: List[Tuple[str, str]], appid: str, processing_dir: str
    ) -> str:
        """
        Generates Lua script. For non-branch repos, `processing_dir` contains loose files.
        This function is NOT called for branch repository successes.
        """
        lua_lines: List[str] = [f"addappid({appid})"]
        processed_depots_for_setmanifest: set[str] = set()

        for depot_id, decryption_key in depot_info:
            lua_lines.append(f'addappid({depot_id},1,"{decryption_key}")')
            processed_depots_for_setmanifest.add(depot_id)

        if os.path.isdir(processing_dir):
            all_manifest_files_in_dir: List[str] = []
            for root, _, files in os.walk(processing_dir):
                for f_name in files:
                    if f_name.endswith(".manifest"):
                        all_manifest_files_in_dir.append(os.path.join(root, f_name))

            def sort_key_manifest(filepath: str) -> Tuple[int, str]:
                filename = os.path.basename(filepath)
                parts = filename.split("_")
                depot_id_str = parts[0]
                manifest_id_val = (
                    filename[len(depot_id_str) + 1 : -len(".manifest")]
                    if len(parts) > 1
                    else ""
                )
                return (
                    int(depot_id_str) if depot_id_str.isdigit() else 0,
                    manifest_id_val,
                )

            try:
                all_manifest_files_in_dir.sort(key=sort_key_manifest)
            except ValueError:
                self.print_colored_ui(
                    "Warning: Could not fully sort manifest files for LUA generation due to naming.",
                    "yellow",
                )

            for manifest_full_path in all_manifest_files_in_dir:
                manifest_filename = os.path.basename(manifest_full_path)
                try:
                    depot_id_from_file = manifest_filename.split("_")[0]
                    if depot_id_from_file.isdigit():
                        if depot_id_from_file not in processed_depots_for_setmanifest:
                            lua_lines.append(f"addappid({depot_id_from_file})")
                            processed_depots_for_setmanifest.add(depot_id_from_file)

                        manifest_id_val = manifest_filename[
                            len(depot_id_from_file) + 1 : -len(".manifest")
                        ]
                        lua_lines.append(
                            f'setManifestid({depot_id_from_file},"{manifest_id_val}",0)'
                        )
                except (IndexError, ValueError):
                    self.print_colored_ui(
                        f"Could not parse depot/manifest_id from filename for LUA: {manifest_filename}",
                        "red",
                    )
        return "\n".join(lua_lines)

    def zip_outcome(
        self, processing_dir: str, selected_repos_for_zip: List[str]
    ) -> None:
        """
        Zips the contents of `processing_dir` (for non-branch repos) and then deletes `processing_dir`.
        The final zip is named based on `processing_dir`'s name and placed in its parent.
        This function is NOT called if the source was a branch repo.
        """
        if not os.path.isdir(processing_dir):
            self.print_colored_ui(
                f"Processing directory {processing_dir} not found for zipping. Skipping zip.",
                "red",
            )
            return

        is_encrypted_source: bool = any(
            self.repos.get(repo_name, "") == "Encrypted"
            for repo_name in selected_repos_for_zip
        )
        strict_mode_active: bool = self.strict_validation_var.get()
        key_files_to_exclude: List[str] = ["key.vdf", "config.vdf"]

        final_zip_base_name: str = os.path.basename(os.path.normpath(processing_dir))
        final_zip_parent_dir: str = os.path.dirname(processing_dir)

        zip_name_suffix: str = " - encrypted.zip" if is_encrypted_source else ".zip"
        final_zip_name: str = final_zip_base_name + zip_name_suffix
        final_zip_path: str = os.path.join(final_zip_parent_dir, final_zip_name)

        try:
            with zipfile.ZipFile(final_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(processing_dir):
                    for file in files:
                        file_path: str = os.path.join(root, file)

                        if (
                            strict_mode_active
                            and os.path.basename(file.lower()) in key_files_to_exclude
                        ):
                            self.print_colored_ui(
                                f"Excluding {file} from zip (strict mode).", "yellow"
                            )
                            continue
                        arcname: str = os.path.relpath(file_path, start=processing_dir)
                        zipf.write(file_path, arcname)

            self.print_colored_ui(f"\nZipped outcome to {final_zip_path}", "cyan")

            try:
                for root_del, dirs_del, files_del in os.walk(
                    processing_dir, topdown=False
                ):
                    for name_f in files_del:
                        os.remove(os.path.join(root_del, name_f))
                    for name_d in dirs_del:
                        os.rmdir(os.path.join(root_del, name_d))
                os.rmdir(processing_dir)
                self.print_colored_ui("Source folder deleted successfully.", "green")
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

    def on_closing(self) -> None:
        if messagebox.askokcancel("Quit", "Do you want to quit?"):
            self.cancel_search = True
            if self.search_thread and self.search_thread.is_alive():
                try:
                    self.search_thread.join(timeout=0.5)
                except RuntimeError:
                    pass
            if self.loop and self.loop.is_running():
                self.loop.call_soon_threadsafe(self.loop.stop)
            self.destroy()

    def toggle_all_repos(self, repo_type: str) -> None:
        if repo_type not in ["encrypted", "decrypted", "branch"]:
            return

        all_relevant_selected: bool = True
        relevant_repos_exist: bool = False
        for repo_name, repo_state_str in self.repos.items():
            if repo_state_str.lower() == repo_type.lower():
                relevant_repos_exist = True
                if (
                    repo_name not in self.repo_vars
                    or not self.repo_vars[repo_name].get()
                ):
                    all_relevant_selected = False
                    break

        if not relevant_repos_exist:
            self.print_colored_ui(f"No {repo_type} repositories to toggle.", "yellow")
            return

        new_state: bool = not all_relevant_selected
        for repo_name, repo_state_str in self.repos.items():
            if (
                repo_state_str.lower() == repo_type.lower()
                and repo_name in self.repo_vars
            ):
                self.repo_vars[repo_name].set(new_state)

        action_str: str = "Selected" if new_state else "Deselected"
        self.print_colored_ui(f"{action_str} all {repo_type} repositories.", "blue")

    def open_add_repo_window(self) -> None:
        self.add_repo_window = ctk.CTkToplevel(self)
        self.add_repo_window.title("Add Repository")
        self.add_repo_window.geometry("400x200")
        self.add_repo_window.resizable(False, False)
        self.add_repo_window.transient(self)
        self.add_repo_window.grab_set()

        ctk.CTkLabel(
            self.add_repo_window, text="Repository Name (e.g., user/repo):"
        ).pack(padx=10, pady=5)
        self.repo_name_entry = ctk.CTkEntry(self.add_repo_window, width=300)
        self.repo_name_entry.pack(padx=10, pady=5)
        self.repo_name_entry.focus()

        ctk.CTkLabel(self.add_repo_window, text="Repository State:").pack(
            padx=10, pady=5
        )
        self.repo_state_var = ctk.StringVar(value="Decrypted")
        ctk.CTkOptionMenu(
            self.add_repo_window,
            variable=self.repo_state_var,
            values=["Encrypted", "Decrypted", "Branch"],
        ).pack(padx=10, pady=5)

        ctk.CTkButton(self.add_repo_window, text="Add", command=self.add_repo).pack(
            padx=10, pady=10
        )

    def add_repo(self) -> None:
        repo_name: str = self.repo_name_entry.get().strip()
        repo_state: str = self.repo_state_var.get()

        if not repo_name:
            messagebox.showwarning(
                "Input Error",
                "Please enter a repository name.",
                parent=self.add_repo_window,
            )
            return
        if "/" not in repo_name or len(repo_name.split("/")) != 2 or " " in repo_name:
            messagebox.showwarning(
                "Input Error",
                "Repository name must be in 'user/repo' format without spaces.",
                parent=self.add_repo_window,
            )
            return
        if repo_name in self.repos:
            messagebox.showwarning(
                "Input Error", "Repository already exists.", parent=self.add_repo_window
            )
            return

        self.repos[repo_name] = repo_state
        self.save_repositories()
        self.refresh_repo_checkboxes()

        self.print_colored_ui(f"Added repository: {repo_name} ({repo_state})", "green")
        self.add_repo_window.destroy()

    def delete_repo(self) -> None:
        repos_to_delete: List[str] = [
            repo for repo, var in self.repo_vars.items() if var.get()
        ]
        if not repos_to_delete:
            messagebox.showwarning(
                "Selection Error", "Please select at least one repository to delete."
            )
            return

        confirm: bool = messagebox.askyesno(
            "Confirm Deletion",
            f"Are you sure you want to delete these {len(repos_to_delete)} repositories?",
        )
        if not confirm:
            return

        for repo in repos_to_delete:
            if repo in self.repos:
                del self.repos[repo]
        self.save_repositories()
        self.refresh_repo_checkboxes()
        self.print_colored_ui(
            f"Deleted repositories: {', '.join(repos_to_delete)}", "red"
        )

    def refresh_repo_checkboxes(self) -> None:
        for widget in self.encrypted_scroll.winfo_children():
            widget.destroy()
        for widget in self.decrypted_scroll.winfo_children():
            widget.destroy()
        for widget in self.branch_scroll.winfo_children():
            widget.destroy()

        new_repo_vars: Dict[str, ctk.BooleanVar] = {}

        for repo_name, repo_state in self.repos.items():
            default_value = repo_state == "Decrypted"
            existing_var = self.repo_vars.get(repo_name)
            current_value = existing_var.get() if existing_var else default_value

            var = ctk.BooleanVar(value=current_value)
            new_repo_vars[repo_name] = var

            scroll_target = None
            if repo_state == "Encrypted":
                scroll_target = self.encrypted_scroll
            elif repo_state == "Decrypted":
                scroll_target = self.decrypted_scroll
            elif repo_state == "Branch":
                scroll_target = self.branch_scroll
            else:
                self.print_colored_ui(
                    f"Unknown repo state '{repo_state}' for '{repo_name}'. Defaulting to Decrypted section.",
                    "yellow",
                )
                scroll_target = self.decrypted_scroll

            if scroll_target:
                cb = ctk.CTkCheckBox(scroll_target, text=repo_name, variable=var)
                cb.pack(anchor="w", padx=10, pady=2)

        self.repo_vars = new_repo_vars

    def open_info_window(self) -> None:
        info_window = ctk.CTkToplevel(self)
        info_window.title("App Information")
        info_window.geometry("600x450")
        info_window.resizable(False, False)
        info_window.transient(self)
        info_window.grab_set()

        info_textbox = Text(
            info_window,
            wrap="word",
            width=580,
            height=400,
            bg="#2B2B2B",
            fg="white",
            font=("Helvetica", 12),
            insertbackground="white",
            padx=5,
            pady=5,
        )
        info_textbox.pack(padx=10, pady=10, fill="both", expand=True)

        tags_config: Dict[str, Dict[str, Any]] = {
            "bold": {"font": ("Helvetica", 12, "bold")},
            "italic": {"font": ("Helvetica", 12, "italic")},
            "title": {
                "font": ("Helvetica", 14, "bold"),
                "foreground": "cyan",
                "spacing1": 5,
                "spacing3": 5,
            },
            "highlight": {"foreground": "green"},
            "note": {"foreground": "orange"},
            "normal": {"font": ("Helvetica", 12), "spacing3": 3},
        }
        for tag_name, config in tags_config.items():
            info_textbox.tag_configure(tag_name, **config)

        info_text_content: List[Tuple[str, str]] = [
            ("Steam Depot Online (SDO) - Version: 1.5.3\n", "title"),
            ("Author: ", "bold"),
            ("FairyRoot\n\n", "highlight"),
            ("1. Understanding Repository Types:\n", "bold"),
            (
                "   - Decrypted Repositories: (Checked by default) Contain necessary decryption keys. Games from here are generally ready to play. A .lua script is generated, and contents are zipped by the tool into `./Games/{GameName}-{AppID}.zip`.\n",
                "normal",
            ),
            (
                "   - Encrypted Repositories: (Unchecked by default) May have latest game manifests but decryption keys are hashed/invalid. A .lua script is generated (likely minimal), and contents are zipped by the tool into `./Games/{GameName}-{AppID}.zip`.\n",
                "note",
            ),
            (
                "   - Branch Repositories: (Unchecked by default) Download a direct .zip archive of an AppID branch from GitHub. This downloaded .zip is saved *as is* directly to `./Games/{GameName}-{AppID}.zip`. **No .lua script is generated, and no further zipping is performed by this tool for Branch types.** Strict Validation does not apply.\n",
                "normal",
            ),
            (
                "   - For Playable Games: Prioritize Decrypted repositories. Branch repos provide raw game data zips.\n",
                "normal",
            ),
            (
                "   - For Latest Manifests (Advanced): Use Encrypted repos and source keys elsewhere.\n\n",
                "normal",
            ),
            ("2. Strict Validation Checkbox:\n", "bold"),
            (
                "   - Applies ONLY to Encrypted/Decrypted (non-Branch) repositories.\n",
                "note",
            ),
            (
                "   - Checked (Default): For non-Branch repos, requires Key.vdf/config.vdf for validity. Prioritizes keys, downloads manifests. Key.vdf/config.vdf NOT in final tool-generated ZIP.\n",
                "normal",
            ),
            (
                "   - Unchecked: For non-Branch repos, downloads full branch content. Parses present Key.vdf/config.vdf. All files, including Key.vdf/config.vdf, WILL be in final tool-generated ZIP.\n\n",
                "normal",
            ),
            ("3. Potential Issues & Solutions:\n", "bold"),
            (
                "   - 'Content is still encrypted' error (non-Branch): Game files downloaded but lack valid decryption keys. Try a Decrypted repository or source keys manually.\n",
                "normal",
            ),
            (
                "   - Rate-limiting: GitHub may rate-limit downloads. Consider a VPN or waiting.\n\n",
                "normal",
            ),
            ("- Overview\n", "title"),
            (
                "Fetches Steam data from GitHub. For Encrypted/Decrypted types, it generates Lua scripts and zips results. For Branch type, it saves the downloaded GitHub zip directly.\nOutput for all successful downloads is `./Games/{GameName}-{AppID}.zip`.\n\n",
                "normal",
            ),
            ("- Features:\n", "title"),
            (
                "- Add/delete GitHub repositories (user/repo) with types: Encrypted, Decrypted, Branch.\n",
                "normal",
            ),
            (
                "- Select repositories; toggle strict validation (for non-Branch repos).\n",
                "normal",
            ),
            ("- Search games by name/AppID (steamui.com).\n", "normal"),
            (
                "- Download: specific files (strict, non-branch), full branch content (non-strict, non-branch), or direct AppID zips (Branch type, saved directly as final zip).\n",
                "normal",
            ),
            (
                "- Generate .lua scripts for Steam emulators (for non-Branch types).\n",
                "normal",
            ),
            (
                "- Zip downloaded files and .lua script (for non-Branch types).\n\n",
                "normal",
            ),
            ("- How to use:\n", "title"),
            (
                "1. Add GitHub repositories. Select type (Encrypted/Decrypted/Branch).\n",
                "normal",
            ),
            (
                "2. Configure 'Strict Validation' (affects non-Branch repos).\n",
                "normal",
            ),
            ("3. Search for a game.\n", "normal"),
            ("4. Select game from results.\n", "normal"),
            (
                "5. Click 'Download'. Final output is `./Games/{GameName}-{AppID}.zip`.\n\n",
                "normal",
            ),
            ("- Please note:\n", "title"),
            ("- Repository order can influence search priority.\n", "normal"),
            ("- Stable internet needed. Mind GitHub's usage terms.\n", "normal"),
            ("- Contact (Telegram): ", "normal"),
            ("t.me/FairyRoot\n", "highlight"),
        ]

        for text, tag in info_text_content:
            info_textbox.insert("end", text, tag)
        info_textbox.configure(state="disabled")
        info_window.focus_force()


if __name__ == "__main__":
    app = ManifestDownloader()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
