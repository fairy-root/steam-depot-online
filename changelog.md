## Changelog

### Version 1.5.5 (Cumulative Update)

**User Interface & Progress Display**
*   **Enhanced Progress Clearing:** Implemented a more precise clearing mechanism for the "Progress" area.
    *   When a new game search is initiated or a game is selected from results, only the "dynamic" content (previous search results, selection messages, and game details) is cleared. Initial "App List Loading" messages remain.
    *   When a download operation is initiated, the *entire* "Progress" area is now fully cleared, providing a fresh log for the download process, and then the initial app list status is re-appended for context.
    * Cleaned the "Progress" area of the cluttered initialization data.
*   **Intelligent Image/Details Display:**
    *   Images (logo, header) are now only displayed in the "Progress" area if they are successfully downloaded. 404 (Not Found) errors for images no longer clutter the output.
    *   Detailed game text information (description, genres, release date) is only displayed if successfully retrieved from the Steam API. If the API call fails or returns no relevant data, the section is skipped, preventing "No detailed text information found" messages from appearing when there's genuinely no data.
*   **Image Handling Improvement:** Addressed the `CTkLabel` warning by using `customtkinter.CTkImage` to wrap `PIL.Image.Image` objects for better HighDPI scaling and integration with CustomTkinter.

**Repository Management**
*   **Corrected "Select All" Toggle:** The `toggle_all_repos` logic has been fixed to correctly determine if all relevant repositories of a specific type are already selected before toggling their state, ensuring predictable behavior.

**Code Quality & Stability**
*   **Synchronous UI Updates:** Refined `append_progress` and clearing operations to ensure they execute synchronously on the main UI thread when needed, resolving issues where messages appeared out of order due to asynchronous scheduling.
*   Improved handling of potential network and API errors to gracefully skip missing assets or data without crashing.

### Version 1.5.3 (Cumulative Update)

**Core Feature: Branch Repository Type & Distinct Download Path**
*   Introduced a new repository type: **"Branch"**.
    *   When a "Branch" repository is selected and successfully provides data for an AppID:
        *   The application downloads a direct `.zip` archive.
        *   The downloaded GitHub zip is saved *directly* as `./Games/{GameName}-{AppID}.zip`.
        *   **No further processing occurs for Branch types:** No `.lua` script is generated from its contents by this tool, and no additional outer zip is created. The output is the raw downloaded GitHub zip.
    *   Strict Validation explicitly does *not* apply to Branch repositories.
*   Added a third section in the UI for "Branch Repositories" with its own "Select All" toggle.
*   Updated "Add Repo" window to include "Branch" as a repository state option.

**Default Selections & UI Adjustments**
*   Modified `refresh_repo_checkboxes` so that only "Decrypted" repositories are checked by default. "Encrypted" and "Branch" repositories are now unchecked by default.
*   Adjusted UI layout in `setup_ui` to accommodate the new "Branch Repositories" section, resizing other repository sections slightly.
*   Updated the "Strict Validation" checkbox label to clarify it applies to "Non-Branch Repos".

**Download & Processing Logic Refinements**
*   Refactored `_perform_download_operations`:
    *   Handles the distinct download and save logic for "Branch" type repositories, saving them directly to their final named zip location in `./Games/`.
    *   For non-Branch types, it continues to create a temporary processing directory (`./Games/{GameName}-{AppID}/`) for downloading files and generating Lua scripts.
*   Modified `async_download_and_process`:
    *   Correctly interprets the `output_path_or_processing_dir` and `source_was_branch` flags from `_perform_download_operations`.
    *   Skips Lua generation and `zip_outcome` calls if `source_was_branch` is true, and provides appropriate user feedback.
    *   Calls `zip_outcome` only for successful non-Branch repository downloads.
*   Removed `_parse_vdfs_from_standalone_zip` and `_extract_zip_to_save_dir` as they are no longer needed with the simplified direct download for Branch types.
*   The `parse_vdf_to_lua` function is now only relevant for non-Branch downloads.
*   The `zip_outcome` function is now only relevant for non-Branch downloads, zipping the contents of the temporary processing directory into the final `./Games/{GameName}-{AppID}.zip`.

**Info Window & User Guidance**
*   Significantly updated the Info window (`open_info_window`) text to:
    *   Clearly explain the new "Branch" repository type, its download behavior (direct GitHub zip), and its output format.
    *   Detail how "Encrypted" and "Decrypted" repositories are handled (Lua generation, tool-created zip).
    *   Clarify that "Strict Validation" only applies to non-Branch repository types.
    *   Reflect changes in default repository selections.
    *   Update overview and feature descriptions.

**Code Cleanup & Robustness**
*   Improved clarity in variable naming related to output paths and processing directories.
*   Ensured consistent creation of the base `./Games/` output directory.

### Version 1.4.2 (Cumulative Update)

