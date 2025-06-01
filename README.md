# Steam Depot Online (SDO)

<div align="center">
  <img src="imgs/app.png" alt="SDO Logo" width="128" height="128">
</div>

## Overview

**Steam Depot Online (SDO)** is a feature-rich tool for downloading and managing Steam game data. This application fetches manifests, `key.vdf` data, or entire game depot zips from GitHub repositories. For standard manifest/key downloads, it generates Lua scripts for decryption keys and compresses the outcome into a zip archive. For "Branch" type repositories, it downloads the game's pre-packaged zip directly.

**Version 2.0.0 introduces significant enhancements including persistent settings, multi-language support, an integrated update checker, batch downloading of AppIDs, and a dedicated tab to manage downloaded manifests.**

<div align="center">
  <img src="imgs/ui.png" alt="SDO UI">
</div>

**Note**: To update manifests, consider using this tool:
[Lua Manifest Updater](https://github.com/fairy-root/lua-manifest-updater)

---

## Features

- **GitHub Repository Integration**:
  - Add or delete repositories containing Steam game data.
  - Support for **Encrypted**, **Decrypted**, and **Branch** repository types with selection toggles.
  - **Your repository selections are now saved and restored between sessions.**
  - **Export and Import** your entire repository list to/from a JSON file via settings.

- **Search Functionality**:
  - Search for games by name or AppID.
  - Displays matching results with game names, AppIDs, and **small game capsule images** for easier identification.

- **Flexible Download Options**:
  - **Single Game Download**: Download the game selected from search results.
  - **Batch AppID Download**: Enter multiple AppIDs (separated by commas or newlines) in the input field, and the tool will download them sequentially.
  - **Encrypted/Decrypted Repos**: Fetches manifests and `key.vdf` files. Generates Lua scripts for use with Steam emulators.
  - **Branch Repos**: Downloads a direct `.zip` archive of an AppID's branch from GitHub (e.g., `AppID.zip`).

- **Output Packaging**:
  - All successful downloads result in a file named `{GameName}-{AppID}.zip` (or similar if encrypted) located in your configured download directory.
  - **Encrypted/Decrypted Repos**: The zip contains downloaded files (manifests, VDFs if non-strict) and the generated `.lua` script.
  - **Branch Repos**: The zip is the direct archive downloaded from the GitHub branch.

- **Persistent Application Settings**:
  - Your window size, theme, download path, strict validation preference, and repository selections are **automatically saved and loaded**.

- **Multi-language Support (Localization)**:
  - Change the application's display language via the settings.
  - Supports adding custom translation files (JSON format) in the `lang/` directory.

- **Integrated Update Checker**:
  - Automatically checks for new SDO versions on startup (configurable in settings).
  - Manually check for updates anytime from the settings window.

- **Downloaded Manifests Tab**:
  - A new tab providing a clear list of all successfully downloaded game `.zip` files in your output directory.
  - Quickly open the downloaded zip with your default app.

- **Enhanced UI Navigation & Control**:
  - **Quick Output Folder Access**: A dedicated button to open the configured download folder.
  - **Informative Tooltips**: Hover over UI elements for helpful descriptions.
  - **Keyboard Shortcuts**: Ctrl+V to paste, Enter to search.

---

## Installation

### Prerequisites

1.  Install Python 3.8 or higher.
2.  Install the required dependencies:

    ```bash
    pip install -r requirements.txt
    ```
    (Alternatively: `pip install asyncio aiohttp aiofiles customtkinter vdf pillow`)

---


### Clone the Repository

```bash
git clone https://github.com/fairy-root/steam-depot-online.git
cd steam-depot-online
```

---

## Usage

1.  **Run the Tool**:

    ```bash
    python app.py
    ```
    (Or `python3 app.py` depending on your Python setup)

2.  **Features Explained**:
    - **Add GitHub repositories** by clicking "Add Repo". Provide the repository name (e.g., `user/repo`) and select its type: **Encrypted**, **Decrypted**, or **Branch**.
    - **Select desired repositories** for searching/downloading. Use "Select All" buttons or individual checkboxes for each repository type. Your selections will be saved automatically.
    - **Configure "Strict Validation"** (applies only to Encrypted/Decrypted types). This setting is also saved.
    - **Enter a game name or AppID** in the input field. For batch download, you can enter multiple AppIDs separated by commas or newlines.
    - Click "Search" to find games by name/AppID and see results.
    - Choose your download mode:
        - **"Selected game in search results"**: Downloads the game you've clicked on from the search results.
        - **"All AppIDs in input field"**: Downloads all AppIDs currently typed into the input field (useful for batch operations).
    - Click "Download".

3.  **Output & Management**:
    - All successful downloads will result in a file named `{GameName}-{AppID}.zip` (or similar if encrypted) located in the `./Games/` directory by default.
    - **For Encrypted/Decrypted Repos**: The zip contains downloaded files (manifests, VDFs if non-strict) and the generated `.lua` script.
    - **For Branch Repos**: The zip is the direct archive downloaded from the GitHub branch.
    - Access the **"Downloaded Manifests" tab** to see a list of your downloaded zips and quickly open their location.
    - Change your default download folder and other application preferences via the **"Settings"** button.

---

## Notes

1.  **Understanding Repository Types & Download Behavior**:

    -   **Decrypted Repositories**:
        -   Usually contain necessary decryption keys. Games are generally ready to play.
        -   The tool downloads manifests and keys, generates a `.lua` script, and zips these into the final output.
    -   **Encrypted Repositories**:
        -   May have the latest game manifests but decryption keys within their `key.vdf`/`config.vdf` might be hashed, partial, or invalid.
        -   The tool downloads manifests and keys, generates a `.lua` script (which might be minimal or require manual key replacement), and zips these. Games downloaded solely from here likely won't work directly ("Content is still encrypted" error).
    -   **Branch Repositories**:
        -   Provide a direct `.zip` download of an AppID's entire branch from GitHub.
        -   The tool saves this downloaded GitHub zip *as is* to the final output path.
        -   Strict Validation does *not* apply to Branch repositories.
        -   **Default Selection**: When a new repository is added or loaded for the first time without a saved selection state, only "Branch" type repositories will be selected by default.
    -   **If you just want a playable game**: Prioritize selecting "Decrypted" repositories. "Branch" repositories can also provide ready-to-use game data if the repository maintainer packages them correctly.
    -   **If you want the latest updates (and are willing to manually manage keys)**: "Encrypted" repositories might have the newest manifests. You would then need to source decryption keys elsewhere. or you can use the [Lua Manifest Updater](https://github.com/fairy-root/lua-manifest-updater)

2.  **Strict Validation Mode (Applies ONLY to Encrypted/Decrypted Repositories)**:
    -   **Checked (Default)**: The tool will strictly require `Key.vdf` or `config.vdf` to be present in the AppID's branch for that repository to be considered valid. It prioritizes finding decryption keys and will download manifest files. If keys are found in a repo, processing for that AppID (from that repo type) stops there. `Key.vdf`/`config.vdf` will **NOT** be included in the final tool-generated ZIP.
    -   **Unchecked**: The tool will download the *full content* (all files and folders recursively) of the AppID's branch from the first repository where it's found. It will still attempt to parse `Key.vdf`/`config.vdf` if present within the downloaded content to extract keys for the `.lua` file. All downloaded files, including `Key.vdf`/`config.vdf`, **WILL** be included in the tool-generated ZIP.

3.  **"Content is still encrypted" Error (for non-Branch downloads)**:
    -   This means game files were downloaded but lack valid decryption keys in the generated `.lua` file.
    -   **Possible Solutions**: Try finding the game in a "Decrypted" repository, or manually source and replace the `DecryptionKey` values in the `.lua` file. Decryption keys for a specific depot ID are usually valid across different manifest IDs for that same depot.

4.  **Rate Limiting**:
    -   GitHub may rate-limit your IP address after extensive use (60 requests per minute). Using a VPN to change your location can help.

---

## Changelog

See the [Changelog](changelog.md) file for more details.

## Donation

Your support is appreciated:

-   **USDt (TRC20)**: `TGCVbSSJbwL5nyXqMuKY839LJ5q5ygn2uS`
-   **BTC**: `13GS1ixn2uQAmFQkte6qA5p1MQtMXre6MT`
-   **ETH (ERC20)**: `0xdbc7a7dafbb333773a5866ccf7a74da15ee654cc`
-   **LTC**: `Ldb6SDxUMEdYQQfRhSA3zi4dCUtfUdsPou`

## Author

-   **GitHub**: [FairyRoot](https://github.com/fairy-root)
-   **Telegram**: [@FairyRoot](https://t.me/FairyRoot)

## Contributing

If you would like to contribute to this project, feel free to fork the repository and submit pull requests. Ensure that your code follows the existing structure, and test it thoroughly.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.