## Changelog

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