**Core Feature: Strict Validation Mode & Download Behavior**
*   Implemented "Strict Validation" checkbox to control download and processing logic:
    *   **Checked State (Strict Mode):**
        *   Requires `Key.vdf` or `config.vdf` (found anywhere in the AppID branch, case-insensitively by filename) for a repository to be considered valid.
        *   Prioritizes finding decryption keys; downloads manifest files.
        *   Stops searching repositories once keys are found.
        *   **`Key.vdf`/`config.vdf` files are NOT included in the final ZIP archive.**
    *   **Unchecked State (Non-Strict Mode):**
        *   Downloads the *full content* (all files and folders recursively) of the AppID's branch from the first repository where found.
        *   Attempts to parse `Key.vdf`/`config.vdf` if present to extract keys for the LUA file.
        *   All downloaded files, including `Key.vdf`/`config.vdf` (if present), WILL be included in the ZIP.

**Download & Processing Logic Enhancements**
*   Enhanced `download_and_process`:
    *   Accurately handles different validation modes.
    *   Correctly identifies `Key.vdf`/`config.vdf` regardless of path within the branch during strict mode.
    *   Supports recursive download when strict validation is off.
*   Refactored `get_manifest`:
    *   More focused on strict mode (downloading specific VDF/manifests by full path).
    *   Handles existing local files better (especially VDFs).
    *   Full content download (non-strict) now primarily via `download_and_process` calling `get_manifest` per file.
*   Adjusted `parse_vdf_to_lua`:
    *   Creates minimal LUA if keys are missing (e.g., non-strict mode).
    *   Improved iteration over manifest files (including subdirectories) for `setManifestid`.
    *   Added sorting for manifest files for more consistent LUA output.

**UI & User Experience Improvements**
*   Updated Info window (`open_info_window`) text to reflect current validation options, download behavior, and ZIP content rules.
*   Added padding/spacing in Info window Text widget for readability.
*   Improved repository addition (`add_repo`) with basic 'user/repo' format validation.
*   Refined `refresh_repo_checkboxes` logic for UI updates and BooleanVar state preservation.
*   Changed default for new repositories in "Add Repo" to "Decrypted".

**Robustness, Stability & File Handling**
*   Improved directory creation robustness in `download_and_process` and `zip_outcome`.
*   Sanitized game names more thoroughly for directory creation.
*   Enhanced `zip_outcome`:
    *   Excludes `Key.vdf`/`config.vdf` from ZIP in strict mode.
    *   More robust folder deletion after zipping.
    *   Correct determination of zip file's parent directory.
*   Improved stability: `on_closing` now attempts to signal `cancel_search` and join search thread.
*   Improved network operations: Enhanced error handling/logging, including `aiohttp` timeouts and less verbose CDN failure logging.

**Logging & Bugfixes**
*   Added more specific error logging for VDF parsing failures (especially non-strict full downloads).
*   Bugfix: Corrected logic in strict mode to properly find/process `Key.vdf`/`config.vdf` in subdirectories, ensuring correct key extraction.
*   Bugfix: Addressed potential `IndexError` in `parse_vdf_to_lua` for malformed manifest filenames.

### Version 1.3.0
*   Ensured asyncio uses `WindowsSelectorEventLoopPolicy` on Windows (addresses potential `aioDNS` issues).
*   Updated the game search functionality to align with changes in the SteamUI API.

### Version 1.2.0
*   UI Enhancements:
    *   Made UI elements resizable with the main window.
    *   Added a minimum size for the main window to ensure UI remains visible.
    *   Made the UI more compact by reducing element sizes by approximately 10%.
*   File Handling: Ensured that zip files originating from downloads involving encrypted repositories are tagged with "encrypted" in their filenames.
*   Info Window: Rewrote the info window content with formatted rich text for better readability and presentation.

### Version 1.1.0
*   UI Layout Adjustments:
    *   Moved the "Progress" section to the right side of the application window.
    *   Relocated the "Download Manifest" button to be adjacent to the "Search" button for a more logical flow.
*   Default Settings: Encrypted repositories are now unchecked by default upon application start.
*   User Guidance:
    *   Added a warning label next to the "Info" button to caution users about encrypted repositories.
    *   Made the text within the "Info" window scrollable.
    *   Enabled word wrap for the text in the "Info" window.

### Version 1.0.0 - Initial Release
*   Core Functionality:
    *   Integrated GitHub repository support, distinguishing between encrypted and decrypted repositories.
    *   Implemented game search by name or AppID using Steam's API.
    *   Enabled downloading of game manifests and `key.vdf` files.
    *   Automated generation of Lua scripts compatible with SteamTools.
    *   Provided ZIP archiving for downloaded files to ensure organized storage.
*   User Interface:
    *   Developed an intuitive UI with features such as clipboard paste for game input.
    *   Allowed toggling of repository selections (encrypted/decrypted).
*   Stability: Implemented robust error handling for user inputs and download processes.