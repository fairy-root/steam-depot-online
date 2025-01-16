import asyncio
import aiohttp
import aiofiles
import os
import vdf
import json
import zipfile
import threading
from functools import partial
from tkinter import END, Text, Scrollbar
import customtkinter as ctk
from tkinter import messagebox

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class ManifestDownloader(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Steam Depot Online (SDO)")
        self.geometry("1400x730")  # Adjusted width to accommodate side-by-side layout
        self.resizable(False, False)

        # Load repositories from JSON file
        self.repos = self.load_repositories()
        self.selected_repos = {repo: True for repo in self.repos}
        self.repo_vars = {}

        # Mapping from AppID to Game Name
        self.appid_to_game = {}

        # Selected game data
        self.selected_appid = None
        self.selected_game_name = None

        self.search_thread = None
        self.cancel_search = False

        self.setup_ui()

    def load_repositories(self):
        if os.path.exists("repositories.json"):
            with open("repositories.json", "r") as f:
                return json.load(f)
        return {}

    def save_repositories(self):
        with open("repositories.json", "w") as f:
            json.dump(self.repos, f)

    def setup_ui(self):
        # Main container frame to hold left and right sections
        main_container = ctk.CTkFrame(self)
        main_container.pack(fill="both", expand=True, padx=20, pady=10)

        # Left side (Main UI)
        left_frame = ctk.CTkFrame(main_container)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        # === Repository Selection Frame ===
        repo_frame = ctk.CTkFrame(left_frame, corner_radius=10)
        repo_frame.pack(padx=0, pady=10, fill="both", expand=False)

        # Create a container frame to hold both Encrypted and Decrypted sections side-by-side
        repos_container = ctk.CTkFrame(repo_frame)
        repos_container.pack(padx=10, pady=5, fill="both", expand=True)

        # Left side (Encrypted Repositories)
        encrypted_frame = ctk.CTkFrame(repos_container)
        encrypted_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))

        encrypted_label_frame = ctk.CTkFrame(encrypted_frame)
        encrypted_label_frame.pack(fill="x")
        encrypted_label = ctk.CTkLabel(
            encrypted_label_frame,
            text="Encrypted Repositories:",
            text_color="cyan",
            font=("Helvetica", 14),
        )
        encrypted_label.pack(padx=10, pady=(10, 5), side="left")

        encrypted_select_all_button = ctk.CTkButton(
            encrypted_label_frame,
            text="Select All",
            width=80,
            command=lambda: self.toggle_all_repos("encrypted"),
        )
        encrypted_select_all_button.pack(padx=70, pady=(10, 5), side="left")

        # Store encrypted_scroll as a class attribute
        self.encrypted_scroll = ctk.CTkScrollableFrame(
            encrypted_frame, width=400, height=150
        )
        self.encrypted_scroll.pack(padx=10, pady=5, fill="both", expand=True)

        # Right side (Decrypted Repositories)
        decrypted_frame = ctk.CTkFrame(repos_container)
        decrypted_frame.pack(side="left", fill="both", expand=True, padx=(5, 0))

        decrypted_label_frame = ctk.CTkFrame(decrypted_frame)
        decrypted_label_frame.pack(fill="x")

        decrypted_label = ctk.CTkLabel(
            decrypted_label_frame,
            text="Decrypted Repositories:",
            text_color="cyan",
            font=("Helvetica", 14),
        )
        decrypted_label.pack(padx=10, pady=(10, 5), side="left")

        decrypted_select_all_button = ctk.CTkButton(
            decrypted_label_frame,
            text="Select All",
            width=80,
            command=lambda: self.toggle_all_repos("decrypted"),
        )
        decrypted_select_all_button.pack(padx=70, pady=(10, 5), side="left")

        # Store decrypted_scroll as a class attribute
        self.decrypted_scroll = ctk.CTkScrollableFrame(
            decrypted_frame, width=400, height=150
        )
        self.decrypted_scroll.pack(padx=10, pady=5, fill="both", expand=True)

        # Create checkboxes in the correct frame
        for repo_name, repo_state in self.repos.items():
            # Set encrypted repositories to unchecked by default
            if repo_state == "Encrypted":
                var = ctk.BooleanVar(value=False)  # Unchecked by default
            else:
                var = ctk.BooleanVar(value=True)  # Checked by default for decrypted

            if repo_state == "Encrypted":
                cb = ctk.CTkCheckBox(
                    self.encrypted_scroll, text=repo_name, variable=var
                )
                cb.pack(anchor="w", padx=10, pady=2)
            else:
                cb = ctk.CTkCheckBox(
                    self.decrypted_scroll, text=repo_name, variable=var
                )
                cb.pack(anchor="w", padx=10, pady=2)
            self.repo_vars[repo_name] = var

        # Add Repo Button
        add_repo_button = ctk.CTkButton(
            repo_frame,
            text="Add Repo",
            command=self.open_add_repo_window,
        )
        add_repo_button.pack(padx=10, pady=5, side="right")

        # Delete Repo Button
        delete_repo_button = ctk.CTkButton(
            repo_frame,
            text="Delete Repo",
            command=self.delete_repo,
        )
        delete_repo_button.pack(padx=10, pady=5, side="right")

        # Info Button
        info_button = ctk.CTkButton(
            repo_frame,
            text="Info",
            command=self.open_info_window,
        )
        info_button.pack(padx=10, pady=5, side="right")

        # Label beside the Info button
        warning_label = ctk.CTkLabel(
            repo_frame,
            text="Games in encrypted repositories will not work.",
            text_color="orange",
            font=("Helvetica", 18),
        )
        warning_label.pack(padx=10, pady=5, side="left")

        # === Frame for Game Input ===
        input_frame = ctk.CTkFrame(left_frame, corner_radius=10)
        input_frame.pack(padx=0, pady=10, fill="x", expand=False)

        input_label = ctk.CTkLabel(
            input_frame,
            text="Enter Game Name or AppID:",
            text_color="cyan",
            font=("Helvetica", 16),
        )
        input_label.pack(padx=10, pady=5, anchor="w")

        self.game_input = ctk.CTkEntry(
            input_frame, placeholder_text="e.g., 123456 or Game Name", width=500
        )
        self.game_input.pack(padx=10, pady=5, side="left", expand=True, fill="x")

        paste_button = ctk.CTkButton(
            input_frame, text="Paste", command=self.paste_from_clipboard
        )
        paste_button.pack(padx=10, pady=5, side="left")

        search_button = ctk.CTkButton(
            input_frame, text="Search", command=self.search_game
        )
        search_button.pack(padx=10, pady=5, side="left")

        # === Download Button ===
        self.download_button = ctk.CTkButton(
            input_frame,
            text="Download",  # Renamed to "Download"
            command=self.download_manifest,
            state="disabled",
        )
        self.download_button.pack(padx=10, pady=5, side="left")

        # === Frame for Search Results ===
        self.results_frame = ctk.CTkFrame(left_frame, corner_radius=10)
        self.results_frame.pack(padx=0, pady=10, fill="both", expand=False)

        self.results_label = ctk.CTkLabel(
            self.results_frame,
            text="Search Results:",
            text_color="cyan",
            font=("Helvetica", 16),
        )
        self.results_label.pack(padx=10, pady=5, anchor="w")

        self.results_var = ctk.StringVar(value=None)
        self.results_radio_buttons = []

        self.results_container = ctk.CTkScrollableFrame(
            self.results_frame, width=860, height=100
        )
        self.results_container.pack(padx=10, pady=5)

        # Right side (Progress Section)
        right_frame = ctk.CTkFrame(main_container)
        right_frame.pack(side="right", fill="both", expand=False, padx=(10, 0))

        # === Progress Text ===
        progress_frame = ctk.CTkFrame(right_frame, corner_radius=10)
        progress_frame.pack(padx=0, pady=10, fill="both", expand=True)

        progress_label = ctk.CTkLabel(
            progress_frame, text="Progress:", text_color="cyan", font=("Helvetica", 16)
        )
        progress_label.pack(padx=10, pady=5, anchor="w")

        text_container = ctk.CTkFrame(progress_frame, corner_radius=10)
        text_container.pack(padx=10, pady=5, fill="both", expand=True)

        self.scrollbar = Scrollbar(text_container)
        self.scrollbar.pack(side="right", fill="y")

        self.progress_text = Text(
            text_container,
            wrap="word",
            height=200,
            state="disabled",
            bg="#2B2B2B",
            fg="white",
            insertbackground="white",
            yscrollcommand=self.scrollbar.set,
            font=("Helvetica", 12),
        )
        self.progress_text.pack(padx=5, pady=5, fill="both", expand=True)

        self.scrollbar.config(command=self.progress_text.yview)

        self.progress_text.tag_configure("green", foreground="green")
        self.progress_text.tag_configure("red", foreground="red")
        self.progress_text.tag_configure("blue", foreground="deepskyblue")
        self.progress_text.tag_configure("yellow", foreground="yellow")
        self.progress_text.tag_configure("cyan", foreground="cyan")
        self.progress_text.tag_configure("magenta", foreground="magenta")
        self.progress_text.tag_configure("default", foreground="white")

    def append_progress(self, message, color="default"):
        """Helper to safely insert text into the Text widget from any thread."""

        def inner():
            self.progress_text.configure(state="normal")
            self.progress_text.insert(END, message + "\n", color)
            self.progress_text.see(END)
            self.progress_text.configure(state="disabled")

        self.after(0, inner)

    def paste_from_clipboard(self):
        try:
            clipboard_text = self.clipboard_get()
            self.game_input.delete(0, END)
            self.game_input.insert(0, clipboard_text)
            self.append_progress("Pasted text from clipboard.", "green")
        except Exception as e:
            messagebox.showerror("Paste Error", f"Failed to paste from clipboard: {e}")

    def search_game(self):
        user_input = self.game_input.get().strip()
        if not user_input:
            messagebox.showwarning("Input Error", "Please enter a game name or AppID.")
            return

        # If a search is already running, cancel it
        if self.search_thread and self.search_thread.is_alive():
            self.cancel_search = True
            self.append_progress("Cancelling previous search...", "yellow")

        # Clear previous results
        for widget in self.results_container.winfo_children():
            widget.destroy()
        self.results_radio_buttons.clear()
        self.results_var.set(None)  # type: ignore
        self.download_button.configure(state="disabled")

        # Clear progress
        self.progress_text.configure(state="normal")
        self.progress_text.delete("1.0", END)
        self.progress_text.configure(state="disabled")

        self.cancel_search = False
        self.search_thread = threading.Thread(
            target=self.run_search, args=(user_input,), daemon=True
        )
        self.search_thread.start()

    def run_search(self, user_input):
        asyncio.run(self.async_search_game(user_input))

    async def async_search_game(self, user_input):
        games = await self.find_appid_by_name(user_input)
        if self.cancel_search:
            self.append_progress("\nSearch cancelled by user.", "yellow")
            return

        if not games:
            self.append_progress(
                "\nNo matching games found. Please try another name.", "red"
            )
            return

        # Clear previous mapping
        self.appid_to_game.clear()

        # Populate mapping and create radio buttons
        for idx, game in enumerate(games, 1):
            if self.cancel_search:
                self.append_progress("\nSearch cancelled by user.", "yellow")
                return
            appid = str(game.get("appid", "Unknown"))
            game_name = game.get("name", "Unknown")
            self.appid_to_game[appid] = game_name

            self.after(0, partial(self.create_radio_button, idx, appid, game_name))

        self.append_progress(
            f"\nFound {len(games)} matching game(s). Please select one.", "cyan"
        )

    def create_radio_button(self, idx, appid, game_name):
        display_text = f"{idx}. {game_name} (AppID: {appid})"
        rb = ctk.CTkRadioButton(
            self.results_container,
            text=display_text,
            variable=self.results_var,
            value=appid,
            command=self.enable_download,
        )
        rb.pack(anchor="w", padx=10, pady=2)
        self.results_radio_buttons.append(rb)

    def enable_download(self):
        selected_appid = self.results_var.get()
        if selected_appid in self.appid_to_game:
            self.selected_appid = selected_appid
            self.selected_game_name = self.appid_to_game[selected_appid]
            self.append_progress(
                f"Selected: {self.selected_game_name} (AppID: {self.selected_appid})",
                "green",
            )
            self.download_button.configure(state="normal")
        else:
            self.append_progress("Selected game not found in mapping.", "red")
            self.download_button.configure(state="disabled")

    def download_manifest(self):
        # Gather selected repos
        selected_repo_list = [repo for repo, var in self.repo_vars.items() if var.get()]
        if not selected_repo_list:
            messagebox.showwarning(
                "Repository Selection", "Please select at least one repository."
            )
            return

        if not self.selected_appid:
            messagebox.showwarning("Selection Error", "Please select a game first.")
            return

        # Disable buttons during download
        self.download_button.configure(state="disabled")

        # Clear progress
        self.progress_text.configure(state="normal")
        self.progress_text.delete("1.0", END)
        self.progress_text.configure(state="disabled")

        threading.Thread(
            target=self.run_download,
            args=(self.selected_appid, self.selected_game_name, selected_repo_list),
            daemon=True,
        ).start()

    def run_download(self, appid, game_name, selected_repos):
        asyncio.run(self.async_download_and_process(appid, game_name, selected_repos))

    async def async_download_and_process(self, appid, game_name, selected_repos):
        collected_depots, save_dir = await self.download_and_process(
            appid, game_name, selected_repos
        )
        if self.cancel_search:
            self.append_progress("\nDownload cancelled by user.", "yellow")
            return

        if collected_depots:
            lua_script = self.parse_vdf_to_lua(collected_depots, appid, save_dir)
            lua_file_path = os.path.join(save_dir, f"{appid}.lua")
            try:
                async with aiofiles.open(
                    lua_file_path, "w", encoding="utf-8"
                ) as lua_file:
                    await lua_file.write(lua_script)
                self.append_progress(
                    f"\n\nGenerating {game_name} unlock file successfully", "blue"
                )
            except Exception as e:
                self.append_progress(f"\nFailed to write Lua script: {e}", "red")

            self.zip_outcome(save_dir)
        else:
            self.append_progress(
                "\nNo depots collected. Download may have failed.", "red"
            )

        self.download_button.configure(state="normal")

    def print_colored_ui(self, text: str, color: str) -> None:
        self.append_progress(text, color)

    def stack_error(self, e):
        return f"{type(e).__name__}: {e}"

    async def search_game_info(self, search_term):
        games = []
        page = 1
        limit = 100
        while True:
            if self.cancel_search:
                self.print_colored_ui("\nSearch cancelled by user.", "yellow")
                return []
            try:
                url = f"https://steamui.com/loadGames.php?search={search_term}&page={page}&limit={limit}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as r:
                        if r.status == 200:
                            content = await r.text()
                            try:
                                data = json.loads(content)
                                new_games = data.get("games", [])
                                if not new_games:
                                    break
                                games.extend(new_games)
                                if len(new_games) < limit:
                                    break
                                page += 1
                            except json.JSONDecodeError:
                                self.print_colored_ui(
                                    "\nFailed to decode JSON response from server.",
                                    "red",
                                )
                                break
                        else:
                            self.print_colored_ui(
                                "\nFailed to obtain game information", "red"
                            )
                            break
            except aiohttp.ClientError as e:
                self.print_colored_ui(
                    f"\nError during game information search: {self.stack_error(e)}",
                    "red",
                )
                break
            except KeyboardInterrupt:
                self.print_colored_ui(
                    "\nSearch game info interrupted by user.", "yellow"
                )
                break
        return games

    async def find_appid_by_name(self, game_name):
        games = await self.search_game_info(game_name)
        if self.cancel_search:
            return []
        if games:
            return games
        self.print_colored_ui("\nNo matching game found", "red")
        return []

    async def get(self, sha, path, repo):
        url_list = [
            f"https://gcore.jsdelivr.net/gh/{repo}@{sha}/{path}",
            f"https://fastly.jsdelivr.net/gh/{repo}@{sha}/{path}",
            f"https://cdn.jsdelivr.net/gh/{repo}@{sha}/{path}",
            f"https://ghproxy.org/https://raw.githubusercontent.com/{repo}/{sha}/{path}",
            f"https://raw.dgithub.xyz/{repo}/{sha}/{path}",
        ]
        retry = 3
        async with aiohttp.ClientSession() as session:
            while retry:
                for url in url_list:
                    if self.cancel_search:
                        self.print_colored_ui("\nDownload cancelled by user.", "yellow")
                        return None
                    try:
                        async with session.get(url, ssl=False) as r:
                            if r.status == 200:
                                return await r.read()
                            else:
                                self.print_colored_ui(
                                    f"Failed to obtain: {path} - status code: {r.status}",
                                    "red",
                                )
                    except aiohttp.ClientError:
                        self.print_colored_ui(
                            f"Failed to obtain: {path} - Connection error", "red"
                        )
                    except KeyboardInterrupt:
                        self.print_colored_ui(
                            f"\nDownload interrupted for: {path}", "yellow"
                        )
                        return None
                retry -= 1
                self.print_colored_ui(
                    f"\nNumber of retries remaining: {retry} - {path}", "yellow"
                )
        self.print_colored_ui(f"\nMaximum number of retries exceeded: {path}", "red")
        return None

    async def get_manifest(self, sha, path, save_dir, repo):
        collected_depots = []
        try:
            if path.endswith(".manifest"):
                save_path = os.path.join(save_dir, path)
                if os.path.exists(save_path):
                    self.print_colored_ui(f"\nExisting list: {path}", "yellow")
                    return collected_depots

                content = await self.get(sha, path, repo)
                if self.cancel_search:
                    self.print_colored_ui("\nDownload cancelled by user.", "yellow")
                    return collected_depots
                if content:
                    self.print_colored_ui(
                        f"\nList download successful: {path}", "green"
                    )
                    async with aiofiles.open(save_path, "wb") as f:
                        await f.write(content)

            elif path in ["Key.vdf", "config.vdf"]:
                content = await self.get(sha, path, repo)
                if self.cancel_search:
                    self.print_colored_ui("\nDownload cancelled by user.", "yellow")
                    return collected_depots
                if content:
                    self.print_colored_ui(f"\nKey download successful: {path}", "green")
                    depots_config = vdf.loads(content.decode(encoding="utf-8"))
                    for depot_id, depot_info in depots_config["depots"].items():
                        collected_depots.append((depot_id, depot_info["DecryptionKey"]))

        except KeyboardInterrupt:
            self.print_colored_ui(
                f"\nManifest processing interrupted: {path}", "yellow"
            )
            return []
        except Exception as e:
            self.print_colored_ui(
                f"\nProcessing failed: {path} - {self.stack_error(e)}", "red"
            )
        return collected_depots

    async def download_and_process(self, app_id, game_name, selected_repos):
        try:
            app_id_list = list(filter(str.isdecimal, app_id.strip().split("-")))
            app_id = app_id_list[0]
            save_dir = f"./Games/{game_name} - {app_id}".replace(":", "").replace(
                "|", ""
            )
            os.makedirs(save_dir, exist_ok=True)

            for repo in selected_repos:
                if self.cancel_search:
                    self.print_colored_ui("\nDownload cancelled by user.", "yellow")
                    return [], save_dir
                self.print_colored_ui(f"\nSearch repository: {repo}", "cyan")

                url = f"https://api.github.com/repos/{repo}/branches/{app_id}"
                async with aiohttp.ClientSession() as session:
                    try:
                        async with session.get(url, ssl=False) as r:
                            if r.status != 200:
                                self.print_colored_ui(
                                    f"Repository {repo} not found or inaccessible.",
                                    "red",
                                )
                                continue
                            r_json = await r.json()
                            if "commit" in r_json:
                                sha = r_json["commit"]["sha"]
                                tree_url = r_json["commit"]["commit"]["tree"]["url"]
                                date = r_json["commit"]["commit"]["author"]["date"]
                                async with session.get(tree_url, ssl=False) as r2:
                                    r2_json = await r2.json()
                                    if "tree" in r2_json:
                                        collected_depots = []

                                        # Try Key.vdf first, then config.vdf
                                        vdf_paths = ["Key.vdf", "config.vdf"]
                                        for vdf_path in vdf_paths:
                                            if self.cancel_search:
                                                self.print_colored_ui(
                                                    "\nDownload cancelled by user.",
                                                    "yellow",
                                                )
                                                return [], save_dir
                                            vdf_result = await self.get_manifest(
                                                sha, vdf_path, save_dir, repo
                                            )
                                            if vdf_result:
                                                collected_depots.extend(vdf_result)
                                                break

                                        for item in r2_json["tree"]:
                                            if self.cancel_search:
                                                self.print_colored_ui(
                                                    "\nDownload cancelled by user.",
                                                    "yellow",
                                                )
                                                return [], save_dir
                                            if item["path"].endswith(".manifest"):
                                                result = await self.get_manifest(
                                                    sha, item["path"], save_dir, repo
                                                )
                                                if result:
                                                    collected_depots.extend(result)

                                        if collected_depots:
                                            self.print_colored_ui(
                                                f"\nList last updated time: {date}",
                                                "yellow",
                                            )
                                            self.print_colored_ui(
                                                f"\nStorage successful: {app_id} in repository: {repo}",
                                                "green",
                                            )
                                            return collected_depots, save_dir
                    except aiohttp.ClientError as e:
                        self.print_colored_ui(
                            f"\nError accessing repository {repo}: {self.stack_error(e)}",
                            "red",
                        )
                    except KeyboardInterrupt:
                        self.print_colored_ui(
                            f"\nDownload and process interrupted during repository search: {repo}",
                            "yellow",
                        )
                        return [], save_dir

                self.print_colored_ui(
                    f"\nGame not found in repo {repo}. Continue searching for the next repository.",
                    "yellow",
                )

            self.print_colored_ui(
                f"\nList download failed: {app_id} in all repositories", "red"
            )
            return [], save_dir
        except KeyboardInterrupt:
            self.print_colored_ui(
                "\nDownload and process interrupted by user.", "yellow"
            )
            return [], ""

    def parse_vdf_to_lua(self, depot_info, appid, save_dir):
        lua_lines = []
        lua_lines.append(f"addappid({appid})")

        for depot_id, decryption_key in depot_info:
            lua_lines.append(f'addappid({depot_id},1,"{decryption_key}")')
            manifest_files = [
                f
                for f in os.listdir(save_dir)
                if f.startswith(depot_id + "_") and f.endswith(".manifest")
            ]
            for manifest_file in manifest_files:
                manifest_id = manifest_file[len(depot_id) + 1 : -len(".manifest")]
                lua_lines.append(f'setManifestid({depot_id},"{manifest_id}",0)')
        return "\n".join(lua_lines)

    def zip_outcome(self, save_dir):
        zip_path = f"{save_dir}.zip"
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(save_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, start=save_dir)
                        zipf.write(file_path, arcname)

            def remove_folder(path):
                for root, dirs, files in os.walk(path, topdown=False):
                    for file in files:
                        os.remove(os.path.join(root, file))
                    for dir in dirs:
                        os.rmdir(os.path.join(root, dir))
                os.rmdir(path)

            remove_folder(save_dir)
            self.print_colored_ui("Folder deleted successfully!", "green")
        except FileNotFoundError:
            self.print_colored_ui("Folder not found.", "red")
        except OSError:
            self.print_colored_ui("Folder is not empty or could not be removed.", "red")
        self.print_colored_ui(f"\nZipped the outcome to {zip_path}", "cyan")

    def on_closing(self):
        if messagebox.askokcancel("Quit", "Do you want to quit?"):
            self.destroy()

    def toggle_all_repos(self, repo_type):
        """Selects or deselects all repositories of a given type."""
        if repo_type not in ["encrypted", "decrypted"]:
            return

        # Check if all are currently selected
        all_selected = True
        for repo_name, repo_state in self.repos.items():
            if repo_state.lower() == repo_type:
                if (
                    repo_name not in self.repo_vars
                    or not self.repo_vars[repo_name].get()
                ):
                    all_selected = False
                    break

        # Toggle
        for repo_name, repo_state in self.repos.items():
            if repo_state.lower() == repo_type:
                if repo_name in self.repo_vars:
                    self.repo_vars[repo_name].set(not all_selected)
                    self.selected_repos[repo_name] = not all_selected

        if all_selected:
            self.print_colored_ui(f"Deselected all {repo_type} repositories", "blue")
        else:
            self.print_colored_ui(f"Selected all {repo_type} repositories", "blue")

    def open_add_repo_window(self):
        self.add_repo_window = ctk.CTkToplevel(self)
        self.add_repo_window.title("Add Repository")
        self.add_repo_window.geometry("400x200")
        self.add_repo_window.resizable(False, False)

        repo_name_label = ctk.CTkLabel(self.add_repo_window, text="Repository Name:")
        repo_name_label.pack(padx=10, pady=5)

        self.repo_name_entry = ctk.CTkEntry(self.add_repo_window, width=300)
        self.repo_name_entry.pack(padx=10, pady=5)

        repo_state_label = ctk.CTkLabel(self.add_repo_window, text="Repository State:")
        repo_state_label.pack(padx=10, pady=5)

        self.repo_state_var = ctk.StringVar(value="Encrypted")
        repo_state_menu = ctk.CTkOptionMenu(
            self.add_repo_window,
            variable=self.repo_state_var,
            values=["Encrypted", "Decrypted"],
        )
        repo_state_menu.pack(padx=10, pady=5)

        add_button = ctk.CTkButton(
            self.add_repo_window,
            text="Add",
            command=self.add_repo,
        )
        add_button.pack(padx=10, pady=10)

    def add_repo(self):
        repo_name = self.repo_name_entry.get().strip()
        repo_state = self.repo_state_var.get()

        if not repo_name:
            messagebox.showwarning("Input Error", "Please enter a repository name.")
            return

        if repo_name in self.repos:
            messagebox.showwarning("Input Error", "Repository already exists.")
            return

        self.repos[repo_name] = repo_state
        self.selected_repos[repo_name] = True
        self.save_repositories()

        var = ctk.BooleanVar(value=True)
        if repo_state == "Encrypted":
            cb = ctk.CTkCheckBox(self.encrypted_scroll, text=repo_name, variable=var)
            cb.pack(anchor="w", padx=10, pady=2)
        else:
            cb = ctk.CTkCheckBox(self.decrypted_scroll, text=repo_name, variable=var)
            cb.pack(anchor="w", padx=10, pady=2)
        self.repo_vars[repo_name] = var

        self.print_colored_ui(f"Added repository: {repo_name} ({repo_state})", "green")
        self.add_repo_window.destroy()  # Close the add repo window

    def delete_repo(self):
        repos_to_delete = [repo for repo, var in self.repo_vars.items() if var.get()]
        if not repos_to_delete:
            messagebox.showwarning(
                "Selection Error", "Please select at least one repository to delete."
            )
            return

        confirm = messagebox.askyesno(
            "Confirm Deletion",
            "Are you sure you want to delete the selected repositories?",
        )
        if not confirm:
            return

        for repo in repos_to_delete:
            del self.repos[repo]
            del self.selected_repos[repo]
            del self.repo_vars[repo]

        self.save_repositories()

        # Refresh the UI
        for widget in self.encrypted_scroll.winfo_children():
            widget.destroy()
        for widget in self.decrypted_scroll.winfo_children():
            widget.destroy()

        for repo_name, repo_state in self.repos.items():
            var = ctk.BooleanVar(value=True)
            if repo_state == "Encrypted":
                cb = ctk.CTkCheckBox(
                    self.encrypted_scroll, text=repo_name, variable=var
                )
                cb.pack(anchor="w", padx=10, pady=2)
            else:
                cb = ctk.CTkCheckBox(
                    self.decrypted_scroll, text=repo_name, variable=var
                )
                cb.pack(anchor="w", padx=10, pady=2)
            self.repo_vars[repo_name] = var

        self.print_colored_ui(
            f"Deleted repositories: {', '.join(repos_to_delete)}", "red"
        )

    def open_info_window(self):
        info_window = ctk.CTkToplevel(self)
        info_window.title("App Information")
        info_window.geometry("600x450")
        info_window.resizable(False, False)

        # Create a CTkTextbox for scrollable and word-wrapped text
        info_textbox = ctk.CTkTextbox(info_window, width=580, height=400, wrap="word")
        info_textbox.pack(padx=10, pady=10, fill="both", expand=True)

        # Info text
        info_text = """
        Steam Depot Online (SDO) - Version: 1.1

        Author: t.me/FairyRoot

        1. make sure to understand the following:
            - if you just want the game, then select all the decrypted repositories,
                and deselect the encrypted ones. the game will get downloaded if it was 
                found in any repository
            - if you want the latest updates, you can get the encrypted game, then replace 
                the decryption keys.
            - Encrypted repositories have latest manifests. (Games will not work)
            - Decrypted repositories have decryption keys. (Games ready to play)
        2. The encrypted repositories have hashed decryption keys, their lua files can be installed, 
                but the games won't run. they would show The content is still encrypted error.
            - Possible Solutions: Find the same game from decrypted repositories, and replace 
                the Decryption Keys.
            - The Decryption Keys would work for the Depots with different Manifest ID.
        3. The encrypted lua files from SWA Tool with the format .st can be installed, 
                and the Decryption keys can be extracted after installing the game.
        4. After some uses, the repositories get rate limited. Use a VPN to change your 
                location after few downloads.

        This tool allows you to download and manage Steam manifests.
        Fetches manifest and key.vdf data from GitHub repositories.
        Generates Lua scripts for decryption keys, and saves them in a zip archive.

        Features:
        - Allows users to add and delete GitHub repositories.
        - Provides options to select from encrypted or decrypted repositories.
        - Searches for games by name or AppID using Steam's API.
        - Downloads game manifests and decryption keys from GitHub repositories.
        - Converts downloaded data into Lua scripts for SteamTools.
        - Zips the downloaded files and Lua script into a zip archive.

        How to use:
        1. Add GitHub repositories containing Steam manifest files.
        2. Enter a game name or AppID in the search box.
        3. Select the desired game from the search results.
        4. Click "Download Manifest" to begin downloading and processing the data.

        Please note:
        - if all repositories are selected, the priority is determined by their order in repositories.json.
        - Ensure you have a stable internet connection for downloading data.
        - Be mindful of repository usage terms.
        - This tool is provided as-is.

        Additional Information:
        - Encrypted repositories require decryption keys to function properly.
        - Games in encrypted repositories will not work without the correct keys.
        - Always verify the integrity of downloaded files before use.
        - For support, contact the author via Telegram: t.me/FairyRoot.
        """

        # Insert the info text into the textbox
        info_textbox.insert("1.0", info_text.strip())
        info_textbox.configure(state="disabled")

        info_window.focus_force()


if __name__ == "__main__":
    app = ManifestDownloader()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
